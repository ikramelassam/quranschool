"""Étape 5E du chantier du moteur d'inscription configurable — fallback
d'affichage pour EXACTEMENT 2 écrans historiques (admin_inscription_detail.html,
admin_eleve_detail.html) qui affichent encore "البرنامج"/"الرواية" par un
libellé fixe dans le template, hérité de l'ancien formulaire à une page.

IMPORTANT — pourquoi ce fichier référence 'programme'/'riwaya' par leur code,
alors que tout le reste de ce chantier (registration.utils.groupes_compatibles,
inscrire_eleve...) interdit explicitement une branche par nom de critère
métier : ce N'EST PAS le moteur générique. C'est un pont de compatibilité
volontairement étroit, réservé à 2 écrans historiques qui affichaient déjà
CES 2 concepts précis par un libellé fixe AVANT ce chantier — le moteur
lui-même (filtrage, wizard, dashboard de configuration) ne connaît jamais
'programme'/'riwaya' par leur nom, seulement ces 2 templates legacy.

Limite assumée : suppose que le مدير/مشرف crée (ou a déjà créé) les critères
"Programme"/"Riwaya" avec les codes exacts 'programme'/'riwaya' — cohérent
avec les exemples donnés dans tout le cahier des charges de ce chantier. Si
un jour ils sont recréés sous un autre code, ce fallback cesse de les
retrouver (retombe alors sur "غير محدد", jamais un crash) — signalé
explicitement ici plutôt que caché, à corriger via une vraie configuration
si ça arrive un jour."""

from django import template

register = template.Library()


@register.filter
def traduire_dynamique(valeur):
    """Chantier UI/i18n du 2026-08-28 (Problème A) — traduit dynamiquement une
    chaîne lue depuis la base (label de ConfigurationChampStructurel/
    ChampInscription/CritereOption/EtapeInscription, configurable par le
    مدير/مشرف) via le MÊME catalogue i18n Django que le reste du site.

    Pourquoi un filtre et pas {% trans %} directement : {% trans %} exige que
    le msgid soit connu au moment de l'extraction (makemessages / notre
    script maison), jamais une variable dont la valeur n'est connue qu'au
    rendu. Délègue à registration.utils.traduire_libelle_dynamique (gettext()
    à la volée sur la valeur) — même fonction utilisée directement en Python
    par les messages de validation qui embarquent un label (voir sa
    docstring), jamais 2 implémentations du même calcul. Si la chaîne
    correspond à un msgid déjà dans le catalogue (le petit vocabulaire SEEDÉ
    par le système), elle ressort traduite ; sinon (un libellé personnalisé
    tapé par le مدير, hors de ce vocabulaire connu) elle ressort TELLE
    QUELLE, jamais cassée — comportement standard de gettext() sur un msgid
    absent, exactement la frontière voulue entre ce Problème A (vocabulaire
    système à traduire) et le Problème B (contenu libre du مدير, qui a son
    propre mécanisme dédié avec champs par langue)."""
    from registration.utils import traduire_libelle_dynamique

    return traduire_libelle_dynamique(valeur)


@register.simple_tag
def reponse_ou_ancien_champ(inscription, valeur_ancien_champ, code_critere):
    """valeur_ancien_champ : le résultat déjà calculé de get_programme_display()/
    get_riwaya_display() côté template (CharField historique, colonne réelle
    sur InscriptionEleve) — fait foi s'il est non vide (candidature créée par
    l'ancien formulaire à une page, encore en service). Sinon, cherche une
    ReponseInscription de `inscription` pour le Critere de code `code_critere`
    (candidature créée par le nouveau parcours, Étape 6/7). "غير محدد"
    explicite si rien nulle part — jamais un vide silencieux qui ressemble à
    un bug pour le مدير/مشرف qui consulte la fiche."""
    if valeur_ancien_champ:
        return valeur_ancien_champ
    if inscription is None:
        return 'غير محدد'

    from registration.models import ReponseInscription

    reponse = ReponseInscription.objects.filter(
        inscription=inscription, critere__code=code_critere, option__isnull=False,
    ).select_related('option').first()
    return reponse.option.label if reponse else 'غير محدد'
