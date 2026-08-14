import os
import re
import unittest

from django.conf import settings


# Régression du 2026-08-14 — deux façons dont un commentaire de développement
# peut fuiter dans le HTML envoyé au navigateur, découvertes en test manuel :
#
# 1. {# ... #} sur plusieurs lignes : le tokenizer de Django utilise la regex
#    {#.*?#} SANS re.DOTALL, donc "." ne matche pas les retours à la ligne —
#    dès qu'un commentaire {# #} contient un \n, il n'est plus reconnu comme
#    commentaire et son texte brut est rendu tel quel dans la page (VISIBLE
#    à l'écran). Fix : {% comment %} ... {% endcomment %} (un vrai tag de
#    bloc, géré par le parser, supporte le multi-lignes).
#
# 2. <!-- ... --> (commentaire HTML natif, pas Django) : celui-ci ne casse
#    aucun parsing — il est envoyé tel quel dans le document HTML. Invisible
#    à l'écran (les navigateurs n'affichent pas les commentaires HTML), mais
#    quand même livré au client (visible via "voir le code source"/devtools).
#    Le projet a choisi de ne pas s'en satisfaire pour du texte de
#    développement : "les commentaires de chantier devraient plutôt être
#    dans les vues Python ou dans git, pas dans le HTML rendu aux
#    utilisateurs." Fix : {% comment %} ... {% endcomment %} également —
#    ce texte n'a alors plus aucune raison d'être servi au navigateur.
#
# Ce test scanne le SOURCE de tous les templates (pas leur rendu — un scan
# statique couvre aussi les templates qui ne sont jamais directement rendus
# tels quels dans les tests existants, contrairement à un test par rendu qui
# ne couvre que les pages effectivement visitées). Pas de DB nécessaire :
# unittest.TestCase brut, pas TestCase Django.

RACINE_TEMPLATES = os.path.join(settings.BASE_DIR, 'templates')

MOTIFS_DEV = re.compile(
    r'(Chantier|voir dashboard\.|voir accounts\.|voir courses\.|voir inscriptions\.'
    r'|voir evaluations\.|voir payments\.|TODO|FIXME|T[aâ]che du)',
    re.IGNORECASE,
)


def _lister_templates():
    for dossier, _, fichiers in os.walk(RACINE_TEMPLATES):
        for f in fichiers:
            if f.endswith('.html'):
                yield os.path.join(dossier, f)


class TemplatesSansFuiteDeCommentairesTests(unittest.TestCase):

    def test_aucun_commentaire_django_multi_lignes_casse(self):
        """Aucun {# ... #} ne doit contenir de retour à la ligne — sinon il
        n'est plus reconnu comme commentaire par Django et fuit en clair."""
        fautifs = []
        for chemin in _lister_templates():
            with open(chemin, encoding='utf-8') as fh:
                contenu = fh.read()
            for m in re.finditer(r'\{#.*?#\}', contenu, re.DOTALL):
                if '\n' in m.group(0):
                    ligne = contenu[:m.start()].count('\n') + 1
                    fautifs.append(f'{os.path.relpath(chemin, settings.BASE_DIR)}:{ligne}')
        self.assertEqual(
            fautifs, [],
            'Commentaire(s) Django {# #} multi-lignes cassé(s), à convertir en '
            '{% comment %}...{% endcomment %} : ' + ', '.join(fautifs)
        )

    def test_aucun_commentaire_html_ne_contient_de_texte_de_developpement(self):
        """Un <!-- --> qui mentionne un chantier/une tâche/un renvoi de code
        est quand même livré au navigateur (juste invisible à l'écran) — ce
        texte n'a rien à faire dans le HTML rendu aux utilisateurs."""
        fautifs = []
        for chemin in _lister_templates():
            with open(chemin, encoding='utf-8') as fh:
                contenu = fh.read()
            for m in re.finditer(r'<!--.*?-->', contenu, re.DOTALL):
                if MOTIFS_DEV.search(m.group(0)):
                    ligne = contenu[:m.start()].count('\n') + 1
                    fautifs.append(f'{os.path.relpath(chemin, settings.BASE_DIR)}:{ligne}')
        self.assertEqual(
            fautifs, [],
            'Commentaire(s) HTML <!-- --> contenant du texte de développement, '
            'à convertir en {% comment %}...{% endcomment %} : ' + ', '.join(fautifs)
        )
