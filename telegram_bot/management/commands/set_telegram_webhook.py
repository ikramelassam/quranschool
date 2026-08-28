import requests
from django.conf import settings
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = (
        "Configure le webhook Telegram (setWebhook) vers /telegram/webhook/ sur "
        "l'URL fournie. À exécuter MANUELLEMENT une fois après déploiement, et à "
        "nouveau uniquement si TELEGRAM_BOT_TOKEN, TELEGRAM_WEBHOOK_SECRET ou le "
        "domaine changent — ce n'est PAS appelé automatiquement à chaque déploiement."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            'url_site',
            help="URL complète du site en HTTPS, ex: https://quranschool.onrender.com",
        )

    def handle(self, *args, **options):
        token = settings.TELEGRAM_BOT_TOKEN
        secret = settings.TELEGRAM_WEBHOOK_SECRET
        if not token:
            raise CommandError("TELEGRAM_BOT_TOKEN n'est pas configuré dans l'environnement.")
        if not secret:
            raise CommandError("TELEGRAM_WEBHOOK_SECRET n'est pas configuré dans l'environnement.")

        url_site = options['url_site'].rstrip('/')
        if not url_site.startswith('https://'):
            raise CommandError("L'URL doit être en HTTPS (Telegram exige un webhook HTTPS).")

        webhook_url = f'{url_site}/telegram/webhook/'
        try:
            reponse = requests.post(
                f'https://api.telegram.org/bot{token}/setWebhook',
                data={'url': webhook_url, 'secret_token': secret},
                timeout=10,
            )
        except Exception as e:
            message_sans_token = str(e).replace(token, '***')
            raise CommandError(f"Échec réseau lors de l'appel à setWebhook : {message_sans_token}")

        resultat = reponse.json()
        if resultat.get('ok'):
            self.stdout.write(self.style.SUCCESS(
                f"Webhook Telegram configuré avec succès vers {webhook_url}"
            ))
        else:
            raise CommandError(f"Échec setWebhook : {resultat.get('description', resultat)}")
