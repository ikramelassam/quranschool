from django.db import migrations


def assigner_tous_les_profs(apps, schema_editor):
    """Avant cette migration, aucun superviseur n'était limité à un sous-ensemble
    de profs (accès total, non filtré). Pour ne rien casser: tout superviseur déjà
    en base au moment de cette migration se voit assigner tous les profs déjà en
    base, pour continuer à voir exactement ce qu'il voyait avant."""
    Superviseur = apps.get_model('accounts', 'Superviseur')
    Prof = apps.get_model('accounts', 'Prof')

    tous_les_profs = list(Prof.objects.all())
    for superviseur in Superviseur.objects.all():
        superviseur.profs_assignes.set(tous_les_profs)


def revenir_en_arriere(apps, schema_editor):
    Superviseur = apps.get_model('accounts', 'Superviseur')
    for superviseur in Superviseur.objects.all():
        superviseur.profs_assignes.clear()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0004_superviseur_profs_assignes'),
    ]

    operations = [
        migrations.RunPython(assigner_tous_les_profs, revenir_en_arriere),
    ]
