from django.core.management.base import BaseCommand

from chat.services import purger_messages_expires


class Command(BaseCommand):
    """Supprime les messages de chat plus vieux que la durée de rétention
    configurée (chat.models.ConfigurationChat, 7 jours par défaut, modifiable
    par le مدير) — Point 12/36 du cahier des charges.

    À planifier en tâche périodique côté hébergement (ex: Render Cron Jobs,
    une fois par jour) :

        python manage.py purge_messages_chat

    Un filet de sécurité opportuniste existe déjà côté application
    (chat.services.purge_opportuniste, appelé au plus 1 fois par heure quand
    le chat est consulté) pour que la purge ait lieu même avant qu'une tâche
    planifiée externe ne soit configurée — voir le rapport de ce chantier."""
    help = "Supprime les messages de chat plus vieux que la durée de rétention configurée."

    def handle(self, *args, **options):
        nb_supprimes = purger_messages_expires()
        self.stdout.write(self.style.SUCCESS(
            f'{nb_supprimes} message(s) de chat supprimé(s) (au-delà de la durée de rétention configurée).'
        ))
