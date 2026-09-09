import re

# Espaces (dont l'espace insecable) + marques directionnelles / caracteres de
# largeur nulle que les claviers arabes et l'autocompletion mobile inserent
# autour d'un texte latin dans un champ RTL. Meme jeu de caracteres que le
# nettoyage JS de templates/inscriptions/_wizard_base.html et de
# templates/accounts/login.html.
#
# Construit a partir de points de code explicites (plutot qu'une classe regex
# ecrite en dur) pour ne PAS mettre de caracteres invisibles dans ce fichier
# source : U+00A0, U+200B..U+200F, U+202A..U+202E, U+2060..U+2064,
# U+2066..U+2069, U+FEFF.
_POINTS_DE_CODE_PARASITES = (
    [0x00A0]
    + list(range(0x200B, 0x2010))
    + list(range(0x202A, 0x202F))
    + list(range(0x2060, 0x2065))
    + list(range(0x2066, 0x206A))
    + [0xFEFF]
)
_CARACTERES_PARASITES_EMAIL = re.compile(
    '[\\s' + ''.join(chr(cp) for cp in _POINTS_DE_CODE_PARASITES) + ']'
)


def nettoyer_email_saisi(valeur):
    """Nettoie un e-mail tape sur mobile : retire les espaces (y compris l'espace
    finale ajoutee par l'autocompletion), l'espace insecable, et les marques
    directionnelles / caracteres de largeur nulle que les claviers arabes
    inserent autour d'un texte latin dans un champ RTL. Sans ca, `str.strip()`
    laisse passer un U+200F colle a l'adresse : le champ `type="email"` bloque
    l'envoi cote navigateur, et si la requete passe quand meme on cree / on
    cherche un compte dont l'e-mail est inutilisable.

    Utilise a la SAISIE (formulaires d'inscription, via inscriptions.views qui
    le re-exporte) et a la CONNEXION (accounts.backend.EmailBackend,
    accounts.views.login_view / mot_de_passe_oublie) : un prof qui s'inscrit
    proprement puis tape son e-mail sur mobile pour se connecter tombait sinon
    sur « email ou mot de passe incorrect »."""
    return _CARACTERES_PARASITES_EMAIL.sub('', valeur or '')
