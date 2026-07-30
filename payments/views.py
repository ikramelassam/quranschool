import datetime

from django.shortcuts import render, redirect, get_object_or_404
from django.urls import reverse
from django.contrib import messages
from accounts.decorators import role_required
from core.utils import paginer, envoyer_notification_telegram
from accounts.models import Eleve
from .models import Paiement


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
        from dashboard.templatetags.libelles_arabes import mois_annee_ar

        paiement = Paiement.objects.create(
            eleve=eleve,
            montant=request.POST.get('montant'),
            mois_reference=request.POST.get('mois_reference'),
            screenshot=request.FILES.get('screenshot'),
        )
        # .create() ne convertit pas mois_reference (chaîne POST brute) en objet
        # date en mémoire — nécessaire pour mois_annee_ar() ci-dessous.
        paiement.refresh_from_db()
        lien_fiche = request.build_absolute_uri(
            reverse('admin_paiement_detail', args=[paiement.id])
        )
        envoyer_notification_telegram(
            f'💰 دفعة جديدة بانتظار المراجعة\n'
            f'الطالب: {eleve.user.get_full_name()}\n'
            f'المبلغ: {paiement.montant} د.م.\n'
            f'الشهر المعني: {mois_annee_ar(paiement.mois_reference)}\n'
            f'رابط الملف: {lien_fiche}'
        )
        messages.success(request, 'تم إرسال إثبات الدفع بنجاح، سيتم مراجعته من طرف الإدارة.')
        return redirect('eleve_paiements')

    paiements = Paiement.objects.filter(eleve=eleve).order_by('-mois_reference')
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
        'eleves': Eleve.objects.select_related('user').order_by('user__first_name'),
        'groupes': Groupe.objects.order_by('nom'),
        'filtres': {
            'statut': statut,
            'eleve': eleve_id,
            'mois': mois,
            'groupe': groupe_id,
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

    # Tous statuts confondus (pas seulement 'valide') pour que le panneau
    # puisse retrouver/modifier un paiement 'en_attente' ou 'rejete' existant,
    # pas seulement en créer un nouveau par-dessus.
    paiement_par_cellule = {}
    for p in Paiement.objects.all():
        cle = (p.eleve_id, p.mois_reference.year, p.mois_reference.month)
        paiement_par_cellule[cle] = p

    mois_payes_par_eleve = {}
    for eleve_id, annee, mois in Paiement.objects.filter(statut='valide').values_list(
        'eleve_id', 'mois_reference__year', 'mois_reference__month'
    ):
        mois_payes_par_eleve.setdefault(eleve_id, set()).add((annee, mois))

    groupes_qs = Groupe.objects.prefetch_related('eleves__user').order_by('nom')
    if groupe_id:
        groupes_qs = groupes_qs.filter(id=groupe_id)

    donnees = []
    for groupe in groupes_qs:
        lignes_eleves = []
        for eleve in groupe.eleves.all():
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
            # "أظهر غير المدفوعين فقط" masque les élèves entièrement à jour — utile
            # pour relancer vite les bonnes familles — mais garde l'historique complet
            # (tous les mois, pas seulement les impayés) pour ceux qui restent affichés,
            # afin de ne pas perdre le contexte de paiement déjà en place sur la page.
            if impayes_seulement and not any(not m['paye'] for m in mois_liste):
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
    mois_str = request.POST.get('mois', '')
    try:
        annee, mois_num = (int(x) for x in mois_str.split('-'))
    except ValueError:
        messages.error(request, 'صيغة الشهر غير صحيحة.')
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

    messages.success(request, f'تم حفظ دفعة {eleve.user.get_full_name()}.')
    return redirect(f"{reverse('suivi_paiements_eleves')}?panel_eleve={eleve.id}&panel_mois={mois_str}")


@role_required('admin')
def admin_paiement_valider(request, paiement_id):
    from django.utils import timezone

    paiement = get_object_or_404(Paiement, id=paiement_id)
    paiement.statut = 'valide'
    paiement.valide_par = request.user
    paiement.date_validation = timezone.now()
    paiement.save()
    messages.success(request, 'تم قبول الدفعة.')
    return redirect('admin_paiement_detail', paiement_id=paiement.id)


@role_required('admin')
def admin_paiement_rejeter(request, paiement_id):
    from django.utils import timezone

    paiement = get_object_or_404(Paiement, id=paiement_id)
    paiement.statut = 'rejete'
    paiement.valide_par = request.user
    paiement.date_validation = timezone.now()
    paiement.save()
    messages.info(request, 'تم رفض الدفعة.')
    return redirect('admin_paiement_detail', paiement_id=paiement.id)
