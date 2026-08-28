import json
import logging
from secrets import compare_digest

from django.conf import settings
from django.http import HttpResponse
from django.utils import timezone
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_POST

from core.utils import envoyer_message_telegram_direct
from .models import AbonneTelegram

logger = logging.getLogger(__name__)

MESSAGE_START_NOUVEAU = (
    '🕌 مرحباً بك في بوت إشعارات منصة زدني علماً.\n\n'
    'تم استلام طلب اشتراكك وهو الآن بانتظار موافقة الإدارة. '
    'ستصلك الإشعارات (طلبات تسجيل، مدفوعات...) فور الموافقة عليه.'
)
MESSAGE_START_DEJA_ACTIF = 'أنت مشترك بالفعل في إشعارات منصة زدني علماً ✅'
MESSAGE_STOP_OK = (
    'تم إلغاء اشتراكك في الإشعارات.\n'
    'يمكنك إرسال /start في أي وقت لإعادة تفعيله (سيحتاج إلى موافقة الإدارة من جديد).'
)
MESSAGE_STOP_INCONNU = 'لست مشتركاً في إشعارات هذا البوت.'
MESSAGE_STOP_DEJA_INACTIF = 'اشتراكك غير مفعّل حالياً.'
MESSAGE_AIDE = (
    'هذا البوت مخصص لإشعارات منصة زدني علماً فقط.\n\n'
    'الأوامر المتاحة:\n'
    '/start — الاشتراك في الإشعارات\n'
    '/stop — إلغاء الاشتراك'
)


def _secret_valide(request):
    """Seule protection du webhook — voir settings.TELEGRAM_WEBHOOK_SECRET et
    telegram_bot.management.commands.set_telegram_webhook. compare_digest (pas
    ==) : comparaison à temps constant, même principe que pour un mot de passe,
    plutôt qu'une simple égalité de chaînes."""
    secret_attendu = settings.TELEGRAM_WEBHOOK_SECRET
    if not secret_attendu:
        # Pas de secret configuré = webhook non exploitable en sécurité, on
        # rejette tout plutôt que d'accepter des updates non authentifiés.
        return False
    secret_recu = request.headers.get('X-Telegram-Bot-Api-Secret-Token', '')
    return compare_digest(secret_recu, secret_attendu)


@csrf_exempt
@require_POST
def webhook(request):
    """Reçoit les updates Telegram (POST) — protégé par le secret_token fourni
    à setWebhook (header X-Telegram-Bot-Api-Secret-Token), PAS par CSRF Django
    (Telegram n'envoie aucun cookie/token CSRF, d'où @csrf_exempt).
    Répond toujours 200 dès que le secret est valide, quoi qu'il arrive
    ensuite en interne (update ignoré, JSON malformé, exception inattendue...)
    — le traitement est idempotent (get_or_create sur /start), rien à gagner
    à laisser Telegram réessayer en boucle un update déjà vu."""
    if not _secret_valide(request):
        return HttpResponse(status=403)

    try:
        data = json.loads(request.body.decode('utf-8'))
    except (ValueError, UnicodeDecodeError):
        return HttpResponse(status=200)

    try:
        _traiter_update(data)
    except Exception:
        logger.exception("Erreur inattendue en traitant un update Telegram.")

    return HttpResponse(status=200)


def _traiter_update(data):
    message = data.get('message') or data.get('edited_message')
    if not message:
        # Autres types d'update (callback_query, my_chat_member...) : rien à
        # faire, ce bot n'utilise que des commandes texte simples.
        return
    chat = message.get('chat') or {}
    chat_id = chat.get('id')
    if chat_id is None:
        return

    texte = (message.get('text') or '').strip()
    frm = message.get('from') or {}
    nom = ' '.join(filter(None, [frm.get('first_name', ''), frm.get('last_name', '')])).strip()
    username = frm.get('username') or ''

    if texte.startswith('/start'):
        _gerer_start(chat_id, nom, username)
    elif texte.startswith('/stop'):
        _gerer_stop(chat_id)
    else:
        envoyer_message_telegram_direct(chat_id, MESSAGE_AIDE)


def _gerer_start(chat_id, nom, username):
    abonne, cree = AbonneTelegram.objects.get_or_create(
        chat_id=chat_id,
        defaults={'nom': nom, 'telegram_username': username},
    )

    if not cree:
        # Rafraîchit nom/username au passage (peuvent avoir changé depuis la
        # 1ère fois) — jamais bloquant, un champ vide ne remplace pas une
        # valeur déjà connue.
        champs_a_jour = []
        if nom and abonne.nom != nom:
            abonne.nom = nom
            champs_a_jour.append('nom')
        if username and abonne.telegram_username != username:
            abonne.telegram_username = username
            champs_a_jour.append('telegram_username')

        if abonne.est_actif:
            if champs_a_jour:
                abonne.save(update_fields=champs_a_jour)
            envoyer_message_telegram_direct(chat_id, MESSAGE_START_DEJA_ACTIF)
            return

        # Inactif (ancien /stop, rejet/désactivation admin, ou auto-désactivation
        # après un 403 Telegram) : repasse SYSTÉMATIQUEMENT en file d'attente —
        # décision de sécurité explicite, jamais de réactivation automatique.
        # Voir AbonneTelegram.__doc__.
        abonne.en_attente_validation = True
        abonne.date_desabonnement = None
        abonne.save(update_fields=champs_a_jour + ['en_attente_validation', 'date_desabonnement'])
        logger.info("Abonné Telegram %s repassé en attente de validation après /start.", chat_id)
    else:
        logger.info("Nouvel abonné Telegram en attente de validation : %s (%s)", chat_id, nom)

    envoyer_message_telegram_direct(chat_id, MESSAGE_START_NOUVEAU)


def _gerer_stop(chat_id):
    try:
        abonne = AbonneTelegram.objects.get(chat_id=chat_id)
    except AbonneTelegram.DoesNotExist:
        envoyer_message_telegram_direct(chat_id, MESSAGE_STOP_INCONNU)
        return

    if not abonne.est_actif:
        envoyer_message_telegram_direct(chat_id, MESSAGE_STOP_DEJA_INACTIF)
        return

    abonne.est_actif = False
    abonne.date_desabonnement = timezone.now()
    abonne.save(update_fields=['est_actif', 'date_desabonnement'])
    logger.info("Abonné Telegram %s désabonné (/stop).", chat_id)
    envoyer_message_telegram_direct(chat_id, MESSAGE_STOP_OK)
