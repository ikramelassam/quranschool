"""Moteur des cycles d'abonnement / relances de paiement — chantier du
2026-09-01. Aucune logique d'affichage ici (même esprit que dashboard.
notifications) : seulement le calcul « où en est l'élève dans ses échéances ».

Voir payments.models.CycleAbonnement.__doc__ pour la règle métier complète.
Points clés :
- Comparaison des Paiement TOUJOURS au mois près (année/mois), jamais par date
  exacte — `mois_reference` est saisi librement par l'élève (jour arbitraire),
  exactement comme le fait déjà payments.views.suivi_paiements_eleves.
- Un cycle n'est réglé que par une SUITE CONTIGUË de mois `valide` à partir de
  son 1er mois : un mois payé plus loin, après un trou, ne « saute » jamais un
  mois impayé.
- Aucune tâche planifiée : `reconcilier` est appelée à la main après chaque
  validation/modification de Paiement, le reste est calculé à la volée.
"""

import calendar
import datetime

from django.db.models import Sum
from django.utils import timezone

DELAI_PAIEMENT_DEFAUT = 10


def _delai_jours():
    """ParametresInscriptions.delai_paiement_jours (10 par défaut) — la MÊME
    valeur que celle déjà affichée à l'élève à l'étape paiement du wizard
    (registration.views.wizard_paiement), jamais un 10 recodé en dur ici."""
    from inscriptions.models import get_parametres_inscriptions

    return get_parametres_inscriptions().delai_paiement_jours or DELAI_PAIEMENT_DEFAUT


def _premier_du_mois(d):
    return datetime.date(d.year, d.month, 1)


def _dernier_du_mois(annee, mois):
    return datetime.date(annee, mois, calendar.monthrange(annee, mois)[1])


def _mois_suivant(annee, mois):
    return (annee + 1, 1) if mois == 12 else (annee, mois + 1)


def _mois_payes(eleve, statuts):
    """Ensemble de (année, mois) ayant au moins un Paiement de `eleve` dans un
    des `statuts` — une seule requête."""
    from .models import Paiement

    return {
        (a, m)
        for a, m in Paiement.objects.filter(eleve=eleve, statut__in=statuts)
        .values_list('mois_reference__year', 'mois_reference__month')
    }


def _mois_couvrants_par_eleve(eleve_ids, statuts=('valide', 'en_attente')):
    """{eleve_id: {(année, mois), ...}} pour une LISTE d'élèves, en UNE requête
    (voir cycles_ouverts_en_retard) — jamais une requête par élève."""
    from .models import Paiement

    couverture = {}
    for eid, a, m in Paiement.objects.filter(
        eleve_id__in=list(eleve_ids), statut__in=statuts,
    ).values_list('eleve_id', 'mois_reference__year', 'mois_reference__month'):
        couverture.setdefault(eid, set()).add((a, m))
    return couverture


def _fin_couverte_contigue(mois_payes, depuis):
    """Dernier jour du dernier mois d'une suite CONTIGUË de mois présents dans
    `mois_payes`, en partant du mois de `depuis`. None si le mois de départ
    lui-même n'est pas payé."""
    annee, mois = depuis.year, depuis.month
    fin = None
    while (annee, mois) in mois_payes:
        fin = _dernier_du_mois(annee, mois)
        annee, mois = _mois_suivant(annee, mois)
    return fin


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
    """Fait avancer autant de cycles que la couverture `valide` le permet.
    Appelée après toute validation/modification d'un Paiement. Ne revient
    JAMAIS en arrière (un Paiement rejeté après coup ne « dé-règle » pas un
    cycle déjà avancé — cas marginal, non demandé)."""
    from .models import CycleAbonnement, Paiement

    mois_payes = _mois_payes(eleve, ['valide'])
    garde = 0
    while garde < 600:  # borne dure : ~50 ans de cycles mensuels, jamais atteinte
        garde += 1
        cycle = cycle_courant(eleve)
        if cycle is None:
            return
        fin_couverte = _fin_couverte_contigue(mois_payes, _premier_du_mois(cycle.date_debut))
        if fin_couverte is None:
            return
        montant = (
            Paiement.objects.filter(
                eleve=eleve,
                statut='valide',
                mois_reference__gte=_premier_du_mois(cycle.date_debut),
                mois_reference__lte=fin_couverte,
            ).aggregate(total=Sum('montant'))['total']
            or 0
        )
        cycle.regle = True
        cycle.date_fin_couverte = fin_couverte
        cycle.date_reglement = timezone.localdate()
        cycle.montant_regle = montant
        cycle.save(update_fields=['regle', 'date_fin_couverte', 'date_reglement', 'montant_regle'])
        CycleAbonnement.objects.create(
            eleve=eleve,
            numero=cycle.numero + 1,
            date_debut=fin_couverte + datetime.timedelta(days=1),
            date_echeance=fin_couverte + datetime.timedelta(days=_delai_jours()),
        )


def cycle_est_en_retard(cycle, aujourdhui=None):
    """True si CE cycle (déjà chargé) est ouvert, échu, et non couvert par un
    Paiement `valide`/`en_attente` sur son 1er mois — 1 requête (`.exists()`).
    Un Paiement `en_attente` suspend la relance sans faire avancer le cycle."""
    if cycle is None or cycle.regle:
        return False
    aujourdhui = aujourdhui or timezone.localdate()
    if aujourdhui <= cycle.date_echeance:
        return False
    from .models import Paiement

    return not Paiement.objects.filter(
        eleve_id=cycle.eleve_id,
        statut__in=('valide', 'en_attente'),
        mois_reference__year=cycle.date_debut.year,
        mois_reference__month=cycle.date_debut.month,
    ).exists()


def est_en_retard(eleve, aujourdhui=None):
    """Idem pour un élève dont on ne connaît pas encore le cycle courant —
    2 requêtes (cycle courant + `.exists()`). Pour une LISTE d'élèves, ne
    jamais boucler là-dessus : utiliser eleves_en_retard() (2 requêtes au
    total, voir sa docstring)."""
    return cycle_est_en_retard(cycle_courant(eleve), aujourdhui)


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
