from django.contrib.auth.backends import ModelBackend
from django.contrib.auth import get_user_model

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
    d'information sur l'ambiguïté)."""
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None or password is None:
            return None
        comptes_correspondants = [
            u for u in User.objects.filter(email=username) if u.check_password(password)
        ]
        if len(comptes_correspondants) == 1:
            return comptes_correspondants[0]
        return None