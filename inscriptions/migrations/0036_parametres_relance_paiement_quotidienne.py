# Generated for the « relances de paiement quotidiennes » chantier (2026-09-02)

import datetime

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('inscriptions', '0035_typeabonnement_label_en_typeabonnement_label_fr'),
    ]

    operations = [
        migrations.AddField(
            model_name='parametresinscriptions',
            name='heure_relance_paiement',
            field=models.TimeField(default=datetime.time(20, 0)),
        ),
        migrations.AddField(
            model_name='parametresinscriptions',
            name='delai_grace_nouvel_eleve_mois',
            field=models.PositiveIntegerField(default=2),
        ),
    ]
