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
import logging
import re

from django.core.exceptions import FieldError
from django.db import transaction

logger = logging.getLogger(__name__)
from django.db.models import Count, Q


# ==================== ÉTAT DU WIZARD CÔTÉ SERVEUR (Étape 6) ====================
# Sécurité non négociable (voir l'échange de validation de ce chantier) : les
# réponses données à chaque étape du parcours public vivent dans la session
# Django (signée, stockage serveur — jamais uniquement des champs cachés HTML
# qu'un visiteur pourrait manipuler entre deux requêtes). Chaque étape FUSIONNE
# ses nouvelles réponses dans ce même dict, jamais ne le remplace — un retour
# en arrière dans le parcours ne perd donc jamais les réponses déjà données
# aux autres étapes.

WIZARD_SESSION_KEY = 'wizard_inscription'


# ==================== CHAMPS STRUCTURELS CONFIGURABLES (chantier 2026-08-22) ====================
# nom/nom_parent/sexe/telephone/date_naissance/email/job_actuel/niveau_scolaire
# restent de VRAIES colonnes InscriptionEleve (jamais migrées vers l'EAV) —
# voir registration.models.ConfigurationChampStructurel.__doc__ pour la
# décision complète. Ces 2 fonctions centralisent la lecture/validation
# GÉNÉRIQUE (label/ordre/obligatoire/regex) partagée par wizard_identite ET
# dashboard.views.admin_eleve_ajouter_manuel — jamais 2 versions maintenues
# séparément, même principe que tout le reste de ce moteur.

def champs_structurels_actifs(code_etape):
    """ConfigurationChampStructurel actifs liés à l'EtapeInscription de code
    `code_etape`, dans l'ordre configuré — liste vide (jamais une exception)
    si l'étape n'existe pas encore."""
    from .models import ConfigurationChampStructurel

    return list(
        ConfigurationChampStructurel.objects.filter(
            etape__code=code_etape, etape__est_actif=True, est_actif=True,
        ).order_by('ordre', 'id')
    )


def valider_champ_structurel_libre(config, valeur):
    """Validation GÉNÉRIQUE (obligatoire + regex optionnelle) pour un champ
    structurel NON verrouillé et sans widget spécial (nom/nom_parent/
    job_actuel/niveau_scolaire — jamais sexe/date_naissance/email/telephone,
    voir ConfigurationChampStructurel.CLES_SANS_TYPE_CHAMP, qui gardent leur
    validation dédiée existante, inchangée par ce chantier). Retourne un
    message d'erreur arabe, ou None si valide.

    La regex n'est appliquée QUE si config.regex_validation est non vide ET
    valeur est non vide — un champ non obligatoire laissé vide ne doit
    jamais être rejeté par une regex qui ne concerne que sa FORME quand il
    est rempli."""
    valeur = (valeur or '').strip()
    if config.obligatoire and not valeur:
        return f'"{config.label}" إلزامي.'
    if valeur and config.regex_validation:
        try:
            if not re.fullmatch(config.regex_validation, valeur):
                return config.message_erreur_regex or f'"{config.label}" غير صالح.'
        except re.error:
            # Regex mal formée par le مدير — jamais un 500 pour l'élève,
            # signalé nulle part d'autre qu'ici : mieux vaut laisser passer
            # une regex cassée que planter le formulaire public.
            pass
    return None


# ==================== NAVIGATION DYNAMIQUE (correction 8, 2026-08-22) ====================
# Avant cette correction, l'enchaînement des pages du wizard public était
# figé dans le CODE (chaque vue faisait redirect('wizard_X') avec X en dur) —
# EtapeInscription.ordre ne triait alors que les ChampInscription À
# L'INTÉRIEUR d'une étape, jamais la SÉQUENCE des étapes elle-même. Les 3
# fonctions ci-dessous font de `ordre`/`est_actif` la SEULE source de vérité
# pour "quelle est la page suivante" — voir EtapeInscription.__doc__ pour la
# liste des étapes verrouillées (CODES_VERROUILLES) qui ne peuvent jamais
# être désactivées, ni celles librement réordonnables/désactivables.
#
# 'intro' (Étape 0, ميثاق) reste HORS de ce mapping : simple écran de
# présentation (PresentationInscription), jamais une étape à reconfigurer.

URL_PAR_CODE_ETAPE = {
    'categorie_age': 'wizard_categorie_age',
    'identite': 'wizard_identite',
    'programme': 'wizard_programme',
    'groupe': 'wizard_groupe',
    'abonnement': 'wizard_abonnement',
    'paiement': 'wizard_paiement',
    'confirmation': 'wizard_confirmation',
}


def etape_est_active(code_etape):
    """True si l'EtapeInscription de ce code existe et est active — False si
    le مدير l'a désactivée, ou si elle n'existe pas encore (jamais une
    exception, même défense qu'ailleurs dans ce chantier)."""
    from .models import EtapeInscription

    return EtapeInscription.objects.filter(code=code_etape, est_actif=True).exists()


def etape_suivante(code_etape_actuelle):
    """Code de la PROCHAINE étape active après `code_etape_actuelle`, selon
    EtapeInscription.ordre — jamais un enchaînement figé dans les vues.

    `code_etape_actuelle` reste inclus dans le calcul même s'il est
    lui-même désactivé (ex: 'groupe' sauté pour l'Individuel, ou désactivé
    par le مدير) — dans les 2 cas, on cherche "la prochaine étape active
    après SA POSITION", peu importe si elle est elle-même active ou non :
    aucun besoin de distinguer les 2 raisons de saut ici, la vue appelante
    n'a jamais à passer de règle métier en plus.

    Retourne None si `code_etape_actuelle` est la dernière étape active —
    ne doit jamais arriver en pratique pour un code du parcours réel tant
    que 'confirmation' (verrouillée active, seed en dernière position)
    reste la dernière étape existante."""
    from .models import EtapeInscription

    codes_actifs = list(
        EtapeInscription.objects.filter(est_actif=True).order_by('ordre', 'id').values_list('code', flat=True)
    )
    if code_etape_actuelle in codes_actifs:
        candidats = codes_actifs[codes_actifs.index(code_etape_actuelle) + 1:]
    else:
        # L'étape actuelle est désactivée (ou inexistante) — retombe sur sa
        # position dans l'ordre COMPLET (actives + inactives) pour retrouver
        # quand même la suite logique, jamais un crash.
        tous_les_codes = list(EtapeInscription.objects.order_by('ordre', 'id').values_list('code', flat=True))
        position = tous_les_codes.index(code_etape_actuelle) if code_etape_actuelle in tous_les_codes else -1
        candidats = [c for c in tous_les_codes[position + 1:] if c in codes_actifs]
    return candidats[0] if candidats else None


def etape_precedente(code_etape_actuelle):
    """Symétrique de etape_suivante() ci-dessus — code de l'étape active
    PRÉCÉDANT `code_etape_actuelle`, selon EtapeInscription.ordre. Ajoutée
    au chantier du 2026-08-23 (Partie 3B, "étapes repositionnables/
    insérables n'importe où") pour donner un bouton "رجوع" correct à
    wizard_etape_personnalisee — les 7 pages réelles gardent, elles, leur
    lien "رجوع" codé en dur vers leur voisine habituelle (hors scope de
    cette correction : les réordonner reste sans effet sur CE bouton précis
    chez elles, seulement chez une étape personnalisée)."""
    from .models import EtapeInscription

    codes_actifs = list(
        EtapeInscription.objects.filter(est_actif=True).order_by('ordre', 'id').values_list('code', flat=True)
    )
    if code_etape_actuelle in codes_actifs:
        candidats = codes_actifs[:codes_actifs.index(code_etape_actuelle)]
    else:
        tous_les_codes = list(EtapeInscription.objects.order_by('ordre', 'id').values_list('code', flat=True))
        position = tous_les_codes.index(code_etape_actuelle) if code_etape_actuelle in tous_les_codes else -1
        candidats = [c for c in tous_les_codes[:position] if c in codes_actifs]
    return candidats[-1] if candidats else None


def _reverse_pour_etape(code_etape):
    """Chemin RÉSOLU (django.urls.reverse) pour QUELCONQUE EtapeInscription
    active — réelle (URL_PAR_CODE_ETAPE, sa propre vue dédiée) ou
    PERSONNALISÉE (Partie 3B, chantier du 2026-08-23 : servie par la vue
    générique wizard_etape_personnalisee, paramétrée par son code — avant
    cette correction, une étape personnalisée n'avait tout simplement AUCUNE
    page, voir url_etape_suivante ci-dessous)."""
    from django.urls import reverse

    if code_etape in URL_PAR_CODE_ETAPE:
        return reverse(URL_PAR_CODE_ETAPE[code_etape])
    return reverse('wizard_etape_personnalisee', kwargs={'code': code_etape})


def url_etape_suivante(code_etape_actuelle, repli='wizard_confirmation'):
    """Chemin résolu de la prochaine étape active après
    `code_etape_actuelle` — réelle OU personnalisée (voir _reverse_pour_
    etape). Toujours un CHEMIN déjà résolu (reverse()), jamais un simple nom
    de vue : redirect() accepte les 2 formes de façon identique (même
    en-tête Location produit), mais {% url %} côté template n'accepte QUE
    des noms de vue SANS paramètre — un chemin déjà résolu reste correct
    dans tous les cas (voir wizard_intro.html, seul endroit qui interpole
    directement ce retour plutôt que de le passer à redirect()).

    AVANT le chantier du 2026-08-23 (Partie 3B) : toute étape personnalisée
    (code hors des 7 réels) était silencieusement IGNORÉE ici — trou
    identifié par l'audit du 2026-08-23, `ordre` la positionnait bien dans
    la liste admin mais elle ne s'affichait JAMAIS au candidat. Désormais
    servie par wizard_etape_personnalisee au même titre que les 7 étapes
    réelles — plus aucune étape active n'est sautée silencieusement, la
    boucle anti-régression n'est donc plus nécessaire (etape_suivante()
    renvoie déjà la bonne étape immédiate, réelle ou personnalisée).

    `repli` n'est utilisé que si AUCUNE étape active ne suit du tout (ne
    devrait jamais arriver tant que 'confirmation' reste verrouillée active
    en dernière position) — jamais un 500 pour un élève réel."""
    from django.urls import reverse

    code = etape_suivante(code_etape_actuelle)
    if code is None:
        return reverse(repli)
    return _reverse_pour_etape(code)


def url_etape_precedente(code_etape_actuelle, repli='wizard_intro'):
    """Symétrique de url_etape_suivante() ci-dessus, pour le bouton "رجوع"
    de wizard_etape_personnalisee (Partie 3B) — voir etape_precedente()."""
    from django.urls import reverse

    code = etape_precedente(code_etape_actuelle)
    if code is None:
        return reverse(repli)
    return _reverse_pour_etape(code)


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

def groupes_compatibles(reponses, exclure_caches_wizard_public=True):
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
    une seule ligne de code neuve (voir RegistrationGenericiteTests).

    exclure_caches_wizard_public (chantier du 2026-08-23, "exclusion manuelle
    d'un groupe") : True par défaut — un Groupe.cache_du_wizard_public=True
    n'est alors JAMAIS renvoyé, quels que soient les critères. Ce défaut sert
    tous les appelants PUBLICS (wizard_groupe et, via inscrire_eleve(), la
    revalidation finale d'une candidature créée par le formulaire public,
    cree_par=None) sans qu'ils aient rien à préciser. Les appelants ADMIN
    (statut_compatibilite_groupe, admin_eleve_ajouter_manuel, et
    inscrire_eleve() quand cree_par n'est pas None) passent explicitement
    False : ce champ ne doit JAMAIS affecter l'ajout manuel Directeur/مشرف —
    le مدير reste libre de choisir consciemment un groupe qu'il a lui-même
    masqué du formulaire public."""
    from courses.models import Groupe

    qs = Groupe.actifs.filter(statut='actif')
    for critere, valeur in reponses.items():
        if not critere.filtrable or valeur in (None, '', [], set(), ()):
            continue
        if critere.backend == 'champ_groupe':
            # Filet de sécurité (audit du 2026-08-23, §1) : champ_modele_groupe
            # est validé à la création du critère (dashboard.views.
            # admin_critere_inscription_ajouter) mais une donnée déjà en base
            # AVANT ce correctif (ou modifiée directement en base) peut encore
            # pointer vers un nom de champ inexistant sur Groupe — jamais un
            # 500 pour un candidat réel à cause d'une configuration mal
            # formée : on ignore ce critère pour CE filtrage (comportement
            # dégradé, comme un critère non filtrable), et on journalise pour
            # que le مدير/مشرف puisse le corriger.
            try:
                qs = qs.filter(**{critere.champ_modele_groupe: valeur})
            except FieldError:
                logger.error(
                    "Critere id=%s (code=%r) : champ_modele_groupe=%r n'existe pas sur "
                    "courses.models.Groupe — filtre ignoré pour ce critère.",
                    critere.pk, critere.code, critere.champ_modele_groupe,
                )
                continue
        elif critere.backend == 'nb_slots':
            alias = f'_nb_slots_critere_{critere.pk}'
            qs = qs.annotate(**{alias: Count('creneau__slots', distinct=True)}).filter(**{alias: valeur})
        else:  # 'eav' — comportement par défaut de tout critère, y compris futur
            options = valeur if isinstance(valeur, (list, tuple, set)) else [valeur]
            qs = qs.filter(valeurs_criteres__critere=critere, valeurs_criteres__option__in=options)
    if exclure_caches_wizard_public:
        qs = qs.exclude(cache_du_wizard_public=True)
    return qs.distinct().select_related('creneau', 'prof__user').prefetch_related('creneau__slots')


def groupes_compatibles_avec_age(reponses, date_naissance, sexe, exclure_caches_wizard_public=True):
    """groupes_compatibles() + 2 contraintes STRUCTURELLES (Creneau.age_min/
    age_max ET Creneau.sexe_cible — champs dédiés, PAS des Critere, voir la
    décision explicite à ce sujet). Toujours appliquées, jamais contournables
    par confirme_override (même principe que courses.utils.raison_
    incompatibilite_groupe, où l'âge reste bloquant même pour le مدير).

    sexe filtrant ajouté le 2026-08-22 (régression signalée par le client :
    "élève femme ne doit jamais voir un groupe hommes et vice-versa") — cette
    fonction n'a JAMAIS filtré sur le sexe depuis la toute première version du
    moteur (308f28e) : ce n'est pas une régression d'un commit récent (fix
    capacité/bugs A/B/C/GrillePrixAbonnement, tous vérifiés innocents — voir
    RegressionSexeGroupesTests), mais un angle mort présent depuis l'origine
    de ce moteur, jamais couvert par un test jusqu'ici.

    Volontairement traité EXACTEMENT comme l'âge (structurel, jamais
    relâché par confirme_override) et PAS comme courses.utils.
    raison_incompatibilite_groupe/avertissements_groupe (où sexe est informatif
    seulement depuis la Tâche 14, décision distincte qui concerne l'ADMIN
    réassignant un Eleve déjà existant à un groupe, un contexte différent) :
    ce moteur régit l'inscription initiale d'un nouvel élève, où la
    ségrégation par sexe est une contrainte dure, jamais négociable, exactement
    comme l'âge — voir RegressionSexeGroupesTests pour la discussion.

    exclure_caches_wizard_public : simplement transmis à groupes_compatibles()
    ci-dessus — voir sa docstring, même règle exacte."""
    from courses.utils import _age_depuis_naissance

    age = _age_depuis_naissance(date_naissance)
    return groupes_compatibles(reponses, exclure_caches_wizard_public=exclure_caches_wizard_public).filter(
        creneau__age_min__lte=age, creneau__age_max__gte=age,
    ).filter(Q(creneau__sexe_cible='mixte') | Q(creneau__sexe_cible=sexe))


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


def snapshot_criteres_pour_demande(reponses_pour_filtrage):
    """{code_critere: valeur_ou_liste_de_codes} à partir du dict {Critere:
    valeur} déjà utilisé par groupes_compatibles() — JAMAIS l'objet Python
    lui-même (non sérialisable en JSONField) : le CODE (stable, lisible),
    jamais le label (recalculé à la lecture depuis Critere/CritereOption,
    voir DemandeNonSatisfaite.__doc__). Utilisé pour enregistrer une
    DemandeNonSatisfaite (chantier du 2026-08-22)."""
    snapshot = {}
    for critere, valeur in reponses_pour_filtrage.items():
        if critere.backend in ('nb_slots', 'champ_groupe'):
            snapshot[critere.code] = valeur
        elif isinstance(valeur, (list, tuple, set)):
            snapshot[critere.code] = [o.code for o in valeur]
        else:
            snapshot[critere.code] = valeur.code
    return snapshot


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
        return nb_slots_reels_systeme()

    qs = groupes_compatibles(reponses_sans_nb_slots).exclude(creneau__isnull=True)
    valeurs = qs.annotate(_n=Count('creneau__slots', distinct=True)).values_list('_n', flat=True)
    return sorted({v for v in valeurs if v})


def nb_slots_reels_systeme():
    """Union des nb_slots réels (Groupe.creneau.slots) de TOUS les groupes
    actifs du système, tous critères/type_offre confondus — jamais 1/2/3/4
    codés en dur. Factorisé depuis la branche 'individuel' de nb_seances_
    disponibles ci-dessus (Étape 9, GrillePrixAbonnement) : la grille de prix
    a besoin EXACTEMENT de la même liste de valeurs pour construire ses
    lignes et son warning de couverture (couverture_grille_prix ci-dessous)
    — un nouveau groupe à 5 séances/semaine doit apparaître aux deux endroits
    en même temps, jamais 2 calculs qui pourraient diverger.

    Recalculée à CHAQUE appel, jamais mise en cache — même philosophie que
    nb_seances_disponibles/couverture_critere."""
    from courses.models import Groupe

    qs = Groupe.actifs.filter(statut='actif').exclude(creneau__isnull=True)
    valeurs = qs.annotate(_n=Count('creneau__slots', distinct=True)).values_list('_n', flat=True)
    return sorted({v for v in valeurs if v})


def nb_slots_repondu(reponses_brutes):
    """Valeur entière déjà répondue pour le champ backend='nb_slots' (ou None
    si pas encore répondu/invalide/masqué) — reponses_brutes au même format
    que wizard_donnees(request)/un POST brut (dict {champ_<id>: valeur}).

    Volontairement PAS filtrée par critere.filtrable (contrairement à
    reponses_pour_filtrage_depuis_resultats) : ici on veut la valeur que
    l'élève a choisie pour l'AFFICHER (calcul du prix effectif, Étape 9),
    pas son rôle dans le filtrage des groupes compatibles — un مدير qui
    désactiverait filtrable sur ce critère ne doit pas faire disparaître le
    prix affiché."""
    resultats = evaluer_champs_actifs(reponses_brutes)
    for r in resultats:
        if r['masque'] or r['erreur'] or not r['paires']:
            continue
        if r['champ'].critere is not None and r['champ'].critere.backend == 'nb_slots':
            try:
                return int(r['paires'][0][1])
            except (ValueError, TypeError):
                return None
    return None


def prix_effectif(type_abonnement, nb_slots):
    """Prix à afficher pour ce TypeAbonnement compte tenu du nombre de
    séances/semaine choisi (Étape 9, GrillePrixAbonnement) : celui de la
    grille si une ligne ACTIVE existe pour cette combinaison EXACTE
    (type_abonnement, nb_slots), sinon TypeAbonnement.prix comme repli —
    l'élève voit TOUJOURS un prix, jamais un blocage silencieux du wizard le
    temps que le مدير configure chaque combinaison une à une.

    nb_slots=None (pas encore répondu à ce stade du parcours) : aucune ligne
    de grille ne peut jamais matcher None, retombe directement sur
    TypeAbonnement.prix — comportement identique à avant ce chantier.

    C'est précisément quand ce repli est utilisé que la combinaison apparaît
    dans couverture_grille_prix()['nb_slots_manquants'] côté dashboard — les
    deux fonctions lisent la même réalité, jamais 2 sources qui divergent."""
    if nb_slots is not None:
        ligne = type_abonnement.grille_prix.filter(nb_slots=nb_slots, est_actif=True).first()
        if ligne is not None:
            return ligne.prix
    return type_abonnement.prix


NB_SLOTS_GRILLE_PRIX_MAX = 10


def plage_nb_slots_grille_prix():
    """[1..NB_SLOTS_GRILLE_PRIX_MAX] — plage FIXE proposée au مدير pour
    éditer GrillePrixAbonnement (correction du 2026-08-22, chantier grille
    de prix incohérente/incomplète).

    Volontairement DÉCORRÉLÉE de nb_slots_reels_systeme() (groupes réels) :
    cette dernière reste valable pour le WIZARD PUBLIC (proposer des
    groupes compatibles à un élève), mais ne dit rien de pertinent pour la
    TARIFICATION — un abonnement Individuel n'a besoin d'AUCUN groupe réel
    pour qu'un nombre de séances soit un choix valide (liberté totale
    depuis le chantier 5). Limiter la grille aux nb_slots déjà présents
    dans de vrais groupes empêchait le مدير de tarifer un nombre de
    séances encore jamais demandé par un vrai groupe (ex: 4 séances/semaine
    en Individuel) — bug reproduit et confirmé le 2026-08-22."""
    return list(range(1, NB_SLOTS_GRILLE_PRIX_MAX + 1))


def couverture_grille_prix(type_abonnement):
    """{'total', 'configures', 'nb_slots_manquants'} — même esprit que
    couverture_critere() ci-dessous (Parties 7-8) : matière première d'un
    warning NON BLOQUANT affiché au مدير sur la page de tarification de ce
    TypeAbonnement (Étape 9), jamais un gate qui empêcherait le wizard de
    continuer — le repli TypeAbonnement.prix (voir prix_effectif) couvre
    déjà ce cas côté élève.

    Base de calcul changée le 2026-08-22 : plage_nb_slots_grille_prix()
    (fixe, 1..10) au lieu de nb_slots_reels_systeme() (groupes réels) — un
    indicateur universel valable pour Groupe ET Individuel, jamais biaisé
    par l'absence de vrai groupe à un nb_slots donné (voir sa docstring).

    Recalculée à CHAQUE appel, jamais mise en cache — même philosophie que
    nb_seances_disponibles/couverture_critere."""
    valeurs = plage_nb_slots_grille_prix()
    configures = set(
        type_abonnement.grille_prix.filter(est_actif=True, nb_slots__in=valeurs).values_list('nb_slots', flat=True)
    )
    return {
        'total': len(valeurs),
        'configures': len(configures),
        'nb_slots_manquants': sorted(set(valeurs) - configures),
    }


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


def statut_compatibilite_groupe(groupe_id, reponses_pour_filtrage, date_naissance, sexe):
    """'ok' (groupe strictement compatible, aucun avertissement), 'contournable'
    (incompatible sur au moins un critère filtrable NON bloquant seulement —
    l'âge, le sexe et tout critère bloquant=True restent respectés) ou
    'incompatible' (âge, sexe ou critère bloquant en désaccord — jamais
    contournable, même par confirme_override). 'incompatible' aussi si
    groupe_id est vide/invalide.

    Vérification en LECTURE SEULE — n'écrit rien, ne crée rien. Applique
    EXACTEMENT la même règle que inscrire_eleve() (Partie 22) en interne pour
    décider si confirme_override peut s'appliquer : les deux appellent
    groupes_compatibles_avec_age() avec, respectivement, TOUTES les réponses
    filtrables puis SEULEMENT les réponses bloquantes. Utilisée par
    dashboard.views.admin_eleve_ajouter_manuel (Étape 7) pour savoir, AVANT
    tout appel à inscrire_eleve(), s'il faut afficher un avertissement
    contournable ou une erreur dure — jamais pour décider de la sécurité
    elle-même, qui reste entièrement portée par inscrire_eleve().

    exclure_caches_wizard_public=False explicitement (chantier du 2026-08-23) :
    cette fonction ne sert QU'à l'admin (admin_eleve_ajouter_manuel), jamais au
    formulaire public — un groupe masqué du wizard public doit rester
    normalement évaluable ('ok'/'contournable') ici, pas systématiquement
    'incompatible' par un effet de bord du masquage."""
    if not groupe_id:
        return 'incompatible'
    if groupes_compatibles_avec_age(
        reponses_pour_filtrage, date_naissance, sexe, exclure_caches_wizard_public=False,
    ).filter(id=groupe_id).exists():
        return 'ok'
    reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
    if groupes_compatibles_avec_age(
        reponses_bloquantes, date_naissance, sexe, exclure_caches_wizard_public=False,
    ).filter(id=groupe_id).exists():
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


def abonnements_avec_prix_effectif(abonnements, nb_slots):
    """Liste de TypeAbonnement (à partir du queryset abonnements_disponibles)
    avec un attribut supplémentaire `.prix_affiche` = prix_effectif(
    abonnement, nb_slots) posé sur chaque instance — jamais écrit en base,
    seulement pour l'affichage (Étape 9, GrillePrixAbonnement). Centralisé
    ici pour que wizard_abonnement (Étape 4) et admin_eleve_ajouter_manuel
    (Étape 7) affichent EXACTEMENT le même prix pour la même combinaison,
    jamais 2 boucles maintenues séparément."""
    resultat = list(abonnements)
    for abonnement in resultat:
        abonnement.prix_affiche = prix_effectif(abonnement, nb_slots)
    return resultat


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
        if champ.type_champ == 'nombre' and (champ.valeur_min is not None or champ.valeur_max is not None):
            # Partie 3 (chantier du 2026-08-23) : bornes optionnelles sur un
            # champ numérique informatif — l'attribut HTML min/max (voir
            # _champs_dynamiques.html) est un confort d'affichage, JAMAIS la
            # seule garantie (même principe que partout ailleurs dans ce
            # moteur) : une valeur hors bornes est ici rejetée AVANT d'être
            # écrite en ReponseInscription, quelle que soit la porte d'entrée
            # (wizard public via inscrire_eleve, ajout manuel admin — les 2
            # passent par evaluer_champs_actifs, donc par cette fonction).
            texte = str(valeur_brute).strip() if valeur_brute not in (None, '') else ''
            if not texte:
                return [], None
            try:
                nombre = int(texte)
            except (ValueError, TypeError):
                return [], f'"{champ.label}" يجب أن يكون رقماً صحيحاً.'
            if champ.valeur_min is not None and nombre < champ.valeur_min:
                return [], f'"{champ.label}" يجب أن يكون {champ.valeur_min} على الأقل.'
            if champ.valeur_max is not None and nombre > champ.valeur_max:
                return [], f'"{champ.label}" يجب ألا يتجاوز {champ.valeur_max}.'
            return [(None, str(nombre))], None
        texte = valeur_brute.strip() if isinstance(valeur_brute, str) else valeur_brute
        return ([(None, texte)] if texte not in (None, '') else []), None

    if critere.backend == 'nb_slots':
        # Pas de CritereOption pour ce backend — stocké en texte brut, jamais
        # comme option puisqu'aucune ligne CritereOption n'existe pour ces
        # valeurs. Chantier du 2026-08-22 ("liberté totale du nombre de
        # séances") : un simple <input type="number"> libre côté client,
        # donc une VRAIE validation serveur devient nécessaire ici (avant,
        # seules des valeurs déjà calculées/valides pouvaient être postées
        # depuis la grille de boutons JS) — entier positif uniquement, sinon
        # message d'erreur, jamais une valeur texte arbitraire silencieusement
        # acceptée.
        texte = str(valeur_brute).strip() if valeur_brute not in (None, '') else ''
        if not texte:
            return [], None
        try:
            nombre = int(texte)
        except (ValueError, TypeError):
            return [], f'"{champ.label}" يجب أن يكون رقماً صحيحاً.'
        if nombre < 1:
            return [], f'"{champ.label}" يجب أن يكون على الأقل 1.'
        return [(None, str(nombre))], None

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
    simple. Utilisée par dashboard.views.admin_eleve_ajouter_manuel pour
    construire reponses_brutes à partir d'un POST brut — MÊME fonction, jamais
    une 2e version réécrite côté admin."""
    extrait = {}
    for cle in post_data:
        if cle.startswith('champ_'):
            valeurs = post_data.getlist(cle)
            extrait[cle] = valeurs if len(valeurs) > 1 else valeurs[0]
    return extrait


def traiter_champs_dynamiques_post(post_data, champs):
    """Valide/extrait les réponses POST pour une liste de ChampInscription
    (avec ou sans critère) déjà filtrée par étape par l'appelant — MÊME
    logique de fond que _reponses_a_creer_pour_champ ci-dessus, mais
    restreinte aux champs D'UNE SEULE PAGE du wizard (jamais un message
    "إلزامي" pour un champ d'une AUTRE étape, contrairement à evaluer_
    champs_actifs qui, lui, revalide TOUT à la confirmation finale, voir
    inscrire_eleve).

    Retourne (nouvelles_valeurs, erreurs) — nouvelles_valeurs prêtes à
    fusionner dans la session (wizard_maj), erreurs = liste de messages
    arabes. Factorisée depuis wizard_programme (chantier du 2026-08-23,
    Partie 3A "extension du moteur générique à l'étape Identité") : même
    fonction pour 'programme' ET 'identite' (et toute étape personnalisée
    future, Partie 3B) — jamais 2 versions divergentes maintenues par
    étape."""
    nouvelles_valeurs = {}
    erreurs = []
    for champ in champs:
        cle = f'champ_{champ.id}'
        if champ.critere and champ.critere.type_champ == 'choix_multiple':
            valeur_brute = post_data.getlist(cle)
        else:
            valeur_brute = post_data.get(cle, '')
        paires, erreur = _reponses_a_creer_pour_champ(champ, valeur_brute)
        if erreur:
            erreurs.append(erreur)
            continue
        if not paires and champ.obligatoire:
            erreurs.append(f'"{champ.label}" إلزامي.')
            continue
        nouvelles_valeurs[cle] = valeur_brute
    return nouvelles_valeurs, erreurs


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
    l'ordre). Retourne une liste ordonnée de dicts {'champ', 'paires',
    'erreur', 'masque'} — 'paires' et 'erreur' au même format que
    _reponses_a_creer_pour_champ. 'masque' reste dans la forme du résultat
    (toujours False) pour ne rien casser chez les appelants qui le
    consultent encore (inscrire_eleve, reponses_pour_filtrage_depuis_
    resultats, dashboard.views._champs_pour_template, admin_eleve_ajouter_
    manuel.html) — chantier du 2026-08-23 : le masquage conditionnel par
    RegleCondition a été retiré (jamais utilisé pour une vraie règle
    depuis sa création, voir registration.models.__doc__), cette clé ne
    peut donc plus jamais valoir True désormais."""
    from .models import ChampInscription

    champs_actifs = list(
        ChampInscription.objects.filter(est_actif=True, etape__est_actif=True)
        .select_related('critere', 'etape').order_by('etape__ordre', 'ordre')
    )
    resultats = []
    for champ in champs_actifs:
        valeur_brute = reponses_brutes.get(f'champ_{champ.id}')
        paires, erreur = _reponses_a_creer_pour_champ(champ, valeur_brute)
        resultats.append({'champ': champ, 'paires': paires, 'erreur': erreur, 'masque': False})

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
      'email', 'job_actuel', 'niveau_scolaire', 'remarques', 'accepte_conditions'
      ('oui'/autre) — présence/obligation de chacun pilotée par registration.
      models.ConfigurationChampStructurel (chantier du 2026-08-22).
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

    # ---- 1. Identité structurelle (registration.models.ConfigurationChamp
    # Structurel, chantier du 2026-08-22) — nom/nom_parent/job_actuel/
    # niveau_scolaire génériques (label/obligatoire/regex configurables) ;
    # sexe/date_naissance/email gardent leur validation dédiée (contraintes
    # structurelles verrouillées, voir CLES_VERROUILLEES) ; telephone garde
    # son mécanisme dédié (déjà validé/assemblé par l'appelant) mais devient
    # non-obligatoire si configuré ainsi. Point UNIQUE partagé par le wizard
    # public ET l'ajout manuel — jamais 2 validations qui pourraient diverger.
    configs_identite = champs_structurels_actifs('identite')
    configs_par_cle = {c.champ_cle: c for c in configs_identite}
    CLES_GENERIQUES = ('nom', 'nom_parent', 'job_actuel', 'niveau_scolaire')

    valeurs_structurelles = {}
    for cle in CLES_GENERIQUES:
        config = configs_par_cle.get(cle)
        valeur = (reponses_brutes.get(cle) or '').strip()
        if config is None:
            valeurs_structurelles[cle] = ''
            continue
        erreur = valider_champ_structurel_libre(config, valeur)
        if erreur:
            erreurs.append(erreur)
        valeurs_structurelles[cle] = valeur
    nom = valeurs_structurelles['nom']

    sexe = reponses_brutes.get('sexe') or ''
    if 'sexe' in configs_par_cle and sexe not in ('homme', 'femme'):
        erreurs.append(f'"{configs_par_cle["sexe"].label}" إلزامي.')

    telephone_config = configs_par_cle.get('telephone')
    telephone = (reponses_brutes.get('telephone') or '').strip()
    if telephone_config is not None and telephone_config.obligatoire and not telephone:
        erreurs.append(f'"{telephone_config.label}" إلزامي.')

    email = (reponses_brutes.get('email') or '').strip()
    if 'email' in configs_par_cle:
        if not email:
            erreurs.append(f'"{configs_par_cle["email"].label}" إلزامي.')
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
    demande_id = reponses_brutes.get('demande_non_satisfaite_id')
    # continuer_sans_groupe : pendant du wizard public (demande_id déjà créée
    # à l'étape 3) pour l'ajout manuel (Étape 7, pas d'étape intermédiaire
    # séparée) — crée ET lie la DemandeNonSatisfaite en un seul passage ici.
    continuer_sans_groupe = reponses_brutes.get('continuer_sans_groupe') == '1'
    # etape_est_active('groupe') (correction 8, 2026-08-22, navigation
    # dynamique) : si le مدير a désactivé cette étape, wizard_groupe ne
    # demande alors JAMAIS de groupe (voir sa propre garde) — exiger
    # groupe_id ici bloquerait TOUTE inscription 'groupe', même avec cette
    # étape volontairement désactivée. Même repli que l'Individuel
    # (groupe_id ignoré), pas une erreur.
    if type_offre_valeur == 'groupe' and etape_est_active('groupe'):
        if not groupe_id:
            # "Continuer sans groupe" (chantier du 2026-08-22, liberté totale
            # du nombre de séances) : accepté SEULEMENT si aucun groupe ne
            # correspond RÉELLEMENT à la combinaison exacte — jamais une
            # confiance aveugle en demande_id/continuer_sans_groupe posté
            # (POST manipulé), revérifié ici comme tout le reste (Partie 22).
            candidats_exacts = (
                groupes_compatibles_avec_age(
                    reponses_pour_filtrage, date_naissance, sexe, exclure_caches_wizard_public=(cree_par is None),
                )
                if date_naissance is not None else Groupe.objects.none()
            )
            if (demande_id or continuer_sans_groupe) and date_naissance is not None and not candidats_exacts.exists():
                groupe_choisi = None
            else:
                erreurs.append('يرجى اختيار مجموعة.')
        elif date_naissance is None:
            pass  # déjà signalé plus haut
        else:
            candidats = groupes_compatibles_avec_age(
                reponses_pour_filtrage, date_naissance, sexe, exclure_caches_wizard_public=(cree_par is None),
            )
            groupe_choisi = candidats.filter(id=groupe_id).first()

            if groupe_choisi is None and demande_id:
                # "Groupe proche" choisi via l'écran "aucun groupe exact" de
                # wizard_groupe (chantier du 2026-08-22) — MÊME relaxation
                # que confirme_override (critères non bloquants seulement,
                # âge/sexe toujours durs), mais pour le PUBLIC : demande_id
                # prouve que ce choix a déjà été proposé et validé serveur à
                # l'étape 3 (wizard_groupe ne propose QUE des groupes de
                # reponses_bloquantes dans ce cas), jamais une confiance
                # aveugle — la requête ci-dessous revérifie ce match de toute
                # façon, demande_id ne fait que décider SI on tente ce repli.
                reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
                candidats_permissifs = groupes_compatibles_avec_age(
                    reponses_bloquantes, date_naissance, sexe, exclure_caches_wizard_public=(cree_par is None),
                )
                groupe_choisi = candidats_permissifs.filter(id=groupe_id).first()

            if groupe_choisi is None and cree_par is not None and confirme_override:
                # Override réservé au Directeur/مشرف (Partie 17) : ne relâche QUE
                # les critères filtrable non bloquants — l'âge et le sexe
                # (structurels) et tout critère bloquant=True restent des
                # contraintes dures, même avec confirme_override=True.
                reponses_bloquantes = {c: v for c, v in reponses_pour_filtrage.items() if c.bloquant}
                # cree_par is not None ici (garde du if ci-dessus) : exclure_
                # caches_wizard_public vaut donc toujours False dans cette
                # branche — écrit pareil que les autres appels de cette
                # fonction, jamais une valeur en dur qui diverge silencieusement
                # si la garde changeait un jour.
                candidats_permissifs = groupes_compatibles_avec_age(
                    reponses_bloquantes, date_naissance, sexe, exclure_caches_wizard_public=(cree_par is None),
                )
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
            nom_parent=valeurs_structurelles['nom_parent'],
            date_naissance=date_naissance,
            sexe=sexe,
            telephone=telephone,
            email=email,
            job_actuel=valeurs_structurelles['job_actuel'],
            niveau_scolaire=valeurs_structurelles['niveau_scolaire'],
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
        if demande_id:
            # Rattache la DemandeNonSatisfaite (déjà créée par wizard_groupe)
            # à la candidature créée (chantier du 2026-08-22) — silencieux si
            # l'ID est invalide/déjà lié à autre chose, jamais une erreur
            # bloquante pour l'inscription elle-même.
            from .models import DemandeNonSatisfaite
            DemandeNonSatisfaite.objects.filter(id=demande_id, inscription__isnull=True).update(
                inscription=inscription
            )
        elif continuer_sans_groupe and groupe_choisi is None:
            # Ajout manuel (Étape 7) : pas d'étape intermédiaire séparée pour
            # créer la demande à l'avance — créée ET liée ici, en un seul passage.
            from courses.utils import _age_depuis_naissance
            from .models import DemandeNonSatisfaite
            nb_slots_valeur = next(
                (v for c, v in reponses_pour_filtrage.items() if c.backend == 'nb_slots'), None
            )
            DemandeNonSatisfaite.objects.create(
                criteres_json=snapshot_criteres_pour_demande(reponses_pour_filtrage),
                type_offre='groupe', nb_slots=nb_slots_valeur,
                age=_age_depuis_naissance(date_naissance), sexe=sexe, inscription=inscription,
                nom=nom, telephone=telephone, email=email,
            )

    return inscription, []
