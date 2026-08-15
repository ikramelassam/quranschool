from .services import annonces_non_lues_pour_eleve


def annonces_badge_context(request):
    """Injecte le badge d'annonces non lues dans tous les templates — même
    patron que chat.context_processors.chat_badge_context (déjà enregistré
    globalement). Uniquement pour role='eleve' : ce sont les seuls
    destinataires d'annonces dans ce chantier (Chantier du 2026-08-15)."""
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or user.role != 'eleve':
        return {}

    from accounts.models import Eleve
    try:
        eleve = Eleve.objects.select_related('inscription').get(user=user)
    except Eleve.DoesNotExist:
        return {}
    return {'annonces_non_lues_total': annonces_non_lues_pour_eleve(eleve, user)}
