from django.db.models.signals import post_delete
from django.dispatch import receiver

from .models import Paiement


@receiver(post_delete, sender=Paiement)
def supprimer_justificatif_a_la_suppression(sender, instance, **kwargs):
    """Nettoie le fichier physique du justificatif (screenshot) quand un
    Paiement est supprimé — Django ne le fait JAMAIS automatiquement par
    défaut : supprimer une ligne qui référence un FileField/ImageField laisse
    le fichier orphelin sur le storage (Cloudinary en prod, disque en dev)
    pour toujours. Se déclenche pour TOUTE suppression de Paiement, qu'elle
    soit directe (ex: depuis /admin/) ou en cascade depuis
    dashboard.views.eleve_supprimer_definitivement (Paiement.eleve =
    CASCADE) — même patron post_delete que accounts.signals, qui gère déjà
    le même genre d'effet de bord pour les inscriptions à la suppression
    d'un Eleve/Prof.

    Suppression réellement demandée par le client (Tâche du 2026-08-12,
    chantier suppression définitive) : le screenshot n'est pas seulement
    détaché de la base, il doit disparaître pour de vrai du stockage — pas
    de fichier orphelin qui traîne indéfiniment.

    save=False : la ligne Paiement est déjà supprimée à ce stade (post_delete),
    il n'y a plus rien à sauvegarder — seul l'appel au storage.delete() sous-
    jacent nous intéresse ici."""
    if instance.screenshot:
        instance.screenshot.delete(save=False)
