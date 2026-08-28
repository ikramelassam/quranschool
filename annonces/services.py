import os

from courses.utils import cible_annonce_pour_eleve, tranche_age_precise, TRANCHES_AGE_PRECISES
from .models import Annonce, LectureAnnonce

# Métadonnées d'affichage des 3 canaux (Chantier "canaux de diffusion" du
# 2026-08-16, icônes retravaillées le même jour) — délibérément PAS un
# modèle Django (voir Annonce.__doc__) : `code` est toujours l'une des
# valeurs de Annonce.CIBLE_CHOICES, jamais une 4e catégorie. Ordre = ordre
# d'affichage dans la liste des canaux.
#
# Pas de champ "icone" ici volontairement : les émoji 👩/👨/🧒 d'origine
# réduisaient chaque public à une pictographie de genre/âge — remplacés par
# UNE SEULE icône SVG "diffusion" partagée (voir templates/annonces/
# _canal_icone.html), la distinction se fait par nom/description, pas par
# l'icône.
CANAUX = [
    {'code': 'femmes_adultes', 'nom': 'النساء', 'description': 'قناة تبليغ للطالبات البالغات'},
    {'code': 'hommes_adultes', 'nom': 'الرجال', 'description': 'قناة تبليغ للطلاب البالغين'},
    {'code': 'mineurs', 'nom': 'الأطفال', 'description': 'قناة تبليغ للطلاب دون 18 سنة'},
]
CANAUX_PAR_CODE = {c['code']: c for c in CANAUX}

# Sous-onglets du canal 'mineurs' (Point 3, chantier catégorisation par âge du
# 2026-08-28) — même 3 tranches que Annonce.TRANCHE_AGE_CHOICES (les libellés
# viennent ici de TRANCHES_AGE_PRECISES, seule source de vérité pour ce texte
# arabe dans tout le projet ; les CODES doivent rester identiques à ceux
# stockés sur Annonce.tranche_age, voir Annonce.TRANCHE_AGE_CHOICES.__doc__
# pour pourquoi ils sont dupliqués plutôt que réutilisés tel quel là-bas).
TRANCHES_ANNONCE = [{'code': code, 'nom': label} for code, label, *_r in TRANCHES_AGE_PRECISES]


def canal_pour_code(code):
    """Métadonnées d'affichage (icône/nom/description) du canal `code`, ou
    None si ce n'est pas l'une des 3 valeurs valides — jamais une 4e
    catégorie inventée à la volée."""
    return CANAUX_PAR_CODE.get(code)


def tranche_annonce_pour_eleve(eleve):
    """Code de tranche d'âge précise (talqin/baraim/yafiun) pour un élève
    mineur, ou None si adulte, âge inconnu, ou âge hors 5-18 ans (même limite
    que courses.utils.TRANCHES_AGE_PRECISES — un enfant de moins de 5 ans n'a
    pas de tranche précise, mais reste dans cible_annonce_pour_eleve=
    'mineurs' et voit donc toujours les publications non ciblées à une
    tranche, voir annonces_visibles_pour_eleve ci-dessous). Réutilise
    courses.utils.tranche_age_precise — même source que Groupe.
    tranches_age_visees et chat.services.ONGLETS_CHAT, jamais une 4e
    implémentation de ce calcul."""
    if eleve.inscription is None or eleve.inscription.date_naissance is None:
        return None
    resultat = tranche_age_precise(eleve.inscription.date_naissance)
    return resultat[0] if resultat else None


def peut_voir_annonce(user, annonce):
    """Vérification d'accès à UNE publication précise (Point C14 du chantier
    canaux — même esprit que chat.permissions.can_access_conversation) :
    مدير/مشرف voient tout, un élève seulement les publications de SON canal
    (recalculé à chaque appel depuis son âge/sexe actuels, jamais mis en
    cache) ET seulement si elles sont encore actives. Utilisée par la vue
    proxy annonce_fichier — jamais l'URL réelle du fichier imprimée
    directement dans un template, exactement comme chat_fichier."""
    if not user.is_authenticated:
        return False
    if user.role in ('admin', 'mshrif'):
        return True
    if user.role != 'eleve':
        return False
    eleve = getattr(user, 'eleve', None)
    if eleve is None or eleve.statut != 'actif':
        return False
    if not annonce.active or cible_annonce_pour_eleve(eleve) != annonce.cible:
        return False
    # Sous-ciblage tranche (Point 3) : une publication 'mineurs' avec
    # tranche_age='' vise TOUS les enfants (comportement historique, voir
    # Annonce.tranche_age.__doc__) ; sinon seulement les élèves de cette
    # tranche précise.
    if annonce.tranche_age:
        return tranche_annonce_pour_eleve(eleve) == annonce.tranche_age
    return True


def canal_pour_eleve(eleve):
    """Métadonnées du canal (unique) de CET élève, pour l'en-tête de branding
    de sa page "الإعلانات" (le rôle élève ne choisit jamais son canal, il
    n'en a qu'un — voir cible_annonce_pour_eleve). None si son âge est
    inconnu, exactement comme annonces_visibles_pour_eleve."""
    cible = cible_annonce_pour_eleve(eleve)
    return canal_pour_code(cible) if cible else None


# ---------------------------------------------------------------------------
# Pièces jointes des publications — même esprit que chat.services (liste
# blanche d'extensions par type + taille max), mais dupliqué ici plutôt
# qu'importé de chat : les 2 apps restent volontairement indépendantes (une
# publication de canal n'est pas un message de conversation).
# ---------------------------------------------------------------------------
EXTENSIONS_PAR_TYPE = {
    'image': ('.jpg', '.jpeg', '.png', '.gif', '.webp'),
    'video': ('.mp4', '.webm', '.mov'),
    'audio': ('.mp3', '.wav', '.ogg', '.oga', '.m4a', '.opus', '.webm', '.aac'),
    'document': ('.pdf', '.doc', '.docx'),
}
TAILLE_MAX_PAR_TYPE_OCTETS = {
    'image': 15 * 1024 * 1024,   # 15 Mo
    'video': 40 * 1024 * 1024,   # 40 Mo — nettement plus lourd qu'une image/un document
    'audio': 15 * 1024 * 1024,
    'document': 15 * 1024 * 1024,
}


def deduire_type_fichier(nom_fichier, content_type=''):
    """Type ('image'/'video'/'audio'/'document') déduit de l'extension, ou
    None si elle ne correspond à aucune liste blanche connue — la publication
    est alors refusée par valider_piece_jointe.

    Cas particulier .webm : seule extension présente à la fois dans 'video'
    (fichier vidéo webm classique) ET 'audio' (blob produit par
    MediaRecorder lors de l'enregistrement direct — voir templates/annonces/
    canal_detail.html, même geste que templates/chat/_panel.html). Levée par
    le content-type envoyé par le navigateur ('audio/webm' pour un
    enregistrement, 'video/webm' ou vide pour un vrai fichier vidéo) —
    utilisé UNIQUEMENT pour choisir le lecteur affiché, jamais pour la
    validation extension/taille qui reste la même liste blanche."""
    extension = os.path.splitext(nom_fichier)[1].lower()
    if extension == '.webm':
        return 'audio' if (content_type or '').startswith('audio/') else 'video'
    for type_fichier, extensions in EXTENSIONS_PAR_TYPE.items():
        if extension in extensions:
            return type_fichier
    return None


def valider_piece_jointe(fichier):
    """Renvoie (type_fichier, erreur). `erreur` est un message arabe si le
    fichier est refusé (extension inconnue ou taille excessive pour son
    type), None s'il est accepté — validation TOUJOURS serveur, jamais sur
    la seule confiance du <input accept=...> côté client."""
    type_fichier = deduire_type_fichier(fichier.name, getattr(fichier, 'content_type', ''))
    if type_fichier is None:
        return None, f'صيغة الملف "{os.path.splitext(fichier.name)[1]}" غير مدعومة.'
    taille_max = TAILLE_MAX_PAR_TYPE_OCTETS[type_fichier]
    if fichier.size > taille_max:
        return None, f'حجم الملف كبير جداً ({fichier.size // (1024 * 1024)} م.ب). الحد الأقصى {taille_max // (1024 * 1024)} م.ب.'
    return type_fichier, None


def annonces_visibles_pour_eleve(eleve):
    """QuerySet des annonces actives ciblant CET élève précisément (jamais les
    3 catégories mélangées) — une seule requête indexée sur cible/active,
    aucune boucle Python sur la table Annonce. Vide (Annonce.objects.none())
    si l'âge de l'élève est inconnu : ne jamais deviner à qui montrer quoi.

    Sous-ciblage tranche (Point 3, 2026-08-28) : pour cible='mineurs', ne
    garde que tranche_age='' (visant TOUS les enfants) OU la tranche précise
    de CET élève — même règle que peut_voir_annonce ci-dessus, ici en
    requête plutôt qu'en vérification unitaire."""
    cible = cible_annonce_pour_eleve(eleve)
    if cible is None:
        return Annonce.objects.none()
    qs = Annonce.objects.filter(cible=cible, active=True)
    if cible == 'mineurs':
        from django.db.models import Q
        tranche = tranche_annonce_pour_eleve(eleve)
        qs = qs.filter(Q(tranche_age='') | Q(tranche_age=tranche)) if tranche else qs.filter(tranche_age='')
    return qs


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


def effectif_par_tranche():
    """{code_tranche: nb_enfants_actifs_concernes} pour les 3 tranches
    d'âge précises — même patron que effectif_par_cible (Point 3, chantier du
    2026-08-28), affiché sur le canal 'mineurs' pour que مدير/مشرف voie
    combien d'enfants chaque tranche touche avant de publier. Ne compte que
    les élèves déjà 'mineurs' au sens de cible_annonce_pour_eleve — un adulte
    ne peut jamais apparaître dans ce compte, même par erreur d'âge limite."""
    from accounts.models import Eleve

    compte = {code: 0 for code, _ in Annonce.TRANCHE_AGE_CHOICES}
    for eleve in Eleve.actifs.select_related('inscription'):
        if cible_annonce_pour_eleve(eleve) != 'mineurs':
            continue
        tranche = tranche_annonce_pour_eleve(eleve)
        if tranche:
            compte[tranche] += 1
    return compte


def canaux_avec_apercu():
    """Les 3 canaux (voir CANAUX) enrichis, pour مدير/مشرف, de l'effectif
    concerné, du nombre de publications actives et de la dernière
    publication de chacun — pour la page de sélection des canaux (cartes
    façon WhatsApp Channels). Un seul passage sur les élèves actifs
    (effectif_par_cible), puis 3 requêtes bornées (une par canal) sur
    Annonce — aucune boucle sur les Annonce elles-mêmes."""
    effectifs = effectif_par_cible()
    resultat = []
    for canal in CANAUX:
        publications = Annonce.objects.filter(cible=canal['code'], active=True)
        resultat.append({
            **canal,
            'effectif': effectifs.get(canal['code'], 0),
            'nb_publications': publications.count(),
            'derniere_publication': publications.first(),  # Meta.ordering = -date_creation
        })
    return resultat


def dernieres_publications(limite=6):
    """Les `limite` dernières publications actives, TOUTES chaînes
    confondues — pour le bloc "آخر النشاط عبر القنوات" de la page de
    sélection des canaux (remplit l'espace sous les 3 cards par quelque
    chose d'utile plutôt que par du vide). Meta.ordering = -date_creation,
    pas de order_by() supplémentaire nécessaire."""
    return list(Annonce.objects.filter(active=True)[:limite])
