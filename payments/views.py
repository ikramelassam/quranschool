import datetime
import io
import logging
import os
from decimal import Decimal, InvalidOperation

from django.core.files.base import ContentFile
from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.utils import timezone
from django.contrib import messages
from django.utils.translation import gettext as gettext_
from accounts.decorators import role_required
from accounts.services import eleves_pour_filtre
from core.utils import paginer, envoyer_notification_telegram_async
from accounts.models import Eleve
from .models import Paiement

# Anti-double-soumission (chantier du 2026-08-16, séparé du fix de
# duplication des messages) : un même élève, même montant, même mois soumis
# il y a moins de ce délai est traité comme un rejeu du même clic — jamais
# comme une 2e preuve de paiement distincte. Évite aussi, en pratique, de
# heurter la contrainte unique_together (eleve, mois_reference) du modèle
# Paiement en cas de double-clic rapide (qui lèverait sinon une IntegrityError
# non rattrapée -> erreur 500).
#
# Chantier du 2026-08-24 (sélecteur de PÉRIODE "من تاريخ"/"إلى تاريخ", en
# remplacement du champ "combien de mois payer" retiré de l'inscription —
# voir registration.utils, plus de trace de nombre_mois_payes) : la
# vérification "ce mois a-t-il déjà un Paiement ?" (voir _creer_paiements_
# pour_periode ci-dessous) rend cette fenêtre largement redondante pour les
# resoumissions (idempotent par construction désormais), mais elle reste la
# seule protection contre une VRAIE course entre 2 requêtes quasi-
# simultanées (double-clic) sur un même mois pas encore en base au moment du
# 2e check — gardée telle quelle, jamais retirée.
FENETRE_ANTI_DOUBLON_SECONDES = 5

# Plafond de sécurité (chantier du 2026-08-24) : une période mal saisie (ex:
# année de début tapée par erreur) ne doit jamais pouvoir créer des centaines
# de Paiement d'un coup — aucun élève réel ne paie plus de 2 ans à l'avance.
NB_MOIS_MAX_PAR_PERIODE = 24

logger = logging.getLogger(__name__)

# Justificatif de paiement : côté cadrage d'image avant l'upload vers le
# storage (Cloudinary en prod). Cause n°1 de la lenteur du bouton « إرسال » sur
# /payments/eleve/ (signalée 2026-09-03) : les élèves envoient une photo/capture
# de virement prise au téléphone (3–10 Mo), poussée telle quelle vers Cloudinary
# DANS le cycle requête/réponse -> plusieurs secondes d'attente sur l'hébergeur
# gratuit. Un justificatif n'a pas besoin de plus : on le redimensionne et on le
# ré-encode en JPEG avant l'envoi (typiquement 5 Mo -> ~200 Ko, ~20× moins à
# transférer). Le champ `screenshot` est `accept="image/*"` côté formulaire, donc
# toujours une image ici.
JUSTIFICATIF_DIMENSION_MAX_PX = 1600
JUSTIFICATIF_QUALITE_JPEG = 80


def _preparer_justificatif(fichier):
    """Redimensionne + ré-encode en JPEG le justificatif uploadé pour accélérer
    l'upload vers le storage. Retourne un objet sauvegardable par
    FileField.save()/`= fichier` (ContentFile nommé, ou le fichier d'origine si
    le traitement échoue — un format exotique ne doit jamais bloquer une preuve
    de paiement légitime)."""
    try:
        from PIL import Image, ImageOps

        fichier.seek(0)
        image = Image.open(fichier)
        image = ImageOps.exif_transpose(image)  # photos de téléphone : respecte l'orientation
        if image.mode not in ('RGB', 'L'):
            fond = Image.new('RGB', image.size, (255, 255, 255))
            fond.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA', 'PA') else None)
            image = fond
        image.thumbnail((JUSTIFICATIF_DIMENSION_MAX_PX, JUSTIFICATIF_DIMENSION_MAX_PX))
        tampon = io.BytesIO()
        image.save(tampon, format='JPEG', quality=JUSTIFICATIF_QUALITE_JPEG, optimize=True)
        nom_base = os.path.splitext(os.path.basename(getattr(fichier, 'name', 'justificatif')))[0] or 'justificatif'
        return ContentFile(tampon.getvalue(), name=f'{nom_base}.jpg')
    except Exception as e:
        logger.warning("Justificatif non recompressé (upload de l'original) : %s", e)
        try:
            fichier.seek(0)
        except Exception:
            pass
        return fichier


def _base_template_admin_ou_mshrif(request):
    """Équivalent local de dashboard.views._base_template_admin_ou_mshrif — les
    paiements élèves sont réutilisés en lecture seule par المشرف."""
    return 'dashboard/base_mshrif.html' if request.user.role == 'mshrif' else 'dashboard/base_admin.html'


def _contexte_base_mshrif(request):
    """Équivalent local de dashboard.views._contexte_base_mshrif (badge sidebar)."""
    if request.user.role != 'mshrif':
        return {}
    from inscriptions.models import InscriptionProf
    return {'nb_demandes_en_attente': InscriptionProf.objects.filter(statut='validee_directeur').count()}


@role_required('eleve')
def eleve_paiements(request):
    eleve = get_object_or_404(Eleve, user=request.user)

    if request.method == 'POST':
        # Défense en profondeur: un élève archivé ne peut plus se connecter (voir
        # accounts.services.archiver_eleve), donc cette vue est normalement
        # inatteignable pour lui — garde explicite malgré tout, chantier du 2026-08-03.
        if eleve.statut == 'archive':
            messages.error(request, gettext_('حسابك مؤرشف — لا يمكن إرسال دفعات جديدة.'))
            return redirect('eleve_paiements')

        from dashboard.templatetags.libelles_arabes import mois_annee_ar

        # Chantier « Paiement unique » du 2026-09-03 : payer plusieurs mois =
        # UN SEUL Paiement (montant total, 1 justificatif, 1 validation), avec
        # `nb_mois_couverts` = nombre de mois couverts d'affilée. L'élève
        # CHOISIT sa date de début (`date_debut`, éditable, pré-remplie avec le
        # début de son cycle d'abonnement ouvert). Le rapprochement avec les
        # CycleAbonnement se fait au mois près sur la fenêtre couverte
        # (payments.cycles.mois_couverts).
        from .cycles import cycle_courant, _ajouter_mois, mois_couverts

        cycle_ouvert = cycle_courant(eleve)
        defaut_debut = cycle_ouvert.date_debut if cycle_ouvert else timezone.localdate()

        try:
            date_debut = datetime.date.fromisoformat(request.POST.get('date_debut', ''))
        except (ValueError, TypeError):
            date_debut = defaut_debut  # tolérant : champ vide/invalide -> défaut

        try:
            nb_mois = int(request.POST.get('nb_mois', ''))
        except (ValueError, TypeError):
            messages.error(request, gettext_('يرجى اختيار عدد الأشهر التي تريد دفعها.'))
            return redirect('eleve_paiements')
        if nb_mois < 1:
            messages.error(request, gettext_('يرجى اختيار عدد الأشهر التي تريد دفعها.'))
            return redirect('eleve_paiements')
        if nb_mois > NB_MOIS_MAX_PAR_PERIODE:
            messages.error(
                request,
                gettext_('المدة المختارة طويلة جداً (%(v0)s شهراً) — الحد الأقصى %(v1)s شهراً في نفس الإرسال.') % {'v0': nb_mois, 'v1': NB_MOIS_MAX_PAR_PERIODE},
            )
            return redirect('eleve_paiements')

        # Montant TOTAL viré (les abonnements n'ont pas tous le même prix
        # mensuel — l'élève connaît la somme, pas forcément le prix au mois).
        try:
            montant_total = Decimal(str(request.POST.get('montant', ''))).quantize(Decimal('0.01'))
        except (InvalidOperation, TypeError, ValueError, ArithmeticError):
            messages.error(request, gettext_('يرجى إدخال المبلغ الإجمالي المدفوع.'))
            return redirect('eleve_paiements')
        if montant_total <= 0:
            messages.error(request, gettext_('يرجى إدخال المبلغ الإجمالي المدفوع.'))
            return redirect('eleve_paiements')

        mois_vises = mois_couverts(date_debut, nb_mois)

        # Anti-double-soumission : même total + même début envoyés il y a moins
        # de FENETRE_ANTI_DOUBLON_SECONDES = rejeu du même clic.
        seuil_anti_doublon = timezone.now() - datetime.timedelta(seconds=FENETRE_ANTI_DOUBLON_SECONDES)
        if Paiement.objects.filter(
            eleve=eleve, montant=montant_total, mois_reference=date_debut, date__gte=seuil_anti_doublon,
        ).exists():
            messages.info(request, gettext_('تم استلام هذه الدفعة بالفعل.'))
            return redirect('eleve_paiements')

        # Seul un Paiement DÉJÀ VALIDÉ verrouille des mois (ils sont réellement
        # réglés). Un Paiement `en_attente` ou `rejete` ne bloque PAS un
        # nouvel envoi : l'élève peut corriger (mauvais montant / mauvaise
        # capture) avant que l'administration ne traite.
        if any(
            mois_vises & mois_couverts(mr, nb)
            for mr, nb in Paiement.objects.filter(eleve=eleve, statut='valide').values_list(
                'mois_reference', 'nb_mois_couverts'
            )
        ):
            messages.error(request, gettext_('بعض الأشهر المختارة مدفوعة ومقبولة مسبقاً — اختر تاريخ بداية أو عدد أشهر مختلفاً.'))
            return redirect('eleve_paiements')

        # Un Paiement `en_attente` qui chevauche est REMPLACÉ par ce nouvel
        # envoi (sinon l'administration verrait deux demandes pour les mêmes
        # mois). Les Paiement `rejete` sont conservés comme historique.
        for ancien in Paiement.objects.filter(eleve=eleve, statut='en_attente'):
            if mois_vises & mois_couverts(ancien.mois_reference, ancien.nb_mois_couverts):
                ancien.delete()

        paiement = Paiement(
            eleve=eleve, montant=montant_total, mois_reference=date_debut, nb_mois_couverts=nb_mois,
        )
        screenshot_upload = request.FILES.get('screenshot')
        if screenshot_upload is not None:
            justificatif = _preparer_justificatif(screenshot_upload)
            paiement.screenshot.save(justificatif.name, justificatif, save=False)
        paiement.save()

        fin_periode = _ajouter_mois(date_debut, nb_mois)
        envoyer_notification_telegram_async(
            f'💰 دفعة جديدة بانتظار المراجعة\n'
            f'الطالب: {eleve.user.get_full_name()}\n'
            f'— {mois_annee_ar(date_debut)} → {mois_annee_ar(fin_periode)} '
            f'({nb_mois} شهر) : {montant_total} د.م. '
            f'({request.build_absolute_uri(reverse("admin_paiement_detail", args=[paiement.id]))})'
        )
        if nb_mois > 1:
            messages.success(
                request,
                gettext_('تم إرسال إثبات الدفع لـ %(v0)s أشهر بنجاح، سيتم مراجعته من طرف الإدارة.') % {'v0': nb_mois},
            )
        else:
            messages.success(request, gettext_('تم إرسال إثبات الدفع بنجاح، سيتم مراجعته من طرف الإدارة.'))
        return redirect('eleve_paiements')

    paiements = Paiement.objects.filter(eleve=eleve).order_by('-mois_reference')
    # Page cible du groupe 🔔 « دفع متأخر » (chantier relances de paiement du
    # 2026-09-01) — marque ce type comme lu : le badge s'éteint jusqu'à ce
    # qu'un NOUVEAU cycle repasse en retard. L'état « en retard » lui-même
    # reste affiché sur cette page tant que le paiement n'est pas fait.
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'paiements_retard')

    # Formulaire (chantier « Paiement unique » du 2026-09-03) : date de début
    # PRÉ-REMPLIE avec le début du cycle ouvert mais MODIFIABLE par l'élève ;
    # il choisit aussi le nombre de mois et le montant total.
    from .cycles import cycle_courant
    cycle_ouvert = cycle_courant(eleve)
    periode_depart = cycle_ouvert.date_debut if cycle_ouvert else timezone.localdate()
    return render(request, 'dashboard/eleve_paiements.html', {
        'eleve': eleve,
        'paiements': paginer(request, paiements, 10),
        'periode_depart': periode_depart,
        'nb_mois_max': NB_MOIS_MAX_PAR_PERIODE,
    })


@role_required('admin', 'mshrif')
def admin_paiements(request):
    from courses.models import Groupe

    statut = request.GET.get('statut', '')
    eleve_id = request.GET.get('eleve', '')
    mois = request.GET.get('mois', '')
    groupe_id = request.GET.get('groupe', '')
    afficher_archives = request.GET.get('afficher_archives') == '1'

    paiements = Paiement.objects.select_related('eleve__user').order_by('-date')
    if statut:
        paiements = paiements.filter(statut=statut)
    if eleve_id:
        paiements = paiements.filter(eleve_id=eleve_id)
    if mois:
        annee, _, num_mois = mois.partition('-')
        paiements = paiements.filter(mois_reference__year=annee, mois_reference__month=num_mois)
    if groupe_id:
        # Paiement n'a pas de FK directe vers Groupe — passe par la relation
        # M2M Groupe.eleves (un élève peut être dans plusieurs halqas, chacun
        # de ses paiements matche alors si l'une d'elles est celle filtrée).
        paiements = paiements.filter(eleve__groupes__id=groupe_id)

    context = {
        'paiements': paginer(request, paiements, 10),
        'eleves': eleves_pour_filtre(afficher_archives, eleve_id),
        'groupes': Groupe.objects.order_by('nom'),
        'filtres': {
            'statut': statut,
            'eleve': eleve_id,
            'mois': mois,
            'groupe': groupe_id,
            'afficher_archives': afficher_archives,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # Page cible du groupe 🔔 « دفعة جديدة من الطالب » (chantier du
    # 2026-09-04, voir dashboard.notifications.notifications_direction) —
    # juste avant le render, jamais avant (même précaution que les autres
    # appelants de marquer_visite).
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'nouveaux_paiements')
    return render(request, 'dashboard/admin_paiements.html', context)


@role_required('admin', 'mshrif')
def admin_paiement_detail(request, paiement_id):
    paiement = get_object_or_404(Paiement, id=paiement_id)

    # « الفترة المطلوب دفعها » : durée totale de la demande (span début → fin
    # exclusive), jamais le détail mois par mois.
    # - Cas courant (chantier « Paiement unique » du 2026-09-03) : UN Paiement
    #   porte `nb_mois_couverts` -> la période est `mois_reference` →
    #   `_ajouter_mois(mois_reference, nb_mois_couverts)`, lue direct.
    # - Fallback LEGACY (paiements d'avant la migration 0011, créés en un
    #   Paiement PAR mois) : on regroupe les « frères » de la même soumission
    #   (même élève, même montant, `date` à ±120 s) pour reconstituer le span.
    from .cycles import _ajouter_mois

    if (paiement.nb_mois_couverts or 1) > 1:
        periode_debut = paiement.mois_reference
        periode_fin = _ajouter_mois(paiement.mois_reference, paiement.nb_mois_couverts)
    else:
        fenetre = datetime.timedelta(seconds=120)
        lot = list(
            Paiement.objects.filter(
                eleve=paiement.eleve,
                montant=paiement.montant,
                nb_mois_couverts=1,
                date__gte=paiement.date - fenetre,
                date__lte=paiement.date + fenetre,
            ).order_by('mois_reference')
        )
        if paiement not in lot:  # garde-fou : le paiement courant fait toujours partie du lot
            lot = [paiement]
        periode_debut = lot[0].mois_reference
        periode_fin = _ajouter_mois(lot[-1].mois_reference, 1)

    context = {
        'paiement': paiement,
        'periode_debut': periode_debut,
        'periode_fin': periode_fin,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # 2e "page cible" du groupe 🔔 « دفعة جديدة من الطالب » (le lien de
    # notification pointe ICI, la fiche d'un paiement précis, pas vers
    # admin_paiements la liste, déjà câblée plus haut) — même précaution que
    # les autres appelants de marquer_visite (juste avant le render).
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'nouveaux_paiements')
    return render(request, 'dashboard/admin_paiement_detail.html', context)


@role_required('admin', 'mshrif')
def suivi_paiements_eleves(request):
    """Vue organisée Groupe -> Élève -> mois avec statut payé/non payé, du mois
    d'inscription de l'élève (user.date_joined) au mois courant. Un mois est
    considéré payé si au moins un Paiement statut='valide' existe pour cet
    élève ce mois-là (agrégation simple sur mois_reference, pas un système
    d'échéances — mois_reference n'est pas garanti au 1er du mois car saisi
    par l'élève via un champ date libre, d'où le filtre year/month plutôt
    qu'une égalité de date).

    Écran maître-détail (Tâche 7 du 2026-07-25) : chaque cellule élève × mois
    est cliquable (?panel_eleve=&panel_mois=) et ouvre un panneau modal sur
    cette même page (jamais de navigation vers une autre entrée sidebar) pour
    voir/créer/modifier le Paiement correspondant — voir paiement_panel_sauvegarder.
    L'ancienne page 'إدارة المدفوعات' (admin_paiements) n'est ni modifiée ni
    retirée du sidebar : elle reste jusqu'à validation explicite du nouveau flux."""
    from django.utils import timezone
    from courses.models import Groupe

    aujourdhui = timezone.localdate()
    groupe_id = request.GET.get('groupe', '')
    impayes_seulement = request.GET.get('impayes') == '1'

    # Correctif perf du 2026-08-30 : les 2 requêtes Paiement ci-dessous
    # chargeaient TOUTE la table à chaque ouverture de cette page, même
    # quand ?groupe= filtrait déjà l'affichage à un seul groupe — une table
    # qui ne fait que grandir avec le temps (1 Paiement par élève par mois
    # payé), contrairement aux N+1 "classiques" qui restent bornés par le
    # nombre d'élèves. Quand un groupe précis est demandé, on ne charge que
    # les paiements des élèves de CE groupe (tous statuts d'élève confondus,
    # pas seulement 'actif' : un élève archivé garde son historique
    # consultable ici, voir plus bas). Sans filtre ?groupe=, la vue affiche
    # volontairement tous les groupes -> aucun scope possible sans changer
    # l'UX (pagination, voir AUDIT_PERFORMANCE_2026-08-30.md point 2.3/9).
    eleves_scope_ids = None
    if groupe_id:
        eleves_scope_ids = list(
            Groupe.objects.filter(id=groupe_id).values_list('eleves__id', flat=True)
        )

    paiements_scope = Paiement.objects.all()
    if eleves_scope_ids is not None:
        paiements_scope = paiements_scope.filter(eleve_id__in=eleves_scope_ids)

    # Tous statuts confondus (pas seulement 'valide') pour que le panneau
    # puisse retrouver/modifier un paiement 'en_attente' ou 'rejete' existant,
    # pas seulement en créer un nouveau par-dessus.
    # Un Paiement multi-mois (chantier « Paiement unique » du 2026-09-03)
    # couvre plusieurs cellules (mois_reference .. +nb_mois_couverts) : chaque
    # cellule couverte pointe vers CE Paiement (clic n'importe où -> même
    # fiche). mois_couverts étend la fenêtre.
    from .cycles import _ajouter_mois, mois_couverts
    from .models import CycleAbonnement

    paiement_par_cellule = {}
    for p in paiements_scope:
        for (annee, mois) in mois_couverts(p.mois_reference, p.nb_mois_couverts):
            paiement_par_cellule[(p.eleve_id, annee, mois)] = p

    mois_payes_par_eleve = {}
    for eleve_id, mr, nb in paiements_scope.filter(statut='valide').values_list(
        'eleve_id', 'mois_reference', 'nb_mois_couverts'
    ):
        mois_payes_par_eleve.setdefault(eleve_id, set()).update(mois_couverts(mr, nb))

    # Jour d'ancrage des périodes de chaque élève (chantier « cycle roulant »
    # du 2026-09-03) : la date_debut de son cycle nº 1. Prefetch pour rester à
    # nombre de requêtes constant (jamais O(élèves)). Repli sur date_joined
    # pour un élève sans cycle (cas résiduel : validé avant le backfill 0007,
    # ou données anciennes).
    cycles1_qs = CycleAbonnement.objects.filter(numero=1)
    if eleves_scope_ids is not None:
        cycles1_qs = cycles1_qs.filter(eleve_id__in=eleves_scope_ids)
    cycle1_par_eleve = dict(cycles1_qs.values_list('eleve_id', 'date_debut'))

    groupes_qs = Groupe.objects.prefetch_related('eleves__user').order_by('nom')
    if groupe_id:
        groupes_qs = groupes_qs.filter(id=groupe_id)

    donnees = []
    for groupe in groupes_qs:
        lignes_eleves = []
        # exclude(statut='archive') — sinon un élève archivé accumule indéfiniment
        # des mois "غير مدفوع" fantômes après son archivage, alors qu'aucun nouveau
        # paiement ne peut plus être créé pour lui (chantier d'archivage du
        # 2026-08-03). Son historique de paiements passés reste consultable via
        # 'إدارة المدفوعات' (admin_paiements), non filtrée.
        for eleve in groupe.eleves.exclude(statut='archive'):
            ancre = cycle1_par_eleve.get(eleve.id) or eleve.user.date_joined.date()
            mois_payes = mois_payes_par_eleve.get(eleve.id, set())
            mois_liste = []
            i = 0
            while i < 600:  # borne dure (~50 ans) — jamais atteinte en pratique
                debut = _ajouter_mois(ancre, i)
                if debut > aujourdhui:
                    break
                fin = _ajouter_mois(ancre, i + 1)
                cle = (debut.year, debut.month)
                mois_liste.append({
                    'label': debut,
                    'label_fin': fin,
                    'paye': cle in mois_payes,
                    'cle_mois': f'{debut.year}-{debut.month:02d}',
                    'paiement': paiement_par_cellule.get((eleve.id, debut.year, debut.month)),
                })
                i += 1
            mois_liste.reverse()
            # "أظهر غير المدفوعين فقط" doit montrer UNIQUEMENT les mois impayes --
            # fix Tache du 2026-08-04 (signale par le client) : l'ancien filtre ne
            # decidait QUE quels eleves afficher (masquait ceux entierement a jour)
            # mais gardait ensuite TOUS leurs mois, payes inclus, dans la ligne --
            # un eleve avec ne serait-ce qu'un seul mois impaye affichait donc
            # aussi tous ses mois payes a cote.
            if impayes_seulement:
                mois_liste = [m for m in mois_liste if not m['paye']]
                if not mois_liste:
                    continue
            # Limité aux 12 mois les plus récents par défaut + bouton "عرض الكل"
            # (Tâche 22 Partie F du 2026-07-26) — un élève inscrit depuis
            # plusieurs années afficherait sinon des dizaines de badges d'un coup.
            lignes_eleves.append({
                'eleve': eleve,
                'mois_liste_recents': mois_liste[:12],
                'mois_liste_anciens': mois_liste[12:],
                'nb_mois_total': len(mois_liste),
            })
        if lignes_eleves:
            donnees.append({'groupe': groupe, 'eleves': lignes_eleves})

    # Panneau détail — ouvert si ?panel_eleve=&panel_mois= sont présents.
    panel = None
    panel_eleve_id = request.GET.get('panel_eleve', '')
    panel_mois = request.GET.get('panel_mois', '')
    if panel_eleve_id and panel_mois:
        panel_eleve = Eleve.objects.select_related('user').filter(id=panel_eleve_id).first()
        try:
            p_annee, p_mois = (int(x) for x in panel_mois.split('-'))
        except ValueError:
            p_annee = p_mois = None
        if panel_eleve and p_annee:
            from .cycles import periode_bornes
            paiement_cellule = paiement_par_cellule.get((panel_eleve.id, p_annee, p_mois))
            if paiement_cellule is not None:
                # Bornes RÉELLES du Paiement qui couvre cette cellule (peut
                # s'étendre sur plusieurs mois).
                p_debut = paiement_cellule.mois_reference
                p_fin = paiement_cellule.periode_fin
            else:
                p_debut, p_fin = periode_bornes(panel_eleve, p_annee, p_mois)
            panel = {
                'eleve': panel_eleve,
                'mois': panel_mois,
                'mois_label': p_debut,
                'mois_label_fin': p_fin,
                'paiement': paiement_cellule,
                'peut_modifier': request.user.role == 'admin',
            }

    context = {
        'donnees': donnees,
        'groupes': Groupe.objects.order_by('nom'),
        'filtres': {
            'groupe': groupe_id,
            'impayes': impayes_seulement,
        },
        'panel': panel,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'dashboard/suivi_paiements_eleves.html', context)


@role_required('admin')
def paiement_panel_sauvegarder(request):
    """Crée ou met à jour le Paiement d'un élève pour un mois donné depuis le
    panneau détail de suivi_paiements_eleves (voir Tâche 7). مشرف exclu (accès
    lecture seule aux paiements, comme partout ailleurs sur cette page)."""
    from django.urls import reverse
    from django.utils import timezone

    if request.method != 'POST':
        return redirect('suivi_paiements_eleves')

    eleve = get_object_or_404(Eleve, id=request.POST.get('eleve_id'))
    if eleve.statut == 'archive':
        messages.error(request, gettext_('تعذر الحفظ: %(v0)s مؤرشف.') % {'v0': eleve.user.get_full_name()})
        return redirect('suivi_paiements_eleves')
    mois_str = request.POST.get('mois', '')
    try:
        annee, mois_num = (int(x) for x in mois_str.split('-'))
    except ValueError:
        messages.error(request, gettext_('صيغة الشهر غير صحيحة.'))
        return redirect('suivi_paiements_eleves')

    # Retrouve le Paiement dont la fenêtre couverte (mois_reference ..
    # +nb_mois_couverts) contient ce mois — un Paiement multi-mois est modifié
    # EN ENTIER depuis n'importe laquelle de ses cellules.
    from .cycles import mois_couverts, periode_bornes
    paiement = next(
        (
            p for p in Paiement.objects.filter(eleve=eleve)
            if (annee, mois_num) in mois_couverts(p.mois_reference, p.nb_mois_couverts)
        ),
        None,
    )
    if paiement is None:
        # Nouveau Paiement (1 mois) ancré sur le DÉBUT réel de la période de
        # l'élève (jour d'ancrage 10→10…) et non le 1er du mois.
        debut_periode, _fin = periode_bornes(eleve, annee, mois_num)
        paiement = Paiement(
            eleve=eleve, mois_reference=debut_periode, nb_mois_couverts=1,
            soumis_par_eleve=False,
        )

    paiement.montant = request.POST.get('montant') or 0
    nouveau_statut = request.POST.get('statut', 'en_attente')
    if nouveau_statut in ('valide', 'rejete') and nouveau_statut != paiement.statut:
        paiement.valide_par = request.user
        paiement.date_validation = timezone.now()
    paiement.statut = nouveau_statut
    if request.FILES.get('screenshot'):
        paiement.screenshot = _preparer_justificatif(request.FILES['screenshot'])
    paiement.save()

    # Chantier relances de paiement (2026-09-01) : toute création/modification
    # de Paiement peut faire avancer un cycle d'abonnement — voir payments.cycles.
    from .cycles import reconcilier
    reconcilier(eleve)

    messages.success(request, gettext_('تم حفظ دفعة %(v0)s.') % {'v0': eleve.user.get_full_name()})
    return redirect(f"{reverse('suivi_paiements_eleves')}?panel_eleve={eleve.id}&panel_mois={mois_str}")


@role_required('admin')
def admin_paiement_valider(request, paiement_id):
    from django.utils import timezone
    from .cycles import reconcilier

    paiement = get_object_or_404(Paiement, id=paiement_id)
    paiement.statut = 'valide'
    paiement.valide_par = request.user
    paiement.date_validation = timezone.now()
    paiement.save()
    # Fait avancer les cycles d'abonnement que ce paiement vient de couvrir
    # (chantier relances de paiement du 2026-09-01) — voir payments.models.
    # CycleAbonnement / payments.cycles.
    reconcilier(paiement.eleve)
    messages.success(request, gettext_('تم قبول الدفعة.'))
    return redirect('admin_paiement_detail', paiement_id=paiement.id)


@role_required('admin')
def admin_paiement_rejeter(request, paiement_id):
    from django.utils import timezone

    paiement = get_object_or_404(Paiement, id=paiement_id)
    paiement.statut = 'rejete'
    paiement.valide_par = request.user
    paiement.date_validation = timezone.now()
    paiement.save()
    messages.info(request, gettext_('تم رفض الدفعة.'))
    return redirect('admin_paiement_detail', paiement_id=paiement.id)


def _message_relance_whatsapp(modele, eleve, cycle, jours_retard):
    """Remplit les espaces réservés du message de relance WhatsApp
    (ReglageRelanceWhatsApp.message, modifiable par مدير/مشرف). `str.replace`
    et non `str.format` : le texte est libre et peut contenir des accolades
    isolées ou un espace réservé inconnu — aucun de ces cas ne doit lever."""
    remplacements = {
        '{nom}': eleve.user.get_full_name(),
        '{date_echeance}': cycle.date_echeance.strftime('%d-%m-%Y'),
        '{jours_retard}': str(jours_retard),
    }
    for cle, valeur in remplacements.items():
        modele = modele.replace(cle, valeur)
    return modele


@role_required('admin', 'mshrif')
def paiements_retards(request):
    """Liste des élèves actifs en retard de paiement (cycle courant échu, rien
    de non-rejeté ne le couvre) — page cible du panneau 🔔 du مدير/مشرف (voir
    dashboard.notifications.notifications_direction). 2 actions par ligne :
    « الانتظار » (retour, aucun effet — décision du client : les relances
    continuent) et « أرشفة » (archivage réversible, مدير + مشرف depuis la
    Tâche du 2026-09-02 — la vue admin_eleve_archiver est
    @role_required('admin', 'mshrif'))."""
    from django.utils import timezone
    from .cycles import eleves_en_retard, RELANCE_JOUR_AVERT_2J
    from .models import get_reglage_relance_whatsapp

    aujourdhui = timezone.localdate()
    modele_message = get_reglage_relance_whatsapp().message
    lignes = []
    for eleve, cycle in eleves_en_retard(avec_groupes=True):
        jours_retard = (aujourdhui - cycle.date_echeance).days
        lignes.append({
            'eleve': eleve,
            'cycle': cycle,
            'jours_retard': jours_retard,
            # À partir de J+8 l'élève voit un avertissement de désactivation
            # imminente dans sa cloche 🔔 (payments.cycles.phase_relance_eleve) :
            # on le signale ici en rouge pour que la direction sache qu'il est
            # temps d'archiver (l'archivage reste MANUEL — bouton أرشفة).
            'urgent': jours_retard >= RELANCE_JOUR_AVERT_2J,
            'groupes': list(eleve.groupes.all()),
            'message_whatsapp': _message_relance_whatsapp(
                modele_message, eleve, cycle, jours_retard
            ),
        })
    lignes.sort(key=lambda l: l['jours_retard'], reverse=True)

    context = {
        'lignes': lignes,
        'peut_archiver': request.user.role in ('admin', 'mshrif'),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    # Page cible du groupe 🔔 « طلاب متأخرون عن الدفع » — éteint le badge (mais
    # la liste ci-dessus reste toujours affichée, même badge éteint). Juste
    # avant le render, jamais avant (même précaution que les autres appelants
    # de marquer_visite : au cas où la vue redirigerait plus tôt un jour).
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'paiements_retard_eleves')
    return render(request, 'dashboard/paiements_retards.html', context)
