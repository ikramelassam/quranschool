"""Middlewares propres au projet core."""

from django.conf import settings
from django.utils.deprecation import MiddlewareMixin


class LangueParDefautArabeMiddleware(MiddlewareMixin):
    """Force l'arabe pour tout visiteur qui n'a pas encore choisi de langue.

    Rappel du fonctionnement de Django (LocaleMiddleware -> get_language_from_request) :
    la langue de la requête est déterminée dans cet ordre
        1. cookie ``settings.LANGUAGE_COOKIE_NAME`` (posé par la vue set_language,
           c'est-à-dire par le sélecteur de langue du site) ;
        2. en-tête ``Accept-Language`` du navigateur/téléphone ;
        3. ``settings.LANGUAGE_CODE`` (ici ``'ar'``).

    On veut supprimer l'étape 2 : la langue du téléphone de l'utilisateur ne doit
    JAMAIS décider à sa place. Tant qu'aucun cookie de langue n'est présent (donc
    tant que l'utilisateur n'a pas cliqué dans le sélecteur), on vide l'en-tête
    ``Accept-Language`` de la requête -> Django retombe directement sur l'étape 3,
    l'arabe.

    Dès que l'utilisateur choisit une langue via le sélecteur, la vue
    ``set_language`` de Django pose le cookie ``LANGUAGE_COOKIE_NAME`` (durée
    ``settings.LANGUAGE_COOKIE_AGE``, voir core/settings.py) : à partir de là ce
    middleware ne touche plus rien et le choix est respecté à chaque visite.

    DOIT être placé AVANT ``django.middleware.locale.LocaleMiddleware`` dans
    ``MIDDLEWARE`` (il modifie ``request.META`` que LocaleMiddleware lira ensuite).
    """

    def process_request(self, request):
        if settings.LANGUAGE_COOKIE_NAME not in request.COOKIES:
            request.META['HTTP_ACCEPT_LANGUAGE'] = ''
