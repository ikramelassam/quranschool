"""Actions transversales sur les comptes (accounts.User/Eleve/Prof) qui doivent
rester centralisées en un seul endroit — voir chantier d'archivage du 2026-08-03.
Toute vue qui archive/réactive un élève ou un prof DOIT passer par les fonctions
ci-dessous plutôt que de modifier `statut`/`is_active` directement, pour ne jamais
oublier une des trois étapes (statut, is_active, invalidation de session)."""

from django.contrib.sessions.models import Session
from django.utils import timezone


def invalider_sessions_utilisateur(utilisateur, request=None):
    """Supprime toutes les sessions actives de cet utilisateur (déconnexion forcée
    sur tous les appareils) — utilisé par le changement d'email ET par l'archivage
    d'un élève/prof. Si la requête courante appartient à ce même utilisateur
    (auto-modification), on fait tourner la clé de SA session courante d'abord
    (cycle_key: opération native Django qui recrée la ligne sous une nouvelle clé
    et supprime l'ancienne proprement) et on l'exclut de la suppression en masse,
    pour ne pas le déconnecter lui-même en plein milieu de son action."""
    session_courante_a_garder = None
    if request is not None and request.user.is_authenticated and request.user.pk == utilisateur.pk:
        request.session.cycle_key()
        session_courante_a_garder = request.session.session_key

    for session in Session.objects.filter(expire_date__gte=timezone.now()):
        if session.session_key == session_courante_a_garder:
            continue
        data = session.get_decoded()
        if str(data.get('_auth_user_id')) == str(utilisateur.pk):
            session.delete()


def archiver_eleve(eleve, request=None):
    """Archive un élève: statut='archive' (exclusion de toutes les listes/sélecteurs
    actifs via Eleve.actifs), is_active=False (bloque toute future connexion — voir
    accounts.backend.EmailBackend, qui hérite de ModelBackend.get_user() et donc
    revérifie is_active à CHAQUE requête, ce qui déconnecte immédiatement une
    session déjà ouverte dès la requête suivante), et invalidation immédiate de
    la session en cours (ceinture + bretelles, ne pas attendre la requête suivante).
    Aucune donnée historique (Presence, Paiement, Evaluation, BilanMensuel) n'est
    touchée — tout reste consultable, voir Eleve.objects (non filtré)."""
    eleve.statut = 'archive'
    eleve.date_suspension = None
    eleve.user.is_active = False
    eleve.user.save(update_fields=['is_active'])
    eleve.save(update_fields=['statut', 'date_suspension'])
    invalider_sessions_utilisateur(eleve.user, request=request)


def reactiver_eleve(eleve, request=None):
    """Réactive un élève archivé (ou suspendu): connexion, visibilité dans les
    listes/sélecteurs et éligibilité à la création de nouvelles données reviennent
    immédiatement — même action de retour à 'actif' dans les deux cas de départ."""
    eleve.statut = 'actif'
    eleve.date_suspension = None
    eleve.user.is_active = True
    eleve.user.save(update_fields=['is_active'])
    eleve.save(update_fields=['statut', 'date_suspension'])


def archiver_prof(prof, request=None):
    """Archive un professeur — même principe qu'archiver_eleve ci-dessus."""
    prof.statut = 'archive'
    prof.user.is_active = False
    prof.user.save(update_fields=['is_active'])
    prof.save(update_fields=['statut'])
    invalider_sessions_utilisateur(prof.user, request=request)


def reactiver_prof(prof, request=None):
    """Réactive un professeur archivé — même principe que reactiver_eleve ci-dessus."""
    prof.statut = 'actif'
    prof.user.is_active = True
    prof.user.save(update_fields=['is_active'])
    prof.save(update_fields=['statut'])


def profs_pour_filtre(afficher_archives, prof_id_selectionne=''):
    """Queryset de profs pour un <select> de filtre (admin_seances, admin_calendrier,
    admin_evaluations): Prof.actifs par défaut, tous les profs si afficher_archives=True
    (case "إظهار المؤرشفين", même convention que admin_eleves/admin_profs). Garde
    toujours visible le prof déjà sélectionné même s'il est archivé et que le toggle
    est décoché, sinon le filtre actif disparaîtrait silencieusement du <select> à
    l'affichage suivant — même principe que courses.views.groupe_modifier pour le
    prof archivé assigné à un groupe."""
    from accounts.models import Prof

    if afficher_archives:
        return list(Prof.objects.select_related('user').order_by('user__first_name'))

    profs = list(Prof.actifs.select_related('user').order_by('user__first_name'))
    if prof_id_selectionne and not any(str(p.id) == str(prof_id_selectionne) for p in profs):
        prof_selectionne = Prof.objects.filter(id=prof_id_selectionne).select_related('user').first()
        if prof_selectionne:
            profs.append(prof_selectionne)
    return profs


def generer_presentation_publique(prof):
    """Paragraphe de présentation généré UNE SEULE FOIS, à la création du compte
    prof (voir dashboard.views._creer_compte_prof — point unique partagé par la
    validation classique du مشرف et l'ajout manuel direct, Chantier du
    2026-08-27), à partir des champs déjà remplis à la candidature. Même patron
    que registration.models.get_presentation_inscription : une valeur de départ
    raisonnable, jamais réécrite automatiquement ensuite — مدير/مشرف peuvent
    l'affiner à la main via dashboard.views.admin_prof_presentation_modifier
    sans qu'un futur appel à cette fonction n'écrase leur texte (cette fonction
    n'est d'ailleurs appelée qu'à la création, jamais depuis cette vue).

    Composé uniquement des champs RÉELLEMENT remplis par le candidat — jamais
    une phrase creuse (ex: 'الشهادات:' suivie de rien) si un champ optionnel
    (certifications) a été laissé vide. Libellés arabes des codes JSONField
    dupliqués ici volontairement (langues/type_eleve_preference), comme le fait
    déjà dashboard.templatetags.libelles_arabes.LIBELLES pour les mêmes codes
    ailleurs dans le projet — jamais une dépendance de accounts vers dashboard."""
    LIBELLES_LANGUES = {'arabe': 'العربية', 'francais': 'الفرنسية', 'anglais': 'الإنجليزية', 'autre': 'أخرى'}
    LIBELLES_TYPE_ELEVE = {'enfants': 'أطفال', 'adultes': 'بالغون'}

    phrases = []
    if prof.niveau_memorisation:
        phrases.append(f'مستوى الحفظ: {prof.niveau_memorisation}.')
    if prof.parcours_scolaire:
        phrases.append(f'المسار الدراسي: {prof.parcours_scolaire}')
    if prof.parcours_enseignant:
        phrases.append(f'مسار التدريس: {prof.parcours_enseignant}')
    if prof.certifications:
        phrases.append(f'من شهاداته وإجازاته: {prof.certifications}')
    if prof.langues:
        libelles = [LIBELLES_LANGUES.get(code, code) for code in prof.langues]
        phrases.append('يتحدث: ' + '، '.join(libelles) + '.')
    # 'les_deux' (يدرّس الأطفال والبالغين) n'est pas une vraie préférence — ne
    # rien dire revient à ne privilégier personne, ça n'apporte aucune info
    # utile au candidat qui lit la présentation. On ne garde que les codes
    # qui expriment une vraie préférence (enfants seuls, ou adultes seuls).
    codes_preference_reelle = [c for c in prof.type_eleve_preference if c in LIBELLES_TYPE_ELEVE]
    if codes_preference_reelle:
        libelles = [LIBELLES_TYPE_ELEVE[code] for code in codes_preference_reelle]
        phrases.append('يفضل التدريس لـ: ' + '، '.join(libelles) + '.')
    return '\n'.join(phrases)


def eleves_pour_filtre(afficher_archives, eleve_id_selectionne=''):
    """Équivalent de profs_pour_filtre pour un <select> d'élèves (admin_paiements,
    admin_evaluations)."""
    from accounts.models import Eleve

    if afficher_archives:
        return list(Eleve.objects.select_related('user').order_by('user__first_name'))

    eleves = list(Eleve.actifs.select_related('user').order_by('user__first_name'))
    if eleve_id_selectionne and not any(str(e.id) == str(eleve_id_selectionne) for e in eleves):
        eleve_selectionne = Eleve.objects.filter(id=eleve_id_selectionne).select_related('user').first()
        if eleve_selectionne:
            eleves.append(eleve_selectionne)
    return eleves
