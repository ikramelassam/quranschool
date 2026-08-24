from django.shortcuts import render


def csrf_failure(request, reason=""):
    """Page affichée quand la vérification CSRF échoue (CSRF_FAILURE_VIEW,
    voir core.settings) — remplace la page 403 par défaut de Django (brute,
    en anglais, illisible pour un candidat/parent sur une plateforme
    entièrement en arabe RTL, voir CLAUDE.md §5 "Contraintes").

    Bug signalé le 2026-08-24 (formulaire du wizard public resté ouvert
    longtemps dans un onglet puis soumis) : le token CSRF intégré dans une
    page chargée il y a longtemps ne correspond plus forcément au cookie
    csrftoken ACTUEL du navigateur (ex: le cookie a été renouvelé/effacé
    entretemps par une visite ailleurs sur le site dans un autre onglet, ou
    par une extension de nettoyage de cookies) — Django rejette alors le
    POST avec "CSRF token from POST incorrect", AVANT même d'atteindre la
    vue. Ce n'est PAS un bug de code (parcours complet revérifié avec
    Client(enforce_csrf_checks=True), aucune anomalie trouvée) : la
    protection CSRF fonctionne exactement comme prévu. Le vrai problème est
    l'ABSENCE de récupération : sans cette vue, l'utilisateur atterrissait
    sur la page 403 technique par défaut de Django, sans explication ni
    moyen de continuer.

    `request.path` (jamais request.get_full_path()/POST data) : recharger
    EXACTEMENT la même URL en GET régénère une page avec un token à jour ET
    valide pour cette page précise, qu'il s'agisse d'une étape du wizard
    public, de l'ajout manuel admin, ou d'un écran de paiement — jamais un
    lien générique vers l'accueil qui ferait perdre l'endroit exact où
    l'utilisateur se trouvait."""
    return render(request, 'errors/csrf_failure.html', {
        'url_reessai': request.path,
    }, status=403)
