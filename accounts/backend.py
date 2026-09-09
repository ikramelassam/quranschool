from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

from accounts.utils import nettoyer_email_saisi

User = get_user_model()

class EmailBackend(ModelBackend):
    """Authentifie par email — le paramètre 'username' reçu ici est en réalité
    l'email saisi dans accounts.views.login_view (formulaire à 2 champs,
    inchangé : email + mot de passe).

    Chantier du 2026-08-10 (partage d'email parent/enfant, voir
    admin_valider_eleve) : plusieurs comptes User peuvent désormais partager
    le même email (username technique différencié en interne, jamais l'email
    lui-même — voir la doc de admin_valider_eleve). get() a donc été remplacé
    par filter() : on essaie le mot de passe fourni contre CHAQUE compte
    correspondant à cet email, jusqu'à trouver le bon. Le mot de passe reste
    le vrai désambiguïsateur, garanti unique par construction pour
    élève/prof/مؤطر (voir dashboard.views.generer_mot_de_passe_sequentiel —
    compteur atomique, aucune collision possible entre 2 comptes).

    Filet de sécurité : si (ce qui ne devrait structurellement jamais arriver
    vu la garantie ci-dessus) le mot de passe fourni correspondait à PLUSIEURS
    comptes ayant cet email, on refuse la connexion plutôt que de choisir l'un
    des deux arbitrairement — retourne None comme un mot de passe incorrect,
    login_view affiche alors le même message générique existant (pas de fuite
    d'information sur l'ambiguïté).

    Normalisation de l'email saisi (2026-09-09, "beaucoup de profs bloqués à la
    connexion sur mobile") — miroir côté connexion du chantier 569113f qui ne
    couvrait que les formulaires d'inscription :
    - nettoyer_email_saisi() retire les marques directionnelles / espaces
      invisibles que le clavier arabe colle à l'adresse dans un champ RTL ;
    - repli insensible à la casse : iOS met une majuscule à la 1re lettre, et
      quelques comptes ont un email enregistré en casse mixte. Sans ça :
      « البريد الإلكتروني أو كلمة المرور غير صحيحة » alors que l'inscription
      s'était faite proprement.

    Ordre des deux requêtes (important) : correspondance EXACTE d'abord — elle
    seule sert l'index btree accounts_user_email_btree, ajouté exprès pour
    éviter un Seq Scan sur toute la table à CHAQUE connexion (audit du
    2026-09-02, voir accounts.models.User.Meta). Le repli email__iexact
    (UPPER(email) = UPPER(...), non indexé) n'est atteint que si l'exact n'a
    rien donné — cas rare (mauvaise casse), Seq Scan tolérable à ce moment-là.
    Comportement des connexions normales (bonne casse) strictement inchangé."""
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        username = nettoyer_email_saisi(username)
        if not username:
            return None

        def _compte_unique(comptes_qs):
            comptes = [u for u in comptes_qs if u.check_password(password)]
            return comptes[0] if len(comptes) == 1 else None

        # Chemin rapide (indexé) : correspondance exacte, comportement historique.
        user = _compte_unique(User.objects.filter(email=username))
        if user is not None:
            return user
        # Repli insensible à la casse — seulement si l'exact n'a rien donné.
        return _compte_unique(User.objects.filter(email__iexact=username))
