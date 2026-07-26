import logging

import requests
from django.conf import settings
from django.core.paginator import Paginator

logger = logging.getLogger(__name__)


def paginer(request, queryset, par_page=10, param='page'):
    """Découpe une longue liste en pages de par_page éléments.
    Retourne un objet Page, itérable comme la queryset d'origine dans les templates.
    param: nom du paramètre GET à utiliser — permet de paginer indépendamment
    deux listes différentes sur une même page (ex: candidatures élèves et
    profs sur la même vue d'ensemble)."""
    paginator = Paginator(queryset, par_page)
    return paginator.get_page(request.GET.get(param))


def envoyer_notification_telegram(message):
    """Envoie `message` au مدير via l'API Telegram Bot (settings.TELEGRAM_BOT_TOKEN/
    TELEGRAM_CHAT_ID, lus depuis l'environnement — jamais en dur dans le code).
    Retourne True si envoyé, False sinon. Ne lève jamais d'exception : un souci
    Telegram (token invalide, réseau, timeout...) ne doit jamais empêcher
    l'opération métier (ex: soumission d'une candidature) qui a déjà eu lieu
    au moment de l'appel — même principe que envoyer_email_bienvenue.
    Si TELEGRAM_BOT_TOKEN/CHAT_ID ne sont pas configurés (ex: environnement de
    test sans .env complet), la notification est silencieusement ignorée."""
    token = settings.TELEGRAM_BOT_TOKEN
    chat_id = settings.TELEGRAM_CHAT_ID
    if not token or not chat_id:
        logger.warning(
            "Notification Telegram ignorée : TELEGRAM_BOT_TOKEN ou TELEGRAM_CHAT_ID "
            "absent des variables d'environnement."
        )
        return False
    try:
        reponse = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data={'chat_id': chat_id, 'text': message},
            timeout=5,
        )
        reponse.raise_for_status()
        return True
    except Exception as e:
        # Ne jamais logger l'exception brute : l'API Telegram n'accepte le token
        # que dans l'URL de la requête, et le message d'erreur de certaines
        # exceptions réseau (ConnectionError, HTTPError...) reproduit cette URL.
        # On masque donc le token avant tout logging, quel que soit le type d'erreur.
        message_sans_token = str(e).replace(token, '***')
        logger.error("Échec de l'envoi de la notification Telegram : %s", message_sans_token)
        return False
