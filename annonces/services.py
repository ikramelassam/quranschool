from courses.utils import cible_annonce_pour_eleve
from .models import Annonce, LectureAnnonce


def annonces_visibles_pour_eleve(eleve):
    """QuerySet des annonces actives ciblant CET élève précisément (jamais les
    3 catégories mélangées) — une seule requête indexée sur cible/active,
    aucune boucle Python sur la table Annonce. Vide (Annonce.objects.none())
    si l'âge de l'élève est inconnu : ne jamais deviner à qui montrer quoi."""
    cible = cible_annonce_pour_eleve(eleve)
    if cible is None:
        return Annonce.objects.none()
    return Annonce.objects.filter(cible=cible, active=True)


def annonces_non_lues_pour_eleve(eleve, user):
    """Nombre d'annonces visibles par cet élève pas encore marquées lues par
    CE user (voir marquer_annonces_lues) — pour le badge sidebar/bannière."""
    return annonces_visibles_pour_eleve(eleve).exclude(lectures__user=user).count()


def marquer_annonces_lues(annonces, user):
    """Marque `annonces` (itérable d'Annonce, ex: la page /annonces/ affichée
    à l'instant) comme lues par `user` — 2 requêtes au total quel que soit le
    nombre d'annonces (une pour savoir lesquelles sont déjà lues, une pour
    créer les lignes manquantes), jamais une requête par annonce. Même patron
    que chat.services.marquer_comme_lu (idempotent, unique_together protège
    contre un double clic/onglet concurrent — ignore_conflicts=True)."""
    ids = [a.id for a in annonces]
    if not ids:
        return
    deja_lues = set(
        LectureAnnonce.objects.filter(user=user, annonce_id__in=ids).values_list('annonce_id', flat=True)
    )
    a_creer = [LectureAnnonce(annonce_id=aid, user=user) for aid in ids if aid not in deja_lues]
    if a_creer:
        LectureAnnonce.objects.bulk_create(a_creer, ignore_conflicts=True)


def effectif_par_cible():
    """{code_cible: nb_eleves_actifs_concernes} — aperçu affiché sur le
    formulaire de création (admin_annonces.html) pour que مدير/مشرف voie
    combien d'élèves seront touchés avant d'envoyer. Boucle Python volontaire
    sur les élèves actifs (petit volume borné, même choix que
    courses.utils.calculer_remuneration_prof pour la même catégorisation
    âge/sexe) plutôt qu'une arithmétique de dates recalculée en SQL, qui
    risquerait de désynchroniser silencieusement cette valeur d'affichage de
    cible_annonce_pour_eleve — la SEULE fonction faisant autorité sur cette
    catégorisation dans tout le projet."""
    from accounts.models import Eleve

    compte = {code: 0 for code, _ in Annonce.CIBLE_CHOICES}
    for eleve in Eleve.actifs.select_related('inscription'):
        cible = cible_annonce_pour_eleve(eleve)
        if cible:
            compte[cible] += 1
    return compte
