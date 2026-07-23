import mimetypes

from django.templatetags.static import static


def logo_context(request):
    """Injecte logo_url/logo_mime_type dans TOUS les templates (pages publiques
    incluses : login, inscriptions) — logo personnalisé du المشرف s'il existe
    (accounts.models.LogoConfig), sinon le logo statique par défaut du projet.
    logo_mime_type sert au favicon dynamique (le type dépend du format uploadé,
    contrairement au 'image/jpeg' auparavant en dur pour le seul logo_nouveau.jpeg)."""
    from .models import get_logo_config

    config = get_logo_config()
    if config.logo:
        logo_url = config.logo.url
        mime_type, _ = mimetypes.guess_type(config.logo.name)
        logo_mime_type = mime_type or 'image/jpeg'
    else:
        logo_url = static('images/logo_nouveau.jpeg')
        logo_mime_type = 'image/jpeg'

    return {'logo_url': logo_url, 'logo_mime_type': logo_mime_type}
