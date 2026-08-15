"""Logique métier du chat qui ne relève pas du contrôle d'accès (voir
chat.permissions) : aperçu de la liste des conversations, comptage des
messages non lus, marquage comme lu, purge de rétention. Séparé de views.py
pour rester testable indépendamment du HTTP, même principe que
courses.utils / dashboard.recherche dans le reste du projet."""
import datetime
import os

from django.core.cache import cache
from django.utils import timezone

from .models import Conversation, Message, LectureConversation, get_configuration_chat
from .permissions import get_conversations_accessibles


def backfiller_conversations_manquantes():
    """Crée une Conversation pour chaque Groupe qui n'en a pas encore —
    nécessaire pour les groupes créés AVANT ce chantier (le signal
    chat.signals.creer_conversation_pour_nouveau_groupe ne se déclenche qu'à
    la création, jamais rétroactivement). Idempotent : filtre déjà sur
    conversation__isnull=True, ET get_or_create en ceinture supplémentaire —
    rejouer cette fonction (ou la migration de données qui réplique cette
    même logique sur les modèles historiques, voir
    chat/migrations/0002_backfill_conversations_existantes.py) ne crée jamais
    de doublon, la contrainte UNIQUE sur Conversation.groupe l'empêchant de
    toute façon. Retourne le nombre de conversations réellement créées.

    Fonction séparée de la migration de données (qui, elle, utilise les
    modèles historiques via apps.get_model — bonne pratique Django pour ne
    jamais dépendre du code applicatif réel dans une migration) : celle-ci
    reste appelable/testable directement avec les vrais modèles, ex. pour un
    outil d'exploitation ou un test."""
    from courses.models import Groupe

    nb_crees = 0
    for groupe in Groupe.objects.filter(conversation__isnull=True):
        _, cree = Conversation.objects.get_or_create(groupe=groupe)
        if cree:
            nb_crees += 1
    return nb_crees


def annoter_separateurs_jour(messages, jour_precedent=None):
    """Attache `.jour_separateur` (objet date() à afficher au-dessus de ce
    message, ou None si aucun séparateur n'est nécessaire) à chaque message
    d'une liste déjà triée chronologiquement (date_envoi croissante).

    Remplace l'ancien tag {% ifchanged %} de _message_bubbles.html : ce tag
    n'a AUCUNE mémoire entre deux rendus HTML indépendants (chaque lot de
    polling ou chaque lot d'historique ancien est produit par un appel
    séparé à render_to_string) et réaffichait donc un séparateur au sommet
    de CHAQUE lot, même quand le jour n'avait pas réellement changé
    (finding MEDIUM de l'audit du 2026-08-15).

    `jour_precedent` : date du dernier message déjà visible côté client
    AVANT ce lot (None si inconnu — chargement initial, ou lot "avant=" où
    le point de départ est par nature une nouvelle plage jamais affichée).
    Pour le polling ("apres="), l'appelant (chat.views.chat_messages) le
    calcule à partir du message ancre (`apres_id`) lui-même — le serveur n'a
    donc besoin d'aucune information supplémentaire fournie par le client."""
    dernier_jour = jour_precedent
    for message in messages:
        jour = timezone.localtime(message.date_envoi).date()
        message.jour_separateur = jour if jour != dernier_jour else None
        dernier_jour = jour
    return messages


def jour_du_message(message_id):
    """Jour (date, en heure locale) du message donné, ou None s'il n'existe
    plus (ex: purgé entre-temps) — sert d'ancre à annoter_separateurs_jour
    pour le polling (voir chat.views.chat_messages)."""
    date_envoi = Message.objects.filter(id=message_id).values_list('date_envoi', flat=True).first()
    if date_envoi is None:
        return None
    return timezone.localtime(date_envoi).date()


def conversations_avec_apercu(user):
    """Liste des conversations accessibles à `user`, chacune enrichie d'un
    aperçu (dernier message) et d'un nombre de messages non lus — tout ce
    dont a besoin le panneau de gauche (Point 19/30), sans jamais charger le
    contenu complet d'AUCUNE conversation (Point 19 : "Ne pas charger le
    contenu complet des chats de la liste").

    Volontairement 3 requêtes simples plutôt qu'une seule requête ORM très
    imbriquée (Subquery corrélée dans un Subquery corrélé) : le gain de
    performance d'une requête unique serait marginal ici (le nombre de
    conversations d'un utilisateur reste petit — quelques dizaines au plus,
    même pour un مؤطر avec beaucoup de profs) alors que le risque de bug
    silencieux d'une requête ORM à double imbrication est réel. Aucune des 3
    requêtes ci-dessous ne scanne l'historique complet : la 2e et 3e sont
    bornées par conversation_id__in=... et la 3e ne ramène que 2 colonnes
    légères (conversation_id, date_envoi), jamais le contenu des messages."""
    conversations = list(
        get_conversations_accessibles(user)
        .select_related('groupe', 'groupe__prof__user', 'groupe__creneau')
        .order_by('-id')
    )
    if not conversations:
        return []

    conv_ids = [c.id for c in conversations]

    # Dernier message de chaque conversation — PostgreSQL DISTINCT ON (le
    # projet impose PostgreSQL, voir CLAUDE.md), une seule requête pour
    # toutes les conversations à la fois.
    derniers_messages = {
        m['conversation_id']: m
        for m in (
            Message.objects.filter(conversation_id__in=conv_ids)
            .order_by('conversation_id', '-date_envoi')
            .distinct('conversation_id')
            .values('conversation_id', 'contenu', 'type_message', 'date_envoi', 'auteur_nom')
        )
    }

    lectures = dict(
        LectureConversation.objects.filter(conversation_id__in=conv_ids, user=user)
        .values_list('conversation_id', 'date_derniere_lecture')
    )

    non_lus_par_conversation = _compter_non_lus_par_conversation(conv_ids, lectures, user)

    for conversation in conversations:
        dernier = derniers_messages.get(conversation.id)
        conversation.dernier_message = dernier
        conversation.nb_non_lus = non_lus_par_conversation.get(conversation.id, 0)

    # Tri : conversation avec l'activité la plus récente en tête (dernier
    # message d'abord, sinon date de création du salon) — comme WhatsApp/
    # Messenger, pas un simple tri par id.
    conversations.sort(
        key=lambda c: c.dernier_message['date_envoi'] if c.dernier_message else c.date_creation,
        reverse=True,
    )
    return conversations


def _compter_non_lus_par_conversation(conv_ids, lectures, user):
    """Un message est non lu s'il est postérieur à la dernière lecture ET n'a
    pas été envoyé par `user` lui-même (on ne notifie jamais quelqu'un de ses
    propres messages). Ne ramène que (conversation_id, date_envoi) — jamais le
    contenu — et seulement pour les messages plus récents que la lecture la
    plus ancienne de l'utilisateur, jamais tout l'historique complet."""
    plus_ancienne_lecture = min(
        (v for v in lectures.values() if v is not None), default=None
    )
    messages_qs = Message.objects.filter(conversation_id__in=conv_ids).exclude(auteur=user)
    # Filtre grossier (borne large) pour réduire le volume ramené : ne garde que
    # les messages postérieurs à la lecture la plus ancienne, OU tout message
    # d'une conversation jamais lue (absente de `lectures`) — le filtre exact
    # par conversation est ensuite appliqué en Python ci-dessous.
    from django.db.models import Q
    if plus_ancienne_lecture is not None:
        messages_qs = messages_qs.filter(
            Q(date_envoi__gt=plus_ancienne_lecture) | Q(conversation_id__in=[
                cid for cid in conv_ids if cid not in lectures
            ])
        )

    compteur = {}
    for m in messages_qs.values('conversation_id', 'date_envoi'):
        seuil = lectures.get(m['conversation_id'])
        if seuil is None or m['date_envoi'] > seuil:
            compteur[m['conversation_id']] = compteur.get(m['conversation_id'], 0) + 1
    return compteur


def total_messages_non_lus(user):
    """Compte total (toutes conversations confondues) pour le badge de
    navigation (Point 14/15) — mis en cache 15 secondes par utilisateur pour
    ne pas recalculer à CHAQUE page vue (le context processor l'appelle sur
    toutes les pages du dashboard, pas seulement /chat/) : un léger délai de
    fraîcheur (15s max) est un compromis raisonnable pour un badge de
    notification, la page chat elle-même reste toujours exacte (calcul direct,
    jamais depuis ce cache — voir chat.views.chat_liste)."""
    if not getattr(user, 'is_authenticated', False) or user.role not in ('admin', 'prof', 'superviseur', 'eleve'):
        return 0

    cle_cache = f'chat_non_lus_total_{user.id}'
    valeur = cache.get(cle_cache)
    if valeur is not None:
        return valeur

    conv_ids = list(get_conversations_accessibles(user).values_list('id', flat=True))
    if not conv_ids:
        cache.set(cle_cache, 0, 15)
        return 0

    lectures = dict(
        LectureConversation.objects.filter(conversation_id__in=conv_ids, user=user)
        .values_list('conversation_id', 'date_derniere_lecture')
    )
    non_lus = _compter_non_lus_par_conversation(conv_ids, lectures, user)
    total = sum(non_lus.values())
    cache.set(cle_cache, total, 15)
    return total


def invalider_cache_non_lus(user_id):
    cache.delete(f'chat_non_lus_total_{user_id}')


def marquer_comme_lu(conversation, user):
    """Pose/actualise la date de dernière lecture de `user` pour cette
    conversation à MAINTENANT — appelé à l'ouverture d'une conversation et à
    chaque poll pendant qu'elle reste ouverte (voir chat.views). Invalide
    immédiatement le cache du badge de CET utilisateur (Point 15 : "il doit
    être possible de marquer une conversation comme lue")."""
    LectureConversation.objects.update_or_create(
        conversation=conversation, user=user,
        defaults={'date_derniere_lecture': timezone.now()},
    )
    invalider_cache_non_lus(user.id)


def purger_messages_expires():
    """Supprime les messages plus anciens que la durée de rétention configurée
    (ConfigurationChat.duree_retention_jours, 7 jours par défaut, Point 12).
    QuerySet.delete() envoie pre_delete/post_delete pour chaque ligne
    supprimée (contrairement à .update()) : le signal
    chat.signals.supprimer_fichier_a_la_suppression nettoie donc bien chaque
    pièce jointe/audio physique associée, aucun fichier orphelin. Ne touche
    JAMAIS Conversation/Groupe/Eleve/Prof/User — uniquement Message."""
    config = get_configuration_chat()
    seuil = timezone.now() - datetime.timedelta(days=config.duree_retention_jours)
    nb_supprimes, _ = Message.objects.filter(date_envoi__lt=seuil).delete()
    return nb_supprimes


def purge_opportuniste():
    """Filet de sécurité pour que la purge ait réellement lieu même si aucune
    tâche planifiée externe (cron) n'est encore configurée sur l'hébergeur
    (Point 12 : "ne pas compter sur l'utilisateur pour supprimer les
    messages"). Appelée depuis chat.views à chaque ouverture de la liste des
    conversations, mais throttlée à 1 exécution par heure maximum via le
    cache — un utilisateur qui ouvre le chat ne déclenche donc jamais un
    DELETE à chaque requête, seulement la première fois après l'expiration du
    throttle. La vraie solution de production reste de planifier
    `python manage.py purge_messages_chat` (ex: Render Cron Jobs) — voir le
    rapport de ce chantier."""
    cle_cache = 'chat_purge_opportuniste_derniere_execution'
    if cache.get(cle_cache):
        return
    cache.set(cle_cache, True, 60 * 60)
    purger_messages_expires()


# ==================== Validation des pièces jointes ====================
# Mêmes principes que dashboard.views._valider_fichier_hakiba (extension en
# liste blanche + taille max, jamais confiance au seul attribut HTML
# 'accept') — listes séparées : un document ne doit pas pouvoir être envoyé
# comme "audio" et inversement.

EXTENSIONS_FICHIER_AUTORISEES = (
    '.pdf', '.doc', '.docx', '.xls', '.xlsx', '.ppt', '.pptx', '.txt',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.zip',
)
EXTENSIONS_AUDIO_AUTORISEES = (
    '.mp3', '.wav', '.m4a', '.ogg', '.oga', '.webm', '.aac', '.opus',
)
TAILLE_MAX_PIECE_JOINTE_OCTETS = 15 * 1024 * 1024  # 15 Mo


def valider_piece_jointe(fichier, type_message):
    """Renvoie un message d'erreur arabe si le fichier est refusé, None s'il
    est accepté. type_message vaut 'audio' ou 'fichier' (jamais 'texte' ici)."""
    extension = os.path.splitext(fichier.name)[1].lower()
    extensions_autorisees = EXTENSIONS_AUDIO_AUTORISEES if type_message == 'audio' else EXTENSIONS_FICHIER_AUTORISEES
    if extension not in extensions_autorisees:
        return f'صيغة الملف "{extension}" غير مقبولة.'
    if fichier.size > TAILLE_MAX_PIECE_JOINTE_OCTETS:
        return f'حجم الملف كبير جداً ({fichier.size // (1024 * 1024)} م.ب). الحد الأقصى 15 م.ب.'
    return None
