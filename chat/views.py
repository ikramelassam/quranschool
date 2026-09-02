from django.http import (
    FileResponse, HttpResponse, HttpResponseBadRequest, HttpResponseForbidden, JsonResponse,
)
from django.shortcuts import render, get_object_or_404
from django.template.loader import render_to_string
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from accounts.decorators import role_required
from courses.utils import valider_photo_groupe
from .models import Conversation, Message
from .permissions import can_access_conversation, participants_conversation, peut_modifier_photo_groupe
from .services import (
    annoter_separateurs_jour, content_type_audio, conversations_avec_apercu,
    filtrer_conversations_par_categorie_et_recherche, jour_du_message, marquer_comme_lu,
    purge_opportuniste, repartition_conversations_par_categorie, valider_piece_jointe,
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
    rechargé en AJAX.

    Clé 'messages_conversation' (PAS 'messages' — correctif du 2026-08-16,
    bug CRITIQUE trouvé par script de vérification) : ce contexte est fusionné
    tel quel dans celui de chat_conversation, qui rend chat/chat.html — donc
    un template de base (base_admin.html etc.) COMPLET, lequel inclut
    dashboard/_messages.html juste avant {% block content %}.
    django.contrib.messages.context_processors.messages injecte DÉJÀ une
    variable de contexte nommée 'messages' (les messages flash Django) dans
    CHAQUE rendu de template — une clé 'messages' ici l'écrasait silencieusement
    avec la liste des Message du chat, faisant boucler _messages.html sur ces
    objets et afficher {{ message }} (donc str(Message), ex: "Auteur —
    محادثة Nom du groupe (date)") dans une bannière Bootstrap .alert en haut
    de CHAQUE page /chat/<id>/ — le "toast" signalé, un par message affiché,
    à chaque chargement/rechargement complet de la page. templates/chat/
    _panel.html (seul autre consommateur de ce dict) a été mis à jour en
    conséquence."""
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
        'messages_conversation': messages_recents,
        'a_plus_ancien': len(messages_recents) == NB_MESSAGES_PAR_PAGE,
        'participants': participants_conversation(conversation),
        'user': request.user,
        # Contrôle l'affichage de l'avatar comme cliquable + la modale de
        # changement de photo (Tâche du 2026-08-17) — voir
        # chat.permissions.peut_modifier_photo_groupe pour le détail des
        # rôles autorisés. Confort d'affichage UNIQUEMENT : la vue
        # chat_modifier_photo_groupe revérifie ce même droit côté serveur.
        'peut_modifier_photo': peut_modifier_photo_groupe(request.user, conversation.groupe),
    }


def _contexte_liste_categorisee(request):
    """Contexte commun 'onglets de catégorie + recherche' (Chantier
    catégorisation du 2026-08-18) pour chat_liste ET chat_conversation — les
    2 rendent le même chat/chat.html, donc les 2 doivent poser les mêmes
    onglets dans l'en-tête de la colonne liste (sinon ils disparaîtraient en
    ouvrant une conversation par lien direct, ex: la nouvelle icône 💬 posée
    sur un groupe — incohérent avec chat_liste). ?categorie=/?q= : même
    convention que courses.views.groupes_list (lien partageable/rechargeable).

    UN SEUL appel à conversations_avec_apercu : la répartition par catégorie
    (compteurs des onglets) porte TOUJOURS sur la liste complète, le filtrage
    affiché sur son résultat — jamais 2 requêtes pour ces 2 besoins, voir les
    docstrings de chat.services."""
    categorie = request.GET.get('categorie', '')
    q = request.GET.get('q', '').strip()
    toutes_conversations = conversations_avec_apercu(request.user)
    conversations = filtrer_conversations_par_categorie_et_recherche(toutes_conversations, categorie, q)
    return {
        'conversations': conversations,
        'categories_chat': repartition_conversations_par_categorie(toutes_conversations),
        'filtre_categorie': categorie,
        'filtre_recherche': q,
        'filtres_actifs': bool(categorie or q),
    }


@role_required(*ROLES_AVEC_CHAT)
def chat_liste(request):
    """Page d'accueil du chat (Point 19/20) : panneau des conversations à
    gauche, aucune conversation ouverte à droite (état vide) — desktop et
    mobile partagent le même template, la bascule liste/conversation sur
    mobile est purement CSS (voir templates/chat/chat.html)."""
    purge_opportuniste()
    contexte = _contexte_liste_categorisee(request)
    contexte.update({
        'conversation_ouverte': None,
        'base_template': _base_template(request),
    })
    return render(request, 'chat/chat.html', contexte)


@role_required(*ROLES_AVEC_CHAT)
def chat_conversation(request, groupe_id):
    """Lien direct vers UNE conversation (Point 20 : URL partageable/rechargeable) —
    même gabarit que chat_liste, avec la conversation demandée déjà ouverte et
    ses derniers messages pré-rendus côté serveur (pas d'aller-retour AJAX
    supplémentaire au premier chargement). C'est cette URL, /chat/<groupe_id>/,
    que réutilise directement la nouvelle icône 💬 posée sur un groupe
    (Chantier icône-chat du 2026-08-18) : aucune nouvelle vue nécessaire."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    marquer_comme_lu(conversation, request.user)
    contexte = _contexte_liste_categorisee(request)
    contexte.update({
        'conversation_ouverte': conversation,
        'base_template': _base_template(request),
    })
    contexte.update(_contexte_messages_initiaux(conversation, request))
    return render(request, 'chat/chat.html', contexte)


@role_required(*ROLES_AVEC_CHAT)
@require_GET
def chat_liste_partial(request):
    """Fragment HTML de la liste des conversations — utilisé par le polling
    du panneau de gauche pour rafraîchir aperçus/badges de non-lus sans
    recharger la page ni les messages ouverts (Point 15/17). Honore les mêmes
    ?categorie=/?q= que chat_liste (Chantier catégorisation du 2026-08-18) :
    le JS de chat.html les rajoute à CHAQUE appel de rafraichirListe() (poll
    10s inclus), sinon le filtre actif se réinitialiserait tout seul au
    premier polling après un clic sur un onglet ou une recherche."""
    categorie = request.GET.get('categorie', '')
    q = request.GET.get('q', '').strip()
    toutes_conversations = conversations_avec_apercu(request.user)
    conversations = filtrer_conversations_par_categorie_et_recherche(toutes_conversations, categorie, q)
    groupe_ouvert_id = request.GET.get('ouverte')
    html = render_to_string('chat/_conversation_liste.html', {
        'conversations': conversations,
        'groupe_ouvert_id': int(groupe_ouvert_id) if groupe_ouvert_id and groupe_ouvert_id.isdigit() else None,
        'filtres_actifs': bool(categorie or q),
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
    can_access_conversation, y donne accès. Un utilisateur sans accès à la
    conversation ne peut donc pas récupérer le fichier même en devinant/
    rejouant cette URL (id de message d'une AUTRE conversation -> 403,
    jamais l'URL réelle du fichier).

    Depuis le 2026-08-31, un document n'est PLUS redirigé vers l'URL Cloudinary
    (le navigateur quittait le site pour res.cloudinary.com) : il est relayé
    par le serveur via core.media_proxy.servir_fichier_media, exactement comme
    le cartable élève et la حقيبة الأستاذ. ?dl=1 force le téléchargement, sinon
    le fichier s'affiche dans l'onglet quand le navigateur sait le faire (PDF,
    image, texte) et se télécharge sinon (Word/Excel/PowerPoint).

    Un vocal (type_message == 'audio') garde son propre chemin : diagnostiqué
    le 2026-08-17 (bug remonté "aucun lecteur visible, juste l'icône 🎤
    statique") en interrogeant directement le compte Cloudinary réel du projet
    — Cloudinary comme le module `mimetypes` de Python (vérifié en local)
    renvoient tous les deux 'video/webm' comme Content-Type pour un .webm,
    jamais 'audio/webm'. Un <audio> à qui le navigateur annonce un
    Content-Type 'video/*' refuse d'initialiser le moindre lecteur, pour TOUT
    vocal (envoyé ou reçu), en local comme en production. On relaie donc le
    contenu avec le bon Content-Type audio/* (chat.services.content_type_audio,
    déterminé UNIQUEMENT depuis l'extension), jamais la table générique de
    core.media_proxy (qui, elle, mappe .webm -> video/webm, correct pour une
    vidéo mais pas pour un vocal)."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    message = get_object_or_404(Message, id=message_id, conversation=conversation)
    if not message.fichier:
        return HttpResponseBadRequest('لا يوجد ملف مرفق بهذه الرسالة.')

    if message.type_message == 'audio':
        # Juste après l'upload, le fichier vocal peut n'être pas encore servable
        # par le stockage (latence de propagation Cloudinary pour une ressource
        # raw — plusieurs secondes possibles sur l'hébergement actuel).
        # RawMediaCloudinaryStorage._open() lève alors IOError (404) ou une
        # requests.HTTPError : on renvoie un 503 « réessaie bientôt » propre
        # plutôt qu'une 500 non gérée — le client (templates/chat/chat.html,
        # reessayerAudioEnErreur) réessaie automatiquement en approche
        # progressive jusqu'à ce que le fichier soit disponible.
        try:
            flux = message.fichier.open('rb')
        except Exception:
            reponse = HttpResponse(
                'الملف الصوتي غير متاح بعد، جارٍ إعادة المحاولة…', status=503,
            )
            reponse['Retry-After'] = '3'
            return reponse
        return FileResponse(flux, content_type=content_type_audio(message.fichier.name))

    from core.media_proxy import servir_fichier_media
    return servir_fichier_media(
        message.fichier,
        telecharger=request.GET.get('dl') == '1',
        nom_telechargement=message.nom_fichier_original or '',
    )


@role_required(*ROLES_AVEC_CHAT)
@require_POST
def chat_modifier_photo_groupe(request, groupe_id):
    """Raccourci "façon WhatsApp" pour changer la photo d'un groupe DEPUIS
    le chat (Tâche du 2026-08-17) : clic sur l'avatar de l'en-tête → modale
    → ce endpoint. S'ajoute au formulaire de gestion de groupe existant
    (courses.views.groupe_ajouter/groupe_modifier, INCHANGÉ) sans le
    remplacer — les deux écrivent sur le MÊME Groupe.photo, donc peu importe
    par où la photo est changée, elle se reflète partout (liste des groupes,
    fiche groupe, chat...) puisque c'est la même colonne en base.

    peut_modifier_photo_groupe revérifiée ICI côté serveur, jamais une
    confiance dans le fait que l'avatar n'était affiché comme cliquable que
    côté client (voir templates/chat/_panel.html) — un utilisateur qui
    rejoue cette requête sans y avoir droit (ex: élève du groupe) reçoit un
    403, la photo n'est jamais modifiée. valider_photo_groupe (courses.utils,
    déjà utilisée par le formulaire de gestion de groupe) est réutilisée
    telle quelle : même règles (extension + taille + image réellement
    valide via Pillow), une seule fonction de validation pour les 2 points
    d'entrée."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    groupe = conversation.groupe
    if not peut_modifier_photo_groupe(request.user, groupe):
        return HttpResponseForbidden('ليس لديك صلاحية تغيير صورة هذه المجموعة.')

    photo = request.FILES.get('photo')
    if not photo:
        return HttpResponseBadRequest('يجب اختيار صورة.')

    erreur_validation = valider_photo_groupe(photo)
    if erreur_validation:
        return HttpResponseBadRequest(erreur_validation)

    # L'ancienne photo (s'il y en avait une) est supprimée du storage APRÈS
    # la sauvegarde de la nouvelle — jamais avant : si la validation avait
    # échoué (cas déjà écarté ci-dessus) ou si save() levait une exception,
    # l'ancienne photo ne doit jamais disparaître pour rien.
    ancienne_photo = groupe.photo
    groupe.photo = photo
    groupe.save(update_fields=['photo'])
    if ancienne_photo:
        ancienne_photo.delete(save=False)

    avatar_html = render_to_string('chat/_avatar_groupe.html', {'groupe': groupe}, request=request)
    return JsonResponse({'ok': True, 'avatar_html': avatar_html})


@role_required(*ROLES_AVEC_CHAT)
@require_POST
def chat_supprimer_message(request, groupe_id, message_id):
    """Suppression "douce" d'UN message par son propre auteur, façon
    WhatsApp (Tâche du 2026-08-17) : le message reste en base (position
    chronologique/séparateur de jour inchangés) mais son contenu est effacé
    et remplacé par un placeholder (voir Message.est_supprime et
    templates/chat/_message_bubbles.html).

    Vérification STRICTE côté serveur (message.auteur_id ==
    request.user.id) — jamais une confiance dans le fait que le bouton
    Supprimer n'était affiché QUE sur ses propres bulles côté client : un
    utilisateur qui rejoue cette requête pour le message de quelqu'un
    d'autre (même en connaissant son id) reçoit un 403, ce message n'est
    JAMAIS modifié. Idempotent : un message déjà supprimé renvoie le même
    résultat sans rien refaire (un double-clic ou une requête rejouée ne
    doit jamais planter ni écraser une seconde fois un contenu déjà vidé)."""
    conversation, erreur = _conversation_ou_403(request, groupe_id)
    if erreur:
        return erreur

    message = get_object_or_404(Message, id=message_id, conversation=conversation)
    if message.auteur_id != request.user.id:
        return HttpResponseForbidden('لا يمكنك حذف رسالة شخص آخر.')

    if not message.est_supprime:
        if message.fichier:
            message.fichier.delete(save=False)
        message.contenu = ''
        message.fichier = None
        message.nom_fichier_original = ''
        message.taille_fichier_octets = None
        message.est_supprime = True
        message.save()

    html = render_to_string('chat/_message_bubbles.html', {
        'messages': [message],
        'user': request.user,
        'groupe_id': conversation.groupe_id,
    }, request=request)
    return JsonResponse({'html': html, 'id': message.id})
