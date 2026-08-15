from django import template
from django.utils import timezone

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
def repere_jour_message(date_envoi):
    """Séparateur de jour au-dessus d'un groupe de messages : "اليوم" / "أمس" /
    date complète — même esprit que dashboard.templatetags.libelles_arabes.
    jours_depuis, mais formulé pour un repère de conversation plutôt qu'une
    ancienneté relative continue."""
    if not date_envoi:
        return ''
    date_locale = timezone.localtime(date_envoi).date()
    aujourdhui = timezone.localdate()
    difference = (aujourdhui - date_locale).days
    if difference == 0:
        return 'اليوم'
    if difference == 1:
        return 'أمس'
    return date_locale.strftime('%Y-%m-%d')


@register.filter
def taille_lisible(taille_octets):
    """1536 -> '1.5 ك.ب', 3_145_728 -> '3.0 م.ب' — pour la carte de pièce jointe."""
    if not taille_octets:
        return ''
    taille_octets = float(taille_octets)
    if taille_octets < 1024:
        return f'{int(taille_octets)} بايت'
    if taille_octets < 1024 * 1024:
        return f'{taille_octets / 1024:.1f} ك.ب'
    return f'{taille_octets / (1024 * 1024):.1f} م.ب'
