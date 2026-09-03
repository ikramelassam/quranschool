"""Re-calage des cycles d'abonnement sur des périodes ROULANTES ancrées sur le
jour d'inscription — chantier du 2026-09-03.

Avant : le moteur découpait l'abonnement en mois calendaires (1er → 1er) et
`reconcilier` recalait la fin de cycle au dernier jour du mois. Un élève
inscrit le 10 septembre voyait donc son cycle suivant démarrer le 1er octobre,
et le sélecteur de paiement « du 10 sep au 10 oct » comptait deux mois.

Après : chaque cycle = une période d'un mois ancrée sur le jour de `date_debut`
du cycle nº 1 (= jour d'inscription) : 10 sep → 10 oct → 10 nov… Un cycle par
période (numero = index de période), au lieu d'un unique cycle « fourre-tout ».

Ce backfill efface les CycleAbonnement existants (reconstruits ci-dessous à
partir des seuls Paiement `valide`, seule source de vérité) et recrée, pour
chaque élève non archivé :
- un cycle « réglé » par période mensuelle entièrement couverte, en partant du
  mois d'inscription et tant que la suite est CONTIGUË ;
- puis le cycle ouvert courant, avec son échéance (début de période + délai).

Le champ Paiement.mois_reference n'est PAS touché : le rapprochement
Paiement ↔ cycle reste au mois près (le mois de DÉBUT de chaque période, qui
est toujours unique d'une période à l'autre)."""

import calendar
import datetime

from django.db import migrations

DELAI_DEFAUT = 10


def _ajouter_mois(d, n):
    """`d` + `n` mois, jour rabaissé au dernier jour du mois cible si besoin.
    Ancrage toujours depuis `d` (jamais chaîné) — cf. payments.cycles._ajouter_mois."""
    total = d.year * 12 + (d.month - 1) + n
    annee, mois0 = divmod(total, 12)
    mois = mois0 + 1
    return datetime.date(annee, mois, min(d.day, calendar.monthrange(annee, mois)[1]))


def recaler(apps, schema_editor):
    Eleve = apps.get_model('accounts', 'Eleve')
    Paiement = apps.get_model('payments', 'Paiement')
    Cycle = apps.get_model('payments', 'CycleAbonnement')
    Parametres = apps.get_model('inscriptions', 'ParametresInscriptions')

    params = Parametres.objects.first()
    delai = (params.delai_paiement_jours if params else None) or DELAI_DEFAUT

    Cycle.objects.all().delete()

    for eleve in Eleve.objects.exclude(statut='archive').select_related('user'):
        debut = eleve.user.date_joined.date()

        montant_par_mois = {}
        for p in Paiement.objects.filter(eleve=eleve, statut='valide'):
            cle = (p.mois_reference.year, p.mois_reference.month)
            montant_par_mois[cle] = montant_par_mois.get(cle, 0) + p.montant

        numero = 1
        i = 0
        # Suite CONTIGUË de périodes couvertes à partir de la période nº 1.
        while (_ajouter_mois(debut, i).year, _ajouter_mois(debut, i).month) in montant_par_mois:
            periode_debut = _ajouter_mois(debut, i)
            periode_fin_excl = _ajouter_mois(debut, i + 1)
            fin_couverte = periode_fin_excl - datetime.timedelta(days=1)
            Cycle.objects.create(
                eleve=eleve,
                numero=numero,
                date_debut=periode_debut,
                date_echeance=periode_debut + datetime.timedelta(days=delai),
                date_fin_couverte=fin_couverte,
                date_reglement=fin_couverte,
                montant_regle=montant_par_mois[(periode_debut.year, periode_debut.month)],
                regle=True,
            )
            numero += 1
            i += 1

        ouvert_debut = _ajouter_mois(debut, i)
        Cycle.objects.create(
            eleve=eleve,
            numero=numero,
            date_debut=ouvert_debut,
            date_echeance=ouvert_debut + datetime.timedelta(days=delai),
            regle=False,
        )


def supprimer(apps, schema_editor):
    apps.get_model('payments', 'CycleAbonnement').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0009_reglagerelancewhatsapp'),
        ('inscriptions', '0019_parametresinscriptions_delai_contact_heures_and_more'),
    ]

    operations = [
        migrations.RunPython(recaler, supprimer),
    ]
