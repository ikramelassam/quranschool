# Chantier anti-doublon du 2026-09-09 : bug signalé par le client — un seul
# groupe « علي بن ابي طالب » créé, mais deux en base (471/472), byte-pour-byte
# identiques, IDs consécutifs. Cause : groupe_ajouter n'avait AUCUNE garde
# anti-double-soumission (ni JS ni serveur), contrairement à
# inscriptions/paiements/annonces. La garde serveur a besoin d'un horodatage
# de création — le modèle Groupe n'en avait pas.
#
# null=True (pas de valeur par défaut rétro-active) : les groupes créés avant
# cette migration gardent date_creation=NULL, ce qui les exclut de la fenêtre
# de détection (`date_creation__gte=seuil`) — aucun risque de faux positif sur
# l'historique existant.

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0046_groupe_creneau_unique'),
    ]

    operations = [
        migrations.AddField(
            model_name='groupe',
            name='date_creation',
            field=models.DateTimeField(auto_now_add=True, null=True),
        ),
    ]
