from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from .models import InscriptionEleve, InscriptionProf, TypeAbonnement
from courses.models import Creneau
import json

MESSAGE_EMAIL_DEJA_UTILISE = (
    'هذا البريد الإلكتروني مستخدم بالفعل من طرف حساب آخر أو طلب تسجيل قيد '
    'الدراسة. يرجى استخدام بريد إلكتروني آخر أو التواصل مع المدرسة.'
)


def _email_deja_utilise(email, exclure_user_id=None):
    """Vérifie si cet email est déjà pris par un compte User existant, ou par
    une InscriptionEleve/InscriptionProf encore en attente de validation.
    Empêche les doublons de candidature avant même la création d'un User
    (voir bug connu #5 du CLAUDE.md, corrigé au niveau de la validation admin,
    mais qu'il vaut mieux éviter dès la soumission du formulaire).
    exclure_user_id: permet de vérifier un changement d'email sur un compte
    existant sans que ce compte se bloque lui-même (même email, même user)."""
    User = get_user_model()
    users_qs = User.objects.filter(email=email)
    if exclure_user_id is not None:
        users_qs = users_qs.exclude(id=exclure_user_id)
    if users_qs.exists():
        return True
    if InscriptionEleve.objects.filter(email=email, statut='en_attente').exists():
        return True
    if InscriptionProf.objects.filter(email=email, statut='en_attente').exists():
        return True
    return False


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

    types_abonnement_json = json.dumps([{
        'code': t.code,
        'label': t.label,
        'prix': str(t.prix),
    } for t in TypeAbonnement.objects.filter(est_actif=True).order_by('ordre')])

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()

        if _email_deja_utilise(email):
            return render(request, 'inscriptions/eleve_formulaire.html', {
                'type_age': type_age,
                'creneaux_json': creneaux_json,
                'types_abonnement_json': types_abonnement_json,
                'erreur_email': MESSAGE_EMAIL_DEJA_UTILISE,
                'old_email': email,
            })

        InscriptionEleve.objects.create(
            nom=request.POST.get('nom'),
            nom_parent=request.POST.get('nom_parent', ''),
            date_naissance=request.POST.get('date_naissance'),
            sexe=request.POST.get('sexe'),
            telephone=request.POST.get('telephone'),
            email=email,
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
        'types_abonnement_json': types_abonnement_json,
    })


def inscription_confirmation(request):
    return render(request, 'inscriptions/confirmation.html')

def inscription_prof(request):
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    contexte_grille = {
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        disponibilites = request.POST.getlist('dispo')

        if _email_deja_utilise(email):
            return render(request, 'inscriptions/prof_formulaire.html', {
                'erreur_email': MESSAGE_EMAIL_DEJA_UTILISE,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

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
            email=email,
            langues=request.POST.getlist('langues'),
            outils_maitrises=request.POST.getlist('outils'),
            type_eleve_preference=request.POST.getlist('type_eleve'),
            contrainte_genre=request.POST.getlist('contrainte_genre'),
            audio_enregistrement=request.FILES.get('audio_enregistrement'),
            disponibilites=disponibilites,
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/prof_formulaire.html', {
        'valeurs_form': set(),
        **contexte_grille,
    })