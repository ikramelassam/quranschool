from django.db import migrations

# Même seuil que courses.utils.AGE_SEUIL_ADULTE — dupliqué ici volontairement
# (convention Django : une migration ne doit jamais importer du code
# applicatif qui pourrait changer de forme indépendamment d'elle plus tard).
AGE_SEUIL_ADULTE = 18


def _categorie_derivee(creneau):
    """Réplique EXACTEMENT courses.utils.categorie_derivee_du_creneau (testée
    via courses.utils.backfiller_categorie_depuis_creneau, voir
    courses/tests.py) sur les modèles historiques — voir cette fonction pour
    la justification de la règle. None si non tranchable (créneau à cheval
    enfant/adulte, ou adulte des deux sexes) : jamais deviné."""
    if creneau.age_max < AGE_SEUIL_ADULTE:
        return 'mineurs'
    if creneau.age_min >= AGE_SEUIL_ADULTE:
        if creneau.sexe_cible == 'homme':
            return 'hommes_adultes'
        if creneau.sexe_cible == 'femme':
            return 'femmes_adultes'
    return None


def remplir_categorie_depuis_creneau(apps, schema_editor):
    """Chantier du 2026-08-19 (demande explicite du client, audit préalable :
    31 groupes réels, 19 auto-classifiables sans ambiguïté, 2 cas ambigus à
    cheval enfant/adulte, 8 sans créneau). Remplit Groupe.categorie
    UNIQUEMENT là où elle est encore vide ET où le créneau assigné permet une
    déduction sans ambiguïté — n'écrase JAMAIS une catégorie déjà saisie
    manuellement (filtre categorie='' avant tout calcul). Les groupes sans
    créneau, ou dont le créneau est à cheval enfant/adulte ou adulte des deux
    sexes, restent volontairement vides : jamais devinés.

    Utilise les modèles HISTORIQUES (apps.get_model), pas les vrais modèles
    applicatifs — bonne pratique standard pour les migrations de données
    (voir aussi courses.utils.backfiller_categorie_depuis_creneau, qui
    réplique la même logique simple mais avec les vrais modèles, pour rester
    testable/réutilisable en dehors du contexte d'une migration)."""
    Groupe = apps.get_model('courses', 'Groupe')
    groupes = Groupe.objects.filter(categorie='', creneau__isnull=False).select_related('creneau')
    for groupe in groupes:
        categorie = _categorie_derivee(groupe.creneau)
        if categorie:
            groupe.categorie = categorie
            groupe.save(update_fields=['categorie'])


def ne_rien_faire_au_retour_arriere(apps, schema_editor):
    """Migration inverse volontairement no-op : reculer ne peut pas
    distinguer de façon fiable les groupes remplis par CETTE migration de
    ceux déjà remplis manuellement avant elle (les deux cas sont
    indiscernables une fois écrits) — même principe que le reste du projet,
    aucune migration ne fait disparaître de données réelles au reverse."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0033_presence_resultat_memorisation'),
    ]

    operations = [
        migrations.RunPython(remplir_categorie_depuis_creneau, ne_rien_faire_au_retour_arriere),
    ]
