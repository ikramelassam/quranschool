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
from django.views.decorators.cache import never_cache

from .utils import wizard_donnees, wizard_maj, wizard_reinitialiser


def wizard_categorie_age(request):
    """Étape -1 (avant même l'introduction/ميثاق) — RESTAURÉE depuis l'ancien
    système (inscriptions.views.inscription_eleve_choix/eleve_choix.html) à
    la demande du client, 2026-08-22 : le visiteur choisit d'abord بالغ/طفل,
    comme aux tout débuts du projet.

    Ce choix N'EST JAMAIS une 2e source de vérité pour l'âge — pas de logique
    d'âge dupliquée : la SEULE source réelle reste tranche_age_depuis_
    naissance(date_naissance), calculée à l'étape 1 (identité) et utilisée
    PARTOUT ailleurs (groupes, abonnements, ouverture par catégorie). Ce
    choix précoce sert à :
    1. Fermer l'accès tôt si la catégorie choisie est fermée — RÉUTILISE TEL
       QUEL le mécanisme déjà existant (inscriptions.views.
       _reponse_categorie_fermee, ParametresInscriptions.ouverte_eleve_*),
       jamais un 2e écran "فتح التسجيل" à maintenir séparément.
    2. Être REVÉRIFIÉ à l'étape 1 contre la VRAIE date de naissance (voir
       wizard_identite, inscriptions.views.MESSAGE_AGE_NE_CORRESPOND_PAS
       réutilisé TEL QUEL) — jamais fait confiance seul, exactement comme
       le faisait déjà l'ancien inscription_eleve_formulaire."""
    from inscriptions.models import get_parametres_inscriptions
    from inscriptions.views import _reponse_categorie_fermee

    if request.method == 'POST':
        type_age_choisi = request.POST.get('type_age', '')
        if type_age_choisi not in ('enfant', 'adulte'):
            return render(request, 'inscriptions/wizard_categorie_age.html', {
                'erreurs': ['يرجى اختيار الفئة العمرية.'],
            })

        parametres = get_parametres_inscriptions()
        if type_age_choisi == 'adulte' and not parametres.ouverte_eleve_adulte:
            return _reponse_categorie_fermee(request, 'adulte')
        if type_age_choisi == 'enfant' and not parametres.ouverte_eleve_enfant:
            return _reponse_categorie_fermee(request, 'enfant')

        wizard_maj(request, {'type_age_choisi': type_age_choisi})
        return redirect('wizard_intro')

    return render(request, 'inscriptions/wizard_categorie_age.html', {})


def wizard_intro(request):
    """Étape 0 — présentation (ميثاق), contenu entièrement lu depuis
    PresentationInscription (Étape 5C), jamais codé en dur dans le template.
    Simple écran d'accueil, aucune donnée à soumettre ici — le bouton mène
    directement à l'étape 1.

    SAUT SERVEUR si la catégorie d'âge n'a pas encore été choisie (chantier
    du 2026-08-22) — pas un simple masquage JS, un visiteur qui force cette
    URL directement est TOUJOURS redirigé, même méthode que le saut Individuel
    de wizard_groupe (Partie 3/26)."""
    from .models import get_presentation_inscription

    if 'type_age_choisi' not in wizard_donnees(request):
        return redirect('wizard_categorie_age')

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
    """Étape 1 — champs structurels CONFIGURABLES (registration.models.
    ConfigurationChampStructurel, chantier du 2026-08-22 : label/ordre/
    obligatoire/actif/placeholder/aide/regex, jamais le stockage — voir sa
    docstring) + champs informatifs configurables (Étape 1, critere=NULL)
    rendus génériquement à la suite.

    sexe/date_naissance/email gardent leur validation DÉDIÉE existante
    (contraintes structurelles, verrouillées obligatoire=True — voir
    CLES_VERROUILLEES) ; telephone garde son widget spécial (indicatif+
    confirmation WhatsApp, _construire_et_valider_telephone) mais devient
    optionnel si configuré ainsi (skip la validation si vide ET non
    obligatoire, jamais un <input> simple). nom/nom_parent/job_actuel/
    niveau_scolaire sont ENTIÈREMENT génériques (valider_champ_structurel_
    libre). Un champ absent de champs_structurels_actifs('identite')
    (est_actif=False) n'est ni affiché, ni validé, ni lu depuis le POST.

    LIMITE ASSUMÉE : seule cette étape sait aujourd'hui rendre des champs
    structurels génériquement — les déplacer vers une autre étape (`etape`
    reste modifiable en base) n'a pas encore d'effet visible ailleurs,
    hors scope de ce chantier.

    Chantier du 2026-08-22 (restauration du choix بالغ/طفل, Étape -1) : SAUT
    SERVEUR si ce choix n'a pas encore été fait (même principe que le saut
    Individuel de wizard_groupe) ; ET revérification de la VRAIE date de
    naissance contre ce choix précoce (tranche_age_depuis_naissance reste la
    SEULE source de vérité, jamais dupliquée — voir wizard_categorie_age)."""
    from courses.utils import tranche_age_depuis_naissance
    from inscriptions.views import MESSAGE_AGE_NE_CORRESPOND_PAS, _construire_et_valider_telephone
    from .utils import champs_structurels_actifs, valider_champ_structurel_libre

    donnees_session = wizard_donnees(request)
    if 'type_age_choisi' not in donnees_session:
        return redirect('wizard_categorie_age')
    type_age_choisi = donnees_session['type_age_choisi']

    champs_info = _champs_informatifs_actifs('identite')
    configs = champs_structurels_actifs('identite')
    configs_par_cle = {c.champ_cle: c for c in configs}
    CLES_GENERIQUES = ('nom', 'nom_parent', 'job_actuel', 'niveau_scolaire')

    # nom_parent dépend du choix بالغ/طفل déjà fait à l'étape -1 (demande du
    # 2026-08-22) — jamais une mention conditionnelle vague ("إن كان
    # المسجَّل قاصراً") : le système SAIT déjà si c'est un mineur. Mutation
    # EN MÉMOIRE seulement (jamais persistée) — n'affecte que ce rendu/cette
    # validation, pas la configuration réelle du مدير. Si le مدير a
    # lui-même désactivé ce champ (absent de configs_par_cle), ce choix
    # reste prioritaire : rien ci-dessous ne le réactive.
    nom_parent_config = configs_par_cle.get('nom_parent')
    if nom_parent_config is not None:
        if type_age_choisi == 'adulte':
            configs = [c for c in configs if c.champ_cle != 'nom_parent']
            del configs_par_cle['nom_parent']
        else:  # 'enfant'
            nom_parent_config.label = 'اسم ولي الأمر'
            nom_parent_config.obligatoire = True

    def _avec_valeurs_actuelles(valeurs):
        # Pose `.valeur_actuelle` sur chaque config à partir d'un dict/
        # QueryDict — évite le piège classique "lookup de dict par variable"
        # en template Django (bug #1 historique du projet, voir CLAUDE.md) :
        # {{ valeurs_form.champ_cle }} ne marche PAS avec un nom dynamique,
        # {{ config.valeur_actuelle }} si.
        for c in configs:
            c.valeur_actuelle = valeurs.get(c.champ_cle, '')
        return configs

    if request.method == 'POST':
        erreurs = []
        nouvelles_valeurs = {}

        for cle in CLES_GENERIQUES:
            config = configs_par_cle.get(cle)
            if config is None:
                continue
            valeur = request.POST.get(cle, '').strip()
            erreur = valider_champ_structurel_libre(config, valeur)
            if erreur:
                erreurs.append(erreur)
            nouvelles_valeurs[cle] = valeur

        if 'sexe' in configs_par_cle:
            sexe = request.POST.get('sexe', '')
            if sexe not in ('homme', 'femme'):
                erreurs.append(f'"{configs_par_cle["sexe"].label}" إلزامي.')
            nouvelles_valeurs['sexe'] = sexe

        if 'email' in configs_par_cle:
            email = request.POST.get('email', '').strip()
            if not email:
                erreurs.append(f'"{configs_par_cle["email"].label}" إلزامي.')
            nouvelles_valeurs['email'] = email

        if 'date_naissance' in configs_par_cle:
            date_naissance_str = request.POST.get('date_naissance', '')
            try:
                date_naissance_obj = datetime.date.fromisoformat(date_naissance_str)
            except (ValueError, TypeError):
                erreurs.append('يرجى إدخال تاريخ ميلاد صحيح.')
            else:
                # Revérifie la VRAIE date de naissance contre le choix
                # précoce بالغ/طفل (wizard_categorie_age) — tranche_age_
                # depuis_naissance reste la SEULE source de vérité, jamais
                # dupliquée ; ce choix précoce n'était qu'une déclaration,
                # jamais fait confiance seul (même principe que l'ancien
                # inscription_eleve_formulaire, réutilise le même message).
                categorie_reelle = tranche_age_depuis_naissance(date_naissance_obj)
                if categorie_reelle != donnees_session.get('type_age_choisi'):
                    erreurs.append(MESSAGE_AGE_NE_CORRESPOND_PAS[categorie_reelle])
            nouvelles_valeurs['date_naissance'] = date_naissance_str

        telephone_config = configs_par_cle.get('telephone')
        if telephone_config is not None:
            telephone_brut = request.POST.get('telephone', '').strip()
            if not telephone_config.obligatoire and not telephone_brut:
                telephone = ''
            else:
                telephone, erreur_tel = _construire_et_valider_telephone(request)
                if erreur_tel:
                    erreurs.append(erreur_tel)
            nouvelles_valeurs['telephone'] = telephone

        for champ in champs_info:
            valeur = request.POST.get(f'champ_{champ.id}', '').strip()
            if champ.obligatoire and not valeur:
                erreurs.append(f'"{champ.label}" إلزامي.')

        if not erreurs:
            for champ in champs_info:
                nouvelles_valeurs[f'champ_{champ.id}'] = request.POST.get(f'champ_{champ.id}', '').strip()
            wizard_maj(request, nouvelles_valeurs)
            return redirect('wizard_programme')

        return render(request, 'inscriptions/wizard_identite.html', {
            'champs_info': champs_info, 'configs': _avec_valeurs_actuelles(request.POST),
            'erreurs': erreurs, 'valeurs_form': request.POST,
            'wizard_etape_num': 1,
        })

    return render(request, 'inscriptions/wizard_identite.html', {
        'champs_info': champs_info, 'configs': _avec_valeurs_actuelles(wizard_donnees(request)),
        'valeurs_form': wizard_donnees(request),
        'wizard_etape_num': 1,
    })


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


def wizard_programme(request):
    """Étape 2 — رendu générique des ChampInscription actifs de l'étape
    'programme' (au minimum, prévus dès le lancement via la migration de
    seed : Programme, Riwaya, Groupe-ou-Individuel, Nombre de séances), en
    respectant les RegleCondition déjà satisfaites par les réponses données
    à l'étape 1 ou plus tôt dans cette même étape.

    Chantier du 2026-08-22 ("liberté totale du nombre de séances") : le
    champ backend='nb_slots' est désormais un simple nombre libre (aucune
    liste calculée depuis les groupes réels existants, contrairement à
    avant) — un élève peut demander N'IMPORTE QUEL nombre, même si aucun
    groupe n'a jamais eu ce nombre de séances. Si ça mène à zéro groupe
    correspondant exactement, voir wizard_groupe (message configurable +
    DemandeNonSatisfaite, généralisé à TOUTE combinaison de critères)."""
    from .utils import _reponses_a_creer_pour_champ, extraire_champs_depuis_post, wizard_donnees, wizard_maj

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
        donnees_pour_masquage = {**donnees, **extraire_champs_depuis_post(request.POST)}
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
            'wizard_etape_num': 2,
        })

    champs = _champs_programme_visibles(donnees)
    return render(request, 'inscriptions/wizard_programme.html', {
        'champs': champs, 'valeurs_form': donnees,
        'wizard_etape_num': 2,
    })


def _type_offre_et_reponses_filtrage(donnees):
    """(valeur du critère backend='champ_groupe', {Critere: valeur}) à partir
    des réponses déjà en session — utilise evaluer_champs_actifs/reponses_
    pour_filtrage_depuis_resultats (Étape 6C, partagées avec inscrire_eleve)
    pour ne JAMAIS diverger sur ce qui compte comme "répondu"."""
    from .utils import evaluer_champs_actifs, reponses_pour_filtrage_depuis_resultats

    resultats = evaluer_champs_actifs(donnees)
    reponses_pour_filtrage = reponses_pour_filtrage_depuis_resultats(resultats)
    type_offre_valeur = next(
        (v for c, v in reponses_pour_filtrage.items() if c.backend == 'champ_groupe'), None
    )
    return type_offre_valeur, reponses_pour_filtrage


def wizard_groupe(request):
    """Étape 3 — UNIQUEMENT si le critère backend='champ_groupe' (type_offre)
    vaut 'groupe'. SAUT SERVEUR sinon (Partie 3/26 du cahier des charges) :
    la vue elle-même redirige directement vers l'abonnement, AVANT tout rendu
    — pas un masquage JS, un visiteur qui force cette URL avec une session
    'individuel' en cours est TOUJOURS redirigé, quelle que soit la méthode
    HTTP (voir WizardGroupeSecuriteTests.test_acces_direct_avec_session_
    individuel_redirige_meme_en_forcant_lurl).

    Chantier du 2026-08-22 ("liberté totale du nombre de séances") : le
    nombre de séances n'étant plus limité à ce qui existe déjà (voir
    wizard_programme), AUCUN groupe ne correspond parfois à la combinaison
    EXACTE choisie — généralisé à TOUTE combinaison de critères, pas
    seulement le nombre de séances.

    Refonte du 2026-08-22 (suite aux tests en local) : dans ce cas, message
    CONCRET (dit explicitement qu'aucune combinaison exacte n'existe) +
    groupes "proches" (correspondant au moins aux critères non négociables
    — âge/sexe structurels + tout critère bloquant=True, même repli que
    confirme_override) DEVENUS SÉLECTIONNABLES, à égalité avec une option
    explicite "لا، أنتظر حتى يتم إنشاء الحلقة" (avec le délai de contact
    configuré, même esprit que le message final de wizard_confirmation) —
    un choix (groupe proche OU attente) est OBLIGATOIRE avant de pouvoir
    avancer. Dans les 2 cas, une DemandeNonSatisfaite est enregistrée : la
    combinaison exacte demandée reste une donnée utile pour le مدير/مشرف
    même quand l'élève accepte finalement un groupe proche."""
    from courses.utils import _age_depuis_naissance
    from inscriptions.models import get_parametres_inscriptions
    from .models import DemandeNonSatisfaite, get_presentation_inscription
    from .utils import (
        groupes_avec_place_disponible, groupes_compatibles_avec_age, snapshot_criteres_pour_demande,
        wizard_donnees, wizard_maj,
    )

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')

    type_offre_valeur, reponses_pour_filtrage = _type_offre_et_reponses_filtrage(donnees)
    if type_offre_valeur != 'groupe':
        return redirect('wizard_abonnement')

    date_naissance = datetime.date.fromisoformat(donnees['date_naissance'])
    sexe = donnees['sexe']
    age = _age_depuis_naissance(date_naissance)
    # prefetch propre à L'AFFICHAGE de cette page (pas au contrat réutilisable
    # de groupes_compatibles_avec_age lui-même) — évite un N+1 sur les
    # critères de chaque groupe affiché (riwaya, etc., montrés génériquement,
    # jamais par nom de critère en dur).
    # groupes_avec_place_disponible (bug du 2026-08-21) : un groupe complet ne
    # doit JAMAIS apparaître dans la liste — cette même variable `groupes` sert
    # aussi au POST juste en dessous, donc la capacité y est désormais
    # garantie AVANT même le clic, pas seulement revérifiée après coup.
    groupes = groupes_avec_place_disponible(
        groupes_compatibles_avec_age(reponses_pour_filtrage, date_naissance, sexe)
    ).prefetch_related('valeurs_criteres__critere', 'valeurs_criteres__option')

    aucun_groupe_exact = not groupes.exists()
    groupes_proches = None
    message_aucun_groupe = None
    delai_contact_heures = None
    if aucun_groupe_exact:
        reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
        groupes_proches = groupes_avec_place_disponible(
            groupes_compatibles_avec_age(reponses_bloquantes, date_naissance, sexe)
        ).prefetch_related('valeurs_criteres__critere', 'valeurs_criteres__option')
        message_aucun_groupe = get_presentation_inscription().message_aucun_groupe_exact
        delai_contact_heures = get_parametres_inscriptions().delai_contact_heures

    contexte_commun = {
        'groupes': groupes, 'groupes_proches': groupes_proches,
        'aucun_groupe_exact': aucun_groupe_exact, 'message_aucun_groupe': message_aucun_groupe,
        'delai_contact_heures': delai_contact_heures,
        'age': age, 'wizard_etape_num': 3,
    }

    def _enregistrer_demande_non_satisfaite():
        nb_slots_valeur = next((v for c, v in reponses_pour_filtrage.items() if c.backend == 'nb_slots'), None)
        return DemandeNonSatisfaite.objects.create(
            criteres_json=snapshot_criteres_pour_demande(reponses_pour_filtrage),
            type_offre='groupe', nb_slots=nb_slots_valeur, age=age, sexe=sexe,
        )

    if request.method == 'POST':
        if aucun_groupe_exact:
            choix_attente = request.POST.get('continuer_sans_groupe') == '1'
            groupe_id = request.POST.get('groupe_id')
            groupe_choisi = None
            if not choix_attente and groupe_id:
                # Revérifié SERVEUR contre groupes_proches (jamais `groupes`,
                # vide ici) — jamais une confiance aveugle dans l'ID posté,
                # même principe que le chemin normal ci-dessous.
                groupe_choisi = groupes_proches.filter(id=groupe_id).first()
                if groupe_choisi is not None and groupe_choisi.eleves.count() >= groupe_choisi.capacite_max:
                    groupe_choisi = None

            if not choix_attente and groupe_choisi is None:
                return render(request, 'inscriptions/wizard_groupe.html', {
                    **contexte_commun,
                    'erreurs': ['يرجى اختيار مجموعة قريبة أو تأكيد الانتظار قبل المتابعة.'],
                })

            # Un choix valide a été fait (groupe proche OU attente) — la
            # combinaison exacte demandée reste tracée dans les 2 cas.
            demande = _enregistrer_demande_non_satisfaite()
            wizard_maj(request, {
                'groupe_id': str(groupe_choisi.id) if groupe_choisi else '',
                'demande_non_satisfaite_id': str(demande.id),
            })
            return redirect('wizard_abonnement')

        groupe_id = request.POST.get('groupe_id')
        groupe_choisi = groupes.filter(id=groupe_id).first() if groupe_id else None
        # Garde-fou redondant mais volontairement conservé : `groupes` exclut
        # déjà les groupes complets depuis le correctif ci-dessus, donc cette
        # 2e vérification ne devrait plus jamais se déclencher en pratique —
        # gardée en défense en profondeur contre un futur changement de
        # `groupes` qui oublierait de repasser par groupes_avec_place_
        # disponible (jamais confiance aveugle à un seul point de contrôle).
        if groupe_choisi is not None and groupe_choisi.eleves.count() >= groupe_choisi.capacite_max:
            groupe_choisi = None
        if groupe_choisi is None:
            return render(request, 'inscriptions/wizard_groupe.html', {
                **contexte_commun, 'erreurs': ['يرجى اختيار مجموعة من القائمة المتاحة.'],
            })
        wizard_maj(request, {'groupe_id': groupe_id})
        return redirect('wizard_abonnement')

    return render(request, 'inscriptions/wizard_groupe.html', contexte_commun)


def wizard_abonnement(request):
    """Étape 4 — point de convergence Groupe + Individuel. Réutilise
    TypeAbonnement TEL QUEL (déjà un système dynamique fonctionnel, Étape 5C/
    TypeAbonnement.type_offre/cible_age) — rien de reconstruit ici, juste
    filtré par les réponses déjà en session.

    Prix affiché (Étape 9, GrillePrixAbonnement, 2026-08-21) : nb_slots est
    déjà connu à ce stade (répondu à l'étape 2, avant Groupe/Individuel) —
    abonnements_avec_prix_effectif() pose `.prix_affiche` sur chaque
    TypeAbonnement, jamais TypeAbonnement.prix affiché brut directement."""
    from courses.utils import tranche_age_depuis_naissance
    from .utils import abonnements_avec_prix_effectif, abonnements_disponibles, nb_slots_repondu

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')

    type_offre_valeur, _ = _type_offre_et_reponses_filtrage(donnees)
    if type_offre_valeur == 'groupe' and 'groupe_id' not in donnees:
        # Choix "Groupe" fait mais aucun groupe encore retenu — retour à
        # l'étape 3 plutôt que de proposer un abonnement sans groupe associé.
        return redirect('wizard_groupe')

    date_naissance = datetime.date.fromisoformat(donnees['date_naissance'])
    type_age = tranche_age_depuis_naissance(date_naissance)
    nb_slots = nb_slots_repondu(donnees)

    # abonnements_disponibles (registration.utils, Étape 7) : même requête que
    # dashboard.views.admin_eleve_ajouter_manuel, jamais 2 versions maintenues
    # séparément.
    abonnements = abonnements_disponibles(type_offre_valeur, type_age)

    if request.method == 'POST':
        code = request.POST.get('abonnement_code', '')
        if not abonnements.filter(code=code).exists():
            return render(request, 'inscriptions/wizard_abonnement.html', {
                'abonnements': abonnements_avec_prix_effectif(abonnements, nb_slots),
                'erreurs': ['يرجى اختيار نوع اشتراك صالح.'],
                'wizard_etape_num': 4,
            })
        wizard_maj(request, {'abonnement_code': code})
        return redirect('wizard_paiement')

    return render(request, 'inscriptions/wizard_abonnement.html', {
        'abonnements': abonnements_avec_prix_effectif(abonnements, nb_slots), 'wizard_etape_num': 4,
    })


def wizard_paiement(request):
    """Étape 5 — moyens de paiement actifs (Étape 5C) + date limite dérivée
    de ParametresInscriptions.delai_paiement_jours (JAMAIS recalculée en dur).
    Le bouton de confirmation de CETTE étape déclenche la revalidation
    complète et l'appel à inscrire_eleve() (Partie 22) — voir la docstring
    détaillée plus bas, section 'REVALIDATION FINALE'. En cas de succès,
    redirige vers wizard_confirmation (Étape 6, affichage seul) en transitant
    par la session, même patron que dashboard.views.confirmation_creation_compte."""
    from django.utils import timezone
    from inscriptions.models import get_parametres_inscriptions
    from payments.models import MoyenPaiement

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')
    if 'abonnement_code' not in donnees:
        return redirect('wizard_abonnement')

    moyens = MoyenPaiement.objects.filter(est_actif=True).order_by('ordre')
    parametres = get_parametres_inscriptions()
    date_limite = timezone.localdate() + datetime.timedelta(days=parametres.delai_paiement_jours)

    if request.method == 'POST':
        return _wizard_confirmer_inscription(request, donnees, moyens, date_limite, parametres)

    return render(request, 'inscriptions/wizard_paiement.html', {
        'moyens': moyens, 'date_limite': date_limite,
        'delai_paiement_jours': parametres.delai_paiement_jours,
        'wizard_etape_num': 5,
    })


def _wizard_confirmer_inscription(request, donnees, moyens, date_limite, parametres):
    """Soumission finale (POST de wizard_paiement, Étape 6E) — REVALIDATION
    COMPLÈTE avant toute création (Partie 22 du cahier des charges) :

    - moyen_paiement_code : validé ici (purement informatif pour cette page,
      inscrire_eleve() ne le connaît pas et n'en a pas besoin).
    - TOUT LE RESTE (option appartenant au bon critère, obligatoire respecté,
      groupe_id revérifié contre groupes_compatibles_avec_age AU MOMENT DE
      CETTE CONFIRMATION — jamais celui, potentiellement périmé, calculé à
      l'étape 3 — capacité, statut actif, individuel -> groupe_id ignoré) :
      délégué ENTIÈREMENT à inscrire_eleve() (Étape 4), qui reçoit `donnees`
      — la SESSION accumulée, jamais le POST brut de cette requête — comme
      reponses_brutes. Aucune logique de sécurité dupliquée ici : c'est
      exactement pour ça que inscrire_eleve() a été conçue et testée de façon
      isolément complète dès l'Étape 4. Un groupe_id en session devenu
      incompatible (groupe rempli/archivé entre l'étape 3 et maintenant, ou
      même injecté directement dans la session par un contournement du
      parcours normal) est donc TOUJOURS re-détecté ici, jamais silencieusement
      accepté (voir WizardConfirmationSecuriteTests.
      test_groupe_id_devenu_incompatible_entre_etape_3_et_confirmation_est_
      rejete_a_la_confirmation)."""
    from .models import get_presentation_inscription
    from .utils import inscrire_eleve

    moyen_code = request.POST.get('moyen_paiement_code', '')
    if not moyens.filter(code=moyen_code).exists():
        return render(request, 'inscriptions/wizard_paiement.html', {
            'moyens': moyens, 'date_limite': date_limite,
            'delai_paiement_jours': parametres.delai_paiement_jours,
            'erreurs': ['يرجى اختيار طريقة دفع صالحة.'],
            'wizard_etape_num': 5,
        })

    inscription, erreurs = inscrire_eleve(donnees, cree_par=None)
    if erreurs:
        return render(request, 'inscriptions/wizard_paiement.html', {
            'moyens': moyens, 'date_limite': date_limite,
            'delai_paiement_jours': parametres.delai_paiement_jours,
            'erreurs': erreurs,
            'wizard_etape_num': 5,
        })

    presentation = get_presentation_inscription()
    wizard_reinitialiser(request)
    # Même patron que dashboard.views.confirmation_creation_compte : transite
    # par la session (jamais l'URL), lu puis effacé (pop) par wizard_confirmation
    # — un rafraîchissement de la page de confirmation ne réaffiche jamais les
    # mêmes infos ni ne permet de rejouer la création.
    request.session['wizard_confirmation'] = {
        'nom': inscription.nom,
        'message_bienvenue': presentation.message_bienvenue,
        'delai_contact_heures': parametres.delai_contact_heures,
    }
    return redirect('wizard_confirmation')


@never_cache
def wizard_confirmation(request):
    """Étape 6 — affichage seul. Les infos transitent par la session (voir
    _wizard_confirmer_inscription ci-dessus), lues puis immédiatement effacées
    (pop) — même patron que dashboard.views.confirmation_creation_compte."""
    info = request.session.pop('wizard_confirmation', None)
    if not info:
        return redirect('wizard_intro')
    return render(request, 'inscriptions/wizard_confirmation.html', info)
