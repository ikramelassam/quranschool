from functools import wraps

from django.contrib.auth.decorators import login_required


def role_required(*roles_autorises):
    """Autorise l'accès seulement aux users connectés dont le role est dans roles_autorises.
    Sinon, renvoie l'utilisateur vers SON propre dashboard (pas d'erreur brute)."""
    def decorateur(vue):
        @login_required
        @wraps(vue)
        def vue_protegee(request, *args, **kwargs):
            if request.user.role not in roles_autorises:
                from .views import redirect_by_role
                return redirect_by_role(request.user)
            return vue(request, *args, **kwargs)
        return vue_protegee
    return decorateur
