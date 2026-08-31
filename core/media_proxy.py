"""Servir un fichier média (Cloudinary en production, disque local en dev)
DEPUIS le domaine du site plutôt que de rediriger le navigateur vers l'URL
brute du stockage (res.cloudinary.com/...).

Besoin exprimé (2026-08-31) : dans le cartable élève, la حقيبة الأستاذ et le
chat interne, un clic sur un fichier faisait quitter le site pour Cloudinary.
On veut que le fichier reste servi par la plateforme — affiché dans l'onglet
quand le navigateur sait le faire (PDF, image, audio, vidéo, texte), téléchargé
sinon (Word/Excel/PowerPoint : aucun navigateur ne les rend nativement).

Chaque vue appelante fait SA propre vérification de permission AVANT d'appeler
servir_fichier_media (cartable : DocumentEleve.pour_eleve ; حقيبة : ciblage
prof/tous ; chat : can_access_conversation) — ce module ne fait QUE relayer le
contenu, il ne décide jamais qui y a droit.

Le relais lit le fichier via FieldFile.open('rb') (côté serveur, comme le fait
déjà chat.views.chat_fichier pour les vocaux depuis le 2026-08-17) : le
navigateur de l'utilisateur ne voit jamais l'URL Cloudinary. Contrepartie
assumée : le trafic fichier transite par le serveur au lieu d'aller directement
au CDN — acceptable pour ce projet (fichiers < 20 Mo, trafic faible)."""
import os

from django.http import FileResponse, Http404

# Extensions que le navigateur affiche/lit nativement dans un onglet — pour
# celles-ci, l'appelant propose "فتح" (inline) en plus de "تحميل". Tout le
# reste (Word/Excel/PowerPoint, archives, formats inconnus) est TOUJOURS servi
# en téléchargement.
EXTENSIONS_AFFICHABLES_NAVIGATEUR = {
    '.pdf',
    '.jpg', '.jpeg', '.png', '.gif', '.webp', '.bmp', '.svg',
    '.txt',
    '.mp3', '.wav', '.ogg', '.oga', '.m4a', '.aac', '.opus',
    '.mp4', '.webm', '.mov', '.m4v',
}

# Content-Type explicite par extension — jamais déduit d'un module de détection
# générique : le stockage Cloudinary annonce par exemple 'video/webm' pour un
# .webm audio, ce qui empêche <audio> de s'initialiser (bug diagnostiqué le
# 2026-08-17, voir chat.services.CONTENT_TYPES_AUDIO — même principe repris ici
# pour tous les types).
CONTENT_TYPES = {
    '.pdf': 'application/pdf',
    '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg', '.png': 'image/png',
    '.gif': 'image/gif', '.webp': 'image/webp', '.bmp': 'image/bmp',
    '.svg': 'image/svg+xml',
    '.txt': 'text/plain; charset=utf-8',
    '.mp3': 'audio/mpeg', '.wav': 'audio/wav', '.ogg': 'audio/ogg',
    '.oga': 'audio/ogg', '.m4a': 'audio/mp4', '.aac': 'audio/aac',
    '.opus': 'audio/opus',
    '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
    '.m4v': 'video/x-m4v',
    '.doc': 'application/msword',
    '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
    '.xls': 'application/vnd.ms-excel',
    '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    '.ppt': 'application/vnd.ms-powerpoint',
    '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
    '.zip': 'application/zip',
}


def _extension(nom_fichier):
    return os.path.splitext(nom_fichier or '')[1].lower()


def est_affichable_navigateur(nom_fichier):
    """True si un navigateur sait afficher/lire ce fichier dans un onglet
    (d'après son extension) — utilisé par les templates pour décider s'ils
    montrent le bouton "فتح" en plus de "تحميل"."""
    return _extension(nom_fichier) in EXTENSIONS_AFFICHABLES_NAVIGATEUR


def content_type_pour(nom_fichier):
    """Content-Type à annoncer pour ce fichier (voir CONTENT_TYPES). Repli sur
    'application/octet-stream' pour une extension inconnue — le navigateur
    téléchargera alors, ce qui est le comportement sûr par défaut."""
    return CONTENT_TYPES.get(_extension(nom_fichier), 'application/octet-stream')


def servir_fichier_media(fieldfile, *, telecharger=False, nom_telechargement=''):
    """Renvoie une FileResponse qui relaie le contenu de `fieldfile` (un
    FieldFile Django) à travers le serveur.

    - telecharger=True  -> Content-Disposition: attachment (téléchargement forcé)
    - telecharger=False -> inline si le navigateur sait afficher ce type,
      attachment sinon.

    nom_telechargement : nom de fichier proposé (ex: le nom d'origine choisi par
    l'utilisateur). À défaut, le basename du fichier stocké.

    Lève Http404 si le champ est vide."""
    if not fieldfile:
        raise Http404('Aucun fichier.')

    nom_stocke = fieldfile.name
    inline = (not telecharger) and est_affichable_navigateur(nom_stocke)

    return FileResponse(
        fieldfile.open('rb'),
        content_type=content_type_pour(nom_stocke),
        as_attachment=not inline,
        filename=_nom_telechargement(nom_telechargement, nom_stocke),
    )


def _nom_telechargement(nom_choisi, nom_stocke):
    """Nom de fichier proposé au navigateur. Part du nom choisi par l'appelant
    (ex: le titre du document) si fourni, sinon du basename stocké — et lui
    recolle l'extension du fichier réel si elle manque (un titre "الحصة
    الأولى" doit se télécharger en "الحصة الأولى.pptx", pas sans extension)."""
    base = (nom_choisi or '').strip() or os.path.basename(nom_stocke)
    extension_reelle = _extension(nom_stocke)
    if extension_reelle and _extension(base) != extension_reelle:
        base += extension_reelle
    return base
