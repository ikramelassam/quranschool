"""Contrôle d'accès centralisé d'Examens — même patron que chat/permissions.py
(Point de référence explicitement demandé) : TOUTE vue qui touche un Examen
ou une Copie précise passe par les fonctions ci-dessous, jamais par une
condition recodée localement. Les permissions ne sont JAMAIS stockées :
toujours recalculées depuis l'état ACTUEL des relations métier (Groupe.prof,
Groupe.eleves, Superviseur.profs_assignes) — un départ/changement de groupe
ou de prof se répercute donc immédiatement, sans donnée à corriger nulle
part.

Rôles et périmètre (décisions validées le 2026-08-16) :
- eleve   : ses propres copies, uniquement les examens PUBLIÉS ou FERMÉS de
            ses groupes ACTUELS (jamais un brouillon, jamais un groupe
            qu'il a quitté).
- prof    : gestion complète (création/édition/publication/correction) des
            examens de SES groupes actuels uniquement.
- superviseur (مؤطر) : lecture seule des examens/copies des groupes des
            profs qu'il supervise actuellement — jamais d'écriture (ni sur
            la structure, ni sur les notes), aucune exigence contraire
            trouvée dans le projet (evaluations.Evaluation, seul autre
            mécanisme où le مؤطر évalue, note le PROF, jamais l'élève).
- admin (مدير) : accès global, lecture ET gestion — CE MODULE reste
            volontairement silencieux sur une gestion admin des examens
            (non demandée) : can_gerer_examen n'autorise QUE le prof
            propriétaire, y compris pour l'admin — voir sa docstring.
- mshrif (المشرف) : lecture seule globale, décision validée le 2026-08-16 —
            DIFFÉRENT du chat qui l'exclut totalement (chat/permissions.py),
            car Examens est un contenu de suivi pédagogique (comme les
            écrans d'admin auxquels mshrif a déjà accès) et non un canal de
            discussion privée (raison de son exclusion du chat)."""
from .models import Examen


def get_examens_accessibles(user):
    """Queryset des Examen visibles par `user`, en lecture, selon son rôle
    ACTUEL. Base de toute la sécurité d'Examens — la liste des examens ET la
    vérification IDOR par examen individuel (can_access_examen ci-dessous)
    l'utilisent TOUTES LES DEUX, aucune 2e logique de filtrage ailleurs."""
    if not user.is_authenticated:
        return Examen.objects.none()

    if user.role in ('admin', 'mshrif'):
        # مدير : accès global. مشرف : lecture seule globale (même queryset
        # que مدير — la distinction lecture/écriture est faite par
        # can_gerer_examen/can_corriger_examen, jamais ici).
        return Examen.objects.all()

    if user.role == 'superviseur':
        superviseur = getattr(user, 'superviseur', None)
        if superviseur is None:
            return Examen.objects.none()
        # Groupes des profs ACTUELLEMENT supervisés — profs_assignes.all()
        # est déjà l'état courant de la M2M.
        return Examen.objects.filter(groupe__prof__in=superviseur.profs_assignes.all())

    if user.role == 'prof':
        prof = getattr(user, 'prof', None)
        if prof is None or prof.statut != 'actif':
            return Examen.objects.none()
        return Examen.objects.filter(groupe__prof=prof)

    if user.role == 'eleve':
        eleve = getattr(user, 'eleve', None)
        if eleve is None or eleve.statut != 'actif':
            return Examen.objects.none()
        # Appartenance ACTUELLE uniquement (groupe__eleves=eleve est l'état
        # courant du M2M Groupe.eleves, jamais l'historique) — un élève
        # transféré ou retiré n'y apparaît plus. Statut : jamais un
        # brouillon (§6 : liste "publié/fermé", jamais "brouillon").
        return Examen.objects.filter(groupe__eleves=eleve, statut__in=('publie', 'ferme'))

    return Examen.objects.none()


def can_access_examen(user, examen):
    """Vérification IDOR pour un Examen précis — jamais un
    Examen.objects.get(id=...) suivi d'un accès direct sans passer par ici."""
    if not user.is_authenticated or examen is None:
        return False
    return get_examens_accessibles(user).filter(pk=examen.pk).exists()


def can_gerer_examen(user, examen):
    """True si `user` peut créer/modifier la structure, publier ou fermer CET
    examen — le PROF PROPRIÉTAIRE du groupe uniquement. Ni admin ni mshrif :
    la gestion pédagogique (questions, publication) reste au prof qui a créé
    l'examen ; admin/mshrif ont un accès de CONSULTATION (voir docstring du
    module) — aucune exigence explicite contraire n'a été formulée."""
    if not user.is_authenticated or examen is None or user.role != 'prof':
        return False
    prof = getattr(user, 'prof', None)
    return prof is not None and prof.statut == 'actif' and examen.groupe.prof_id == prof.id


def can_corriger_examen(user, examen):
    """True si `user` peut noter/commenter les réponses des copies de CET
    examen — même périmètre que can_gerer_examen (le prof propriétaire
    uniquement, §11 du cahier des charges : 'le professeur corrige')."""
    return can_gerer_examen(user, examen)


def can_access_copie(user, copie):
    """Vérification IDOR pour UNE copie précise. Élève : uniquement SA
    PROPRE copie, jamais celle d'un autre élève même du même groupe.
    Prof/superviseur/admin/mshrif : accès si l'examen parent leur est
    accessible en lecture (mêmes règles que can_access_examen)."""
    if not user.is_authenticated or copie is None:
        return False
    if user.role == 'eleve':
        eleve = getattr(user, 'eleve', None)
        return eleve is not None and copie.eleve_id == eleve.id
    return can_access_examen(user, copie.examen)


def can_modifier_copie(user, copie):
    """True si `user` (l'élève, propriétaire) peut encore répondre/modifier
    CETTE copie — propriétaire ET copie.modifiable (statut + chrono encore
    valides, voir Copie.modifiable). Utilisée par la vue d'autosave ET la
    page de passage — jamais un contrôle recodé localement."""
    if not user.is_authenticated or copie is None or user.role != 'eleve':
        return False
    eleve = getattr(user, 'eleve', None)
    return eleve is not None and copie.eleve_id == eleve.id and copie.modifiable
