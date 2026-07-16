from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import role_required
from core.utils import paginer
from .models import Groupe, Creneau
from .utils import regenerer_pour_nouveau_creneau, creneaux_manquants_pour_prof, raison_incompatibilite_groupe
from accounts.models import Prof, Eleve


def _message_incompatibilite(prof, manquants):
    jours_dict = dict(Creneau.JOUR_CHOICES)
    details = '، '.join(f'{jours_dict.get(j, j)} {h.strftime("%H:%M")}' for j, h in manquants)
    return (
        f'لا يمكن إسناد {prof.user.get_full_name} لهذه الحلقة: '
        f'هذا المعلم غير متفرغ في الأوقات التالية حسب جدول تفرغه المعتمد: {details}.'
    )


@role_required('admin')
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

    return render(request, 'courses/admin_groupes.html', {
        'groupes': paginer(request, groupes, 10),
        'aucun_creneau': not Creneau.objects.filter(est_actif=True).exists(),
        'profs': Prof.objects.select_related('user').order_by('user__first_name'),
        'creneaux': Creneau.objects.order_by('id'),
        'filtres': {
            'statut': statut,
            'prof': prof_id,
            'creneau': creneau_id,
        },
    })


@role_required('admin')
def groupe_ajouter(request):
    creneaux = Creneau.objects.filter(est_actif=True)

    if request.method == 'POST':
        creneau_id = request.POST.get('creneau')
        if not creneau_id:
            messages.error(request, 'يجب اختيار حلقة قبل إنشاء المجموعة. أنشئ حلقة أولاً إذا لم تتوفر أي حلقة.')
            return render(request, 'courses/admin_groupe_ajouter.html', {
                'creneaux': creneaux,
                'profs': Prof.objects.all(),
            })

        prof_id = request.POST.get('prof') or None
        if prof_id:
            prof_obj = get_object_or_404(Prof, id=prof_id)
            creneau_obj = get_object_or_404(Creneau, id=creneau_id)
            manquants = creneaux_manquants_pour_prof(prof_obj, creneau_obj)
            if manquants:
                messages.error(request, _message_incompatibilite(prof_obj, manquants))
                return render(request, 'courses/admin_groupe_ajouter.html', {
                    'creneaux': creneaux,
                    'profs': Prof.objects.all(),
                })

        groupe = Groupe.objects.create(
            nom=request.POST.get('nom'),
            prof_id=prof_id,
            creneau_id=creneau_id,
            description=request.POST.get('description', ''),
            capacite_max=request.POST.get('max_eleves', 10),
            type_capacite=request.POST.get('type_capacite', 'groupe'),
        )
        regenerer_pour_nouveau_creneau(groupe)
        messages.success(request, 'تمت إضافة المجموعة وتوليد حصصها تلقائياً بنجاح.')
        return redirect('admin_groupes')

    profs = Prof.objects.all()
    return render(request, 'courses/admin_groupe_ajouter.html', {
        'creneaux': creneaux,
        'profs': profs,
    })


@role_required('admin')
def groupe_detail(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleves_disponibles = Eleve.objects.exclude(groupes=groupe)
    return render(request, 'courses/admin_groupe_detail.html', {
        'groupe': groupe,
        'eleves_disponibles': eleves_disponibles,
    })


@role_required('admin')
def groupe_ajouter_eleve(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve_id = request.POST.get('eleve_id')
    if eleve_id:
        eleve = get_object_or_404(Eleve, id=eleve_id)
        raison = raison_incompatibilite_groupe(eleve, groupe)
        if raison:
            messages.error(request, f'تعذّرت إضافة الطالب إلى المجموعة: {raison}')
        else:
            groupe.eleves.add(eleve)
            messages.success(request, 'تمت إضافة الطالب إلى المجموعة.')
    return redirect('admin_groupe_detail', groupe_id=groupe_id)

@role_required('admin')
def groupe_modifier(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    creneaux = Creneau.objects.filter(est_actif=True)
    profs = Prof.objects.all()

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
        if nouveau_prof_id:
            prof_obj = get_object_or_404(Prof, id=nouveau_prof_id)
            creneau_obj = get_object_or_404(Creneau, id=nouveau_creneau_id)
            manquants = creneaux_manquants_pour_prof(prof_obj, creneau_obj)
            if manquants:
                messages.error(request, _message_incompatibilite(prof_obj, manquants))
                return render(request, 'courses/admin_groupe_modifier.html', {
                    'groupe': groupe,
                    'creneaux': creneaux,
                    'profs': profs,
                })

        groupe.nom = request.POST.get('nom')
        groupe.description = request.POST.get('description', '')
        groupe.capacite_max = request.POST.get('capacite_max', 10)
        groupe.type_capacite = request.POST.get('type_capacite', 'groupe')
        groupe.statut = request.POST.get('statut')
        groupe.prof_id = nouveau_prof_id
        groupe.creneau_id = nouveau_creneau_id
        groupe.save()

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


@role_required('admin')
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

    return render(request, 'courses/admin_creneaux.html', {
        'creneaux': paginer(request, creneaux, 10),
        'filtres': {
            'sexe_cible': sexe_cible,
            'actif': actif,
            'type_seance': type_seance,
            'riwaya': riwaya,
        },
    })


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