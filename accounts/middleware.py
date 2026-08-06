from django.conf import settings
from django.shortcuts import redirect


class ForcerChangementMotDePasseMiddleware:
    """Redirige tout utilisateur connecté ayant encore doit_changer_mot_de_passe=True
    vers la page de changement de mot de passe, avant qu'il puisse accéder à quoi
    que ce soit d'autre sur le site (voir dashboard.views.generer_mot_de_passe_temporaire).

    ROLES_EXEMPTES (Points 13/14/17, décision du directeur du 2026-08-05) :
    élève/prof/مؤطر ne passent JAMAIS par ce changement forcé, quelle que
    soit la valeur de doit_changer_mot_de_passe en base — exclusion
    explicite par rôle plutôt que de dépendre uniquement du fait que les
    nouveaux comptes de ces rôles ne mettent plus jamais ce champ à True :
    couvre aussi d'éventuels comptes déjà créés avant ce changement, sans
    nécessiter de migration de données sur les lignes existantes."""

    CHEMINS_EXEMPTES = ('/accounts/mot-de-passe/', '/accounts/logout/')
    PREFIXES_EXEMPTES = ('/static/', settings.MEDIA_URL, '/admin/')
    ROLES_EXEMPTES = ('eleve', 'prof', 'superviseur')

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = request.user
        if (
            user.is_authenticated
            and getattr(user, 'doit_changer_mot_de_passe', False)
            and getattr(user, 'role', None) not in self.ROLES_EXEMPTES
            and request.path not in self.CHEMINS_EXEMPTES
            and not request.path.startswith(self.PREFIXES_EXEMPTES)
        ):
            return redirect('password_change')
        return self.get_response(request)
