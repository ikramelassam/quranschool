from django.http import HttpResponseForbidden, JsonResponse, HttpResponseBadRequest
from django.shortcuts import render, redirect, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from accounts.decorators import role_required
from .models import Conversation, Message
from .permissions import can_access_conversation, participants_conversation
from .services import (
    annoter_separateurs_jour, conversations_avec_apercu, jour_du_message,
    marquer_comme_lu, purge_opportuniste, valider_piece_jointe,
)

NB_MESSAGES_PAR_PAGE = 30

# مشرف exclu volontairement (Point 3 : "il n'y a PAS de مشرف dans le chat").
ROLES_AVEC_CHAT = ('eleve', 'prof', 'superviseur', 'admin')

BASE_TEMPLATE_PAR_ROLE = {
    'admin': 'dashboard/base_admin.html',
    'prof': 'dashboard/base_prof.html',
    'eleve': 'dashboard/base_eleve.html',
    'superviseur': 'dashboard/base_superviseur.html',
}


def _base_template(request):
    return BASE_TEMPLATE_PAR_ROLE[request.user.role]


def _conversation_ou_403(request, groupe_id):
    """Point d'entrée UNIQUE de vérification d'accès pour toute vue qui cible
    une conversation précise (Point 27/28) — résout la Conversation à partir
    du groupe demandé puis vérifie can_access_conversation AVANT de renvoyer
    quoi que ce soit. Aucune donnée de la conversation n'est exposée si
    l'accès est refusé (Point 9 : "Aucune donnée de la conversation interdite
    ne doit être renvoyée avant le contrôle de permission")."""
    conversation = get_object_or_404(Conversation, groupe_id=groupe_id)
    if not can_access_conversation(request.user, conversation):
        return None, HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذه المحادثة.')
    return conversation, None


def _contexte_messages_initiaux(conversation, request):
    """Les NB_MESSAGES_PAR_PAGE derniers messages, dans l'ordre chronologique
    (Point 17 : jamais tout l'historique) — utilisé pour le chargement
    initial d'une conversation, que ce soit la page complète ou le panneau
    rechargé en AJAX."""
    # Pas de select_related('auteur') : le template n'affiche jamais de champ live
    # de l'auteur (email/téléphone interdits de toute façon) — seulement les
    # instantanés auteur_nom/auteur_role figés sur le Message lui-même (voir
    # Message.__doc__), donc aucun besoin de rejoindre la table User ici.
    messages_recents = list(
        conversation.messages.order_by('-date_envoi')[:NB_MESSAGES_PAR_PAGE]
    )
    messages_recents.reverse()
    annoter_separateurs_jour(messages_recents)
    return {
        'conversation': conversation,
        'groupe': conversation.groupe,
        'messages': messages_recents,
        'a_plus_ancien': len(messages_recents) == NB_MESSAGES_PAR_PAGE,
        'participants': participants_conversation(conversation),
        'user': request.user,
    }


@role_required(*ROLES_AVEC_CHAT)
def chat_liste(request):
    """Page d'accueil du chat (Point 19/20) : panneau des conversations à
    gauche, aucune conversation ouverte à droite (état vide) — desktop et
    mobile partagent le même template, la bascule liste/conversation sur
    mobile est purement CSS (voir templates/chat/chat.html)."""
    purge_opportuniste()
    conversations = conversations_avec_apercu(request.user)
    return render(request, 'chat/chat.html', {
        'conversations': conversations,
        'conversation_ouverte': None,
        'base_template': _base_template(request),
    })


@role_required(*ROLES_AVEC_CHAT)
def chat_conversation(request, groupe_id):
    """Lien direct vers UNE conversation (Point 20 : URL partageable/rechargeable) —
    même gabarit que chat_liste, avec la conversation demandée déjà ouverte et
    ses derniers messages pré-rendus côté serveur (pas d'aller-retour AJAX
    supplémentaire au premier chargement)."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    marquer_comme_lu(conversation, request.user)
    conversations = conversations_avec_apercu(request.user)
    contexte = {
        'conversations': conversations,
        'conversation_ouverte': conversation,
        'base_template': _base_template(request),
    }
    contexte.update(_contexte_messages_initiaux(conversation, request))
    return render(request, 'chat/chat.html', contexte)


@role_required(*ROLES_AVEC_CHAT)
@require_GET
def chat_liste_partial(request):
    """Fragment HTML de la liste des conversations — utilisé par le polling
    du panneau de gauche pour rafraîchir aperçus/badges de non-lus sans
    recharger la page ni les messages ouverts (Point 15/17)."""
    conversations = conversations_avec_apercu(request.user)
    groupe_ouvert_id = request.GET.get('ouverte')
    html = render_to_string('chat/_conversation_liste.html', {
        'conversations': conversations,
        'groupe_ouvert_id': int(groupe_ouvert_id) if groupe_ouvert_id and groupe_ouvert_id.isdigit() else None,
    }, request=request)
    return JsonResponse({'html': html})


@role_required(*ROLES_AVEC_CHAT)
@require_GET
def chat_panel(request, groupe_id):
    """Fragment HTML du panneau de conversation (en-tête + derniers messages +
    zone de composition) — utilisé pour ouvrir une conversation en AJAX
    (bascule sans recharger toute la page, Point 20/30)."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur
    marquer_comme_lu(conversation, request.user)
    html = render_to_string('chat/_panel.html', _contexte_messages_initiaux(conversation, request), request=request)
    return JsonResponse({'html': html})


@role_required(*ROLES_AVEC_CHAT)
@require_GET
def chat_messages(request, groupe_id):
    """Pagination par curseur (Point 17), les 3 branches BORNÉES à
    NB_MESSAGES_PAR_PAGE (finding HIGH de l'audit du 2026-08-15 : la branche
    `apres=` ne l'était pas — un curseur périmé pouvait renvoyer tout
    l'historique restant d'un coup) :
    - `avant=<id>` : jusqu'à NB_MESSAGES_PAR_PAGE messages plus anciens que cet
      id (défilement remontant dans l'historique) ;
    - `apres=<id>` : jusqu'à NB_MESSAGES_PAR_PAGE messages plus récents que cet
      id, en ordre chronologique (polling). `a_plus_recent=true` dans la
      réponse signale qu'il reste d'autres messages au-delà de ce lot — le JS
      ré-interroge alors immédiatement avec le nouveau dernier_id au lieu
      d'attendre le prochain tick (voir templates/chat/chat.html, poll()) ;
    - aucun des deux : les NB_MESSAGES_PAR_PAGE derniers messages (identique
      au chargement initial, utilisé si le JS a perdu son curseur).

    Chaque message reçoit aussi `.jour_separateur` (chat.services.
    annoter_separateurs_jour) pour que le séparateur de jour ne soit émis
    qu'une seule fois par vraie transition de jour, jamais rejoué au sommet
    de chaque lot indépendant (finding MEDIUM du même audit)."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    avant_id = request.GET.get('avant')
    apres_id = request.GET.get('apres')
    base_qs = conversation.messages.all()
    a_plus_recent = False

    if apres_id and apres_id.isdigit():
        # +1 : "sonde" bon marché pour savoir s'il reste d'autres messages
        # au-delà de ce lot, sans requête COUNT séparée — tronqué juste après.
        lot = list(base_qs.filter(id__gt=int(apres_id)).order_by('date_envoi')[:NB_MESSAGES_PAR_PAGE + 1])
        a_plus_recent = len(lot) > NB_MESSAGES_PAR_PAGE
        messages = lot[:NB_MESSAGES_PAR_PAGE]
        a_plus_ancien = False
        jour_precedent = jour_du_message(int(apres_id))
    elif avant_id and avant_id.isdigit():
        messages = list(base_qs.filter(id__lt=int(avant_id)).order_by('-date_envoi')[:NB_MESSAGES_PAR_PAGE])
        a_plus_ancien = len(messages) == NB_MESSAGES_PAR_PAGE
        messages.reverse()
        jour_precedent = None
    else:
        messages = list(base_qs.order_by('-date_envoi')[:NB_MESSAGES_PAR_PAGE])
        a_plus_ancien = len(messages) == NB_MESSAGES_PAR_PAGE
        messages.reverse()
        jour_precedent = None

    annoter_separateurs_jour(messages, jour_precedent=jour_precedent)

    html = render_to_string('chat/_message_bubbles.html', {
        'messages': messages,
        'user': request.user,
        'groupe_id': conversation.groupe_id,
    }, request=request)

    return JsonResponse({
        'html': html,
        'a_plus_ancien': a_plus_ancien,
        'a_plus_recent': a_plus_recent,
        'premier_id': messages[0].id if messages else None,
        'dernier_id': messages[-1].id if messages else None,
        'nb_messages': len(messages),
    })


@role_required(*ROLES_AVEC_CHAT)
@require_POST
def chat_envoyer(request, groupe_id):
    """Envoi d'un message — texte, audio ou pièce jointe (Point 13/22).
    Validation serveur systématique (jamais confiance au seul JS, désactivant
    le bouton d'envoi côté client) : un message vide (ni texte ni fichier) est
    refusé, un fichier hors liste blanche ou trop volumineux est refusé."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    contenu = (request.POST.get('contenu') or '').strip()
    fichier = request.FILES.get('fichier')
    type_message = request.POST.get('type_message', 'texte')
    if type_message not in ('texte', 'audio', 'fichier'):
        type_message = 'texte'

    if not fichier and not contenu:
        return HttpResponseBadRequest('لا يمكن إرسال رسالة فارغة.')

    if fichier and type_message == 'texte':
        # Un fichier envoyé sans type explicite (audio/fichier) précisé par le
        # client est traité comme pièce jointe générique par défaut.
        type_message = 'fichier'
    if fichier:
        erreur_validation = valider_piece_jointe(fichier, type_message)
        if erreur_validation:
            return HttpResponseBadRequest(erreur_validation)

    # Jour du dernier message AVANT celui-ci (pour le séparateur — voir
    # chat.services.annoter_separateurs_jour) : capturé avant la création,
    # sinon la nouvelle ligne se retrouverait à comparer à elle-même.
    message_precedent = conversation.messages.order_by('-date_envoi').first()
    jour_precedent = (
        timezone.localtime(message_precedent.date_envoi).date() if message_precedent else None
    )

    message = Message.objects.create(
        conversation=conversation,
        auteur=request.user,
        auteur_nom=request.user.get_full_name(),
        auteur_role=request.user.role,
        type_message=type_message if fichier else 'texte',
        contenu=contenu,
        fichier=fichier or None,
        nom_fichier_original=fichier.name if fichier else '',
        taille_fichier_octets=fichier.size if fichier else None,
    )

    # L'expéditeur a par définition déjà "lu" son propre message.
    marquer_comme_lu(conversation, request.user)

    annoter_separateurs_jour([message], jour_precedent=jour_precedent)
    html = render_to_string('chat/_message_bubbles.html', {
        'messages': [message],
        'user': request.user,
        'groupe_id': conversation.groupe_id,
    }, request=request)
    return JsonResponse({'html': html, 'id': message.id})


@role_required(*ROLES_AVEC_CHAT)
@require_POST
def chat_marquer_lu(request, groupe_id):
    """Marque la conversation comme lue pour l'utilisateur courant (Point 15) —
    appelée à l'ouverture d'une conversation et périodiquement pendant
    qu'elle reste affichée à l'écran."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur
    marquer_comme_lu(conversation, request.user)
    return JsonResponse({'ok': True})


@role_required(*ROLES_AVEC_CHAT)
@require_GET
def chat_fichier(request, groupe_id, message_id):
    """Accès sécurisé à une pièce jointe/audio (Point 23/24/28) : l'URL réelle
    du fichier (Cloudinary en prod, /media/ en dev) n'est JAMAIS imprimée
    directement dans un template chat — seule cette vue, après vérification
    can_access_conversation, redirige vers le fichier. Un utilisateur sans
    accès à la conversation ne peut donc pas récupérer le fichier même en
    devinant/rejouant cette URL (id de message d'une AUTRE conversation ->
    403, jamais l'URL réelle du fichier)."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    message = get_object_or_404(Message, id=message_id, conversation=conversation)
    if not message.fichier:
        return HttpResponseBadRequest('لا يوجد ملف مرفق بهذه الرسالة.')
    return redirect(message.fichier.url)
