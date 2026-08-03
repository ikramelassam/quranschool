from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from accounts.decorators import role_required
from core.utils import paginer
from .models import Groupe, Creneau, HistoriqueGroupeEleve
from .utils import regenerer_pour_nouveau_creneau, creneaux_manquants_pour_prof, raison_incompatibilite_groupe, avertissements_groupe, avertissements_prof_creneau
from accounts.models import Prof, Eleve


def _base_template_admin_ou_mshrif(request):
    """Équivalent local de dashboard.views._base_template_admin_ou_mshrif — pages
    admin de gestion des groupes/créneaux réutilisées en lecture seule par المشرف."""
    return 'dashboard/base_mshrif.html' if request.user.role == 'mshrif' else 'dashboard/base_admin.html'


def _contexte_base_mshrif(request):
    """Équivalent local de dashboard.views._contexte_base_mshrif (badge sidebar)."""
    if request.user.role != 'mshrif':
        return {}
    from inscriptions.models import InscriptionProf
    return {'nb_demandes_en_attente': InscriptionProf.objects.filter(statut='validee_directeur').count()}


def _message_incompatibilite(prof, manquants):
    jours_dict = dict(Creneau.JOUR_CHOICES)
    details = '، '.join(f'{jours_dict.get(j, j)} {h.strftime("%H:%M")}' for j, h in manquants)
    return (
        f'لا يمكن إسناد {prof.user.get_full_name()} لهذه الحلقة: '
        f'هذا المعلم غير متفرغ في الأوقات التالية حسب جدول تفرغه المعتمد: {details}.'
    )


@role_required('admin', 'mshrif')
def groupes_list(request):
    statut = request.GET.get('statut', '')
    prof_id = request.GET.get('prof', '')
    creneau_id = request.GET.get('creneau', '')

    groupes = Groupe.objects.select_related('prof__user', 'creneau').order_by('id')
    if statut:
        groupes = groupes.filter(statut=statut)
    if prof_id:
        groupes = groupes.filter(prof_id=prof_id)
    if creneau_id:
        groupes = groupes.filter(creneau_id=creneau_id)

    context = {
        'groupes': paginer(request, groupes, 10),
        'aucun_creneau': not Creneau.objects.filter(est_actif=True).exists(),
        'profs': Prof.actifs.select_related('user').order_by('user__first_name'),
        'creneaux': Creneau.objects.order_by('id'),
        'filtres': {
            'statut': statut,
            'prof': prof_id,
            'creneau': creneau_id,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'courses/admin_groupes.html', context)


@role_required('admin')
def groupe_ajouter(request):
    creneaux = Creneau.objects.filter(est_actif=True)
    profs = Prof.actifs.all()

    if request.method == 'POST':
        creneau_id = request.POST.get('creneau')
        if not creneau_id:
            messages.error(request, 'يجب اختيار حلقة قبل إنشاء المجموعة. أنشئ حلقة أولاً إذا لم تتوفر أي حلقة.')
            return render(request, 'courses/admin_groupe_ajouter.html', {
                'creneaux': creneaux,
                'profs': profs,
            })

        prof_id = request.POST.get('prof') or None
        confirme = request.POST.get('confirme') == '1'
        avertissements_prof = []
        if prof_id:
            # Revalidé côté serveur même si le <select> exclut déjà les profs
            # archivés (Prof.actifs) — se protège contre un POST direct avec un
            # id manipulé (chantier d'archivage du 2026-08-03).
            prof_obj = get_object_or_404(Prof, id=prof_id)
            if prof_obj.statut == 'archive':
                messages.error(request, f'تعذّر إسناد {prof_obj.user.get_full_name()}: هذا الأستاذ مؤرشف.')
                return render(request, 'courses/admin_groupe_ajouter.html', {
                    'creneaux': creneaux,
                    'profs': profs,
                })
            creneau_obj = get_object_or_404(Creneau, id=creneau_id)
            manquants = creneaux_manquants_pour_prof(prof_obj, creneau_obj)
            if manquants:
                messages.error(request, _message_incompatibilite(prof_obj, manquants))
                return render(request, 'courses/admin_groupe_ajouter.html', {
                    'creneaux': creneaux,
                    'profs': profs,
                })

            avertissements_prof = avertissements_prof_creneau(prof_obj, creneau_obj)
            if avertissements_prof and not confirme:
                groupe_previsualise = Groupe(
                    nom=request.POST.get('nom'),
                    prof_id=prof_id,
                    creneau_id=creneau_id,
                    description=request.POST.get('description', ''),
                    capacite_max=request.POST.get('max_eleves', 10),
                    type_capacite=request.POST.get('type_capacite', 'groupe'),
                    lien_reunion=request.POST.get('lien_reunion', ''),
                )
                return render(request, 'courses/admin_groupe_ajouter.html', {
                    'creneaux': creneaux,
                    'profs': profs,
                    'groupe': groupe_previsualise,
                    'avertissements_prof': avertissements_prof,
                })

        groupe = Groupe.objects.create(
            nom=request.POST.get('nom'),
            prof_id=prof_id,
            creneau_id=creneau_id,
            description=request.POST.get('description', ''),
            capacite_max=request.POST.get('max_eleves', 10),
            type_capacite=request.POST.get('type_capacite', 'groupe'),
            lien_reunion=request.POST.get('lien_reunion', ''),
        )
        regenerer_pour_nouveau_creneau(groupe)
        for avertissement in avertissements_prof:
            messages.warning(request, avertissement)
        messages.success(request, 'تمت إضافة المجموعة وتوليد حصصها تلقائياً بنجاح.')
        return redirect('admin_groupes')

    return render(request, 'courses/admin_groupe_ajouter.html', {
        'creneaux': creneaux,
        'profs': profs,
    })


def _ajouter_eleve_au_groupe(eleve, groupe):
    """Ajout effectif (M2M + ouverture d'une ligne d'historique) — utilisé par
    l'ajout direct, la confirmation après avertissement, et le transfert."""
    groupe.eleves.add(eleve)
    HistoriqueGroupeEleve.objects.create(eleve=eleve, groupe=groupe)


def _retirer_eleve_du_groupe(eleve, groupe):
    """Retrait effectif (M2M + fermeture de la ligne d'historique ouverte).
    Ne touche jamais aux Presence/Evaluation passées: elles sont liées à la
    Seance, pas à l'appartenance M2M au groupe (Tâche 18 du 2026-07-26)."""
    groupe.eleves.remove(eleve)
    HistoriqueGroupeEleve.objects.filter(eleve=eleve, groupe=groupe, date_fin__isnull=True).update(date_fin=timezone.now())


@role_required('admin', 'mshrif')
def groupe_detail(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleves_disponibles = Eleve.actifs.exclude(groupes=groupe)
    autres_groupes_actifs = (
        Groupe.objects.filter(statut='actif')
        .exclude(id=groupe.id)
        .exclude(prof__statut='archive')
        .select_related('creneau')
    )

    # État "en attente de confirmation" (Tâche 18, Partie D) — recalculé à
    # chaque affichage à partir du seul ID transmis par l'URL, jamais depuis
    # un avertissement mémorisé côté client, pour ne jamais afficher un
    # avertissement obsolète ou fabriqué.
    eleve_en_attente = None
    avertissements_en_attente = []
    action_en_attente = None
    destination_en_attente = None

    confirmer_ajout_id = request.GET.get('confirmer_ajout')
    confirmer_transfert_id = request.GET.get('confirmer_transfert')
    destination_id = request.GET.get('destination')

    if confirmer_ajout_id:
        candidat = Eleve.objects.filter(id=confirmer_ajout_id).select_related('user').first()
        if candidat and raison_incompatibilite_groupe(candidat, groupe) is None:
            avertissements = avertissements_groupe(candidat, groupe)
            if avertissements:
                eleve_en_attente = candidat
                avertissements_en_attente = avertissements
                action_en_attente = 'ajout'
    elif confirmer_transfert_id and destination_id:
        candidat = Eleve.objects.filter(id=confirmer_transfert_id).select_related('user').first()
        destination = Groupe.objects.filter(id=destination_id).select_related('creneau').first()
        if candidat and destination and raison_incompatibilite_groupe(candidat, destination) is None:
            avertissements = avertissements_groupe(candidat, destination)
            if avertissements:
                eleve_en_attente = candidat
                avertissements_en_attente = avertissements
                action_en_attente = 'transfert'
                destination_en_attente = destination

    context = {
        'groupe': groupe,
        'eleves_disponibles': eleves_disponibles,
        'autres_groupes_actifs': autres_groupes_actifs,
        'eleve_en_attente': eleve_en_attente,
        'avertissements_en_attente': avertissements_en_attente,
        'action_en_attente': action_en_attente,
        'destination_en_attente': destination_en_attente,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'courses/admin_groupe_detail.html', context)


@role_required('admin')
def groupe_ajouter_eleve(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve_id = request.POST.get('eleve_id')
    confirme = request.POST.get('confirme') == '1'
    if eleve_id:
        eleve = get_object_or_404(Eleve, id=eleve_id)
        raison = raison_incompatibilite_groupe(eleve, groupe)
        if raison:
            messages.error(request, f'تعذّرت إضافة الطالب إلى المجموعة: {raison}')
        else:
            avertissements = avertissements_groupe(eleve, groupe)
            if avertissements and not confirme:
                url = reverse('admin_groupe_detail', args=[groupe_id]) + f'?confirmer_ajout={eleve.id}'
                return redirect(url)
            with transaction.atomic():
                _ajouter_eleve_au_groupe(eleve, groupe)
            for avertissement in avertissements:
                messages.warning(request, avertissement)
            messages.success(request, 'تمت إضافة الطالب إلى المجموعة.')
    return redirect('admin_groupe_detail', groupe_id=groupe_id)


@role_required('admin')
def groupe_retirer_eleve(request, groupe_id, eleve_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve = get_object_or_404(Eleve, id=eleve_id)
    if request.method == 'POST':
        with transaction.atomic():
            _retirer_eleve_du_groupe(eleve, groupe)
        messages.success(request, f'تمت إزالة {eleve.user.get_full_name()} من المجموعة (سجل حصصه وتقييماته محفوظ).')
    return redirect('admin_groupe_detail', groupe_id=groupe_id)


@role_required('admin')
def groupe_transferer_eleve(request, groupe_id, eleve_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve = get_object_or_404(Eleve, id=eleve_id)
    destination_id = request.POST.get('destination_id')
    confirme = request.POST.get('confirme') == '1'

    if not destination_id:
        messages.error(request, 'يجب اختيار مجموعة الوجهة قبل النقل.')
        return redirect('admin_groupe_detail', groupe_id=groupe_id)

    destination = get_object_or_404(Groupe, id=destination_id)
    raison = raison_incompatibilite_groupe(eleve, destination)
    if raison:
        messages.error(request, f'تعذّر نقل الطالب: {raison}')
        return redirect('admin_groupe_detail', groupe_id=groupe_id)

    avertissements = avertissements_groupe(eleve, destination)
    if avertissements and not confirme:
        url = (
            reverse('admin_groupe_detail', args=[groupe_id])
            + f'?confirmer_transfert={eleve.id}&destination={destination.id}'
        )
        return redirect(url)

    with transaction.atomic():
        _retirer_eleve_du_groupe(eleve, groupe)
        _ajouter_eleve_au_groupe(eleve, destination)
    for avertissement in avertissements:
        messages.warning(request, avertissement)
    messages.success(request, f'تم نقل {eleve.user.get_full_name()} إلى مجموعة {destination.nom} (سجل حصصه وتقييماته في المجموعة السابقة محفوظ).')
    return redirect('admin_groupe_detail', groupe_id=groupe_id)

@role_required('admin')
def groupe_modifier(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    creneaux = Creneau.objects.filter(est_actif=True)
    # Prof.actifs exclut les archivés du choix — SAUF le prof déjà assigné à ce
    # groupe s'il vient d'être archivé: on le garde visible (étiqueté "مؤرشف"
    # dans le template) pour que l'admin voie clairement qui est en place et
    # puisse le réassigner explicitement, plutôt que de le faire disparaître
    # silencieusement du formulaire (chantier d'archivage du 2026-08-03).
    profs = list(Prof.actifs.all())
    if groupe.prof_id and groupe.prof and groupe.prof.statut == 'archive' and groupe.prof not in profs:
        profs.append(groupe.prof)

    if request.method == 'POST':
        nouveau_creneau_id = request.POST.get('creneau')
        if not nouveau_creneau_id:
            messages.error(request, 'يجب اختيار حلقة للمجموعة.')
            return render(request, 'courses/admin_groupe_modifier.html', {
                'groupe': groupe,
                'creneaux': creneaux,
                'profs': profs,
            })

        creneau_a_change = str(groupe.creneau_id) != str(nouveau_creneau_id)

        nouveau_prof_id = request.POST.get('prof') or None
        prof_a_change = str(groupe.prof_id) != str(nouveau_prof_id)
        confirme = request.POST.get('confirme') == '1'
        avertissements_prof = []
        # Ne revalider la compatibilité prof/créneau que si l'un des deux change réellement —
        # sinon un groupe déjà assigné avant durcissement des disponibilités (ou avec une
        # matrice de dispo incomplète) devient bloqué pour toute autre modification (ex: lien_reunion).
        if nouveau_prof_id and (creneau_a_change or prof_a_change):
            prof_obj = get_object_or_404(Prof, id=nouveau_prof_id)
            # Revalidé côté serveur (le <select> exclut déjà les archivés, sauf le
            # prof déjà en place — voir plus haut) — se protège contre un POST
            # direct choisissant un AUTRE prof archivé que celui déjà assigné.
            if prof_a_change and prof_obj.statut == 'archive':
                messages.error(request, f'تعذّر إسناد {prof_obj.user.get_full_name()}: هذا الأستاذ مؤرشف.')
                return render(request, 'courses/admin_groupe_modifier.html', {
                    'groupe': groupe,
                    'creneaux': creneaux,
                    'profs': profs,
                })
            creneau_obj = get_object_or_404(Creneau, id=nouveau_creneau_id)
            manquants = creneaux_manquants_pour_prof(prof_obj, creneau_obj)
            if manquants:
                messages.error(request, _message_incompatibilite(prof_obj, manquants))
                return render(request, 'courses/admin_groupe_modifier.html', {
                    'groupe': groupe,
                    'creneaux': creneaux,
                    'profs': profs,
                })

            avertissements_prof = avertissements_prof_creneau(prof_obj, creneau_obj)
            if avertissements_prof and not confirme:
                groupe_previsualise = Groupe(
                    id=groupe.id,
                    nom=request.POST.get('nom'),
                    description=request.POST.get('description', ''),
                    capacite_max=request.POST.get('capacite_max', 10),
                    type_capacite=request.POST.get('type_capacite', 'groupe'),
                    statut=request.POST.get('statut'),
                    prof_id=nouveau_prof_id,
                    creneau_id=nouveau_creneau_id,
                    lien_reunion=request.POST.get('lien_reunion', ''),
                )
                return render(request, 'courses/admin_groupe_modifier.html', {
                    'groupe': groupe_previsualise,
                    'creneaux': creneaux,
                    'profs': profs,
                    'avertissements_prof': avertissements_prof,
                })

        groupe.nom = request.POST.get('nom')
        groupe.description = request.POST.get('description', '')
        groupe.capacite_max = request.POST.get('capacite_max', 10)
        groupe.type_capacite = request.POST.get('type_capacite', 'groupe')
        groupe.statut = request.POST.get('statut')
        groupe.prof_id = nouveau_prof_id
        groupe.creneau_id = nouveau_creneau_id
        groupe.lien_reunion = request.POST.get('lien_reunion', '')
        groupe.save()

        for avertissement in avertissements_prof:
            messages.warning(request, avertissement)
        if creneau_a_change:
            regenerer_pour_nouveau_creneau(groupe)
            messages.success(request, 'تم تعديل المجموعة وإعادة توليد حصصها حسب الحلقة الجديدة.')
        else:
            messages.success(request, 'تم تعديل المجموعة بنجاح.')
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    return render(request, 'courses/admin_groupe_modifier.html', {
        'groupe': groupe,
        'creneaux': creneaux,
        'profs': profs,
    })


@role_required('admin', 'mshrif')
def creneaux_list(request):
    sexe_cible = request.GET.get('sexe_cible', '')
    actif = request.GET.get('actif', '')
    type_seance = request.GET.get('type_seance', '')
    riwaya = request.GET.get('riwaya', '')

    creneaux = Creneau.objects.all().order_by('id')
    if sexe_cible:
        creneaux = creneaux.filter(sexe_cible=sexe_cible)
    if actif:
        creneaux = creneaux.filter(est_actif=(actif == '1'))
    if type_seance:
        creneaux = creneaux.filter(type_seance=type_seance)
    if riwaya:
        creneaux = creneaux.filter(riwaya=riwaya)

    context = {
        'creneaux': paginer(request, creneaux, 10),
        'filtres': {
            'sexe_cible': sexe_cible,
            'actif': actif,
            'type_seance': type_seance,
            'riwaya': riwaya,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'courses/admin_creneaux.html', context)


@role_required('admin')
def creneau_ajouter(request):
    if request.method == 'POST':
        Creneau.objects.create(
            sexe_cible=request.POST.get('sexe_cible'),
            type_seance=request.POST.get('type_seance'),
            riwaya=request.POST.get('riwaya'),
            age_min=request.POST.get('age_min'),
            age_max=request.POST.get('age_max'),
            jour_1=request.POST.get('jour_1'),
            heure_debut_1=request.POST.get('heure_debut_1'),
            heure_fin_1=request.POST.get('heure_fin_1'),
            jour_2=request.POST.get('jour_2'),
            heure_debut_2=request.POST.get('heure_debut_2'),
            heure_fin_2=request.POST.get('heure_fin_2'),
        )
        messages.success(request, 'تمت إضافة الحلقة بنجاح.')
        return redirect('admin_creneaux')

    return render(request, 'courses/admin_creneau_ajouter.html')


@role_required('admin')
def creneau_modifier(request, creneau_id):
    creneau = get_object_or_404(Creneau, id=creneau_id)

    if request.method == 'POST':
        champs_horaire = ['jour_1', 'heure_debut_1', 'heure_fin_1', 'jour_2', 'heure_debut_2', 'heure_fin_2']
        anciennes_valeurs_horaire = {champ: getattr(creneau, champ) for champ in champs_horaire}

        creneau.sexe_cible = request.POST.get('sexe_cible')
        creneau.type_seance = request.POST.get('type_seance')
        creneau.riwaya = request.POST.get('riwaya')
        creneau.age_min = request.POST.get('age_min')
        creneau.age_max = request.POST.get('age_max')
        creneau.jour_1 = request.POST.get('jour_1')
        creneau.heure_debut_1 = request.POST.get('heure_debut_1')
        creneau.heure_fin_1 = request.POST.get('heure_fin_1')
        creneau.jour_2 = request.POST.get('jour_2')
        creneau.heure_debut_2 = request.POST.get('heure_debut_2')
        creneau.heure_fin_2 = request.POST.get('heure_fin_2')
        creneau.save()

        # L'horaire (jour/heure) est stocké sur le Creneau, partagé par tous les
        # Groupe qui le référencent — un changement ici doit déplacer les séances
        # futures de CHAQUE groupe concerné, pas seulement d'un seul (Tâche 19,
        # Bug 1 du 2026-07-26). On ne régénère que si jour/heure ont vraiment
        # changé, pour ne pas effacer inutilement des séances lors d'une simple
        # modification d'âge/sexe/type sans lien avec le planning.
        horaire_a_change = any(
            str(anciennes_valeurs_horaire[champ]) != str(getattr(creneau, champ))
            for champ in champs_horaire
        )
        if horaire_a_change:
            with transaction.atomic():
                for groupe in creneau.groupes.all():
                    regenerer_pour_nouveau_creneau(groupe)
            messages.success(request, 'تم تعديل الحلقة وإعادة توليد حصص جميع المجموعات المرتبطة بها حسب التوقيت الجديد.')
        else:
            messages.success(request, 'تم تعديل الحلقة بنجاح.')
        return redirect('admin_creneaux')

    return render(request, 'courses/admin_creneau_modifier.html', {
        'creneau': creneau,
    })


@role_required('admin')
def creneau_toggle(request, creneau_id):
    creneau = get_object_or_404(Creneau, id=creneau_id)
    creneau.est_actif = not creneau.est_actif
    creneau.save()
    messages.info(request, 'تم تفعيل الحلقة.' if creneau.est_actif else 'تم تعطيل الحلقة.')
    return redirect('admin_creneaux')