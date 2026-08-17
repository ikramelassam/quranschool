"""Contrôle d'accès centralisé du chat (Point 27 du cahier des charges) —
TOUTE vue chat qui touche une conversation précise (page, messages, envoi,
polling, marquage lu, fichier/audio) passe par can_access_conversation ci-
dessous, jamais par une condition recodée localement. Les permissions ne
sont JAMAIS stockées : toujours recalculées depuis l'état ACTUEL des
relations métier existantes (Groupe.prof, Groupe.eleves, Superviseur.
profs_assignes) — un départ/changement de groupe, de prof ou de مؤطر se
répercute donc immédiatement, sans donnée à corriger nulle part.

Rôles avec accès au chat : eleve, prof, superviseur (مؤطر), admin (مدير).
Le مشرف (role='mshrif') n'a JAMAIS accès au chat — aucune fonction ci-dessous
ne le traite, il tombe systématiquement dans le cas "aucun accès"."""
from .models import Conversation


def get_conversations_accessibles(user):
    """Queryset des Conversation auxquelles `user` a accès EN CE MOMENT, selon
    son rôle actuel. Base de toute la sécurité du chat : la liste des
    conversations (chat.views.chat_liste) ET la vérification IDOR par
    conversation individuelle (can_access_conversation ci-dessous)
    l'utilisent TOUTES LES DEUX — aucune 2e logique de filtrage ailleurs."""
    if not user.is_authenticated:
        return Conversation.objects.none()

    if user.role == 'admin':
        # مدير : visibilité globale, volontaire (Point 8) — aucune restriction.
        return Conversation.objects.all()

    if user.role == 'superviseur':
        superviseur = getattr(user, 'superviseur', None)
        if superviseur is None:
            return Conversation.objects.none()
        # Groupes des profs ACTUELLEMENT supervisés — profs_assignes.all() est
        # déjà l'état courant de la M2M, donc un changement de supervision se
        # répercute au prochain appel, sans rien à recalculer explicitement.
        return Conversation.objects.filter(groupe__prof__in=superviseur.profs_assignes.all())

    if user.role == 'prof':
        prof = getattr(user, 'prof', None)
        if prof is None or prof.statut != 'actif':
            return Conversation.objects.none()
        return Conversation.objects.filter(groupe__prof=prof)

    if user.role == 'eleve':
        eleve = getattr(user, 'eleve', None)
        if eleve is None or eleve.statut != 'actif':
            return Conversation.objects.none()
        # groupe__eleves=eleve : appartenance M2M ACTUELLE (Groupe.eleves),
        # jamais l'historique (HistoriqueGroupeEleve) — un élève transféré ou
        # retiré n'y apparaît plus, exactement la règle demandée.
        return Conversation.objects.filter(groupe__eleves=eleve)

    # mshrif (المشرف) et tout autre rôle : pas de chat.
    return Conversation.objects.none()


def can_access_conversation(user, conversation):
    """Vérification IDOR pour UNE conversation précise — jamais
    `Conversation.objects.get(id=...)` suivi d'un accès direct sans passer par
    ici (Point 28). Retourne un booléen, aucune donnée n'est renvoyée avant
    cet appel dans les vues qui l'utilisent."""
    if not user.is_authenticated or conversation is None:
        return False
    return get_conversations_accessibles(user).filter(pk=conversation.pk).exists()


def peut_modifier_photo_groupe(user, groupe):
    """Qui peut changer la photo de profil d'un groupe DEPUIS LE CHAT (Tâche
    du 2026-08-17 "avatar façon WhatsApp") — recalculée à chaque appel,
    jamais stockée, même principe que le reste de ce fichier. Réservé au
    مدير (admin) UNIQUEMENT — décision explicite (pas prof/superviseur même
    responsables du groupe, pas élève), cohérent avec le fait que la gestion
    de groupe elle-même (courses/) est déjà réservée à admin/mshrif. Cette
    fonction est le SEUL endroit qui décide de ce droit : à la fois pour
    afficher (ou non) l'avatar comme cliquable côté template, et pour la
    vérification stricte côté vue (chat.views.chat_modifier_photo_groupe) —
    jamais une confiance dans le fait que l'avatar n'était pas affiché."""
    if not user.is_authenticated or groupe is None:
        return False
    return user.role == 'admin'


def participants_conversation(conversation):
    """Liste d'affichage des participants ACTUELS d'une conversation — utilisée
    uniquement pour le panneau "membres" du chat (jamais pour calculer une
    permission, voir can_access_conversation ci-dessus). Chaque entrée est un
    dict {user, role_code, role_label} : le template n'affiche JAMAIS
    user.email / user.telephone directement (règle de sécurité des contacts,
    Point 4) — seulement get_full_name() + role_label."""
    from accounts.models import User, Superviseur

    groupe = conversation.groupe
    participants = []

    if groupe.prof_id and groupe.prof.statut == 'actif':
        participants.append({'user': groupe.prof.user, 'role_code': 'prof', 'role_label': 'الأستاذ'})

    for eleve in groupe.eleves.filter(statut='actif').select_related('user').order_by('user__first_name'):
        participants.append({'user': eleve.user, 'role_code': 'eleve', 'role_label': 'التلميذ'})

    if groupe.prof_id:
        superviseurs = Superviseur.objects.filter(profs_assignes=groupe.prof).select_related('user')
        for superviseur in superviseurs:
            participants.append({'user': superviseur.user, 'role_code': 'superviseur', 'role_label': 'المؤطر'})

    for admin_user in User.objects.filter(role='admin').order_by('first_name'):
        participants.append({'user': admin_user, 'role_code': 'admin', 'role_label': 'المدير'})

    return participants
