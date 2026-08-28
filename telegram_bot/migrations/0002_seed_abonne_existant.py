# Chantier abonnement Telegram automatique.
# Préserve la continuité des notifications existantes pendant la transition :
# l'ancien chat_id unique codé en dur (settings.TELEGRAM_CHAT_ID, ancien système
# à un seul destinataire) devient le tout premier AbonneTelegram, déjà actif et
# déjà validé — pas de coupure de notification le temps que le مدير/مشرف
# ré-envoie /start et se fasse valider comme n'importe quel nouvel abonné.
#
# Migration à sens unique (reverse_code=noop) : si TELEGRAM_CHAT_ID est absent
# ou invalide (ex: environnement de test sans .env complet), ne fait rien
# plutôt que de faire planter `migrate`.

from django.conf import settings
from django.db import migrations


def seed_abonne_existant(apps, schema_editor):
    chat_id_brut = settings.TELEGRAM_CHAT_ID
    if not chat_id_brut:
        return
    try:
        chat_id = int(chat_id_brut)
    except (TypeError, ValueError):
        return

    AbonneTelegram = apps.get_model('telegram_bot', 'AbonneTelegram')
    AbonneTelegram.objects.get_or_create(
        chat_id=chat_id,
        defaults={
            'nom': 'Migration automatique (ancien TELEGRAM_CHAT_ID)',
            'est_actif': True,
            'en_attente_validation': False,
        },
    )


class Migration(migrations.Migration):

    dependencies = [
        ('telegram_bot', '0001_initial'),
    ]

    operations = [
        migrations.RunPython(seed_abonne_existant, reverse_code=migrations.RunPython.noop),
    ]
