import logging

import requests
from django.conf import settings
from django.core.paginator import Paginator
from django.utils import timezone

logger = logging.getLogger(__name__)


def paginer(request, queryset, par_page=10, param='page'):
    """Découpe une longue liste en pages de par_page éléments.
    Retourne un objet Page, itérable comme la queryset d'origine dans les templates.
    param: nom du paramètre GET à utiliser — permet de paginer indépendamment
    deux listes différentes sur une même page (ex: candidatures élèves et
    profs sur la même vue d'ensemble)."""
    paginator = Paginator(queryset, par_page)
    return paginator.get_page(request.GET.get(param))


class TelegramBloque(Exception):
    """Levée par envoyer_message_telegram_direct quand Telegram répond 403
    "Forbidden: bot was blocked by the user" — signal fiable et non ambigu que
    CE destinataire précis a bloqué le bot (ou supprimé la conversation),
    distinct d'un simple souci réseau/timeout transitoire qui ne doit jamais
    entraîner de désactivation automatique (voir envoyer_notification_telegram)."""
    pass


def envoyer_message_telegram_direct(chat_id, texte):
    """Appel bas niveau à l'API Telegram sendMessage vers UN destinataire précis
    (chat_id numérique). Ne lève jamais d'exception réseau/timeout (retourne
    False, logue l'échec) — SAUF TelegramBloque, volontairement laissée
    remonter pour que l'appelant décide quoi en faire (voir usages : la boucle
    de envoyer_notification_telegram désactive l'abonné, une réponse au
    webhook l'ignore simplement).
    Utilisée à la fois par envoyer_notification_telegram (diffusion à tous les
    abonnés actifs) et par telegram_bot.views (réponses individuelles à
    /start, /stop, etc.) — un seul endroit qui parle réellement à l'API Telegram."""
    token = settings.TELEGRAM_BOT_TOKEN
    if not token:
        logger.warning(
            "Envoi Telegram ignoré (destinataire %s) : TELEGRAM_BOT_TOKEN absent "
            "des variables d'environnement.", chat_id
        )
        return False
    try:
        reponse = requests.post(
            f'https://api.telegram.org/bot{token}/sendMessage',
            data={'chat_id': chat_id, 'text': texte},
            timeout=5,
        )
    except Exception as e:
        # Ne jamais logger l'exception brute : l'API Telegram n'accepte le token
        # que dans l'URL de la requête, et le message d'erreur de certaines
        # exceptions réseau (ConnectionError, HTTPError...) reproduit cette URL.
        # On masque donc le token avant tout logging, quel que soit le type d'erreur.
        message_sans_token = str(e).replace(token, '***')
        logger.error("Échec réseau de l'envoi Telegram vers %s : %s", chat_id, message_sans_token)
        return False

    if reponse.status_code == 403:
        raise TelegramBloque(chat_id)
    if not reponse.ok:
        logger.error(
            "Échec de l'envoi Telegram vers %s (HTTP %s) : %s",
            chat_id, reponse.status_code, reponse.text
        )
        return False
    return True


def envoyer_notification_telegram(message):
    """Envoie `message` à TOUS les abonnés Telegram actifs (telegram_bot.
    AbonneTelegram, est_actif=True) — remplace l'ancien système à chat_id
    unique codé en dur (voir telegram_bot app). Un échec sur UN destinataire
    (bloqué, réseau, timeout...) n'empêche jamais l'envoi aux autres — chaque
    envoi est isolé dans son propre bloc try/except.
    Ne lève jamais d'exception : un souci Telegram ne doit jamais empêcher
    l'opération métier (ex: soumission d'une candidature) qui a déjà eu lieu
    au moment de l'appel — même principe que envoyer_email_bienvenue, et que
    l'ancienne version de cette fonction.
    Retourne True si au moins un envoi a réussi, False sinon (aucun abonné
    actif, ou tous les envois ont échoué) — comme avant, aucun appelant actuel
    n'inspecte cette valeur (tous les appels sont fire-and-forget)."""
    # Import tardif (comme les autres imports de modèles dans dashboard/views.py) :
    # évite un import circulaire, telegram_bot.views importe lui-même core.utils
    # pour ses réponses individuelles (envoyer_message_telegram_direct).
    from telegram_bot.models import AbonneTelegram

    abonnes = list(AbonneTelegram.objects.filter(est_actif=True))
    if not abonnes:
        logger.warning("Notification Telegram ignorée : aucun abonné actif.")
        return False

    au_moins_un_envoi_reussi = False
    for abonne in abonnes:
        try:
            if envoyer_message_telegram_direct(abonne.chat_id, message):
                au_moins_un_envoi_reussi = True
        except TelegramBloque:
            # Signal sans ambiguïté (voir TelegramBloque) : cet abonné a bloqué
            # le bot. Désactivation automatique — un /start ultérieur de sa part
            # repassera de toute façon en file d'attente (voir AbonneTelegram),
            # donc aucun risque de réactivation non désirée par cette désactivation.
            abonne.est_actif = False
            abonne.date_desabonnement = timezone.now()
            abonne.save(update_fields=['est_actif', 'date_desabonnement'])
            logger.warning(
                "Abonné Telegram %s désactivé automatiquement (bot bloqué par l'utilisateur).",
                abonne.chat_id
            )
        except Exception as e:
            # Défense en profondeur : envoyer_message_telegram_direct ne devrait
            # normalement jamais lever autre chose que TelegramBloque, mais un
            # souci sur UN destinataire ne doit dans tous les cas jamais
            # interrompre l'envoi aux autres.
            logger.error("Échec inattendu de l'envoi Telegram vers %s : %s", abonne.chat_id, e)

    return au_moins_un_envoi_reussi


def envoyer_notification_telegram_async(message):
    """Comme envoyer_notification_telegram, mais SANS bloquer la requête HTTP
    en cours (Correctif perf du 2026-08-30, voir AUDIT_PERFORMANCE_2026-08-30.md
    point 5.1) : chaque envoi fait un appel réseau synchrone (timeout=5) par
    abonné actif, DANS le cycle requête/réponse de l'utilisateur (élève qui
    soumet un paiement, candidat qui s'inscrit, mot de passe oublié...) — un
    souci Telegram (lent ou indisponible) retardait alors une action qui n'a
    pourtant rien à voir avec Telegram. Ici, l'envoi part dans un thread
    daemon détaché : la réponse HTTP part immédiatement, l'envoi continue en
    arrière-plan. Pas de file d'attente Celery/Redis (hors de portée sur cet
    hébergeur) — juste ne pas faire attendre l'utilisateur pour un
    "fire-and-forget" qui l'était déjà fonctionnellement (aucun appelant
    n'inspecte la valeur de retour, voir la docstring ci-dessus).

    Limite à connaître (acceptée explicitement, pas un oubli) : un thread
    daemon est tué net si le worker gunicorn redémarre avant sa fin — dans ce
    cas rarissime, l'envoi Telegram peut ne jamais partir, silencieusement.
    Acceptable ici : la notification reste "best effort" par design (un échec
    individuel n'a jamais empêché l'opération métier déjà effectuée), ce
    correctif ne fait qu'élargir légèrement cette même tolérance à un
    redémarrage pile pendant cette fenêtre de quelques centaines de ms."""
    import threading
    from django.db import connection

    def _cible():
        try:
            envoyer_notification_telegram(message)
        finally:
            # La connexion DB ouverte par ce thread (AbonneTelegram.objects...)
            # est thread-locale : Django ne la ferme jamais tout seul en dehors
            # du cycle requête/réponse normal (voir request_finished). Sans ce
            # close() explicite, CONN_MAX_AGE (settings.py) la laisserait
            # ouverte indéfiniment — un thread neuf par notification finirait
            # par accumuler des connexions Postgres jamais relâchées.
            connection.close()

    threading.Thread(target=_cible, daemon=True).start()
