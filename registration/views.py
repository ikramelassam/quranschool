"""Wizard public d'inscription élève (Étape 6 du chantier) — parcours en 6
étapes fonctionnelles (+ Étape 0 introduction), entièrement piloté par la
configuration du dashboard (Étape 5) et branché sur registration.utils.
inscrire_eleve() (Étape 4, déjà complet et testé isolément).

Ne remplace PAS /register/student (inscriptions.views.inscription_eleve_*,
inscriptions/urls.py) — les deux parcours coexistent tant que celui-ci n'est
pas validé en conditions réelles, comme demandé explicitement.

État accumulé dans la session (voir registration.utils.wizard_donnees/
wizard_maj) — jamais dans des champs cachés HTML entre 2 requêtes."""

import datetime

from django.shortcuts import render, redirect

from .utils import wizard_donnees, wizard_maj, wizard_reinitialiser


def wizard_intro(request):
    """Étape 0 — présentation (ميثاق), contenu entièrement lu depuis
    PresentationInscription (Étape 5C), jamais codé en dur dans le template.
    Simple écran d'accueil, aucune donnée à soumettre ici — le bouton mène
    directement à l'étape 1."""
    from .models import get_presentation_inscription

    return render(request, 'inscriptions/wizard_intro.html', {
        'presentation': get_presentation_inscription(),
    })


def _champs_informatifs_actifs(code_etape):
    """ChampInscription actifs, critere=NULL (informatifs purs), liés à
    l'EtapeInscription de code `code_etape` — utilisé par l'Étape 1
    (Partie "Plus : tout ChampInscription actif et lié à cette étape avec
    critere=NULL, rendu génériquement après les champs fixes"). Liste vide
    (jamais une exception) si l'étape n'existe pas encore (مدير ne l'a pas
    créée) — comportement dégradé propre, pas un 500."""
    from .models import ChampInscription

    return list(
        ChampInscription.objects.filter(
            etape__code=code_etape, etape__est_actif=True, est_actif=True, critere__isnull=True,
        ).order_by('ordre', 'id')
    )


def wizard_identite(request):
    """Étape 1 — champs structurels fixes (déjà de vraies colonnes sur
    InscriptionEleve, JAMAIS transformés en EAV, voir registration.models.
    ChampInscription.__doc__) + champs informatifs configurables (Étape 1,
    critere=NULL) rendus génériquement à la suite.

    Téléphone/WhatsApp : réutilise TEL QUEL inscriptions.views._construire_et_
    valider_telephone (même template partiel inscriptions/_verification_
    whatsapp.html, même fonction de validation serveur) — rien de nouveau
    réimplémenté ici, exactement comme demandé."""
    from inscriptions.views import _construire_et_valider_telephone

    champs_info = _champs_informatifs_actifs('identite')

    if request.method == 'POST':
        erreurs = []
        nom = request.POST.get('nom', '').strip()
        sexe = request.POST.get('sexe', '')
        email = request.POST.get('email', '').strip()
        date_naissance_str = request.POST.get('date_naissance', '')

        if not nom:
            erreurs.append('الاسم الكامل إلزامي.')
        if sexe not in ('homme', 'femme'):
            erreurs.append('الجنس إلزامي.')
        if not email:
            erreurs.append('البريد الإلكتروني إلزامي.')

        try:
            datetime.date.fromisoformat(date_naissance_str)
        except (ValueError, TypeError):
            erreurs.append('يرجى إدخال تاريخ ميلاد صحيح.')

        telephone, erreur_tel = _construire_et_valider_telephone(request)
        if erreur_tel:
            erreurs.append(erreur_tel)

        for champ in champs_info:
            valeur = request.POST.get(f'champ_{champ.id}', '').strip()
            if champ.obligatoire and not valeur:
                erreurs.append(f'"{champ.label}" إلزامي.')

        if not erreurs:
            nouvelles_valeurs = {
                'nom': nom, 'nom_parent': request.POST.get('nom_parent', '').strip(),
                'sexe': sexe, 'telephone': telephone, 'date_naissance': date_naissance_str,
                'email': email, 'job_actuel': request.POST.get('job_actuel', '').strip(),
            }
            for champ in champs_info:
                nouvelles_valeurs[f'champ_{champ.id}'] = request.POST.get(f'champ_{champ.id}', '').strip()
            wizard_maj(request, nouvelles_valeurs)
            return redirect('wizard_programme')

        return render(request, 'inscriptions/wizard_identite.html', {
            'champs_info': champs_info, 'erreurs': erreurs, 'valeurs_form': request.POST,
            'wizard_etape_num': 1,
        })

    return render(request, 'inscriptions/wizard_identite.html', {
        'champs_info': champs_info, 'valeurs_form': wizard_donnees(request),
        'wizard_etape_num': 1,
    })


# TODO Étape 6B : rendu générique de l'étape "اختيار البرنامج" (programme/
# riwaya/groupe-individuel/nb séances dynamique + RegleCondition).
def wizard_programme(request):
    return redirect('wizard_identite')


# TODO Étape 6C : groupes compatibles, avec saut serveur si Individuel.
def wizard_groupe(request):
    return redirect('wizard_programme')


# TODO Étape 6D : liste TypeAbonnement filtrée (déjà existant, à réutiliser).
def wizard_abonnement(request):
    return redirect('wizard_groupe')


# TODO Étape 6D : moyens de paiement + date limite + soumission finale.
def wizard_paiement(request):
    return redirect('wizard_abonnement')


# TODO Étape 6E : affichage du message de bienvenue après inscrire_eleve().
def wizard_confirmation(request):
    return redirect('wizard_intro')
