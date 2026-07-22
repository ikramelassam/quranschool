from django.db import migrations

TARIFS = [
    ('groupe', 'enfant', 70),
    ('groupe', 'adulte', 50),
    ('individuel', 'enfant', 45),
    ('individuel', 'adulte', 35),
]


def seed_tarifs(apps, schema_editor):
    TarifRemuneration = apps.get_model('courses', 'TarifRemuneration')
    for type_capacite, tranche_age, montant in TARIFS:
        TarifRemuneration.objects.get_or_create(
            type_capacite=type_capacite,
            tranche_age=tranche_age,
            defaults={'montant': montant},
        )


def reverse_seed_tarifs(apps, schema_editor):
    TarifRemuneration = apps.get_model('courses', 'TarifRemuneration')
    for type_capacite, tranche_age, _ in TARIFS:
        TarifRemuneration.objects.filter(type_capacite=type_capacite, tranche_age=tranche_age).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0015_tarifremuneration'),
    ]

    operations = [
        migrations.RunPython(seed_tarifs, reverse_seed_tarifs),
    ]
