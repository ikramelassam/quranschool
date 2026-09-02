"""Supprime les fichiers de DÉMONSTRATION que Cloudinary dépose automatiquement
sur tout nouveau compte (dossier `samples/` : paysages, animaux, e-commerce… +
les images racine `cld-sample*`, `main-sample`, `sample`). Ils n'ont jamais été
uploadés par l'application mais comptent dans le quota de stockage du plan Free
(25 crédits/mois) — ~170 Mo sur ce compte, dont 120 Mo de vidéos d'exemple.

Garde-fou ABSOLU : la commande refuse de toucher tout `public_id` commençant par
`media/` (préfixe de tous les FileField/ImageField du projet, voir
core.settings.STORAGES['default'] = RawMediaCloudinaryStorage) ou par
`chat_attachments/` (chat.storage.ChatAttachmentStorage) — seuls les fichiers
HORS de ces deux préfixes sont candidats à la suppression.

DRY-RUN par défaut (liste seulement). Ajouter --apply pour supprimer réellement :

    python manage.py purger_fichiers_demo_cloudinary            # aperçu
    python manage.py purger_fichiers_demo_cloudinary --apply    # suppression

Un seul passage suffit (Cloudinary ne recrée pas ces fichiers). Sans effet en
dev/tests sans Cloudinary configuré (CLOUDINARY_CLOUD_NAME absent).
"""
from django.conf import settings
from django.core.management.base import BaseCommand

# Préfixes appartenant à l'application — jamais supprimés, quoi qu'il arrive.
PREFIXES_APPLICATION = ('media/', 'chat_attachments/')


class Command(BaseCommand):
    help = ("Supprime les fichiers de démo déposés par Cloudinary sur le compte "
            "(dossier samples/, images cld-sample*). DRY-RUN sauf --apply.")

    def add_arguments(self, parser):
        parser.add_argument(
            '--apply', action='store_true',
            help="Supprime réellement (sinon : aperçu seul, rien n'est supprimé).",
        )

    def handle(self, *args, **options):
        if not getattr(settings, 'CLOUDINARY_CLOUD_NAME', ''):
            self.stdout.write("Cloudinary non configuré (CLOUDINARY_CLOUD_NAME absent) — rien à faire.")
            return

        import cloudinary
        import cloudinary.api

        cfg = getattr(settings, 'CLOUDINARY_STORAGE', {})
        cloudinary.config(
            cloud_name=cfg.get('CLOUD_NAME'),
            api_key=cfg.get('API_KEY'),
            api_secret=cfg.get('API_SECRET'),
            secure=True,
        )

        appliquer = options['apply']
        total_fichiers = 0
        total_octets = 0

        for resource_type in ('image', 'video', 'raw'):
            ressources = self._toutes_les_ressources(cloudinary, resource_type)
            demo = [r for r in ressources
                    if not r['public_id'].startswith(PREFIXES_APPLICATION)]
            conserves = len(ressources) - len(demo)
            octets_demo = sum(r.get('bytes', 0) for r in demo)

            self.stdout.write(self.style.MIGRATE_HEADING(f"\nresource_type = {resource_type}"))
            self.stdout.write(f"  application (conservé)  : {conserves} fichier(s)")
            self.stdout.write(f"  démo (à supprimer)      : {len(demo)} fichier(s), "
                              f"{octets_demo / 1024 / 1024:.2f} Mo")
            for r in sorted(demo, key=lambda r: -r.get('bytes', 0)):
                self.stdout.write(f"      {r.get('bytes', 0) / 1024 / 1024:7.2f} Mo  {r['public_id']}")

            total_fichiers += len(demo)
            total_octets += octets_demo

            if appliquer and demo:
                ids = [r['public_id'] for r in demo]
                for lot in (ids[i:i + 100] for i in range(0, len(ids), 100)):
                    reponse = cloudinary.api.delete_resources(
                        lot, resource_type=resource_type, type='upload',
                    )
                    supprimes = sum(1 for v in reponse.get('deleted', {}).values() if v == 'deleted')
                    self.stdout.write(self.style.SUCCESS(
                        f"  >> supprimé(s) ({resource_type}) : {supprimes}/{len(lot)}"))

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\nTOTAL démo : {total_fichiers} fichier(s), {total_octets / 1024 / 1024:.2f} Mo"))

        if not appliquer:
            self.stdout.write(self.style.WARNING(
                "\nDRY-RUN : rien supprimé. Relancer avec --apply pour agir."))
            return

        try:
            cloudinary.api.delete_folder('samples')
            self.stdout.write(self.style.SUCCESS("Dossier 'samples' supprimé."))
        except Exception as e:  # dossier déjà absent ou non vide : non bloquant
            self.stdout.write(self.style.WARNING(f"Dossier 'samples' non supprimé : {e}"))
        self.stdout.write(self.style.SUCCESS("\nSuppression terminée."))

    @staticmethod
    def _toutes_les_ressources(cloudinary, resource_type):
        """Toutes les ressources 'upload' d'un type, en suivant la pagination."""
        ressources = []
        curseur = None
        while True:
            page = cloudinary.api.resources(
                resource_type=resource_type, type='upload',
                max_results=500, next_cursor=curseur,
            )
            ressources.extend(page.get('resources', []))
            curseur = page.get('next_cursor')
            if not curseur:
                break
        return ressources
