from django.core.management.base import BaseCommand

from chat.services import migrer_acces_public_pieces_jointes


class Command(BaseCommand):
    """Bascule access_mode='public' sur Cloudinary pour TOUTES les pièces
    jointes de chat (documents + vocaux) déjà en base AVANT le chantier "fix
    accès public aux fichiers du chat (Cloudinary 401)" du 2026-08-27 — voir
    chat.storage.__doc__ pour le détail complet du bug corrigé. Les NOUVEAUX
    uploads sont déjà corrigés automatiquement (chat.storage.ChatAttachmentStorage),
    cette commande est donc UN SEUL passage rétroactif, pas une tâche
    récurrente à planifier.

    À exécuter une fois, en production, après déploiement de ce chantier :

        python manage.py migrer_acces_public_pieces_jointes_chat

    Sans effet (0 fichier traité) en dev/tests sans Cloudinary configuré —
    voir chat.services.migrer_acces_public_pieces_jointes.__doc__."""
    help = "Bascule access_mode='public' sur Cloudinary pour les pièces jointes de chat déjà en base."

    def handle(self, *args, **options):
        resultat = migrer_acces_public_pieces_jointes()
        self.stdout.write(
            f"{resultat['succes']} sur {resultat['total']} pièce(s) jointe(s) basculée(s) avec succès."
        )
        if resultat['echecs']:
            self.stdout.write(self.style.WARNING(f"{len(resultat['echecs'])} échec(s) :"))
            for message_id, public_id, erreur in resultat['echecs']:
                self.stdout.write(self.style.WARNING(f"  - Message id={message_id} (public_id={public_id!r}) : {erreur}"))
        else:
            self.stdout.write(self.style.SUCCESS("Aucun échec."))
