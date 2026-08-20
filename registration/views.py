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
import json

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


def _extraire_champs_depuis_post(post_data):
    """dict {champ_<id>: valeur} depuis un QueryDict POST — valeur = liste
    si plusieurs valeurs soumises sous la même clé (choix multiple), sinon
    chaîne simple. Utilisé pour évaluer les RegleCondition avec les réponses
    de LA soumission EN COURS (voir wizard_programme), pas seulement celles
    déjà enregistrées en session avant elle."""
    extrait = {}
    for cle in post_data:
        if cle.startswith('champ_'):
            valeurs = post_data.getlist(cle)
            extrait[cle] = valeurs if len(valeurs) > 1 else valeurs[0]
    return extrait


def _champs_programme_visibles(donnees):
    """ChampInscription actifs liés à l'étape 'programme', MOINS ceux masqués
    par une RegleCondition satisfaite (champ_est_masque, Étape 4) compte tenu
    des réponses déjà en session — recalculé à chaque affichage, jamais mis
    en cache."""
    from .models import ChampInscription
    from .utils import champ_est_masque

    tous_les_champs = list(
        ChampInscription.objects.filter(est_actif=True, etape__est_actif=True)
        .select_related('critere', 'etape').order_by('etape__ordre', 'ordre')
    )
    codes_repondus = _codes_repondus_depuis_session(donnees, tous_les_champs)

    return [
        c for c in tous_les_champs
        if c.etape.code == 'programme' and not champ_est_masque(c, codes_repondus)
    ]


def _codes_repondus_depuis_session(donnees, tous_les_champs):
    """{critere_id: {code, ...}} reconstruit depuis les réponses déjà en
    session — même format que registration.utils.champ_est_masque attend,
    nécessaire pour évaluer les RegleCondition à l'affichage (avant toute
    soumission), cohérent avec ce qu'inscrire_eleve() referait à la
    validation finale."""
    from .models import CritereOption

    codes = {}
    for champ in tous_les_champs:
        if champ.critere_id is None or champ.critere.backend == 'nb_slots':
            continue
        valeur_brute = donnees.get(f'champ_{champ.id}')
        if not valeur_brute:
            continue
        valeurs = valeur_brute if isinstance(valeur_brute, list) else [valeur_brute]
        options = CritereOption.objects.filter(critere_id=champ.critere_id, code__in=valeurs)
        if options:
            codes.setdefault(champ.critere_id, set()).update(o.code for o in options)
    return codes


def _donnees_filtrage_json_pour_wizard():
    """Un objet par Groupe actif avec créneau : {groupe_id, valeurs:
    {critere_id: code_ou_valeur}, nb_slots} — sert au calcul EN DIRECT (JS,
    sans requête serveur) du nombre de séances réellement proposables à
    l'étape 2, à mesure que l'élève répond aux autres champs de la MÊME
    étape (Programme/Riwaya/Groupe-ou-Individuel). Même patron que
    creneaux_json déjà utilisé par l'ancien formulaire à une page
    (eleve_formulaire.html) pour filtrer les créneaux par âge/sexe côté
    client — PUREMENT un confort d'affichage immédiat, jamais la source de
    vérité : le filtrage définitif et sécurisé est TOUJOURS refait côté
    serveur par groupes_compatibles() à l'étape 3 et à la confirmation
    finale (Étape 6E), qui ne font JAMAIS confiance à ce qu'affichait le
    navigateur.

    N'inclut QUE les critères filtrable=True et backend != 'nb_slots' (ce
    dernier étant précisément la valeur qu'on cherche à calculer, pas un
    filtre)."""
    from courses.models import Groupe
    from .models import Critere

    criteres_filtrables = list(
        Critere.objects.filter(est_actif=True, filtrable=True).exclude(backend='nb_slots')
    )
    groupes = (
        Groupe.actifs.filter(statut='actif', creneau__isnull=False)
        .prefetch_related('valeurs_criteres__option', 'creneau__slots')
    )

    donnees = []
    for groupe in groupes:
        valeurs_par_critere = {v.critere_id: v.option_id for v in groupe.valeurs_criteres.all()}
        valeurs = {}
        for critere in criteres_filtrables:
            if critere.backend == 'champ_groupe':
                valeurs[critere.id] = getattr(groupe, critere.champ_modele_groupe, None)
            else:
                option_id = valeurs_par_critere.get(critere.id)
                option = next(
                    (v.option for v in groupe.valeurs_criteres.all() if v.option_id == option_id), None
                ) if option_id else None
                valeurs[critere.id] = option.code if option else None
        donnees.append({
            'groupe_id': groupe.id,
            'valeurs': valeurs,
            'nb_slots': groupe.creneau.slots.count(),
        })
    return donnees


def wizard_programme(request):
    """Étape 2 — رendu générique des ChampInscription actifs de l'étape
    'programme' (au minimum, prévus dès le lancement via la migration de
    seed : Programme, Riwaya, Groupe-ou-Individuel, Nombre de séances), en
    respectant les RegleCondition déjà satisfaites par les réponses données
    à l'étape 1 ou plus tôt dans cette même étape.

    RÈGLE CRITIQUE : le champ backend='nb_slots' (nombre de séances) n'a
    JAMAIS d'options codées en dur — le template reçoit uniquement le JSON
    de _donnees_filtrage_json_pour_wizard() et calcule les valeurs proposées
    EN DIRECT en JS à partir des groupes réels. Un nouveau groupe à N séances
    créé demain par le مدير apparaît automatiquement, sans toucher au code
    (voir WizardProgrammeNbSeancesDynamiqueTests)."""
    from .utils import _reponses_a_creer_pour_champ, wizard_donnees, wizard_maj

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')

    if request.method == 'POST':
        # IMPORTANT : les RegleCondition doivent être évaluées avec les
        # réponses de CETTE soumission, pas seulement celles déjà en
        # session AVANT elle — sinon un champ que la réponse en cours vient
        # justement de démasquer/masquer serait jugé sur un état périmé
        # (bug détecté par WizardProgrammeTests.test_regle_conditionnelle_
        # masque_un_champ). Fusion purement locale à ce calcul, la session
        # elle-même n'est mise à jour qu'après validation complète, plus bas.
        donnees_pour_masquage = {**donnees, **_extraire_champs_depuis_post(request.POST)}
        champs = _champs_programme_visibles(donnees_pour_masquage)

        erreurs = []
        nouvelles_valeurs = {}
        for champ in champs:
            cle = f'champ_{champ.id}'
            if champ.critere and champ.critere.type_champ == 'choix_multiple':
                valeur_brute = request.POST.getlist(cle)
            else:
                valeur_brute = request.POST.get(cle, '')
            paires, erreur = _reponses_a_creer_pour_champ(champ, valeur_brute)
            if erreur:
                erreurs.append(erreur)
                continue
            if not paires and champ.obligatoire:
                erreurs.append(f'"{champ.label}" إلزامي.')
                continue
            nouvelles_valeurs[cle] = valeur_brute

        if not erreurs:
            wizard_maj(request, nouvelles_valeurs)
            return redirect('wizard_groupe')

        return render(request, 'inscriptions/wizard_programme.html', {
            'champs': champs, 'erreurs': erreurs, 'valeurs_form': {**donnees, **request.POST.dict()},
            'donnees_filtrage_json': json.dumps(_donnees_filtrage_json_pour_wizard()),
            'wizard_etape_num': 2,
        })

    champs = _champs_programme_visibles(donnees)
    return render(request, 'inscriptions/wizard_programme.html', {
        'champs': champs, 'valeurs_form': donnees,
        'donnees_filtrage_json': json.dumps(_donnees_filtrage_json_pour_wizard()),
        'wizard_etape_num': 2,
    })


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
