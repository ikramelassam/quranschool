"""Stockage Cloudinary dédié aux pièces jointes du chat interne (chat.models.
Message.fichier — documents ET vocaux, les deux partagent ce même champ).

Chantier "fix accès public aux fichiers du chat (Cloudinary 401)" du
2026-08-27 : depuis avril 2024, Cloudinary applique access_mode='authenticated'
par défaut à toute NOUVELLE ressource resource_type='raw' (PDF, docs, audio...),
même sans configuration explicite côté compte — confirmé sur ce projet en
interrogeant le compte Cloudinary réel (Admin API), voir le rapport de ce
chantier. Le storage global du projet (core.settings.STORAGES['default'] =
cloudinary_storage.storage.RawMediaCloudinaryStorage NU, utilisé par tous les
AUTRES FileField/ImageField : photos de groupe, audio de candidature prof,
screenshots de paiement...) ne force AUCUNE valeur pour access_mode — chaque
nouvelle pièce jointe de chat devenait donc inaccessible (401) via son URL
directe, cassant le lien servi par chat.views.chat_fichier (redirection pour
un document, requests.get() interne pour un vocal — les deux échouent
pareillement sur une ressource access_mode='authenticated').

Décision produit EXPLICITE (2026-08-27) : tous les fichiers échangés dans ce
chat sont non-sensibles, donc TOUJOURS access_mode='public'. L'accès reste
néanmoins contrôlé au niveau applicatif : chat.views.chat_fichier vérifie déjà
can_access_conversation avant de révéler l'URL réelle à qui que ce soit (voir
sa docstring) — access_mode='public' rend seulement l'URL elle-même
utilisable une fois obtenue, il ne dispense jamais de cette vérification.

Scope volontairement LIMITÉ à ce SEUL champ (storage DÉDIÉ, jamais un
changement du storage global partagé par tout le projet) — voir
storage_pieces_jointes_chat() ci-dessous. Les autres usages de Cloudinary
partagent potentiellement le même bug de fond (même resource_type='raw' par
défaut, voir core.settings) mais ne sont PAS concernés par ce chantier : à
signaler séparément si confirmé, jamais corrigé ici sans confirmation
explicite (voir rapport)."""
import os

import cloudinary.uploader
from cloudinary_storage.storage import RawMediaCloudinaryStorage


class ChatAttachmentStorage(RawMediaCloudinaryStorage):
    """Identique à RawMediaCloudinaryStorage (même RESOURCE_TYPE='raw', même
    TAG par défaut, même schéma de nommage/dossier) — seule différence :
    _upload() force type='upload' et access_mode='public' à CHAQUE upload,
    jamais laissé au défaut du compte Cloudinary (voir docstring du module).
    Ne touche à rien d'autre (delete/url/exists/size... hérités tels quels)."""

    def _upload(self, name, content):
        options = {
            'use_filename': True,
            'resource_type': self._get_resource_type(name),
            'tags': self.TAG,
            'type': 'upload',
            'access_mode': 'public',
        }
        folder = os.path.dirname(name)
        if folder:
            options['folder'] = folder
        return cloudinary.uploader.upload(content, **options)


def storage_pieces_jointes_chat():
    """Storage à utiliser pour chat.models.Message.fichier — un CALLABLE (pas
    une instance figée à l'import), supporté par Django FileField(storage=...)
    depuis Django 4.2, évalué au chargement du modèle. Reproduit EXACTEMENT le
    même repli conditionnel que core.settings.STORAGES['default'] (stockage
    local tant que CLOUDINARY_CLOUD_NAME n'est pas fourni — dev/tests sans
    identifiants réels) : ChatAttachmentStorage n'est utilisé QUE quand
    Cloudinary est réellement configuré, jamais un changement de comportement
    dans un environnement qui ne l'a pas — voir le commentaire équivalent dans
    settings.py pour la même règle appliquée au storage global."""
    from django.conf import settings

    if getattr(settings, 'CLOUDINARY_CLOUD_NAME', ''):
        return ChatAttachmentStorage()
    from django.core.files.storage import default_storage
    return default_storage
