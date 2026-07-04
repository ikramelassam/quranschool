from django.shortcuts import render, redirect
from .models import InscriptionEleve, InscriptionProf
from courses.models import Creneau
import json

def inscription_eleve_choix(request):
    return render(request, 'inscriptions/eleve_choix.html')


def inscription_eleve_formulaire(request, type_age):
    creneaux = Creneau.objects.filter(est_actif=True)
    
    creneaux_json = json.dumps([{
        'id': c.id,
        'label': str(c),
        'age_min': c.age_min,
        'age_max': c.age_max,
        'sexe_cible': c.sexe_cible,
    } for c in creneaux])

    if request.method == 'POST':
        InscriptionEleve.objects.create(
            nom=request.POST.get('nom'),
            nom_parent=request.POST.get('nom_parent', ''),
            date_naissance=request.POST.get('date_naissance'),
            sexe=request.POST.get('sexe'),
            telephone=request.POST.get('telephone'),
            email=request.POST.get('email'),
            creneau_souhaite_id=request.POST.get('creneau_souhaite') or None,
            programme=request.POST.get('programme'),
            riwaya=request.POST.get('riwaya'),
            outil=request.POST.get('outil'),
            abonnement=request.POST.get('abonnement'),
            accepte_conditions=request.POST.get('accepte_conditions') == 'oui',
            remarques=request.POST.get('remarques', ''),
            disponibilites_libres=request.POST.get('disponibilites_libres', ''),
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/eleve_formulaire.html', {
        'type_age': type_age,
        'creneaux_json': creneaux_json,
    })


def inscription_confirmation(request):
    return render(request, 'inscriptions/confirmation.html')

def inscription_prof(request):
    if request.method == 'POST':
        InscriptionProf.objects.create(
            nom=request.POST.get('nom'),
            prenom=request.POST.get('prenom'),
            date_naissance=request.POST.get('date_naissance'),
            ville=request.POST.get('ville'),
            statut_familial=request.POST.get('statut_familial'),
            job_actuel=request.POST.get('job_actuel'),
            certifications=request.POST.get('certifications'),
            niveau_memorisation=request.POST.get('niveau_memorisation'),
            parcours_scolaire=request.POST.get('parcours_scolaire'),
            parcours_enseignant=request.POST.get('parcours_enseignant'),
            gestion_eleve_faible=request.POST.get('gestion_eleve_faible'),
            gestion_eleve_absent=request.POST.get('gestion_eleve_absent'),
            email=request.POST.get('email'),
            langues=request.POST.getlist('langues'),
            outils_maitrises=request.POST.getlist('outils'),
            type_eleve_preference=request.POST.getlist('type_eleve'),
            contrainte_genre=request.POST.getlist('contrainte_genre'),
            audio_enregistrement=request.FILES.get('audio_enregistrement'),
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/prof_formulaire.html')