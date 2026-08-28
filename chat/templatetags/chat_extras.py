from django import template
from django.utils import timezone
from django.utils.translation import gettext as _

register = template.Library()


@register.filter
def abrege_badge(nombre):
    """9 -> '9', 10 -> '9+' — même convention que WhatsApp/Messenger pour un
    badge qui doit rester compact dans la sidebar (Point 15)."""
    try:
        nombre = int(nombre)
    except (TypeError, ValueError):
        return ''
    if nombre <= 0:
        return ''
    return '9+' if nombre > 9 else str(nombre)


@register.filter
def heure_message(date_envoi):
    """Heure courte (HH:MM) affichée sous chaque bulle de message."""
    if not date_envoi:
        return ''
    return timezone.localtime(date_envoi).strftime('%H:%M')


@register.filter
def repere_jour_message(jour):
    """Libellé d'un séparateur de jour : "اليوم" / "أمس" / date complète — même
    esprit que dashboard.templatetags.libelles_arabes.jours_depuis, mais
    formulé pour un repère de conversation plutôt qu'une ancienneté relative
    continue. Prend un objet date() déjà résolu (pas un datetime) : le jour
    en heure locale est calculé UNE SEULE FOIS par message, côté serveur,
    par chat.services.annoter_separateurs_jour — pas ici à chaque rendu."""
    if not jour:
        return ''
    aujourdhui = timezone.localdate()
    difference = (aujourdhui - jour).days
    if difference == 0:
        return _('اليوم')
    if difference == 1:
        return _('أمس')
    return jour.strftime('%Y-%m-%d')


@register.filter
def nom_categorie_chat(code_categorie):
    """Libellé court d'un Groupe.categorie pour l'affichage dans le chat (ex:
    'femmes_adultes' -> 'النساء') — Chantier catégorisation du 2026-08-18.
    Réutilise annonces.services.canal_pour_code, jamais une 2e table de
    correspondance (même source que chat.services.
    repartition_conversations_par_categorie). Duplication volontaire du
    FILTRE lui-même par rapport à annonces_extras.canal_nom — même principe
    déjà établi dans ce fichier pour taille_lisible ci-dessous (apps de
    templatetags indépendantes) — mais PAS de son comportement : canal_nom
    renvoie le code tel quel si inconnu (utile pour Annonce.cible, jamais
    vide) alors qu'ici une categorie vide est un cas normal et attendu (voir
    Groupe.categorie.__doc__, "groupes sans catégorie") -> "غير مصنف", pas
    une chaîne vide qui laisserait un badge illisible."""
    from annonces.services import canal_pour_code
    canal = canal_pour_code(code_categorie)
    return canal['nom'] if canal else _('غير مصنف')


@register.filter
def taille_lisible(taille_octets):
    """1536 -> '1.5 ك.ب', 3_145_728 -> '3.0 م.ب' — pour la carte de pièce jointe."""
    if not taille_octets:
        return ''
    taille_octets = float(taille_octets)
    if taille_octets < 1024:
        return _('%(n)d بايت') % {'n': int(taille_octets)}
    if taille_octets < 1024 * 1024:
        return _('%(n).1f ك.ب') % {'n': taille_octets / 1024}
    return _('%(n).1f م.ب') % {'n': taille_octets / (1024 * 1024)}
