from django.shortcuts import render, redirect, get_object_or_404
from accounts.decorators import role_required
from .models import Groupe, Creneau
from accounts.models import Prof, Eleve


@role_required('admin')
def groupes_list(request):
    groupes = Groupe.objects.all()
    return render(request, 'courses/admin_groupes.html', {
        'groupes': groupes,
    })


@role_required('admin')
def groupe_ajouter(request):
    if request.method == 'POST':
        Groupe.objects.create(
            nom=request.POST.get('nom'),
            prof_id=request.POST.get('prof') or None,
            creneau_id=request.POST.get('creneau') or None,
            description=request.POST.get('description', ''), 
            capacite_max=request.POST.get('max_eleves', 10),
        )
        return redirect('admin_groupes')

    creneaux = Creneau.objects.filter(est_actif=True)
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
        groupe.eleves.add(eleve_id)
    return redirect('admin_groupe_detail', groupe_id=groupe_id)

@role_required('admin')
def groupe_modifier(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    creneaux = Creneau.objects.filter(est_actif=True)
    profs = Prof.objects.all()

    if request.method == 'POST':
        groupe.nom = request.POST.get('nom')
        groupe.description = request.POST.get('description', '')
        groupe.capacite_max = request.POST.get('capacite_max', 10)
        groupe.statut = request.POST.get('statut')
        groupe.prof_id = request.POST.get('prof') or None
        groupe.creneau_id = request.POST.get('creneau') or None
        groupe.save()
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    return render(request, 'courses/admin_groupe_modifier.html', {
        'groupe': groupe,
        'creneaux': creneaux,
        'profs': profs,
    })


@role_required('admin')
def creneaux_list(request):
    creneaux = Creneau.objects.all()
    return render(request, 'courses/admin_creneaux.html', {
        'creneaux': creneaux,
    })


@role_required('admin')
def creneau_ajouter(request):
    if request.method == 'POST':
        Creneau.objects.create(
            sexe_cible=request.POST.get('sexe_cible'),
            age_min=request.POST.get('age_min'),
            age_max=request.POST.get('age_max'),
            jour_1=request.POST.get('jour_1'),
            heure_debut_1=request.POST.get('heure_debut_1'),
            heure_fin_1=request.POST.get('heure_fin_1'),
            jour_2=request.POST.get('jour_2'),
            heure_debut_2=request.POST.get('heure_debut_2'),
            heure_fin_2=request.POST.get('heure_fin_2'),
        )
        return redirect('admin_creneaux')

    return render(request, 'courses/admin_creneau_ajouter.html')


@role_required('admin')
def creneau_modifier(request, creneau_id):
    creneau = get_object_or_404(Creneau, id=creneau_id)

    if request.method == 'POST':
        creneau.sexe_cible = request.POST.get('sexe_cible')
        creneau.age_min = request.POST.get('age_min')
        creneau.age_max = request.POST.get('age_max')
        creneau.jour_1 = request.POST.get('jour_1')
        creneau.heure_debut_1 = request.POST.get('heure_debut_1')
        creneau.heure_fin_1 = request.POST.get('heure_fin_1')
        creneau.jour_2 = request.POST.get('jour_2')
        creneau.heure_debut_2 = request.POST.get('heure_debut_2')
        creneau.heure_fin_2 = request.POST.get('heure_fin_2')
        creneau.save()
        return redirect('admin_creneaux')

    return render(request, 'courses/admin_creneau_modifier.html', {
        'creneau': creneau,
    })


@role_required('admin')
def creneau_toggle(request, creneau_id):
    creneau = get_object_or_404(Creneau, id=creneau_id)
    creneau.est_actif = not creneau.est_actif
    creneau.save()
    return redirect('admin_creneaux')