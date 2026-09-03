"""Moteur des cycles d'abonnement / relances de paiement — chantier du
2026-09-01. Aucune logique d'affichage ici (même esprit que dashboard.
notifications) : seulement le calcul « où en est l'élève dans ses échéances ».

Voir payments.models.CycleAbonnement.__doc__ pour la règle métier complète.
Points clés :
- Chaque cycle = UNE période mensuelle ancrée sur le jour de `date_debut` du
  cycle 1 : élève inscrit le 10 -> périodes 10→10, 10→10… (chantier du
  2026-09-03, en remplacement du découpage en mois calendaires 1er→1er).
- Comparaison des Paiement au mois près (année/mois) du DÉBUT de la période —
  `mois_reference` est saisi librement par l'élève (jour arbitraire) et deux
  périodes consécutives tombent toujours dans deux mois calendaires distincts,
  donc cette clé reste sans ambiguïté (voir _mois_ref).
- Un cycle n'est réglé que si SON mois de début est `valide` : payer un mois
  plus loin, après un trou, ne règle jamais le cycle en attente. Payer
  plusieurs mois d'affilée règle plusieurs cycles à la file.
- Aucune tâche planifiée : `reconcilier` est appelée à la main après chaque
  validation/modification de Paiement, le reste est calculé à la volée.
"""

import calendar
import datetime
from decimal import Decimal, ROUND_HALF_UP

from django.utils import timezone

DELAI_PAIEMENT_DEFAUT = 10
_ZERO = Decimal('0.00')


def _part_mensuelle(montant, nb_mois_couverts):
    """Part mensuelle du montant total d'un Paiement (240 د.م. / 3 mois -> 80)."""
    n = max(nb_mois_couverts or 1, 1)
    return (Decimal(montant) / n).quantize(Decimal('0.01'), rounding=ROUND_HALF_UP)

# Escalade de la relance élève (chantier du 2026-09-02) — jours de retard
# comptés APRÈS `cycle.date_echeance` (J+1 = lendemain de l'échéance).
# Un « nouvel élève » (inscrit depuis moins de ParametresInscriptions.
# delai_grace_nouvel_eleve_mois mois) n'est relancé qu'à partir de J+5 ;
# un ancien élève dès J+1. À partir de J+8 les deux suivent le même
# décompte (« dans 2 jours »… « il reste 1 jour »… « imminent »).
RELANCE_JOUR_DEBUT_NOUVEL_ELEVE = 5
RELANCE_JOUR_DEBUT_ANCIEN_ELEVE = 1
RELANCE_JOUR_AVERT_2J = 8
RELANCE_JOUR_AVERT_1J = 9
RELANCE_JOUR_CRITIQUE = 10
GRACE_NOUVEL_ELEVE_MOIS_DEFAUT = 2

PHASE_SILENCE = 'silence'      # rien dans la cloche (phase de grâce)
PHASE_SIMPLE = 'simple'        # rappel simple, répété chaque jour
PHASE_AVERT_2J = 'avert_2j'    # J+8 : « dans 2 jours votre compte sera désactivé »
PHASE_AVERT_1J = 'avert_1j'    # J+9 : « il reste 1 jour »
PHASE_CRITIQUE = 'critique'    # J+10 et au-delà : désactivation imminente


def _delai_jours():
    """ParametresInscriptions.delai_paiement_jours (10 par défaut) — la MÊME
    valeur que celle déjà affichée à l'élève à l'étape paiement du wizard
    (registration.views.wizard_paiement), jamais un 10 recodé en dur ici."""
    from inscriptions.models import get_parametres_inscriptions

    return get_parametres_inscriptions().delai_paiement_jours or DELAI_PAIEMENT_DEFAUT


def _ajouter_mois(d, n):
    """`d` décalée de `n` mois, le jour rabaissé au dernier jour du mois cible
    si nécessaire (31 janv. + 1 mois -> 28/29 févr.). L'ANCRAGE se fait
    toujours depuis la date d'origine passée en argument, jamais en chaînant
    les appels — sinon un élève inscrit un 31 dériverait (31->28->28->28…).
    Chantier « cycle roulant ancré sur le jour d'inscription » du 2026-09-03 :
    la période d'un élève inscrit le 10 court du 10 au 10, pas du 1er au 1er."""
    total = d.year * 12 + (d.month - 1) + n
    annee, mois0 = divmod(total, 12)
    mois = mois0 + 1
    return datetime.date(annee, mois, min(d.day, calendar.monthrange(annee, mois)[1]))


def _mois_ref(d):
    """(année, mois) du DÉBUT de la période commençant à `d` — clé de
    rattachement d'un Paiement à un cycle. Deux périodes consécutives (même
    jour d'ancrage, à un mois d'écart) tombent toujours dans deux mois
    calendaires distincts, donc cette clé reste unique par période — c'est ce
    qui permet de garder le rapprochement Paiement<->cycle au mois près
    (mois_reference saisi au jour près par l'élève) sans re-caler l'historique."""
    return (d.year, d.month)


def _premier_cycle(eleve):
    """Le cycle nº 1 (le plus ancien) — sa `date_debut` est le jour d'ancrage
    de TOUTES les périodes de l'élève (période N = date_debut + (N-1) mois)."""
    return eleve.cycles_abonnement.order_by('numero').first()


def periode_bornes(eleve, annee, mois):
    """(début, fin exclusive) de la période mensuelle de `eleve` dont le mois
    de DÉBUT est (annee, mois), d'après le jour d'ancrage (date_debut du cycle
    nº 1) : élève inscrit le 10 -> (10/06, 10/07) pour (2026, 6). Repli
    1er→1er du mois si l'élève n'a aucun cycle ou si (annee, mois) est
    antérieur à son ancrage (données d'avant le backfill)."""
    premier = _premier_cycle(eleve)
    ancre = premier.date_debut if premier else None
    if ancre is not None:
        offset = (annee - ancre.year) * 12 + (mois - ancre.month)
        if offset >= 0:
            return _ajouter_mois(ancre, offset), _ajouter_mois(ancre, offset + 1)
    debut = datetime.date(annee, mois, 1)
    return debut, _ajouter_mois(debut, 1)


def mois_couverts(mois_reference, nb_mois_couverts):
    """{(année, mois), …} de chaque mois couvert par UN Paiement : de
    `mois_reference` inclus à +`nb_mois_couverts` mois exclus (10 sep + 3 ->
    sep, oct, nov). Un Paiement d'avant le chantier « Paiement unique » du
    2026-09-03 a nb_mois_couverts=1 -> un seul (année, mois)."""
    return {
        (d.year, d.month)
        for d in (_ajouter_mois(mois_reference, i) for i in range(max(nb_mois_couverts or 1, 1)))
    }


def _mois_couvrants_par_eleve(eleve_ids, statuts=('valide', 'en_attente')):
    """{eleve_id: {(année, mois), ...}} pour une LISTE d'élèves, en UNE requête
    (voir cycles_ouverts_en_retard) — jamais une requête par élève. Coverage
    étendue par `nb_mois_couverts`."""
    from .models import Paiement

    couverture = {}
    for eid, mr, nb in Paiement.objects.filter(
        eleve_id__in=list(eleve_ids), statut__in=statuts,
    ).values_list('eleve_id', 'mois_reference', 'nb_mois_couverts'):
        couverture.setdefault(eid, set()).update(mois_couverts(mr, nb))
    return couverture


def cycle_courant(eleve):
    """Le cycle ouvert (non réglé) le plus ancien, ou None si l'élève n'a aucun
    cycle (jamais validé, ou données antérieures au backfill 0007)."""
    return eleve.cycles_abonnement.filter(regle=False).order_by('numero').first()


def demarrer_cycles(eleve, date_reference=None):
    """Crée le cycle 1 si l'élève n'a AUCUN cycle ouvert. Idempotent — ne fait
    rien s'il en a déjà un. Appelée à la validation de l'inscription."""
    if cycle_courant(eleve) is not None:
        return
    from .models import CycleAbonnement

    jour = date_reference or timezone.localdate()
    dernier = eleve.cycles_abonnement.order_by('-numero').first()
    numero = (dernier.numero + 1) if dernier else 1
    CycleAbonnement.objects.create(
        eleve=eleve,
        numero=numero,
        date_debut=jour,
        date_echeance=jour + datetime.timedelta(days=_delai_jours()),
    )


def redemarrer_cycle_courant(eleve, date_reference=None):
    """Réarme le cycle ouvert à partir de `date_reference` (désarchivage :
    l'élève repart avec une fenêtre de paiement neuve à compter du jour de
    réactivation — décision du client). Crée le cycle 1 s'il n'en a aucun."""
    cycle = cycle_courant(eleve)
    if cycle is None:
        demarrer_cycles(eleve, date_reference=date_reference)
        return
    jour = date_reference or timezone.localdate()
    cycle.date_debut = jour
    cycle.date_echeance = jour + datetime.timedelta(days=_delai_jours())
    cycle.save(update_fields=['date_debut', 'date_echeance'])


def reconcilier(eleve):
    """Règle autant de cycles que la couverture `valide` le permet — UN cycle
    par période mensuelle, ancrée sur le jour de `date_debut` du cycle 1
    (10 → 10 → 10…, chantier du 2026-09-03). Appelée après toute
    validation/modification d'un Paiement. Ne revient JAMAIS en arrière (un
    Paiement rejeté après coup ne « dé-règle » pas un cycle déjà avancé — cas
    marginal, non demandé).

    Un Paiement `valide` qui COUVRE le mois du DÉBUT de la période du cycle
    courant (mois_reference .. +nb_mois_couverts) règle ce cycle et ouvre le
    suivant (`date_debut` = jour d'ancrage + 1 mois, `date_echeance` = +
    delai). Un Paiement multi-mois règle donc plusieurs cycles à la file, et
    sa part mensuelle (montant / nb_mois_couverts) est portée sur chacun."""
    from .models import CycleAbonnement, Paiement

    valides = list(
        Paiement.objects.filter(eleve=eleve, statut='valide').values_list(
            'mois_reference', 'nb_mois_couverts', 'montant'
        )
    )
    mois_payes = set()
    for mr, nb, _montant in valides:
        mois_payes |= mois_couverts(mr, nb)

    premier = _premier_cycle(eleve)
    if premier is None:
        return
    ancre = premier.date_debut
    delai = _delai_jours()
    garde = 0
    while garde < 600:  # borne dure : ~50 ans de cycles mensuels, jamais atteinte
        garde += 1
        cycle = cycle_courant(eleve)
        if cycle is None:
            return
        cle_mois = _mois_ref(cycle.date_debut)
        if cle_mois not in mois_payes:
            return
        # Cas normal : période N = ancre + N mois (pas de dérive fin-de-mois,
        # 31 janv. reste ancré au 31). Cas désarchivage : `redemarrer_cycle_
        # courant` a repositionné le cycle ouvert hors de cette grille — on
        # repart alors de SA propre date_debut.
        if cycle.date_debut == _ajouter_mois(ancre, cycle.numero - 1):
            prochain_debut = _ajouter_mois(ancre, cycle.numero)
        else:
            prochain_debut = _ajouter_mois(cycle.date_debut, 1)
        fin_couverte = prochain_debut - datetime.timedelta(days=1)
        # Part mensuelle de chaque Paiement valide qui couvre CE mois.
        montant = sum(
            (_part_mensuelle(mnt, nb) for mr, nb, mnt in valides if cle_mois in mois_couverts(mr, nb)),
            _ZERO,
        )
        cycle.regle = True
        cycle.date_fin_couverte = fin_couverte
        cycle.date_reglement = timezone.localdate()
        cycle.montant_regle = montant
        cycle.save(update_fields=['regle', 'date_fin_couverte', 'date_reglement', 'montant_regle'])
        CycleAbonnement.objects.create(
            eleve=eleve,
            numero=cycle.numero + 1,
            date_debut=prochain_debut,
            date_echeance=prochain_debut + datetime.timedelta(days=delai),
        )


def cycle_est_en_retard(cycle, aujourdhui=None):
    """True si CE cycle (déjà chargé) est ouvert, échu, et non couvert par un
    Paiement `valide`/`en_attente` sur son 1er mois — 1 requête. Un Paiement
    `en_attente` suspend la relance sans faire avancer le cycle ; un Paiement
    multi-mois couvre plusieurs mois (mois_reference .. +nb_mois_couverts)."""
    if cycle is None or cycle.regle:
        return False
    aujourdhui = aujourdhui or timezone.localdate()
    if aujourdhui <= cycle.date_echeance:
        return False
    from .models import Paiement

    cle_mois = _mois_ref(cycle.date_debut)
    return not any(
        cle_mois in mois_couverts(mr, nb)
        for mr, nb in Paiement.objects.filter(
            eleve_id=cycle.eleve_id, statut__in=('valide', 'en_attente'),
        ).values_list('mois_reference', 'nb_mois_couverts')
    )


def est_en_retard(eleve, aujourdhui=None):
    """Idem pour un élève dont on ne connaît pas encore le cycle courant —
    2 requêtes (cycle courant + `.exists()`). Pour une LISTE d'élèves, ne
    jamais boucler là-dessus : utiliser eleves_en_retard() (2 requêtes au
    total, voir sa docstring)."""
    return cycle_est_en_retard(cycle_courant(eleve), aujourdhui)


def jours_de_retard(cycle, aujourdhui=None):
    """Nombre de jours écoulés depuis `cycle.date_echeance` (0 le jour même de
    l'échéance, 1 le lendemain…). Négatif si l'échéance est encore à venir."""
    aujourdhui = aujourdhui or timezone.localdate()
    return (aujourdhui - cycle.date_echeance).days


def _grace_nouvel_eleve_mois():
    from inscriptions.models import get_parametres_inscriptions

    return (
        get_parametres_inscriptions().delai_grace_nouvel_eleve_mois
        or GRACE_NOUVEL_ELEVE_MOIS_DEFAUT
    )


def est_nouvel_eleve(eleve):
    """True si l'élève est inscrit depuis moins de `delai_grace_nouvel_eleve_
    mois` mois (ParametresInscriptions) — sa relance de paiement ne démarre
    qu'à J+5 de retard au lieu de J+1. Référence : `user.date_joined`, comme
    l'amorçage des seuils de notification (dashboard.notifications._seuils)."""
    limite = timezone.now() - datetime.timedelta(days=30 * _grace_nouvel_eleve_mois())
    return eleve.user.date_joined >= limite


def jour_debut_relance(eleve):
    """J+1 pour un ancien élève, J+5 pour un nouvel élève (voir est_nouvel_eleve)."""
    return (
        RELANCE_JOUR_DEBUT_NOUVEL_ELEVE if est_nouvel_eleve(eleve)
        else RELANCE_JOUR_DEBUT_ANCIEN_ELEVE
    )


def phase_relance_eleve(eleve, cycle, aujourdhui=None):
    """Phase d'escalade de la relance affichée à l'élève dans la cloche 🔔,
    en fonction des jours de retard et de l'ancienneté de l'élève. Renvoie
    l'une des constantes PHASE_* (le libellé texte, lui, vit dans
    dashboard.notifications — ce module ne fait aucun affichage).

    N'a de sens que pour un cycle réellement en retard (cycle_est_en_retard) —
    l'appelant fait ce test d'abord."""
    j = jours_de_retard(cycle, aujourdhui)
    if j < jour_debut_relance(eleve):
        return PHASE_SILENCE
    if j >= RELANCE_JOUR_CRITIQUE:
        return PHASE_CRITIQUE
    if j == RELANCE_JOUR_AVERT_1J:
        return PHASE_AVERT_1J
    if j == RELANCE_JOUR_AVERT_2J:
        return PHASE_AVERT_2J
    return PHASE_SIMPLE


def cycles_ouverts_en_retard(avec_groupes=False):
    """Liste des CycleAbonnement réellement en retard (ouvert + échu + élève
    non archivé + 1er mois non couvert par un Paiement valide/en_attente).

    **Nombre de requêtes CONSTANT**, quel que soit le nombre d'élèves — jamais
    de boucle par élève (c'était le point chaud des pages 🔔 مدير / de la page
    paiements_retards, corrigé le 2026-09-01) :
      1. tous les cycles ouverts échus des élèves non archivés, `eleve__user`
         en select_related ;
      2. les mois `valide`/`en_attente` de ces seuls élèves, en un lot ;
      (3. si `avec_groupes` : les halqas de ces élèves, en un lot — utile
          UNIQUEMENT à la page paiements_retards qui les affiche ; le panneau
          🔔 n'en a pas besoin.)
    Index dédié : payments_cycleabonnement (regle, date_echeance).

    Invariant : au plus UN cycle ouvert par élève (reconcilier / demarrer_
    cycles / redemarrer_cycle_courant le garantissent), donc aucun dédoublon
    à gérer ici."""
    from .models import CycleAbonnement

    aujourdhui = timezone.localdate()
    qs = (
        CycleAbonnement.objects.filter(regle=False, date_echeance__lt=aujourdhui)
        .exclude(eleve__statut='archive')
        .select_related('eleve__user')
    )
    if avec_groupes:
        qs = qs.prefetch_related('eleve__groupes')
    candidats = list(qs)
    if not candidats:
        return []

    couverture = _mois_couvrants_par_eleve([c.eleve_id for c in candidats])
    return [
        c for c in candidats
        if (c.date_debut.year, c.date_debut.month) not in couverture.get(c.eleve_id, ())
    ]


def eleves_en_retard(avec_groupes=False):
    """(Eleve, CycleAbonnement) pour chaque élève en retard — voir
    cycles_ouverts_en_retard() (nombre de requêtes constant, aucune boucle
    par élève)."""
    return [(c.eleve, c) for c in cycles_ouverts_en_retard(avec_groupes=avec_groupes)]
