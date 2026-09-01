"""Wizard public d'inscription élève (Étape 6 du chantier) — parcours en 6
étapes fonctionnelles (+ Étape 0 introduction), entièrement piloté par la
configuration du dashboard (Étape 5) et branché sur registration.utils.
inscrire_eleve() (Étape 4, déjà complet et testé isolément).

Bascule du 2026-08-24 (décision explicite du Directeur, voir registration/
MIGRATION_NOTES.md) : ce parcours REMPLACE désormais /register/student
(wizard_categorie_age y est monté directement, voir core/urls.py) —
l'ancien formulaire à une page (inscriptions.views.inscription_eleve_*,
inscriptions/urls.py) n'est plus lié nulle part publiquement mais reste en
place, dormant, pas supprimé (rollback possible en 1 ligne dans core/urls.py).

État accumulé dans la session (voir registration.utils.wizard_donnees/
wizard_maj) — jamais dans des champs cachés HTML entre 2 requêtes."""

import datetime

from django.shortcuts import render, redirect
from django.urls import reverse
from django.views.decorators.cache import never_cache
from django.utils.translation import gettext as gettext_

from core.utils import envoyer_notification_telegram_async
from courses.utils import tranche_age_depuis_naissance
from .utils import wizard_donnees, wizard_maj, wizard_reinitialiser, traduire_libelle_dynamique


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
                'erreurs': [gettext_('يرجى اختيار الفئة العمرية.')],
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
    à la prochaine étape active après 'categorie_age' (correction 8,
    2026-08-22, navigation dynamique) — 'identite' normalement, mais
    résolu dynamiquement pour rester cohérent si elle venait à changer de
    position (elle reste verrouillée première en pratique, voir
    EtapeInscription.CODES_VERROUILLES, mais jamais un lien codé en dur ici
    non plus).

    SAUT SERVEUR si la catégorie d'âge n'a pas encore été choisie (chantier
    du 2026-08-22) — pas un simple masquage JS, un visiteur qui force cette
    URL directement est TOUJOURS redirigé, même méthode que le saut Individuel
    de wizard_groupe (Partie 3/26)."""
    from .models import get_presentation_inscription
    from .utils import url_etape_suivante

    if 'type_age_choisi' not in wizard_donnees(request):
        return redirect('wizard_categorie_age')

    return render(request, 'inscriptions/wizard_intro.html', {
        'presentation': get_presentation_inscription(),
        'url_suivante': url_etape_suivante('categorie_age'),
    })


def _champs_visibles_pour_etape(code_etape):
    """ChampInscription actifs liés à l'étape `code_etape` — informatifs
    (critere=NULL) ET avec critère — recalculé à chaque affichage, jamais
    mis en cache.

    Généralisée le 2026-08-23 (Partie 3A, "extension du moteur générique à
    l'étape Identité") depuis l'ancienne _champs_programme_visibles
    (réservée à 'programme') ET l'ancienne _champs_informatifs_actifs
    (réservée à 'identite', critere=NULL uniquement — un ChampInscription
    AVEC critère attaché à l'étape Identité n'était alors JAMAIS rendu,
    bien que créable sans erreur depuis le dashboard : trou identifié par
    l'audit du 2026-08-23). Une seule fonction pour TOUTE étape (et toute
    étape personnalisée future, Partie 3B) — jamais 2 (ou 3) versions
    maintenues séparément. Liste vide (jamais une exception) si l'étape
    n'existe pas encore (مدير ne l'a pas créée) — comportement dégradé
    propre, pas un 500.

    Ne prend plus les réponses déjà en session en paramètre depuis le
    retrait du masquage conditionnel (RegleCondition, chantier du
    2026-08-23 — jamais utilisé pour une vraie règle depuis sa création,
    voir registration.models.__doc__) : la liste des champs d'une étape
    ne dépend plus de ce que l'élève a déjà répondu ailleurs."""
    from .models import ChampInscription

    return list(
        ChampInscription.objects.filter(est_actif=True, etape__est_actif=True, etape__code=code_etape)
        .select_related('critere', 'etape').order_by('ordre')
    )


def wizard_identite(request):
    """Étape 1 — champs structurels CONFIGURABLES (registration.models.
    ConfigurationChampStructurel, chantier du 2026-08-22 : label/ordre/
    obligatoire/actif/placeholder/aide/regex, jamais le stockage — voir sa
    docstring) + champs dynamiques configurables de l'étape Identité,
    informatifs OU avec critère (chantier du 2026-08-23, Partie 3A —
    rendu générique EXACTEMENT comme l'étape Programme, voir
    _champs_visibles_pour_etape) rendus génériquement à la suite.

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
    from .utils import (
        appliquer_regle_nom_parent, champs_structurels_actifs,
        traiter_champs_dynamiques_post, url_etape_suivante,
        valider_champ_structurel_libre,
    )

    donnees_session = wizard_donnees(request)
    if 'type_age_choisi' not in donnees_session:
        return redirect('wizard_categorie_age')
    type_age_choisi = donnees_session['type_age_choisi']

    configs = champs_structurels_actifs('identite')
    configs_par_cle = {c.champ_cle: c for c in configs}
    CLES_GENERIQUES = ('nom', 'nom_parent', 'job_actuel', 'niveau_scolaire')

    # nom_parent dépend du choix بالغ/طفل déjà fait à l'étape -1 (demande du
    # 2026-08-22) — jamais une mention conditionnelle vague ("إن كان
    # المسجَّل قاصراً") : le système SAIT déjà si c'est un mineur. Règle
    # PARTAGÉE avec inscrire_eleve (registration.utils.
    # appliquer_regle_nom_parent, correction du 2026-08-28) — avant ce
    # partage, seule cette vue appliquait la mutation, jamais la
    # revalidation finale à l'étape paiement, qui pouvait alors exiger
    # nom_parent pour un adulte selon la configuration brute du مدير.
    configs = appliquer_regle_nom_parent(configs, configs_par_cle, type_age_choisi)

    # job_actuel : même incohérence que nom_parent (label seedé en 0004
    # avec une mention conditionnelle vague, "أو عمل ولي الأمر إن كان
    # المسجَّل قاصراً") — même correction, même principe (le choix بالغ/طفل
    # est déjà connu, jamais reposer la question implicitement dans le
    # label). Contrairement à nom_parent, ce champ reste affiché dans les
    # 2 cas (juste sa CIBLE change) — jamais supprimé de `configs`.
    job_actuel_config = configs_par_cle.get('job_actuel')
    if job_actuel_config is not None:
        if type_age_choisi == 'adulte':
            job_actuel_config.label = 'العمل الحالي'
        else:  # 'enfant'
            job_actuel_config.label = 'عمل ولي الأمر'

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
                erreurs.append(gettext_('"%(label)s" إلزامي.') % {'label': configs_par_cle['sexe'].label_localise})
            nouvelles_valeurs['sexe'] = sexe

        if 'email' in configs_par_cle:
            email = request.POST.get('email', '').strip()
            if not email:
                erreurs.append(gettext_('"%(label)s" إلزامي.') % {'label': configs_par_cle['email'].label_localise})
            nouvelles_valeurs['email'] = email

        if 'date_naissance' in configs_par_cle:
            date_naissance_str = request.POST.get('date_naissance', '')
            try:
                date_naissance_obj = datetime.date.fromisoformat(date_naissance_str)
            except (ValueError, TypeError):
                erreurs.append(gettext_('يرجى إدخال تاريخ ميلاد صحيح.'))
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

        # Champs dynamiques (informatifs OU avec critère, chantier du
        # 2026-08-23) — même mécanique que wizard_programme. Erreurs
        # ajoutées à celles déjà accumulées ci-dessus (structurels), un
        # seul message par champ.
        champs = _champs_visibles_pour_etape('identite')
        nouvelles_valeurs_dyn, erreurs_dyn = traiter_champs_dynamiques_post(request.POST, champs)
        erreurs += erreurs_dyn

        if not erreurs:
            nouvelles_valeurs.update(nouvelles_valeurs_dyn)
            wizard_maj(request, nouvelles_valeurs)
            return redirect(url_etape_suivante('identite'))

        return render(request, 'inscriptions/wizard_identite.html', {
            'champs': champs, 'configs': _avec_valeurs_actuelles(request.POST),
            'erreurs': erreurs, 'valeurs_form': request.POST,
            'wizard_etape_num': 1,
        })

    champs = _champs_visibles_pour_etape('identite')
    return render(request, 'inscriptions/wizard_identite.html', {
        'champs': champs, 'configs': _avec_valeurs_actuelles(wizard_donnees(request)),
        'valeurs_form': wizard_donnees(request),
        'wizard_etape_num': 1,
    })


def wizard_programme(request):
    """Étape 2 — رendu générique des ChampInscription actifs de l'étape
    'programme' (au minimum, prévus dès le lancement via la migration de
    seed : Programme, Riwaya, Groupe-ou-Individuel, Nombre de séances).

    Le champ backend='nb_slots' est passé par 3 comportements le même jour
    (2026-08-29) avant ce dernier : (1) "liberté totale du nombre de séances"
    (2026-08-22, nombre libre non filtré), (2) cases filtrées par les groupes
    réels correspondant EXACTEMENT à programme/riwaya/type_offre déjà
    choisis, (3) cases filtrées par l'existence d'un groupe QUELCONQUE dans
    le système. Les 2 tentatives à base de groupes réels bloquaient (ou
    risquaient de bloquer) la progression dès CETTE étape pour toute
    combinaison sans groupe exact — précisément le cas que wizard_groupe est
    déjà conçu pour gérer une étape plus loin (message configurable + groupes
    proches + DemandeNonSatisfaite). Retenu à la place : la liste de cases
    vient de courses.models.OptionNbSeances (dashboard.views.
    admin_options_nb_seances, /dashboard/admin/parametres/options-nb-seances/)
    — le catalogue partagé du 2026-08-27 (tarification élève/barème salaire
    prof), réutilisé ici plutôt que dupliqué — configurée UNE FOIS par le
    مدير/مشرف, plus jamais recalculée depuis les groupes ni filtrée par les
    autres réponses de cette même étape. Voir OptionNbSeances.__doc__
    (courses/models.py) pour le détail du catalogue.

    SAUT SERVEUR si l'étape 'programme' a été désactivée par le مدير
    (correction 8, 2026-08-22, navigation dynamique) — même principe que le
    saut Individuel de wizard_groupe : un visiteur qui force cette URL est
    TOUJOURS redirigé, quelle que soit la méthode HTTP."""
    from courses.models import OptionNbSeances
    from .utils import (
        etape_est_active, traiter_champs_dynamiques_post, url_etape_suivante,
        valeurs_options_nb_seances_actives, wizard_donnees, wizard_maj,
    )
    from courses.utils import tranche_age_precise

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')
    if not etape_est_active('programme'):
        return redirect(url_etape_suivante('programme'))

    # Partie B (2026-08-24) : simple info affichée au candidat (n'a AUCUN
    # effet sur le filtrage/ouverture — voir courses.utils.tranche_age_
    # precise.__doc__, qui ne remplace jamais tranche_age_depuis_naissance/
    # AGE_SEUIL_ADULTE, seule source de vérité pour l'ouverture par
    # catégorie et le filtrage réel des groupes). None (adulte, ou hors
    # 5-18 ans) -> tranche_age_label reste vide, rien n'est affiché.
    resultat_tranche = tranche_age_precise(
        datetime.date.fromisoformat(donnees['date_naissance']) if donnees.get('date_naissance') else None
    )
    tranche_age_label = resultat_tranche[1] if resultat_tranche else ''

    # Cases affichées pour "عدد الحصص الأسبوعية" — communes au GET et aux 2
    # branches du POST, jamais 2 requêtes divergentes. Voir docstring
    # ci-dessus : configurées par le مدير, jamais dérivées des groupes.
    options_nb_seances = OptionNbSeances.objects.filter(est_actif=True).order_by('ordre', 'valeur')

    if request.method == 'POST':
        champs = _champs_visibles_pour_etape('programme')
        nouvelles_valeurs, erreurs = traiter_champs_dynamiques_post(request.POST, champs)

        if not erreurs:
            # Revalidation stricte contre les options ACTIVES configurées par
            # le مدير — le JS n'a pu proposer que celles-là, mais un POST
            # forgé pourrait en soumettre une autre, jamais une confiance
            # aveugle au POST. valeur_brute déjà validée (entier positif en
            # texte) par traiter_champs_dynamiques_post ci-dessus — jamais
            # reparsée ici.
            champ_nb_seances = next((c for c in champs if c.critere and c.critere.backend == 'nb_slots'), None)
            if champ_nb_seances is not None:
                valeur_brute = nouvelles_valeurs.get(f'champ_{champ_nb_seances.id}')
                if valeur_brute not in (None, '') and int(valeur_brute) not in valeurs_options_nb_seances_actives():
                    erreurs.append(
                        f'"{champ_nb_seances.label}" لم يعد متاحاً، الرجاء اختيار قيمة أخرى.'
                    )

        if not erreurs:
            wizard_maj(request, nouvelles_valeurs)
            return redirect(url_etape_suivante('programme'))

        return render(request, 'inscriptions/wizard_programme.html', {
            'champs': champs, 'erreurs': erreurs, 'valeurs_form': {**donnees, **request.POST.dict()},
            'tranche_age_label': tranche_age_label,
            'wizard_etape_num': 2,
            'options_nb_seances': options_nb_seances,
        })

    champs = _champs_visibles_pour_etape('programme')
    return render(request, 'inscriptions/wizard_programme.html', {
        'champs': champs, 'valeurs_form': donnees,
        'tranche_age_label': tranche_age_label,
        'wizard_etape_num': 2,
        'options_nb_seances': options_nb_seances,
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
    from accounts.models import get_visibilite_prof
    from courses.utils import _age_depuis_naissance
    from .models import DemandeNonSatisfaite, get_presentation_inscription
    from .utils import (
        etape_est_active, groupes_avec_place_disponible, groupes_compatibles_avec_age,
        snapshot_criteres_pour_demande, url_etape_suivante, wizard_donnees, wizard_maj,
    )

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')

    # SAUT SERVEUR (correction 8, 2026-08-22, navigation dynamique) : soit le
    # critère type_offre vaut 'individuel' (déjà le cas avant cette
    # correction), soit le مدير a lui-même désactivé cette étape — dans les
    # 2 cas, url_etape_suivante('groupe') retrouve la même page suivante,
    # aucun besoin de distinguer la raison ici.
    type_offre_valeur, reponses_pour_filtrage = _type_offre_et_reponses_filtrage(donnees)
    if type_offre_valeur != 'groupe' or not etape_est_active('groupe'):
        return redirect(url_etape_suivante('groupe'))

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
    texte_attente_groupe = None
    afficher_disponibilites_si_attente = False
    jours_dispo, heures_dispo = None, None
    if aucun_groupe_exact:
        reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
        groupes_proches = groupes_avec_place_disponible(
            groupes_compatibles_avec_age(reponses_bloquantes, date_naissance, sexe)
        ).prefetch_related('valeurs_criteres__critere', 'valeurs_criteres__option')
        presentation = get_presentation_inscription()
        # _localise (chantier i18n du 2026-08-28) : repli automatique sur l'arabe
        # si le مدير/مشرف n'a pas encore saisi la traduction FR/EN — voir
        # PresentationInscription._localise.
        message_aucun_groupe = presentation.message_aucun_groupe_exact_localise
        # Chantier du 2026-08-25 : texte de la carte "⏳ لا، أنتظر حتى يتم
        # إنشاء الحلقة" — voir registration.models.PresentationInscription.
        # texte_attente_groupe.
        texte_attente_groupe = presentation.texte_attente_groupe_localise
        # Chantier du 2026-08-27 : matrice de disponibilités optionnelle à
        # côté de la carte "attente" — voir PresentationInscription.
        # afficher_disponibilites_si_attente.__doc__. Ne contrôle JAMAIS la
        # carte "attente" elle-même (toujours affichée ci-dessus), seulement
        # cette matrice EN PLUS. jours/heures calculés seulement si le
        # réglage est actif (aucune requête DB, mais pas de travail inutile).
        afficher_disponibilites_si_attente = presentation.afficher_disponibilites_si_attente
        if afficher_disponibilites_si_attente:
            from courses.utils import JOURS_SEMAINE_DISPO, generer_heures_grille
            jours_dispo, heures_dispo = JOURS_SEMAINE_DISPO, generer_heures_grille()

    contexte_commun = {
        'groupes': groupes, 'groupes_proches': groupes_proches,
        'aucun_groupe_exact': aucun_groupe_exact, 'message_aucun_groupe': message_aucun_groupe,
        'texte_attente_groupe': texte_attente_groupe,
        'afficher_disponibilites_si_attente': afficher_disponibilites_si_attente,
        'jours': jours_dispo, 'heures': heures_dispo,
        'dispo_selectionnees': set(request.POST.getlist('dispo')) if request.method == 'POST' else set(),
        # Chantier du 2026-08-27 (présentation publique du prof) — même
        # réglage que eleve_prof_detail.html, voir accounts.models.
        # VisibiliteProf.afficher_presentation_wizard. select_related déjà
        # en place sur 'prof__user' (groupes_compatibles) : aucune requête
        # supplémentaire pour lire groupe.prof.presentation_publique, simple
        # colonne du même JOIN.
        'visibilite': get_visibilite_prof(),
        'age': age, 'wizard_etape_num': 3,
    }

    def _enregistrer_demande_non_satisfaite():
        nb_slots_valeur = next((v for c, v in reponses_pour_filtrage.items() if c.backend == 'nb_slots'), None)
        # nom/telephone/email : déjà collectés à l'étape Identité (donnees),
        # bien avant que l'InscriptionEleve elle-même n'existe — voir
        # DemandeNonSatisfaite.nom.__doc__.
        return DemandeNonSatisfaite.objects.create(
            criteres_json=snapshot_criteres_pour_demande(reponses_pour_filtrage),
            type_offre='groupe', nb_slots=nb_slots_valeur, age=age, sexe=sexe,
            nom=donnees.get('nom', ''), telephone=donnees.get('telephone', ''),
            email=donnees.get('email', ''),
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
                    'erreurs': [gettext_('يرجى اختيار مجموعة قريبة أو تأكيد الانتظار قبل المتابعة.')],
                })

            # Un choix valide a été fait (groupe proche OU attente) — la
            # combinaison exacte demandée reste tracée dans les 2 cas.
            demande = _enregistrer_demande_non_satisfaite()
            wizard_maj(request, {
                'groupe_id': str(groupe_choisi.id) if groupe_choisi else '',
                'demande_non_satisfaite_id': str(demande.id),
                # Chantier du 2026-08-27 — capturée que le réglage soit actif
                # ou non (si inactif, la grille n'est jamais rendue, donc
                # 'dispo' n'apparaît simplement jamais dans le POST : liste
                # vide, aucun cas particulier nécessaire ici). inscrire_eleve()
                # la copie telle quelle dans InscriptionEleve.disponibilites.
                'disponibilites': request.POST.getlist('dispo'),
            })
            return redirect(url_etape_suivante('groupe'))

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
                **contexte_commun, 'erreurs': [gettext_('يرجى اختيار مجموعة من القائمة المتاحة.')],
            })
        wizard_maj(request, {'groupe_id': groupe_id})
        return redirect(url_etape_suivante('groupe'))

    return render(request, 'inscriptions/wizard_groupe.html', contexte_commun)


def wizard_abonnement(request):
    """Étape 4 — point de convergence Groupe + Individuel. Réutilise
    TypeAbonnement TEL QUEL (déjà un système dynamique fonctionnel, Étape 5C/
    TypeAbonnement.type_offre/cible_age) — rien de reconstruit ici, juste
    filtré par les réponses déjà en session.

    Prix affiché (Étape 9, GrillePrixAbonnement, 2026-08-21) : nb_slots_pour_
    tarification() (chantier du 2026-09-01) — le nombre de séances RÉEL de la
    حلقة retenue à l'étape 3 si l'élève en a choisi une (y compris un « groupe
    proche » dont le nombre de séances diffère de ce qu'il avait demandé),
    sinon le nombre déclaré à l'étape programme. abonnements_avec_prix_
    effectif() pose `.prix_affiche` sur chaque TypeAbonnement, jamais
    TypeAbonnement.prix affiché brut directement."""
    from courses.utils import tranche_age_depuis_naissance
    from .utils import (
        abonnements_avec_prix_effectif, abonnements_disponibles, etape_est_active,
        nb_slots_pour_tarification, prix_est_configure, url_etape_suivante,
    )

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')

    type_offre_valeur, _ = _type_offre_et_reponses_filtrage(donnees)
    # etape_est_active('groupe') évite une boucle infinie (correction 8,
    # 2026-08-22) : si cette étape est désactivée par le مدير, groupe_id ne
    # sera JAMAIS en session (wizard_groupe redirige déjà lui-même vers la
    # suite sans jamais le demander) — sans cette condition, ce garde-fou
    # renverrait indéfiniment vers wizard_groupe, qui renverrait aussitôt ici.
    if type_offre_valeur == 'groupe' and etape_est_active('groupe') and 'groupe_id' not in donnees:
        # Choix "Groupe" fait mais aucun groupe encore retenu — retour à
        # l'étape 3 plutôt que de proposer un abonnement sans groupe associé.
        return redirect('wizard_groupe')

    date_naissance = datetime.date.fromisoformat(donnees['date_naissance'])
    type_age = tranche_age_depuis_naissance(date_naissance)
    nb_slots = nb_slots_pour_tarification(donnees)

    # abonnements_disponibles (registration.utils, Étape 7) : même requête que
    # dashboard.views.admin_eleve_ajouter_manuel, jamais 2 versions maintenues
    # séparément.
    abonnements = abonnements_disponibles(type_offre_valeur, type_age)

    if request.method == 'POST':
        code = request.POST.get('abonnement_code', '')
        abonnement_choisi = abonnements.filter(code=code).first()
        # Revalidé côté serveur (bug du 2026-08-29) : une carte à 0 د.م.
        # (voir prix_est_configure) est masquée/désactivée côté template,
        # mais jamais une confiance aveugle dans le POST — même principe que
        # partout ailleurs dans ce projet.
        if abonnement_choisi is None or not prix_est_configure(abonnement_choisi, nb_slots):
            return render(request, 'inscriptions/wizard_abonnement.html', {
                'abonnements': abonnements_avec_prix_effectif(abonnements, nb_slots),
                'erreurs': [gettext_('يرجى اختيار نوع اشتراك صالح.')],
                'wizard_etape_num': 4,
            })
        wizard_maj(request, {'abonnement_code': code})
        return redirect(url_etape_suivante('abonnement'))

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
    from .utils import inscrire_eleve, url_etape_suivante

    moyen_code = request.POST.get('moyen_paiement_code', '')
    if not moyens.filter(code=moyen_code).exists():
        return render(request, 'inscriptions/wizard_paiement.html', {
            'moyens': moyens, 'date_limite': date_limite,
            'delai_paiement_jours': parametres.delai_paiement_jours,
            'erreurs': [gettext_('يرجى اختيار طريقة دفع صالحة.')],
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

    # Notif Telegram au مدير/مشرف (voir telegram_bot app) — équivalent de
    # l'appel qui existait dans l'ancien formulaire à une page (inscriptions.
    # views.inscription_eleve_formulaire), jamais reporté ici lors du chantier
    # "registration" du 2026-08-24 (bug identifié le 2026-08-31 : aucune notif
    # de candidature élève n'était envoyée depuis la bascule vers ce wizard).
    lien_fiche = request.build_absolute_uri(
        reverse('admin_inscription_eleve_detail', args=[inscription.id])
    )
    if inscription.date_naissance is not None:
        categorie_label = 'بالغ' if tranche_age_depuis_naissance(inscription.date_naissance) == 'adulte' else 'طفل'
    else:
        categorie_label = 'غير محدد'
    envoyer_notification_telegram_async(
        f'📥 طلب تسجيل جديد — طالب ({categorie_label})\n'
        f'الاسم: {inscription}\n'
        f'تاريخ التقديم: {inscription.date_soumission.strftime("%Y-%m-%d %H:%M")}\n'
        f'رابط الملف: {lien_fiche}'
    )

    presentation = get_presentation_inscription()
    wizard_reinitialiser(request)
    # Même patron que dashboard.views.confirmation_creation_compte : transite
    # par la session (jamais l'URL), lu puis effacé (pop) par wizard_confirmation
    # — un rafraîchissement de la page de confirmation ne réaffiche jamais les
    # mêmes infos ni ne permet de rejouer la création.
    request.session['wizard_confirmation'] = {
        'nom': inscription.nom,
        # _localise (chantier i18n du 2026-08-28) : repli automatique sur l'arabe
        # si le مدير/مشرف n'a pas encore saisi la traduction FR/EN.
        'message_bienvenue': presentation.message_bienvenue_localise,
        'delai_contact_heures': parametres.delai_contact_heures,
    }
    return redirect(url_etape_suivante('paiement'))


@never_cache
def wizard_confirmation(request):
    """Étape 6 — affichage seul. Les infos transitent par la session (voir
    _wizard_confirmer_inscription ci-dessus), lues puis immédiatement effacées
    (pop) — même patron que dashboard.views.confirmation_creation_compte."""
    info = request.session.pop('wizard_confirmation', None)
    if not info:
        return redirect('wizard_intro')
    return render(request, 'inscriptions/wizard_confirmation.html', info)


def wizard_etape_personnalisee(request, code):
    """Page GÉNÉRIQUE unique pour TOUTE étape personnalisée créée librement
    par le مدير au-delà des 7 étapes réelles (Partie 3B, chantier du
    2026-08-23, "étapes repositionnables/insérables n'importe où") —
    exemple concret : "الشروط والأحكام" insérée entre 'abonnement' et
    'paiement'. RÉUTILISE À L'IDENTIQUE le moteur déjà partagé par
    wizard_identite/wizard_programme (Partie 3A) : _champs_visibles_pour_
    etape (rendu) et traiter_champs_dynamiques_post (validation) — jamais
    une 3e version divergente, une seule vue Python sert un nombre
    illimité d'étapes personnalisées.

    AVANT cette correction : une étape personnalisée n'avait tout
    simplement AUCUNE page — url_etape_suivante l'ignorait silencieusement
    (trou identifié par l'audit du 2026-08-23, voir son ancienne docstring).
    Obligatoire non rempli -> erreur claire affichée ICI, jamais un blocage
    silencieux plus loin dans le parcours (contrairement au trou déjà
    documenté pour un champ attaché à une étape sans page dédiée avant ce
    chantier) : cette vue EST la page dédiée, pour n'importe quel code.

    SAUT SERVEUR (mêmes principes que les 7 vues réelles) : `code`
    correspondant à une des 7 étapes réelles -> redirigé vers SA vraie vue
    dédiée (jamais un rendu générique en doublon, qui bypasserait sa
    logique propre — âge/sexe pour 'identite', groupes pour 'groupe'...) ;
    étape inexistante/désactivée (URL forcée, supprimée entretemps) ->
    redirigé proprement au début du parcours, jamais un 404/500 réel."""
    from .models import EtapeInscription
    from .utils import (
        URL_PAR_CODE_ETAPE, traiter_champs_dynamiques_post,
        url_etape_precedente, url_etape_suivante,
    )

    if code in URL_PAR_CODE_ETAPE:
        return redirect(URL_PAR_CODE_ETAPE[code])

    etape = EtapeInscription.objects.filter(code=code, est_actif=True).first()
    if etape is None:
        return redirect('wizard_categorie_age')

    donnees = wizard_donnees(request)
    if 'nom' not in donnees:
        return redirect('wizard_identite')

    if request.method == 'POST':
        champs = _champs_visibles_pour_etape(code)
        nouvelles_valeurs, erreurs = traiter_champs_dynamiques_post(request.POST, champs)

        if not erreurs:
            wizard_maj(request, nouvelles_valeurs)
            return redirect(url_etape_suivante(code))

        return render(request, 'inscriptions/wizard_etape_personnalisee.html', {
            'etape': etape, 'champs': champs, 'erreurs': erreurs,
            'url_precedente': url_etape_precedente(code),
        })

    champs = _champs_visibles_pour_etape(code)
    return render(request, 'inscriptions/wizard_etape_personnalisee.html', {
        'etape': etape, 'champs': champs,
        'url_precedente': url_etape_precedente(code),
    })
