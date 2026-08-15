from .services import total_messages_non_lus


def chat_badge_context(request):
    """Injecte le badge de messages non lus dans TOUS les templates (comme
    accounts.context_processors.logo_context, déjà enregistré globalement) —
    permet à chaque base_*.html (admin/prof/eleve/superviseur, jamais mshrif)
    d'afficher le badge dans le lien "الرسائل" de la sidebar sans que chaque
    vue du site n'ait à le calculer explicitement (Point 14/15)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated:
        return {}
    return {'chat_non_lus_total': total_messages_non_lus(user)}
