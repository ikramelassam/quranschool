import datetime

from django.shortcuts import render, redirect
from django.contrib.auth import get_user_model
from django.urls import reverse
from .models import InscriptionEleve, InscriptionProf, TypeAbonnement
from core.utils import envoyer_notification_telegram
from courses.utils import AGE_SEUIL_ADULTE, tranche_age_depuis_naissance
import json

MESSAGE_EMAIL_DEJA_UTILISE = (
    'هذا البريد الإلكتروني مستخدم بالفعل من طرف حساب آخر أو طلب تسجيل قيد '
    'الدراسة. يرجى استخدام بريد إلكتروني آخر أو التواصل مع المدرسة.'
)

MESSAGE_AGE_NE_CORRESPOND_PAS = {
    'adulte': 'يبدو أنك بالغ (18 سنة فما فوق) — يرجى استخدام نموذج التسجيل الخاص بالبالغين.',
    'enfant': 'يبدو أنك طفل (أقل من 18 سنة) — يرجى استخدام نموذج التسجيل الخاص بالأطفال.',
}


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
    from courses.utils import generer_heures_grille, JOURS_SEMAINE_DISPO

    types_abonnement_json = json.dumps([{
        'code': t.code,
        'label': t.label,
        'prix': str(t.prix),
    } for t in TypeAbonnement.objects.filter(est_actif=True, cible_age__in=[type_age, 'les_deux']).order_by('ordre')])

    contexte_grille = {
        'jours': JOURS_SEMAINE_DISPO,
        'heures': generer_heures_grille(),
        'age_seuil_adulte': AGE_SEUIL_ADULTE,
    }

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        disponibilites = request.POST.getlist('dispo')
        date_naissance_str = request.POST.get('date_naissance', '')

        if _email_deja_utilise(email):
            return render(request, 'inscriptions/eleve_formulaire.html', {
                'type_age': type_age,
                'types_abonnement_json': types_abonnement_json,
                'erreur_email': MESSAGE_EMAIL_DEJA_UTILISE,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        # Garde-fou serveur, indépendant du JS de eleve_formulaire.html: même
        # une requête POST directe (JS désactivé, script, curl) ne peut pas
        # créer une InscriptionEleve dont la catégorie choisie (type_age, le
        # paramètre d'URL) contredit l'âge réel calculé depuis date_naissance.
        try:
            date_naissance = datetime.date.fromisoformat(date_naissance_str)
        except ValueError:
            date_naissance = None

        if date_naissance is not None:
            categorie_reelle = tranche_age_depuis_naissance(date_naissance)
            if categorie_reelle != type_age:
                return render(request, 'inscriptions/eleve_formulaire.html', {
                    'type_age': type_age,
                    'types_abonnement_json': types_abonnement_json,
                    'erreur_age': MESSAGE_AGE_NE_CORRESPOND_PAS[categorie_reelle],
                    'old_email': email,
                    'valeurs_form': set(disponibilites),
                    **contexte_grille,
                })

        inscription = InscriptionEleve.objects.create(
            nom=request.POST.get('nom'),
            nom_parent=request.POST.get('nom_parent', ''),
            date_naissance=request.POST.get('date_naissance'),
            sexe=request.POST.get('sexe'),
            telephone=request.POST.get('telephone'),
            email=email,
            programme=request.POST.get('programme'),
            riwaya=request.POST.get('riwaya'),
            outil=request.POST.get('outil'),
            abonnement=request.POST.get('abonnement'),
            accepte_conditions=request.POST.get('accepte_conditions') == 'oui',
            remarques=request.POST.get('remarques', ''),
            disponibilites_libres=request.POST.get('disponibilites_libres', ''),
            disponibilites=disponibilites,
        )
        lien_fiche = request.build_absolute_uri(
            reverse('admin_inscription_eleve_detail', args=[inscription.id])
        )
        if date_naissance is not None:
            categorie_label = 'بالغ' if tranche_age_depuis_naissance(date_naissance) == 'adulte' else 'طفل'
        else:
            categorie_label = 'غير محدد'
        envoyer_notification_telegram(
            f'📥 طلب تسجيل جديد — طالب ({categorie_label})\n'
            f'الاسم: {inscription}\n'
            f'تاريخ التقديم: {inscription.date_soumission.strftime("%Y-%m-%d %H:%M")}\n'
            f'رابط الملف: {lien_fiche}'
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/eleve_formulaire.html', {
        'type_age': type_age,
        'types_abonnement_json': types_abonnement_json,
        'valeurs_form': set(),
        **contexte_grille,
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
        compte_bancaire = request.POST.get('compte_bancaire', '').strip()
        rib = request.POST.get('rib', '').strip()
        telephone = request.POST.get('telephone', '').strip()
        audio_enregistrement = request.FILES.get('audio_enregistrement')

        if _email_deja_utilise(email):
            return render(request, 'inscriptions/prof_formulaire.html', {
                'erreur_email': MESSAGE_EMAIL_DEJA_UTILISE,
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        # Pas de Django Forms dans ce projet (request.POST.get() brut) — le HTML5
        # required peut être contourné, donc on revalide ces champs côté serveur
        # avant toute création (voir bug RIB/compte bancaire vides malgré le
        # champ obligatoire en apparence, et l'audio qui doit devenir obligatoire).
        champs_manquants = []
        if not compte_bancaire:
            champs_manquants.append('رقم الحساب البنكي')
        if not rib:
            champs_manquants.append('RIB')
        if not telephone:
            champs_manquants.append('رقم الهاتف')
        if not audio_enregistrement:
            champs_manquants.append('التسجيل الصوتي')

        if champs_manquants:
            return render(request, 'inscriptions/prof_formulaire.html', {
                'erreur_champs': 'الحقول التالية إلزامية ولم يتم تعبئتها: ' + '، '.join(champs_manquants),
                'old_email': email,
                'valeurs_form': set(disponibilites),
                **contexte_grille,
            })

        inscription = InscriptionProf.objects.create(
            nom=request.POST.get('nom'),
            prenom=request.POST.get('prenom'),
            date_naissance=request.POST.get('date_naissance'),
            telephone=telephone,
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
            compte_bancaire=compte_bancaire,
            rib=rib,
            audio_enregistrement=audio_enregistrement,
            disponibilites=disponibilites,
        )
        lien_fiche = request.build_absolute_uri(
            reverse('admin_inscription_prof_detail', args=[inscription.id])
        )
        envoyer_notification_telegram(
            f'📥 طلب تسجيل جديد — أستاذ\n'
            f'الاسم: {inscription}\n'
            f'تاريخ التقديم: {inscription.date_soumission.strftime("%Y-%m-%d %H:%M")}\n'
            f'رابط الملف: {lien_fiche}'
        )
        return redirect('inscription_confirmation')

    return render(request, 'inscriptions/prof_formulaire.html', {
        'valeurs_form': set(),
        **contexte_grille,
    })