from django.conf import settings
from django.contrib import messages
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
    nécessiter de migration de données sur les lignes existantes.

    BUG CORRIGÉ (Tâche du 2026-08-06, "chantier groupé final", point 1) :
    un مدير/مشرف dont le PROPRE compte a encore doit_changer_mot_de_passe=True
    (ex: après un "mot de passe oublié" sur son propre compte, qui pose ce
    champ à True pour ce rôle — voir accounts.views.mot_de_passe_oublie)
    se faisait rediriger SILENCIEUSEMENT loin de N'IMPORTE QUELLE action
    admin en cours — y compris un POST de réinitialisation du mot de passe
    d'UN AUTRE compte (élève/prof/مؤطر) : le POST n'atteignait jamais la vue,
    donc aucune réinitialisation n'avait lieu, mais l'admin/مشرف ne voyait
    qu'un changement d'écran vers "تغيير كلمة المرور" sans aucun message
    d'erreur — pouvant facilement être interprété à tort comme "l'action a
    réussi, je continue autre chose", laissant croire qu'un nouveau mot de
    passe avait été généré pour l'autre compte alors qu'il ne l'a jamais été.
    Le message ci-dessous rend ce blocage explicite et visible plutôt que
    silencieux ; il ne change PAS le comportement (le blocage lui-même reste
    volontaire), seulement sa lisibilité pour l'utilisateur redirigé."""

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
            messages.warning(
                request,
                'يجب عليك تغيير كلمة مرورك أولاً قبل القيام بأي إجراء آخر — '
                'الإجراء الذي حاولت القيام به لم يُنفَّذ.'
            )
            return redirect('password_change')
        return self.get_response(request)
