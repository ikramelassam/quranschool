"""Moteur du nouveau parcours d'inscription — Étape 4 du chantier.

Trois fonctions centrales :
- groupes_compatibles(reponses) : filtrage générique des groupes, 3 backends fixes
  (eav/champ_groupe/nb_slots), JAMAIS une branche par nom de critère métier.
- couverture_critere(critere) : matière première des warnings de configuration
  incomplète (Parties 7-8 du cahier des charges).
- inscrire_eleve(reponses_brutes, cree_par=None, confirme_override=False) : point
  d'entrée UNIQUE pour créer une candidature — utilisé À L'IDENTIQUE par le
  formulaire public (Étape 6) et l'ajout manuel Directeur/مشرف (Étape 7). Pas
  encore branché à aucune vue à ce stade (voir registration/views.py, toujours
  vide) — complète et testée isolément, comme demandé.

Limites connues et assumées à ce stade (à lever aux étapes suivantes, jamais
silencieuses) :
- "وسيلة الحضور" (InscriptionEleve.outil) ne fait pas encore partie du nouveau
  parcours — laissé vide pour toute candidature créée ici.
- InscriptionEleve.programme/riwaya (CharField historiques) restent vides pour
  toute candidature créée ici — la source de vérité pour Programme/Riwaya est
  désormais ReponseInscription, pas ces 2 colonnes (voir leur docstring dans
  inscriptions.models pour la justification de les avoir rendues blank=True).
  Les écrans admin existants qui les affichent directement (admin_inscription_
  detail.html...) afficheront donc un blanc pour ces candidatures tant qu'un
  chantier ultérieur ne les branche pas sur ReponseInscription à l'affichage.
- L'assemblage/la validation du téléphone (indicatif + confirmation WhatsApp)
  N'EST PAS refait ici — c'est un mécanisme de FORMULAIRE (dépend de la forme
  exacte du POST), pas une règle métier. La vue appelante (Étape 6/7) doit
  continuer à utiliser inscriptions.views._construire_et_valider_telephone(
  request) TEL QUEL puis transmettre le numéro déjà validé dans
  reponses_brutes['telephone'] — c'est ça, "réutiliser le mécanisme existant",
  pas le dupliquer à l'intérieur d'une fonction censée être indépendante de la
  forme d'une requête HTTP.
- L'affectation RÉELLE du nouvel Eleve au groupe choisi (InscriptionEleve.
  groupe_choisi) à la validation admin n'est PAS câblée ici — dashboard.views.
  admin_valider_eleve, existant, n'est pas modifié par ce commit.
"""

import datetime

from django.db import transaction
from django.db.models import Count


# ==================== ÉTAT DU WIZARD CÔTÉ SERVEUR (Étape 6) ====================
# Sécurité non négociable (voir l'échange de validation de ce chantier) : les
# réponses données à chaque étape du parcours public vivent dans la session
# Django (signée, stockage serveur — jamais uniquement des champs cachés HTML
# qu'un visiteur pourrait manipuler entre deux requêtes). Chaque étape FUSIONNE
# ses nouvelles réponses dans ce même dict, jamais ne le remplace — un retour
# en arrière dans le parcours ne perd donc jamais les réponses déjà données
# aux autres étapes.

WIZARD_SESSION_KEY = 'wizard_inscription'


def wizard_donnees(request):
    """Dict accumulé des réponses du wizard en cours pour cette session —
    jamais None, {} si rien n'a encore été soumis."""
    return request.session.get(WIZARD_SESSION_KEY, {})


def wizard_maj(request, nouvelles_valeurs):
    """Fusionne `nouvelles_valeurs` dans le dict déjà en session (remplace
    seulement les clés présentes dans nouvelles_valeurs, conserve tout le
    reste) et force la persistance — Django ne détecte JAMAIS automatiquement
    la mutation d'un dict imbriqué dans la session, session.modified = True
    est indispensable ici, sans quoi la mise à jour serait silencieusement
    perdue à la fin de la requête."""
    donnees = wizard_donnees(request)
    donnees.update(nouvelles_valeurs)
    request.session[WIZARD_SESSION_KEY] = donnees
    request.session.modified = True
    return donnees


def wizard_reinitialiser(request):
    """Vide le wizard en cours — appelé après une confirmation réussie
    (Étape 6), pour qu'un rechargement de la page de confirmation ou un
    retour arrière du navigateur ne puisse jamais rejouer une 2e soumission
    avec les mêmes réponses."""
    request.session.pop(WIZARD_SESSION_KEY, None)
    request.session.modified = True


# ==================== FILTRAGE GÉNÉRIQUE DES GROUPES (Phase 6) ====================

def groupes_compatibles(reponses):
    """reponses : dict {Critere: valeur}, valeur selon critere.backend :
    - 'eav' : une CritereOption, ou une liste/tuple/set de CritereOption (choix
      multiple — le groupe doit avoir AU MOINS UNE des options choisies).
    - 'champ_groupe' : la valeur brute du champ réel (ex: 'groupe'/'individuel'
      pour type_capacite).
    - 'nb_slots' : un entier (nombre de séances hebdomadaires souhaité).

    Seuls les critères filtrable=True sont pris en compte — un critère informatif
    présent dans reponses (ex: "Pays") est silencieusement ignoré ici, il ne sert
    jamais à exclure un groupe. Un critère absent de reponses n'est pas non plus
    filtré : "pas de réponse" ne veut jamais dire "aucun groupe ne convient".

    Chaque critère répondu ajoute UN appel .filter() séparé -> UNE jointure SQL
    par critère (sémantique ET entre critères, garantie par Django : des appels
    .filter() successifs sur une même relation inverse ne se combinent JAMAIS
    dans la même jointure, contrairement à .filter(a=x, b=y) en un seul appel).
    Une seule requête SQL au total, quel que soit le nombre de critères — jamais
    de boucle Python sur tous les groupes.

    AUCUNE branche 'if critere.code == ...' : la généricité tient entièrement sur
    ces 3 valeurs FERMÉES de critere.backend, jamais sur le nom métier du
    critère — c'est ce qui permet à "Mode d'apprentissage préféré"/"Langue
    préférée"/tout critère futur jamais imaginé aujourd'hui de fonctionner sans
    une seule ligne de code neuve (voir RegistrationGenericiteTests)."""
    from courses.models import Groupe

    qs = Groupe.actifs.filter(statut='actif')
    for critere, valeur in reponses.items():
        if not critere.filtrable or valeur in (None, '', [], set(), ()):
            continue
        if critere.backend == 'champ_groupe':
            qs = qs.filter(**{critere.champ_modele_groupe: valeur})
        elif critere.backend == 'nb_slots':
            alias = f'_nb_slots_critere_{critere.pk}'
            qs = qs.annotate(**{alias: Count('creneau__slots', distinct=True)}).filter(**{alias: valeur})
        else:  # 'eav' — comportement par défaut de tout critère, y compris futur
            options = valeur if isinstance(valeur, (list, tuple, set)) else [valeur]
            qs = qs.filter(valeurs_criteres__critere=critere, valeurs_criteres__option__in=options)
    return qs.distinct().select_related('creneau', 'prof__user').prefetch_related('creneau__slots')


def groupes_compatibles_avec_age(reponses, date_naissance):
    """groupes_compatibles() + contrainte d'âge structurelle (Creneau.age_min/
    age_max — champ dédié, PAS un Critere, voir la décision explicite à ce sujet).
    Toujours appliquée, jamais contournable par confirme_override (même principe
    que courses.utils.raison_incompatibilite_groupe, où l'âge reste bloquant même
    pour le مدير)."""
    from courses.utils import _age_depuis_naissance

    age = _age_depuis_naissance(date_naissance)
    return groupes_compatibles(reponses).filter(creneau__age_min__lte=age, creneau__age_max__gte=age)


def groupes_avec_place_disponible(queryset):
    """Exclut les groupes dont le nombre d'élèves a déjà atteint capacite_max
    — RÉSERVÉ À L'AFFICHAGE d'une liste de choix (wizard_groupe étape 3,
    admin_eleve_ajouter_manuel round 2, Étape 7) : ne jamais montrer un groupe
    complet comme une option cliquable, plutôt que le laisser choisir puis le
    refuser après coup avec un message générique.

    Correction du bug signalé le 2026-08-21 : groupes_compatibles()/
    groupes_compatibles_avec_age() ne filtraient QUE sur les critères et
    l'âge, jamais sur la capacité — la vérification de capacité existait déjà
    (voir inscrire_eleve() et le POST de wizard_groupe), mais seulement pour
    REFUSER un choix déjà fait, jamais pour retirer un groupe complet de la
    liste affichée en premier lieu.

    Volontairement une fonction SÉPARÉE, PAS fusionnée dans groupes_
    compatibles()/groupes_compatibles_avec_age() elles-mêmes : inscrire_eleve()
    a besoin de distinguer "groupe complet" (message dédié "المجموعة المختارة
    مكتملة العدد") d'un désaccord de critère/âge (message générique "لم تعد
    متاحة أو لا تتوافق") — si groupes_compatibles() excluait déjà les groupes
    complets de sa requête, inscrire_eleve() ne recevrait plus jamais ce cas
    précis à la ligne où il vérifie explicitement la capacité (le groupe
    aurait déjà disparu de `candidats` plus haut) et perdrait ce message
    spécifique. La capacité reste donc revalidée séparément, une 2e fois, à
    la confirmation finale (inscrire_eleve, déjà en place, INCHANGÉ par ce
    correctif) — jamais contournable, y compris par confirme_override
    (Directeur/مشرف, voir Partie 17)."""
    from django.db.models import Count, F

    return queryset.annotate(_nb_eleves_actuel=Count('eleves', distinct=True)).filter(
        _nb_eleves_actuel__lt=F('capacite_max')
    )


def nb_seances_disponibles(reponses_sans_nb_slots):
    """Valeurs de 'nombre de séances hebdomadaires' RÉELLEMENT proposables à
    l'élève à l'étape 2 — jamais 1/2/3/4 codés en dur. reponses_sans_nb_slots :
    même format que groupes_compatibles(), SANS le critère nb_slots lui-même
    (on cherche justement ses valeurs possibles, pas à filtrer dessus).

    COMPORTEMENT DISTINCT SELON type_offre (bug signalé le 2026-08-21 —
    contredisait une décision déjà actée, voir ReponseInscription.valeur_texte
    dans registration/models.py : "nb_seances_hebdo en parcours Individuel,
    purement indicatif") :
    - 'groupe' (ou type_offre absent/pas encore répondu) : filtré STRICTEMENT
      contre les vrais CreneauSlot des groupes compatibles avec TOUTES les
      réponses déjà données (programme/riwaya/...) — comportement historique,
      inchangé.
    - 'individuel' : en Individuel, il n'existe structurellement PAS de groupe
      individuel réel préconfiguré pour chaque combinaison de critères — c'est
      l'école qui monte l'horaire sur mesure après coup. Filtrer strictement
      donnerait donc souvent une liste VIDE, bloquant l'inscription à tort.
      Retourne à la place l'union des nb_slots de TOUS les groupes actifs du
      système (tous types de groupes, tous critères confondus, PAS restreint
      à individuel+riwaya+programme exacts) — une liste de choix raisonnable,
      jamais vide tant qu'au moins un groupe existe quelque part.

    Recalculée à CHAQUE appel, jamais mise en cache — un nouveau groupe à 5
    séances/semaine créé par le مدير apparaît immédiatement à la prochaine
    requête, sans action supplémentaire (même philosophie que
    courses.utils.lien_seance_est_actif)."""
    critere_type_offre = next((c for c in reponses_sans_nb_slots if c.backend == 'champ_groupe'), None)
    type_offre_valeur = reponses_sans_nb_slots.get(critere_type_offre) if critere_type_offre else None

    if type_offre_valeur == 'individuel':
        from courses.models import Groupe
        qs = Groupe.actifs.filter(statut='actif').exclude(creneau__isnull=True)
    else:
        qs = groupes_compatibles(reponses_sans_nb_slots).exclude(creneau__isnull=True)

    valeurs = qs.annotate(_n=Count('creneau__slots', distinct=True)).values_list('_n', flat=True)
    return sorted({v for v in valeurs if v})


# ==================== COUVERTURE D'UN CRITÈRE (Parties 7-8) ====================

def couverture_critere(critere):
    """None si critere.backend != 'eav' — 'champ_groupe' (porté par un champ réel
    toujours renseigné sur Groupe) et 'nb_slots' (dérivé, jamais "manquant" par
    construction) n'ont structurellement aucune notion de "groupe non configuré".
    Sinon {'total', 'configures', 'groupes_manquants'} — recalculé à chaque appel,
    jamais mis en cache, même philosophie que groupes_compatibles/nb_seances_
    disponibles. Utilisé par le dashboard (Étape 5) pour afficher le warning
    avant d'activer filtrable=True/obligatoire=True sur un critère."""
    from courses.models import Groupe

    if critere.backend != 'eav':
        return None

    groupes_actifs = Groupe.actifs.filter(statut='actif')
    total = groupes_actifs.count()
    ids_configures = set(
        groupes_actifs.filter(valeurs_criteres__critere=critere).values_list('id', flat=True)
    )
    return {
        'total': total,
        'configures': len(ids_configures),
        'groupes_manquants': groupes_actifs.exclude(id__in=ids_configures),
    }


def statut_compatibilite_groupe(groupe_id, reponses_pour_filtrage, date_naissance):
    """'ok' (groupe strictement compatible, aucun avertissement), 'contournable'
    (incompatible sur au moins un critère filtrable NON bloquant seulement —
    l'âge et tout critère bloquant=True restent respectés) ou 'incompatible'
    (âge ou critère bloquant en désaccord — jamais contournable, même par
    confirme_override). 'incompatible' aussi si groupe_id est vide/invalide.

    Vérification en LECTURE SEULE — n'écrit rien, ne crée rien. Applique
    EXACTEMENT la même règle que inscrire_eleve() (Partie 22) en interne pour
    décider si confirme_override peut s'appliquer : les deux appellent
    groupes_compatibles_avec_age() avec, respectivement, TOUTES les réponses
    filtrables puis SEULEMENT les réponses bloquantes. Utilisée par
    dashboard.views.admin_eleve_ajouter_manuel (Étape 7) pour savoir, AVANT
    tout appel à inscrire_eleve(), s'il faut afficher un avertissement
    contournable ou une erreur dure — jamais pour décider de la sécurité
    elle-même, qui reste entièrement portée par inscrire_eleve()."""
    if not groupe_id:
        return 'incompatible'
    if groupes_compatibles_avec_age(reponses_pour_filtrage, date_naissance).filter(id=groupe_id).exists():
        return 'ok'
    reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
    if groupes_compatibles_avec_age(reponses_bloquantes, date_naissance).filter(id=groupe_id).exists():
        return 'contournable'
    return 'incompatible'


def abonnements_disponibles(type_offre_valeur, type_age):
    """TypeAbonnement actifs cohérents avec la tranche d'âge et, si connu, le
    type_offre (groupe/individuel) — factorisé depuis wizard_abonnement
    (Étape 6D) pour que l'ajout manuel (Étape 7) propose exactement la même
    liste, jamais une 2e requête maintenue séparément."""
    from inscriptions.models import TypeAbonnement

    abonnements = TypeAbonnement.objects.filter(est_actif=True, cible_age__in=[type_age, 'les_deux'])
    if type_offre_valeur:
        abonnements = abonnements.filter(type_offre=type_offre_valeur)
    return abonnements.order_by('ordre')


def definir_valeurs_groupe(groupe, critere, options):
    """Remplace l'ENSEMBLE des GroupeCritereValeur d'un (groupe, critere) par
    `options` (liste de CritereOption, 0 à N selon type_champ) — même idiome
    "remplacer, jamais accumuler" que courses.utils.matrice_vers_lignes/
    remplacer_slots_creneau. Réservé aux critères backend='eav' : appeler ceci
    pour 'champ_groupe' ou 'nb_slots' est une erreur de programmation (ces 2
    backends ne stockent jamais de GroupeCritereValeur, voir leur docstring
    dans registration.models) — lève ValueError plutôt que d'écrire une
    donnée qui ne serait jamais lue par groupes_compatibles()."""
    from .models import GroupeCritereValeur

    if critere.backend != 'eav':
        raise ValueError(
            f"definir_valeurs_groupe : critere '{critere.code}' est backend='{critere.backend}', "
            f"pas 'eav' — aucune GroupeCritereValeur ne doit jamais être écrite pour ce backend."
        )

    GroupeCritereValeur.objects.filter(groupe=groupe, critere=critere).delete()
    GroupeCritereValeur.objects.bulk_create([
        GroupeCritereValeur(groupe=groupe, critere=critere, option=option) for option in options
    ])


# ==================== RÈGLES CONDITIONNELLES (Phase 7 / Partie 16) ====================

def _regle_satisfaite(regle, codes_options_repondus_par_critere):
    """codes_options_repondus_par_critere : {critere_id: {code, code, ...}} — les
    codes d'options déjà choisies pour chaque critère répondu jusqu'ici."""
    codes_repondus = codes_options_repondus_par_critere.get(regle.critere_condition_id, set())
    codes_regle = set(regle.valeurs)
    if regle.operateur == 'egal' or regle.operateur == 'dans':
        return bool(codes_repondus & codes_regle)
    if regle.operateur == 'different':
        return bool(codes_repondus) and not (codes_repondus & codes_regle)
    return False


def _regles_pour(instance):
    from django.contrib.contenttypes.models import ContentType
    from .models import RegleCondition

    ct = ContentType.objects.get_for_model(instance)
    return RegleCondition.objects.filter(
        cible_content_type=ct, cible_object_id=instance.pk, est_actif=True
    ).select_related('critere_condition')


def champ_est_masque(champ, codes_options_repondus_par_critere):
    """True si champ.etape OU champ lui-même est masqué par au moins une
    RegleCondition satisfaite par les réponses déjà données. Une étape masquée
    masque tous ses champs, sans qu'il faille dupliquer une règle par champ
    (ex: 'SI type_offre != groupe -> masquer étape Choisir un groupe' masque
    tous les champs de cette étape en une seule règle)."""
    if any(_regle_satisfaite(r, codes_options_repondus_par_critere) for r in _regles_pour(champ.etape)):
        return True
    return any(_regle_satisfaite(r, codes_options_repondus_par_critere) for r in _regles_pour(champ))


# ==================== VALIDATION D'UNE RÉPONSE DE CHAMP ====================

def _reponses_a_creer_pour_champ(champ, valeur_brute):
    """Traduit la valeur brute soumise (code d'option, texte, ou entier pour
    nb_slots) en liste de tuples (option_ou_None, valeur_texte) à écrire en
    ReponseInscription — plusieurs tuples pour un choix_multiple (une ligne par
    option choisie, même patron que GroupeCritereValeur). Liste vide = rien à
    créer (champ non répondu). Renvoie (liste, message_erreur_ou_None) — l'erreur
    n'est levée que pour une valeur structurellement invalide (option inexistante/
    désactivée pour ce critère), jamais pour une simple absence de réponse (la
    règle "obligatoire" est vérifiée par l'appelant, pas ici)."""
    critere = champ.critere

    if critere is None:
        # Champ informatif pur (Étape 1, ex: "Pays"/"Niveau scolaire") — jamais
        # d'option possible, type_champ vient du ChampInscription lui-même.
        texte = valeur_brute.strip() if isinstance(valeur_brute, str) else valeur_brute
        return ([(None, texte)] if texte not in (None, '') else []), None

    if critere.backend == 'nb_slots':
        # Pas de CritereOption pour ce backend (valeurs calculées à la volée,
        # voir nb_seances_disponibles) — stocké en texte brut, jamais comme
        # option puisqu'aucune ligne CritereOption n'existe pour ces valeurs.
        texte = str(valeur_brute).strip() if valeur_brute not in (None, '') else ''
        return ([(None, texte)] if texte else []), None

    if critere.type_champ == 'choix_multiple':
        codes = [c for c in (valeur_brute if isinstance(valeur_brute, (list, tuple)) else [valeur_brute]) if c]
        if not codes:
            return [], None
        options = list(critere.options.filter(est_actif=True, code__in=codes))
        if len(options) != len(set(codes)):
            return [], f'خيار غير صالح ضمن "{champ.label}".'
        return [(o, '') for o in options], None

    if critere.type_champ == 'choix_unique':
        code = valeur_brute
        if not code:
            return [], None
        option = critere.options.filter(est_actif=True, code=code).first()
        if option is None:
            return [], f'خيار غير صالح ضمن "{champ.label}".'
        return [(option, '')], None

    # texte/email/telephone/nombre/date/booleen rattaché à un critère (rare mais
    # possible — un Critere peut très bien ne jamais servir au filtrage).
    texte = valeur_brute.strip() if isinstance(valeur_brute, str) else valeur_brute
    return ([(None, texte)] if texte not in (None, '') else []), None


def extraire_champs_depuis_post(post_data):
    """dict {champ_<id>: valeur} depuis un QueryDict POST — valeur = liste si
    plusieurs valeurs soumises sous la même clé (choix multiple), sinon chaîne
    simple. Déplacé depuis registration/views.py vers ce module (Étape 7) : à
    l'origine réservé à wizard_programme (évaluer les RegleCondition avec les
    réponses de LA soumission EN COURS, pas seulement celles déjà en session),
    désormais aussi utilisé par dashboard.views.admin_eleve_ajouter_manuel pour
    construire reponses_brutes à partir d'un POST brut — MÊME fonction, jamais
    une 2e version réécrite côté admin."""
    extrait = {}
    for cle in post_data:
        if cle.startswith('champ_'):
            valeurs = post_data.getlist(cle)
            extrait[cle] = valeurs if len(valeurs) > 1 else valeurs[0]
    return extrait


def donnees_filtrage_json_pour_wizard():
    """Un objet par Groupe actif avec créneau : {groupe_id, valeurs:
    {critere_id: code_ou_valeur}, nb_slots} — sert au calcul EN DIRECT (JS,
    sans requête serveur) du nombre de séances réellement proposables, à
    mesure que l'élève (ou le Directeur/مشرف à l'Étape 7) répond aux autres
    champs de la même étape (Programme/Riwaya/Groupe-ou-Individuel). Même
    patron que creneaux_json déjà utilisé par l'ancien formulaire à une page
    (eleve_formulaire.html) pour filtrer les créneaux par âge/sexe côté
    client — PUREMENT un confort d'affichage immédiat, jamais la source de
    vérité : le filtrage définitif et sécurisé est TOUJOURS refait côté
    serveur par groupes_compatibles() (wizard_groupe, admin_eleve_ajouter_
    manuel, inscrire_eleve()), qui ne fait JAMAIS confiance à ce qu'affichait
    le navigateur. Déplacé depuis registration/views.py (Étape 7) : fonction
    pure, sans dépendance à `request`, partagée par le wizard public ET
    l'ajout manuel Directeur/مشرف — jamais 2 versions maintenues séparément.

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


# ==================== ÉVALUATION PARTAGÉE DES CHAMPS ACTIFS (Étape 6C) ====================
# Factorisé depuis inscrire_eleve() : wizard_groupe (aperçu des groupes
# compatibles à l'étape 3, AVANT confirmation) et inscrire_eleve (revalidation
# à la confirmation finale, étape 6) doivent construire le même
# {Critere: valeur} à partir des mêmes réponses brutes — sinon un groupe
# proposé à l'étape 3 pourrait être refusé à l'étape 6 pour une raison qui
# n'a rien à voir avec un changement réel de disponibilité, simplement parce
# que les deux vues auraient chacune leur propre logique de reconstruction,
# divergente au moindre écart futur.

def evaluer_champs_actifs(reponses_brutes):
    """Parcourt tous les ChampInscription actifs (toutes étapes, dans
    l'ordre), en respectant les RegleCondition (champ_est_masque) évaluées
    AU FUR ET À MESURE avec les réponses déjà rencontrées dans CE MÊME
    passage — un champ démasqué par une réponse plus haut dans le parcours
    est donc pris en compte correctement. Retourne une liste ordonnée de
    dicts {'champ', 'paires', 'erreur', 'masque'} — 'paires' et 'erreur' au
    même format que _reponses_a_creer_pour_champ, vide/None si 'masque' est
    True (jamais évalué dans ce cas)."""
    from .models import ChampInscription

    resultats = []
    codes_options_repondus = {}
    champs_actifs = list(
        ChampInscription.objects.filter(est_actif=True, etape__est_actif=True)
        .select_related('critere', 'etape').order_by('etape__ordre', 'ordre')
    )
    for champ in champs_actifs:
        if champ_est_masque(champ, codes_options_repondus):
            resultats.append({'champ': champ, 'paires': [], 'erreur': None, 'masque': True})
            continue

        valeur_brute = reponses_brutes.get(f'champ_{champ.id}')
        paires, erreur = _reponses_a_creer_pour_champ(champ, valeur_brute)
        resultats.append({'champ': champ, 'paires': paires, 'erreur': erreur, 'masque': False})

        if champ.critere is not None and not erreur:
            codes = {o.code for o, _ in paires if o is not None}
            if codes:
                codes_options_repondus.setdefault(champ.critere_id, set()).update(codes)

    return resultats


def reponses_pour_filtrage_depuis_resultats(resultats):
    """Construit {Critere: valeur} (format attendu par groupes_compatibles/
    groupes_compatibles_avec_age) à partir du résultat de
    evaluer_champs_actifs() — ignore les champs masqués, en erreur, non liés
    à un critère, ou dont le critère n'est pas filtrable."""
    reponses = {}
    for r in resultats:
        champ = r['champ']
        if r['masque'] or r['erreur'] or champ.critere is None or not champ.critere.filtrable or not r['paires']:
            continue
        if champ.critere.backend == 'nb_slots':
            # r['paires'] == [(None, '<entier en texte>')].
            try:
                reponses[champ.critere] = int(r['paires'][0][1])
            except (ValueError, TypeError):
                pass
        elif champ.critere.backend == 'champ_groupe':
            # r['paires'] == [(option, '')] — le CODE de l'option est la
            # valeur brute à comparer au champ réel de Groupe.
            premiere_option = r['paires'][0][0]
            if premiere_option is not None:
                reponses[champ.critere] = premiere_option.code
        else:
            options_choisies = [o for o, _ in r['paires'] if o is not None]
            if options_choisies:
                reponses[champ.critere] = options_choisies
    return reponses


# ==================== POINT D'ENTRÉE UNIQUE (Parties 9, 22) ====================

def inscrire_eleve(reponses_brutes, cree_par=None, confirme_override=False):
    """Crée une InscriptionEleve + ses ReponseInscription (immuables — aucune vue
    de modification n'existe nulle part sur ReponseInscription, voir
    registration/views.py) à partir d'un dict à plat reponses_brutes, MÊME FORME
    quelle que soit la porte d'entrée (public, Directeur, مشرف) :

    - champs d'identité structurels, clés directes (jamais transformés en EAV) :
      'nom', 'nom_parent', 'sexe', 'telephone' (DÉJÀ validé/assemblé par
      l'appelant, voir docstring du module), 'date_naissance' (ISO 'AAAA-MM-JJ'),
      'email', 'job_actuel', 'remarques', 'accepte_conditions' ('oui'/autre).
    - réponse à un ChampInscription dynamique : clé 'champ_<id>', valeur = code
      d'option (choix), liste de codes (choix multiple), texte/nombre brut, ou
      entier (nb_slots).
    - 'groupe_id' : uniquement utilisé si le critère backend='champ_groupe' a
      répondu 'groupe' — REVALIDÉ dans tous les cas (Partie 22), jamais fait
      confiance tel quel. Silencieusement ignoré (jamais une erreur) si la
      réponse est 'individuel' — sécurité serveur contre un POST manipulé
      (Partie 3/26), pas seulement un masquage JS de l'étape.
    - 'abonnement_code' : code TypeAbonnement choisi, revalidé (actif, cohérent
      avec type_offre et la tranche d'âge réelle de l'élève).

    cree_par=None : formulaire public. cree_par=<User admin/mshrif> : ajout
    manuel (Étape 7) — permissions strictement identiques pour les 2 rôles,
    contrôlées par la vue appelante (accounts.decorators.role_required), pas ici.

    confirme_override : réservé à cree_par non None — permet de passer outre un
    critère filtrable NON bloquant (critere.bloquant=False) en désaccord avec le
    groupe choisi, jamais un critère bloquant ni une contrainte structurelle
    (âge, capacité, statut actif). Le formulaire public ne peut jamais valoir
    True ici (imposé par la vue appelante, pas par cette fonction — voir Partie
    17 : bloquant/avertissement reste une distinction PAR CRITÈRE, configurable
    depuis le dashboard, jamais un interrupteur global).

    Retourne (inscription, erreurs) : erreurs = liste de messages arabes (rien
    n'est créé) si la validation échoue ; (inscription, []) si la création a
    réussi. Ne lève jamais d'exception pour une erreur de saisie utilisateur."""
    from courses.models import Groupe
    from courses.utils import tranche_age_depuis_naissance
    from inscriptions.models import InscriptionEleve, TypeAbonnement, get_parametres_inscriptions
    from inscriptions.views import _email_bloque_pour_candidature_eleve, MESSAGE_EMAIL_DEJA_UTILISE
    from .models import ReponseInscription

    erreurs = []

    # ---- 1. Identité structurelle ----
    nom = (reponses_brutes.get('nom') or '').strip()
    sexe = reponses_brutes.get('sexe') or ''
    email = (reponses_brutes.get('email') or '').strip()
    telephone = (reponses_brutes.get('telephone') or '').strip()

    if not nom:
        erreurs.append('الاسم الكامل إلزامي.')
    if sexe not in ('homme', 'femme'):
        erreurs.append('الجنس إلزامي.')
    if not telephone:
        erreurs.append('رقم الهاتف إلزامي.')
    if not email:
        erreurs.append('البريد الإلكتروني إلزامي.')
    elif _email_bloque_pour_candidature_eleve(email):
        erreurs.append(MESSAGE_EMAIL_DEJA_UTILISE)

    date_naissance = None
    try:
        date_naissance = datetime.date.fromisoformat(reponses_brutes.get('date_naissance', ''))
    except (ValueError, TypeError):
        erreurs.append('يرجى إدخال تاريخ ميلاد صحيح.')

    if date_naissance is not None:
        type_age = tranche_age_depuis_naissance(date_naissance)
        parametres = get_parametres_inscriptions()
        categorie_fermee = (
            (type_age == 'adulte' and not parametres.ouverte_eleve_adulte)
            or (type_age == 'enfant' and not parametres.ouverte_eleve_enfant)
        )
        if categorie_fermee:
            erreurs.append('التسجيل مغلق حالياً لهذه الفئة العمرية.')
    else:
        type_age = None

    if erreurs:
        return None, erreurs

    # ---- 2. Champs dynamiques actifs, en respectant les règles conditionnelles ----
    # evaluer_champs_actifs/reponses_pour_filtrage_depuis_resultats : brique
    # PARTAGÉE avec wizard_groupe (aperçu étape 3) — voir leur docstring,
    # jamais de logique de reconstruction dupliquée entre l'aperçu et la
    # validation finale.
    resultats = evaluer_champs_actifs(reponses_brutes)

    a_creer = []  # [(champ, option, valeur_texte)]
    for r in resultats:
        if r['masque']:
            continue
        champ, paires, erreur = r['champ'], r['paires'], r['erreur']
        if erreur:
            erreurs.append(erreur)
            continue
        if not paires and champ.obligatoire:
            erreurs.append(f'"{champ.label}" إلزامي.')
            continue
        for option, texte in paires:
            a_creer.append((champ, option, texte))

    if erreurs:
        return None, erreurs

    reponses_pour_filtrage = reponses_pour_filtrage_depuis_resultats(resultats)

    # ---- 3. Groupe (uniquement si le critère champ_groupe='type_offre' vaut 'groupe') ----
    critere_type_offre = next(
        (c for c in reponses_pour_filtrage if c.backend == 'champ_groupe'), None
    )
    type_offre_valeur = reponses_pour_filtrage.get(critere_type_offre) if critere_type_offre else None

    groupe_choisi = None
    groupe_id = reponses_brutes.get('groupe_id')
    if type_offre_valeur == 'groupe':
        if not groupe_id:
            erreurs.append('يرجى اختيار مجموعة.')
        elif date_naissance is None:
            pass  # déjà signalé plus haut
        else:
            candidats = groupes_compatibles_avec_age(reponses_pour_filtrage, date_naissance)
            groupe_choisi = candidats.filter(id=groupe_id).first()

            if groupe_choisi is None and cree_par is not None and confirme_override:
                # Override réservé au Directeur/مشرف (Partie 17) : ne relâche QUE
                # les critères filtrable non bloquants — l'âge (structurel) et
                # tout critère bloquant=True restent des contraintes dures, même
                # avec confirme_override=True.
                reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
                candidats_permissifs = groupes_compatibles_avec_age(reponses_bloquantes, date_naissance)
                groupe_choisi = candidats_permissifs.filter(id=groupe_id).first()

            if groupe_choisi is None:
                erreurs.append('المجموعة المختارة لم تعد متاحة أو لا تتوافق مع اختياراتك.')
            elif groupe_choisi.statut != 'actif':
                erreurs.append('المجموعة المختارة لم تعد نشطة.')
            elif groupe_choisi.eleves.count() >= groupe_choisi.capacite_max:
                erreurs.append('المجموعة المختارة مكتملة العدد.')
    else:
        # Individuel (ou critère absent/mal configuré) : un groupe_id posté n'est
        # JAMAIS utilisé — sécurité serveur (Partie 3/26), pas juste un masquage
        # JS de l'étape. Silencieux, jamais une erreur bloquante pour l'élève.
        groupe_id = None

    if erreurs:
        return None, erreurs

    # ---- 4. Abonnement ----
    abonnement_code = reponses_brutes.get('abonnement_code', '')
    abonnement = TypeAbonnement.objects.filter(code=abonnement_code, est_actif=True).first()
    if abonnement is None:
        erreurs.append('يرجى اختيار نوع الاشتراك.')
    else:
        if type_offre_valeur and abonnement.type_offre != type_offre_valeur:
            erreurs.append('نوع الاشتراك المختار لا يتوافق مع نوع الحصة (جماعي/فردي).')
        if type_age and abonnement.cible_age not in (type_age, 'les_deux'):
            erreurs.append('نوع الاشتراك المختار لا يتوافق مع الفئة العمرية.')

    if erreurs:
        return None, erreurs

    # ---- 5. Création (tout ou rien) ----
    with transaction.atomic():
        inscription = InscriptionEleve.objects.create(
            nom=nom,
            nom_parent=(reponses_brutes.get('nom_parent') or '').strip(),
            date_naissance=date_naissance,
            sexe=sexe,
            telephone=telephone,
            email=email,
            job_actuel=(reponses_brutes.get('job_actuel') or '').strip(),
            abonnement=abonnement.code,
            groupe_choisi=groupe_choisi,
            cree_par=cree_par,
            accepte_conditions=reponses_brutes.get('accepte_conditions') == 'oui',
            remarques=(reponses_brutes.get('remarques') or '').strip(),
        )
        ReponseInscription.objects.bulk_create([
            ReponseInscription(
                inscription=inscription, champ=champ, critere=champ.critere,
                option=option, valeur_texte=texte or '',
            )
            for champ, option, texte in a_creer
        ])

    return inscription, []
