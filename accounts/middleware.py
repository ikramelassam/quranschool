from django.conf import settings
from django.shortcuts import redirect


class ForcerChangementMotDePasseMiddleware:
    """Redirige tout utilisateur connecté ayant encore doit_changer_mot_de_passe=True
    vers la page de changement de mot de passe, avant qu'il puisse accéder à quoi
    que ce soit d'autre sur le site (voir dashboard.views.MOT_DE_PASSE_TEMPORAIRE)."""

    CHEMINS_EXEMPTES = ('/accounts/mot-de-passe/', '/accounts/logout/')
    PREFIXES_EXEMPTES = ('/static/', settings.MEDIA_URL, '/admin/')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and getattr(user, 'doit_changer_mot_de_passe', False)
            and request.path not in self.CHEMINS_EXEMPTES
            and not request.path.startswith(self.PREFIXES_EXEMPTES)
        ):
            return redirect('password_change')
        return self.get_response(request)
