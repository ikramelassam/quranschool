import datetime

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


def _mois_entre_inclus(date_debut, date_fin):
    """Liste de date(annee, mois, 1) — un par mois — du mois de `date_debut`
    au mois de `date_fin` INCLUS (le jour exact du mois dans `date_debut`/
    `date_fin` n'a jamais d'importance, seul le couple année/mois compte,
    exactement comme partout ailleurs où Paiement.mois_reference est comparé
    — voir payments.views.suivi_paiements_eleves, qui groupe déjà par
    mois_reference__year/__month plutôt que par égalité de date exacte).
    `date_debut` et `date_fin` dans le MÊME mois -> liste à un seul élément,
    comportement strictement identique à l'ancien champ "الشهر المعني" (un
    seul mois par soumission)."""
    mois = []
    annee, num_mois = date_debut.year, date_debut.month
    while (annee, num_mois) <= (date_fin.year, date_fin.month):
        mois.append(datetime.date(annee, num_mois, 1))
        num_mois += 1
        if num_mois > 12:
            num_mois = 1
            annee += 1
    return mois


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

        # Chantier du 2026-08-24 : sélecteur de PÉRIODE ("من تاريخ"/"إلى
        # تاريخ") en remplacement de l'ancien champ unique "الشهر المعني" —
        # même page, même modèle Paiement (toujours un Paiement PAR mois,
        # unique_together (eleve, mois_reference) inchangé), juste une
        # boucle sur tous les mois de la période au lieu d'une création
        # unique. Une période sur un seul mois (من/إلى identiques) reproduit
        # exactement l'ancien comportement.
        try:
            date_debut = datetime.date.fromisoformat(request.POST.get('date_debut', ''))
            date_fin = datetime.date.fromisoformat(request.POST.get('date_fin', ''))
        except (ValueError, TypeError):
            messages.error(request, gettext_('يرجى إدخال فترة صحيحة ("من تاريخ" و"إلى تاريخ").'))
            return redirect('eleve_paiements')

        if date_fin < date_debut:
            messages.error(request, gettext_('"إلى تاريخ" يجب أن يكون بعد "من تاريخ" أو مساوياً له.'))
            return redirect('eleve_paiements')

        mois_periode = _mois_entre_inclus(date_debut, date_fin)
        if len(mois_periode) > NB_MOIS_MAX_PAR_PERIODE:
            messages.error(
                request,
                gettext_('المدة المختارة طويلة جداً (%(v0)s شهراً) — الحد الأقصى %(v1)s شهراً في نفس الإرسال.') % {'v0': len(mois_periode), 'v1': NB_MOIS_MAX_PAR_PERIODE},
            )
            return redirect('eleve_paiements')

        # Fichier lu UNE SEULE FOIS (chantier du 2026-08-24) : le même
        # justificatif peut couvrir plusieurs mois -> plusieurs Paiement
        # distincts, chacun avec sa PROPRE copie du fichier (ContentFile,
        # jamais le même objet UploadedFile réutilisé directement sur
        # plusieurs .save() — son flux serait déjà épuisé après la 1ère
        # écriture).
        screenshot_upload = request.FILES.get('screenshot')
        contenu_screenshot = screenshot_upload.read() if screenshot_upload else None

        montant = request.POST.get('montant')
        seuil_anti_doublon = timezone.now() - datetime.timedelta(seconds=FENETRE_ANTI_DOUBLON_SECONDES)
        mois_crees, mois_deja_existants = [], []
        for mois in mois_periode:
            # Idempotent par construction : un mois déjà enregistré (peu
            # importe son statut — قيد المراجعة/مقبول/مرفوض, la contrainte
            # unique_together interdit de toute façon un 2e Paiement pour ce
            # même mois) est simplement ignoré, jamais une IntegrityError non
            # rattrapée. La fenêtre anti-doublon (FENETRE_ANTI_DOUBLON_SECONDES)
            # reste la protection contre un VRAI double-clic quasi-simultané
            # sur un mois pas encore visible par ce check.
            deja_present = Paiement.objects.filter(
                eleve=eleve, mois_reference__year=mois.year, mois_reference__month=mois.month,
            ).exists()
            deja_soumis_a_linstant = Paiement.objects.filter(
                eleve=eleve, montant=montant, mois_reference=mois, date__gte=seuil_anti_doublon,
            ).exists()
            if deja_present or deja_soumis_a_linstant:
                mois_deja_existants.append(mois)
                continue

            paiement = Paiement(eleve=eleve, montant=montant, mois_reference=mois)
            if contenu_screenshot is not None:
                paiement.screenshot.save(screenshot_upload.name, ContentFile(contenu_screenshot), save=False)
            paiement.save()
            mois_crees.append(paiement)

        if mois_crees:
            lignes_mois = '\n'.join(
                f'— {mois_annee_ar(p.mois_reference)} : {p.montant} د.م. '
                f'({request.build_absolute_uri(reverse("admin_paiement_detail", args=[p.id]))})'
                for p in mois_crees
            )
            envoyer_notification_telegram_async(
                f'💰 دفعة جديدة بانتظار المراجعة\n'
                f'الطالب: {eleve.user.get_full_name()}\n'
                f'{lignes_mois}'
            )
            messages.success(
                request,
                gettext_('تم إرسال إثبات الدفع لـ %(v0)s شهر بنجاح، سيتم مراجعته من طرف الإدارة.') % {'v0': len(mois_crees)}
                if len(mois_crees) > 1 else gettext_('تم إرسال إثبات الدفع بنجاح، سيتم مراجعته من طرف الإدارة.')
            )
        if mois_deja_existants:
            noms = '، '.join(mois_annee_ar(m) for m in mois_deja_existants)
            messages.info(request, gettext_('الأشهر التالية كانت مسجلة مسبقاً ولم تُرسَل مجدداً: %(v0)s') % {'v0': noms})
        return redirect('eleve_paiements')

    paiements = Paiement.objects.filter(eleve=eleve).order_by('-mois_reference')
    # Page cible du groupe 🔔 « دفع متأخر » (chantier relances de paiement du
    # 2026-09-01) — marque ce type comme lu : le badge s'éteint jusqu'à ce
    # qu'un NOUVEAU cycle repasse en retard. L'état « en retard » lui-même
    # reste affiché sur cette page tant que le paiement n'est pas fait.
    from dashboard.notifications import marquer_visite
    marquer_visite(request.user, 'paiements_retard')
    return render(request, 'dashboard/eleve_paiements.html', {
        'eleve': eleve,
        'paiements': paginer(request, paiements, 10),
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
    return render(request, 'dashboard/admin_paiements.html', context)


@role_required('admin', 'mshrif')
def admin_paiement_detail(request, paiement_id):
    paiement = get_object_or_404(Paiement, id=paiement_id)
    context = {
        'paiement': paiement,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
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
    paiement_par_cellule = {}
    for p in paiements_scope:
        cle = (p.eleve_id, p.mois_reference.year, p.mois_reference.month)
        paiement_par_cellule[cle] = p

    mois_payes_par_eleve = {}
    for eleve_id, annee, mois in paiements_scope.filter(statut='valide').values_list(
        'eleve_id', 'mois_reference__year', 'mois_reference__month'
    ):
        mois_payes_par_eleve.setdefault(eleve_id, set()).add((annee, mois))

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
            depart = eleve.user.date_joined.date()
            annee, mois = depart.year, depart.month
            mois_payes = mois_payes_par_eleve.get(eleve.id, set())
            mois_liste = []
            while (annee, mois) <= (aujourdhui.year, aujourdhui.month):
                mois_liste.append({
                    'label': datetime.date(annee, mois, 1),
                    'paye': (annee, mois) in mois_payes,
                    'cle_mois': f'{annee}-{mois:02d}',
                    'paiement': paiement_par_cellule.get((eleve.id, annee, mois)),
                })
                mois += 1
                if mois > 12:
                    mois = 1
                    annee += 1
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
            panel = {
                'eleve': panel_eleve,
                'mois': panel_mois,
                'mois_label': datetime.date(p_annee, p_mois, 1),
                'paiement': paiement_par_cellule.get((panel_eleve.id, p_annee, p_mois)),
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

    # Retrouve le Paiement existant pour ce mois (peu importe le jour exact de
    # mois_reference, saisi librement par l'élève à l'origine) plutôt que de
    # risquer un doublon via get_or_create sur une date arbitraire (le 1er du
    # mois) qui ne matcherait pas un enregistrement déjà là à un autre jour.
    paiement = Paiement.objects.filter(
        eleve=eleve, mois_reference__year=annee, mois_reference__month=mois_num
    ).first()
    if paiement is None:
        paiement = Paiement(eleve=eleve, mois_reference=datetime.date(annee, mois_num, 1))

    paiement.montant = request.POST.get('montant') or 0
    nouveau_statut = request.POST.get('statut', 'en_attente')
    if nouveau_statut in ('valide', 'rejete') and nouveau_statut != paiement.statut:
        paiement.valide_par = request.user
        paiement.date_validation = timezone.now()
    paiement.statut = nouveau_statut
    if request.FILES.get('screenshot'):
        paiement.screenshot = request.FILES['screenshot']
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
