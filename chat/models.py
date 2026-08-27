from django.conf import settings
from django.db import models

from .storage import storage_pieces_jointes_chat


class Conversation(models.Model):
    """Salon de discussion d'UN groupe — relation 1:1 stricte avec courses.Groupe
    (OneToOneField = contrainte UNIQUE en base, garantit qu'un groupe ne peut
    jamais avoir 2 conversations, même en cas de double requête/action
    concurrente — voir chat.signals.creer_conversation_pour_nouveau_groupe,
    qui la crée automatiquement à la création du Groupe).

    Aucune table de participants ici volontairement (voir chat.permissions) :
    qui a accès à cette conversation se déduit TOUJOURS en direct de l'état
    actuel du groupe (groupe.prof, groupe.eleves.all(), groupe.prof.superviseurs)
    plutôt que d'une 2e source de vérité qui risquerait de devenir incohérente
    avec la vraie composition du groupe (départ/arrivée d'élève, changement de
    prof/مؤطر) — exactement la règle métier demandée : les permissions suivent
    l'état actuel, pas un instantané figé à la création."""
    groupe = models.OneToOneField(
        'courses.Groupe',
        on_delete=models.CASCADE,
        related_name='conversation',
    )
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"محادثة {self.groupe.nom}"

    class Meta:
        verbose_name = "Conversation"
        verbose_name_plural = "Conversations"


class Message(models.Model):
    """Un message dans le salon d'un groupe — texte, audio ou pièce jointe.

    auteur en SET_NULL (pas CASCADE) : si le compte de l'expéditeur est un jour
    supprimé définitivement (chantier du 2026-08-12, toujours possible pour
    مدير/مشرف), le message ne doit pas disparaître avec lui — l'historique du
    GROUPE doit survivre au départ d'un membre (règle métier explicite). auteur_nom
    et auteur_role sont donc un INSTANTANÉ figé au moment de l'envoi (jamais
    recalculés) : l'identité affichée reste celle de la personne au moment où
    elle a écrit, même si elle quitte le groupe, change de rôle ou est supprimée
    ensuite — même logique que BilanMensuel.prof (courses.models) qui garde son
    contenu même auteur détaché. auteur_role ne sert JAMAIS à revérifier une
    permission (seul chat.permissions fait foi pour l'accès), uniquement à
    afficher le bon libellé de rôle sous le nom (ex: "الأستاذ")."""
    TYPE_CHOICES = [
        ('texte', 'نص'),
        ('audio', 'رسالة صوتية'),
        ('fichier', 'ملف مرفق'),
    ]
    ROLE_LABELS = {
        'eleve': 'التلميذ',
        'prof': 'الأستاذ',
        'superviseur': 'المؤطر',
        'admin': 'المدير',
    }

    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='messages',
    )
    auteur = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='+',
    )
    auteur_nom = models.CharField(max_length=150, blank=True, default='')
    auteur_role = models.CharField(max_length=20, blank=True, default='')

    type_message = models.CharField(max_length=10, choices=TYPE_CHOICES, default='texte')
    contenu = models.TextField(blank=True)
    # storage dédié (chat.storage.storage_pieces_jointes_chat) depuis le
    # Chantier "fix accès public aux fichiers du chat (Cloudinary 401)" du
    # 2026-08-27 — force access_mode='public' à l'upload, contrairement au
    # storage global du projet (voir sa docstring pour le détail complet).
    fichier = models.FileField(
        upload_to='chat_attachments/%Y/%m/', storage=storage_pieces_jointes_chat, null=True, blank=True,
    )
    nom_fichier_original = models.CharField(max_length=255, blank=True, default='')
    taille_fichier_octets = models.PositiveIntegerField(null=True, blank=True)
    # Suppression "douce" façon WhatsApp (Tâche du 2026-08-17) : la ligne
    # RESTE en base (position chronologique/séparateur de jour inchangés,
    # cohérent avec le reste du module qui n'a jamais de "trous" dans le fil)
    # — seul le CONTENU est effacé (contenu/fichier/nom_fichier_original/
    # taille_fichier_octets, voir chat.views.chat_supprimer_message) et un
    # placeholder "message supprimé" est affiché à la place (voir
    # templates/chat/_message_bubbles.html). Différent de la purge de
    # rétention (chat.services.purger_messages_expires) qui, elle, fait une
    # VRAIE suppression de la ligne — deux mécanismes distincts, l'un
    # n'empêche pas l'autre (un message "supprimé" par son auteur reste
    # purgé normalement après le délai de rétention, comme n'importe quel
    # autre message).
    est_supprime = models.BooleanField(default=False)

    date_envoi = models.DateTimeField(auto_now_add=True)

    @property
    def auteur_role_label(self):
        return self.ROLE_LABELS.get(self.auteur_role, '')

    def __str__(self):
        return f"{self.auteur_nom} — {self.conversation} ({self.date_envoi:%Y-%m-%d %H:%M})"

    class Meta:
        ordering = ['date_envoi']
        verbose_name = "Message"
        verbose_name_plural = "Messages"
        indexes = [
            # Couvre les 2 requêtes les plus fréquentes : "derniers messages d'une
            # conversation" (liste + panneau, ORDER BY date_envoi DESC/ASC filtré
            # par conversation) et "messages après/avant tel id" (polling +
            # pagination remontante) — les deux filtrent TOUJOURS par conversation
            # puis trient par date_envoi.
            models.Index(fields=['conversation', 'date_envoi'], name='chat_msg_conv_date_idx'),
            # Purge (chat.services.purger_messages_expires) : WHERE date_envoi < seuil
            # sur TOUTE la table, sans filtre par conversation — index séparé.
            models.Index(fields=['date_envoi'], name='chat_msg_date_idx'),
        ]


class LectureConversation(models.Model):
    """Marque jusqu'où CET utilisateur a lu CETTE conversation — la seule donnée
    qui ne peut pas se déduire de l'état actuel du groupe (contrairement à
    l'accès lui-même, voir Conversation.__doc__), donc légitimement une table à
    part (Point 26 du cahier des charges : ne pas dupliquer une source de
    vérité déjà déductible, mais ceci n'en est pas une)."""
    conversation = models.ForeignKey(
        Conversation,
        on_delete=models.CASCADE,
        related_name='lectures',
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name='+',
    )
    date_derniere_lecture = models.DateTimeField(null=True, blank=True)

    class Meta:
        unique_together = ('conversation', 'user')
        verbose_name = "Lecture de conversation"
        verbose_name_plural = "Lectures de conversation"

    def __str__(self):
        return f"{self.user} — {self.conversation}"


class ConfigurationChat(models.Model):
    """Réglage global (singleton, même patron que accounts.get_visibilite_prof/
    get_charte/get_programme_general) : durée de conservation des messages,
    modifiable UNIQUEMENT par le مدير (Point 12 du cahier des charges — "durée
    configurable par le directeur"). Purgée par chat.services.purger_messages_expires,
    appelée par la commande de gestion `purge_messages_chat` ET en filet de
    sécurité opportuniste depuis chat.views (voir sa docstring)."""
    duree_retention_jours = models.PositiveIntegerField(default=7)
    derniere_modification_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "إعدادات الاحتفاظ برسائل الدردشة"

    class Meta:
        verbose_name = "Configuration du chat"
        verbose_name_plural = "Configuration du chat"


def get_configuration_chat():
    """Renvoie l'unique instance de ConfigurationChat, en la créant (valeur par
    défaut 7 jours) si elle n'existe pas encore — même patron singleton que
    accounts.models.get_visibilite_prof()."""
    config, _ = ConfigurationChat.objects.get_or_create(pk=1)
    return config
