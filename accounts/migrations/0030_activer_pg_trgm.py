# Recherche globale (Chantier du 2026-08-14) — active l'extension PostgreSQL
# pg_trgm, prérequis pour tous les index GIN trigram ajoutés par ce chantier
# (accounts.User/Prof, courses.Groupe, inscriptions.InscriptionEleve) et pour
# les lookups __trigram_similar utilisés par dashboard.recherche. Doit être
# appliquée AVANT toute migration AddIndex avec opclasses=['gin_trgm_ops'] —
# les migrations de ces 3 autres apps dépendent explicitement de celle-ci
# (voir leurs fichiers 0027/0031 respectifs) pour garantir l'ordre sur une
# base fraîche (ex: nouvel environnement de dev), pas seulement sur la base
# de dev actuelle où l'ordre d'exécution manuel suffirait.
#
# Commande pour la prod (Render) : la migration s'en charge automatiquement
# (CREATE EXTENSION IF NOT EXISTS), à condition que l'utilisateur PostgreSQL
# du DATABASE_URL ait le droit de créer des extensions — c'est le cas par
# défaut sur Render Postgres managé (rôle propriétaire de la base).
from django.contrib.postgres.operations import TrigramExtension
from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0029_element_hakiba_refonte'),
    ]

    operations = [
        TrigramExtension(),
    ]
