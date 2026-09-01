"""Backfill des cycles d'abonnement pour les élèves déjà validés — chantier
« relances de paiement » du 2026-09-01.

Sans ce backfill, la fonctionnalité ne concernerait AUCUN élève existant : les
cycles ne sont créés qu'à la validation d'une inscription (qui a déjà eu lieu)
ou au désarchivage. Ici on reconstitue, pour chaque élève actif sans cycle :
- un cycle « réglé » unique couvrant toute la suite CONTIGUË de mois `valide`
  depuis son mois d'inscription (user.date_joined),
- puis le cycle ouvert courant, avec son échéance.

Volontairement PAS de reconstitution cycle par cycle de l'historique (un seul
cycle réglé « fourre-tout ») : seul l'état COURANT (échéance en cours, retard ou
non) compte pour la fonctionnalité ; le détail par cycle se construira
correctement au fil des futures validations (payments.cycles.reconcilier).

Anti-inondation : un élève déjà en retard depuis longtemps apparaîtra bien comme
tel dès le déploiement — c'est voulu (le مدير doit justement voir ces
retards-là), et la notification est un simple ÉTAT (pas un flux d'événements
horodatés qui « remonterait » d'un coup)."""

import calendar
import datetime

from django.db import migrations

DELAI_DEFAUT = 10


def _dernier_du_mois(annee, mois):
    return datetime.date(annee, mois, calendar.monthrange(annee, mois)[1])


def _mois_suivant(annee, mois):
    return (annee + 1, 1) if mois == 12 else (annee, mois + 1)


def backfill(apps, schema_editor):
    Eleve = apps.get_model('accounts', 'Eleve')
    Paiement = apps.get_model('payments', 'Paiement')
    Cycle = apps.get_model('payments', 'CycleAbonnement')
    Parametres = apps.get_model('inscriptions', 'ParametresInscriptions')

    params = Parametres.objects.first()
    delai = (params.delai_paiement_jours if params else None) or DELAI_DEFAUT

    for eleve in Eleve.objects.exclude(statut='archive').select_related('user'):
        if Cycle.objects.filter(eleve=eleve).exists():
            continue

        debut = eleve.user.date_joined.date()
        mois_payes = {
            (a, m)
            for a, m in Paiement.objects.filter(eleve=eleve, statut='valide')
            .values_list('mois_reference__year', 'mois_reference__month')
        }

        # Suite contiguë de mois valides à partir du mois d'inscription.
        annee, mois = debut.year, debut.month
        fin_couverte = None
        while (annee, mois) in mois_payes:
            fin_couverte = _dernier_du_mois(annee, mois)
            annee, mois = _mois_suivant(annee, mois)

        numero = 1
        if fin_couverte is not None:
            montant = sum(
                (
                    p.montant
                    for p in Paiement.objects.filter(
                        eleve=eleve,
                        statut='valide',
                        mois_reference__gte=datetime.date(debut.year, debut.month, 1),
                        mois_reference__lte=fin_couverte,
                    )
                ),
                0,
            )
            Cycle.objects.create(
                eleve=eleve,
                numero=numero,
                date_debut=debut,
                date_echeance=debut + datetime.timedelta(days=delai),
                date_fin_couverte=fin_couverte,
                date_reglement=fin_couverte,
                montant_regle=montant,
                regle=True,
            )
            numero += 1
            debut_ouvert = fin_couverte + datetime.timedelta(days=1)
            echeance_ouvert = fin_couverte + datetime.timedelta(days=delai)
        else:
            debut_ouvert = debut
            echeance_ouvert = debut + datetime.timedelta(days=delai)

        Cycle.objects.create(
            eleve=eleve,
            numero=numero,
            date_debut=debut_ouvert,
            date_echeance=echeance_ouvert,
            regle=False,
        )


def supprimer(apps, schema_editor):
    apps.get_model('payments', 'CycleAbonnement').objects.all().delete()


class Migration(migrations.Migration):

    dependencies = [
        ('payments', '0006_cycleabonnement'),
        ('inscriptions', '0019_parametresinscriptions_delai_contact_heures_and_more'),
    ]

    operations = [
        migrations.RunPython(backfill, supprimer),
    ]
