# Seed des 2 positions de séance déjà réellement utilisées aujourd'hui (les
# seules qui existent dans les groupes actuels, voir Seance.
# numero_dans_la_semaine) — reproduit EXACTEMENT le comportement actuel basé
# sur CritereEleve.type_lie, avant toute personnalisation par l'admin :
#   position 1 (impaire, ancien axe 'hifz')      : critères commun + hifz
#   position 2 (paire, ancien axe 'mouraja3a')   : critères commun + mouraja3a
# Toute position >= 3 encore jamais rencontrée se crée automatiquement à la
# volée avec le même gabarit (voir Seance.criteres_applicables) — inutile de
# la pré-créer ici, aucune limite artificielle n'est imposée par cette
# migration.
from django.db import migrations


def seed(apps, schema_editor):
    ProfilCriteresSeance = apps.get_model('courses', 'ProfilCriteresSeance')
    CritereEleve = apps.get_model('courses', 'CritereEleve')

    for position, axe in ((1, 'hifz'), (2, 'mouraja3a')):
        profil, _ = ProfilCriteresSeance.objects.get_or_create(position=position)
        profil.criteres.set(CritereEleve.objects.filter(type_lie__in=('commun', axe)))


def revert(apps, schema_editor):
    ProfilCriteresSeance = apps.get_model('courses', 'ProfilCriteresSeance')
    ProfilCriteresSeance.objects.filter(position__in=(1, 2)).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0050_profil_criteres_seance'),
    ]

    operations = [
        migrations.RunPython(seed, revert),
    ]
