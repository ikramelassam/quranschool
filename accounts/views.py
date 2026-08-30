from django.shortcuts import render, redirect
from django.contrib.auth import authenticate, login, logout, update_session_auth_hash, get_user_model
from django.contrib.auth.decorators import login_required
from django.contrib import messages
from django.utils.translation import gettext as _

def login_view(request):
    if request.user.is_authenticated:
        return redirect_by_role(request.user)
    
    if request.method == 'POST':
        email = request.POST.get('email')
        password = request.POST.get('password')
        
        user = authenticate(request, username=email, password=password)

        if user is not None:
            # EmailBackend.authenticate() (accounts.backend) valide le mot de passe
            # sans regarder is_active — le check est fait ici, séparément, pour
            # afficher un message clair et distinct plutôt que le message générique
            # "mot de passe incorrect" (voir accounts.services.archiver_eleve/prof,
            # qui met is_active=False à l'archivage — chantier du 2026-08-03).
            if not user.is_active:
                return render(request, 'accounts/login.html', {
                    'error': _('حسابك مؤرشف حالياً، تواصل مع الإدارة.')
                })
            login(request, user)
            return redirect_by_role(user)
        else:
            return render(request, 'accounts/login.html', {
                'error': _('البريد الإلكتروني أو كلمة المرور غير صحيحة')
            })
    
    return render(request, 'accounts/login.html')




def redirect_by_role(user):
    if user.role == 'eleve':
        return redirect('dashboard_eleve')
    elif user.role == 'prof':
        return redirect('dashboard_prof')
    elif user.role == 'superviseur':
        return redirect('dashboard_superviseur')
    elif user.role == 'admin':
        return redirect('dashboard_admin')
    elif user.role == 'mshrif':
        return redirect('dashboard_mshrif')
    return redirect('login')



def logout_view(request):
    logout(request)
    return redirect('login')


# Libellés arabes du rôle pour le message Telegram de mot_de_passe_oublie —
# permet au مدير de savoir immédiatement à qui transmettre le nouveau mot de
# passe, sans avoir à rouvrir la fiche du compte (Tâche du 2026-08-05).
LIBELLES_ROLE_MDP_OUBLIE = {
    'eleve': 'طالب',
    'prof': 'أستاذ',
    'superviseur': 'مؤطر',
}


def _normaliser_nom_pour_comparaison(nom):
    """Espaces superflus réduits à un seul + casse ignorée (casefold, plus robuste
    qu'un simple .lower() pour l'unicode/arabe) — évite qu'un espace en trop ou une
    majuscule empêche une correspondance légitime. Cas réel trouvé en production au
    moment d'écrire cette fonction : un nom de compte contient un double espace
    ('عمران  بقاس') — sans cette normalisation, la comparaison aurait échoué."""
    return ' '.join(nom.split()).casefold()


def mot_de_passe_oublie(request):
    """"نسيت كلمة المرور ؟" (Tâche 22 Partie E du 2026-07-26) — pas d'envoi email
    (Brevo non fiable, voir Partie D) : le mot de passe généré est envoyé au
    مدير via le bot Telegram déjà utilisé pour les notifications d'inscription
    (core.utils.envoyer_notification_telegram), à charge pour lui de le
    transmettre au titulaire du compte. Message affiché identique que l'email
    existe ou non, pour ne jamais révéler quels emails sont enregistrés (et
    identique aussi entre élève/prof/مؤطر et مدير/مشرف, pour ne pas révéler le
    rôle associé à un email).

    Historique : Points 13/14/17 (décision du 2026-08-05) avaient retiré tout
    moyen pour élève/prof/مؤطر de changer leur mot de passe, y compris ce
    mécanisme. Nouvelle décision du même jour : "mot de passe oublié" est
    réactivé pour ces 3 rôles, mais SANS repasser par le self-service classique
    — même principe que la création de compte : mot de passe séquentiel
    (zidanieilmanN@@, generer_mot_de_passe_sequentiel), appliqué immédiatement
    (l'ancien devient invalide), jamais affiché au demandeur, jamais de
    changement forcé à la prochaine connexion (doit_changer_mot_de_passe=False,
    cohérent avec le reste du chantier mots de passe). مدير/مشرف gardent
    exactement leur ancien comportement (mot de passe temporaire aléatoire,
    changement forcé à la prochaine connexion) — flux séparé, inchangé.

    Chantier du 2026-08-10 (partage d'email parent/enfant, voir
    admin_valider_eleve) : un email peut désormais correspondre à PLUSIEURS
    comptes élève. Contrairement à la connexion normale (où le mot de passe
    fourni désambiguïse), "mot de passe oublié" n'a par définition aucun mot
    de passe disponible — un 2e champ "nom complet" a donc été ajouté à CE
    formulaire uniquement (la connexion normale reste à 2 champs, inchangée).
    Comparaison insensible à la casse ET aux espaces superflus (voir
    _normaliser_nom_pour_comparaison). Aucune correspondance exacte email+nom
    -> même message générique que tout autre échec, aucune régénération —
    protection contre l'énumération de comptes, inchangée. S'applique aussi
    à مدير/مشرف (même formulaire unique pour tous les rôles) : sans risque,
    tous les comptes existants ont un nom complet non vide (vérifié)."""
    from core.utils import envoyer_notification_telegram_async
    from dashboard.views import generer_mot_de_passe_temporaire, generer_mot_de_passe_sequentiel

    if request.method == 'POST':
        email = request.POST.get('email', '').strip()
        nom_saisi = request.POST.get('nom_complet', '').strip()
        User = get_user_model()

        user = None
        if email and nom_saisi:
            nom_normalise = _normaliser_nom_pour_comparaison(nom_saisi)
            for candidat in User.objects.filter(email=email):
                if _normaliser_nom_pour_comparaison(candidat.get_full_name()) == nom_normalise:
                    user = candidat
                    break

        if user and user.role in ('eleve', 'prof', 'superviseur'):
            nouveau_mot_de_passe = generer_mot_de_passe_sequentiel()
            user.set_password(nouveau_mot_de_passe)
            user.doit_changer_mot_de_passe = False
            user.save()
            envoyer_notification_telegram_async(
                f'🔑 طلب كلمة مرور جديدة\n'
                f'الحساب: {user.get_full_name()} ({LIBELLES_ROLE_MDP_OUBLIE[user.role]})\n'
                f'البريد: {email}\n'
                f'كلمة المرور الجديدة: {nouveau_mot_de_passe}'
            )
        elif user:
            nouveau_mot_de_passe = generer_mot_de_passe_temporaire()
            user.set_password(nouveau_mot_de_passe)
            user.doit_changer_mot_de_passe = True
            user.save()
            envoyer_notification_telegram_async(
                f'🔑 طلب "نسيت كلمة المرور"\n'
                f'الحساب: {email}\n'
                f'كلمة المرور الجديدة: {nouveau_mot_de_passe}\n'
                f'يرجى تبليغها لصاحب الحساب.'
            )
        messages.success(
            request,
            'إذا كان هذا البريد مسجلاً لدينا، تواصل مع الإدارة للحصول على كلمة المرور الجديدة.'
        )
        # Reste sur la même page (au lieu de rediriger vers login) pour pouvoir
        # proposer tout de suite un contact direct avec le مدير (WhatsApp/email),
        # plutôt que de faire attendre le relais Telegram (Tâche du 2026-07-28).
        admin_principal = User.objects.filter(role='admin').order_by('id').first()
        return render(request, 'accounts/mot_de_passe_oublie.html', {
            'soumis': True,
            'admin_principal': admin_principal,
        })

    return render(request, 'accounts/mot_de_passe_oublie.html')


@login_required
def reinitialiser_mon_mot_de_passe(request):
    """Même mécanisme que mot_de_passe_oublie, pour un utilisateur déjà connecté
    qui veut réinitialiser (Tâche 22 Partie E) — accessible depuis sa page
    profil. Déconnecte immédiatement (l'ancien mot de passe devient invalide)."""
    from core.utils import envoyer_notification_telegram_async
    from dashboard.views import generer_mot_de_passe_temporaire

    # Points 13/14/17 (Tâche du 2026-08-04) : même retrait du self-service
    # que password_change_view — élève/prof/مؤطر ne peuvent plus déclencher
    # eux-mêmes un changement de leur mot de passe, sous aucune forme.
    if request.user.role in ('eleve', 'prof', 'superviseur'):
        messages.info(request, 'لتغيير كلمة المرور، يرجى التواصل مع الإدارة.')
        return redirect_by_role(request.user)

    if request.method == 'POST':
        nouveau_mot_de_passe = generer_mot_de_passe_temporaire()
        email = request.user.email
        request.user.set_password(nouveau_mot_de_passe)
        request.user.doit_changer_mot_de_passe = True
        request.user.save()
        envoyer_notification_telegram_async(
            f'🔑 طلب إعادة تعيين كلمة مرور (من داخل الحساب)\n'
            f'الحساب: {email}\n'
            f'كلمة المرور الجديدة: {nouveau_mot_de_passe}\n'
            f'يرجى تبليغها لصاحب الحساب.'
        )
        logout(request)
        messages.success(
            request,
            _('تم إنشاء كلمة مرور جديدة وإشعار الإدارة بها — تواصل معها للحصول عليها، '
              'ثم سجّل الدخول من جديد.')
        )
        return redirect('login')
    return redirect_by_role(request.user)


@login_required
def modifier_telephone(request):
    """Modifie le téléphone du User connecté — partagé par élève/prof/مؤطر
    (Tâche 11 du 2026-07-25). Vue générique (n'agit que sur request.user),
    comme password_change_view : chaque page profil poste ici avec un champ
    caché 'next' (nom d'URL) pour revenir sur elle-même après sauvegarde."""
    if request.method == 'POST':
        request.user.telephone = request.POST.get('telephone', '').strip()
        request.user.save(update_fields=['telephone'])
        messages.success(request, _('تم تحديث رقم الهاتف بنجاح.'))
        next_url = request.POST.get('next')
        if next_url:
            return redirect(next_url)
    return redirect_by_role(request.user)


BASE_TEMPLATE_PAR_ROLE = {
    'eleve': 'dashboard/base_eleve.html',
    'prof': 'dashboard/base_prof.html',
    'superviseur': 'dashboard/base_superviseur.html',
    'admin': 'dashboard/base_admin.html',
    'mshrif': 'dashboard/base_mshrif.html',
}
COULEUR_PAR_ROLE = {
    'eleve': '#2d5a1b',
    'admin': '#2d5a1b',
    'prof': '#1a3a5c',
    'superviseur': '#6b3a2a',
    'mshrif': '#1A0D00',
}


@login_required
def password_change_view(request):
    changement_force = request.user.doit_changer_mot_de_passe

    # Points 13/14/17 (décision du directeur du 2026-08-05) : élève/prof/مؤطر
    # ne peuvent JAMAIS changer leur mot de passe depuis cette vue — ni en
    # self-service, ni via un changement forcé (le changement forcé lui-même
    # a été retiré pour ces 3 rôles, voir
    # accounts.middleware.ForcerChangementMotDePasseMiddleware.ROLES_EXEMPTES
    # et la création de compte qui ne met plus jamais doit_changer_mot_de_passe
    # à True pour eux). Blocage inconditionnel ici en défense en profondeur,
    # au cas où cette URL serait quand même atteinte directement.
    if request.user.role in ('eleve', 'prof', 'superviseur'):
        messages.info(request, 'لتغيير كلمة المرور، يرجى التواصل مع الإدارة.')
        return redirect_by_role(request.user)

    if request.method == 'POST':
        ancien = request.POST.get('ancien_mot_de_passe')
        nouveau = request.POST.get('nouveau_mot_de_passe')
        confirmation = request.POST.get('confirmation')

        if not request.user.check_password(ancien):
            messages.error(request, 'كلمة المرور الحالية غير صحيحة.')
        elif nouveau != confirmation:
            messages.error(request, 'كلمتا المرور الجديدتان غير متطابقتين.')
        elif len(nouveau) < 8:
            messages.error(request, 'يجب أن تحتوي كلمة المرور الجديدة على 8 أحرف على الأقل.')
        else:
            request.user.set_password(nouveau)
            request.user.doit_changer_mot_de_passe = False
            request.user.save()
            update_session_auth_hash(request, request.user)
            messages.success(request, 'تم تغيير كلمة المرور بنجاح.')
            return redirect_by_role(request.user)

    return render(request, 'accounts/password_change.html', {
        'base_template': BASE_TEMPLATE_PAR_ROLE.get(request.user.role, 'dashboard/base_eleve.html'),
        'couleur': COULEUR_PAR_ROLE.get(request.user.role, '#2d5a1b'),
        'changement_force': changement_force,
    })