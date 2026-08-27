# Generated manually — Besoin 1.4 (2026-08-27), suite de 0028_typeabonnement_duree_choix_ferme

from django.db import migrations

# Variantes de texte arabe libre RÉELLEMENT connues avec certitude (même
# principe best-effort que 0024_typeabonnement_duree.DUREES_CONNUES : jamais
# une supposition sur une valeur ambiguë) — couvre le seed initial ('شهر',
# '3 أشهر', voir 0004_seed_types_abonnement/0024) ET les variantes que le
# مدير a pu saisir librement depuis, avant ce chantier (formulaire texte
# libre, voir admin_abonnement_ajouter.html d'avant ce commit).
VARIANTES_CONNUES = {
    '1mois': ['شهر', 'شهر واحد', '1 شهر'],
    '3mois': ['3 أشهر', '3أشهر'],
    '6mois': ['6 أشهر', '6أشهر'],
    '1an': ['سنة', 'سنة واحدة', '1 سنة', '12 شهر', '12 أشهر'],
}


def convertir(apps, schema_editor):
    """Ne touche QUE les valeurs reconnues avec certitude — toute autre
    valeur (y compris déjà un code du nouveau schéma, ou un texte
    non reconnu) reste TELLE QUELLE : TypeAbonnement.duree_affichee
    (get_duree_display() or label) affiche alors ce texte tel quel plutôt
    qu'un code brut, donc aucune perte d'information visible pour le مدير
    même sans conversion — voir la docstring de duree_affichee."""
    TypeAbonnement = apps.get_model('inscriptions', 'TypeAbonnement')
    inverse = {variante: code for code, variantes in VARIANTES_CONNUES.items() for variante in variantes}
    for abonnement in TypeAbonnement.objects.exclude(duree=''):
        code = inverse.get(abonnement.duree)
        if code:
            abonnement.duree = code
            abonnement.save(update_fields=['duree'])


def reverse_convertir(apps, schema_editor):
    """Best-effort (même principe que 0024/0025) : reconvertit un code
    connu vers SA PREMIÈRE variante d'origine — ne restaure pas fidèlement
    une variante différente choisie parmi plusieurs (ex: '3أشهر' redevient
    '3 أشهر'), acceptable pour une réversibilité de secours."""
    TypeAbonnement = apps.get_model('inscriptions', 'TypeAbonnement')
    for abonnement in TypeAbonnement.objects.filter(duree__in=VARIANTES_CONNUES.keys()):
        abonnement.duree = VARIANTES_CONNUES[abonnement.duree][0]
        abonnement.save(update_fields=['duree'])


class Migration(migrations.Migration):

    dependencies = [
        ('inscriptions', '0028_typeabonnement_duree_choix_ferme'),
    ]

    operations = [
        migrations.RunPython(convertir, reverse_convertir),
    ]
