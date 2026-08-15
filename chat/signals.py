from django.db.models.signals import post_save, post_delete
from django.dispatch import receiver

from courses.models import Groupe
from .models import Conversation, Message


@receiver(post_save, sender=Groupe)
def creer_conversation_pour_nouveau_groupe(sender, instance, created, **kwargs):
    """Crée automatiquement le salon de discussion du groupe — Point 2 du
    cahier des charges : "L'utilisateur ne doit jamais avoir à créer
    manuellement le chat." Ne s'exécute qu'à la CRÉATION (created=True), jamais
    à chaque sauvegarde ultérieure du groupe (modification, archivage...).

    get_or_create (et non .create() direct) : filet de sécurité si ce signal
    était un jour appelé deux fois pour le même groupe (ex: fixture/migration
    de données rejouée) — la contrainte UNIQUE sur Conversation.groupe
    (OneToOneField) empêche de toute façon tout doublon réel en base, même en
    cas d'accès concurrents ; un seul Groupe ne peut être créé qu'une fois
    (Groupe.objects.create() est un unique INSERT atomique dans
    courses.views.groupe_ajouter), donc ce signal ne peut pas être déclenché
    deux fois en parallèle pour la même ligne."""
    if created:
        Conversation.objects.get_or_create(groupe=instance)


@receiver(post_delete, sender=Message)
def supprimer_fichier_a_la_suppression(sender, instance, **kwargs):
    """Nettoie le fichier physique (pièce jointe/audio) quand un Message est
    supprimé — même patron que payments.signals.supprimer_justificatif_a_la_suppression
    (post_delete, save=False car la ligne est déjà supprimée à ce stade).
    Se déclenche pour TOUTE suppression, y compris la purge en masse
    (chat.services.purger_messages_expires : QuerySet.delete() envoie bien
    pre_delete/post_delete pour chaque ligne concernée, contrairement à
    .update()) — aucun fichier orphelin ne doit rester sur le storage
    (Cloudinary en prod, disque en dev) après une purge automatique."""
    if instance.fichier:
        instance.fichier.delete(save=False)
