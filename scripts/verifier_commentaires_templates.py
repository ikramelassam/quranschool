"""Détecte les commentaires Django {# ... #} mal fermés (fuite de texte
visible sur le site) — Tâche du 2026-08-06.

CAUSE DU BUG (mécanisme exact) :
Le lexer de Django tokenise les templates avec une regex qui NE traverse
PAS les sauts de ligne (pas de re.DOTALL) pour la syntaxe {# ... #} —
contrairement à {% comment %}...{% endcomment %}, qui elle accepte le
multi-ligne. Concrètement : `{#.*?#}` ne matche que si tout tient sur UNE
SEULE ligne. Dès qu'un commentaire {# #} s'étale sur plusieurs lignes,
Django ne reconnaît plus l'ouverture {# comme le début d'un tag de
commentaire : il n'y a alors AUCUNE syntaxe de commentaire reconnue à cet
endroit, et le texte — {# inclus — est rendu tel quel, en clair, sur la
page HTML finale. Ce n'est pas une erreur de rendu (pas de crash, pas de
warning) : le bug est invisible tant qu'on n'ouvre pas la page rendue.

Historique : ce bug s'est produit à répétition au fil des chantiers (au
moins 10 cas confirmés au 2026-08-06, dans templates créés à des dates
différentes) car rien ne le détectait automatiquement — seule une lecture
manuelle de la page rendue le révèle. Ce script comble ce trou : il
scanne TOUS les templates du projet (pas seulement ceux d'un chantier en
cours) sans avoir besoin de les rendre.

CONVENTION À RESPECTER (mesure préventive) :
- {# commentaire sur une seule ligne #}  -> OK, toujours.
- Un commentaire de plus d'une ligne DOIT utiliser {% comment %} / {% endcomment %}.
  Ne jamais utiliser {# #} pour un commentaire qui dépasse la ligne.

USAGE :
    python scripts/verifier_commentaires_templates.py
Code de sortie 0 si rien trouvé, 1 sinon (utilisable dans un hook
pre-commit ou une étape de CI si le projet en adopte un jour).
"""
import os
import re
import sys

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

RACINE_TEMPLATES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')

# Une ligne est suspecte si elle contient '{#' sans '#}' plus loin sur LA
# MÊME ligne -- exactement la condition sous laquelle Django ne referme
# jamais le tag et le traite comme du texte littéral.
MOTIF_OUVERTURE_NON_FERMEE = re.compile(r'\{#(?:(?!#\}).)*$')


def scanner(racine=RACINE_TEMPLATES):
    trouvailles = []
    nb_fichiers = 0
    for dirpath, _dirnames, filenames in os.walk(racine):
        for fn in filenames:
            if not fn.endswith('.html'):
                continue
            nb_fichiers += 1
            chemin = os.path.join(dirpath, fn)
            with open(chemin, encoding='utf-8') as f:
                lignes = f.readlines()
            for i, ligne in enumerate(lignes, start=1):
                if MOTIF_OUVERTURE_NON_FERMEE.search(ligne):
                    trouvailles.append((chemin, i, ligne.rstrip()))
    return nb_fichiers, trouvailles


def main():
    nb_fichiers, trouvailles = scanner()
    print(f"Templates scannés : {nb_fichiers}")
    if not trouvailles:
        print("OK — aucune fuite de commentaire {# #} détectée.")
        return 0

    print(f"\n❌ {len(trouvailles)} fuite(s) potentielle(s) détectée(s) :\n")
    for chemin, lineno, contenu in trouvailles:
        rel = os.path.relpath(chemin, os.path.dirname(RACINE_TEMPLATES))
        print(f"  {rel}:{lineno}")
        print(f"    {contenu[:160]}")
        print()
    print("Corrige en remplaçant {# ... #} par {% comment %} ... {% endcomment %}"
          " si le commentaire dépasse une ligne.")
    return 1


if __name__ == '__main__':
    sys.exit(main())
