# Generated manually — Chantier "salaire prof par nb séances/semaine" du 2026-08-27

from django.db import migrations

# Cases initiales du catalogue partagé (Besoin 1.5) — 1/2/3, comme demandé
# explicitement ; le مدير/مشرف peut en ajouter d'autres depuis son profil
# APRÈS ce seed (voir dashboard.views.admin_option_nb_seances_ajouter).
OPTIONS_NB_SEANCES = [1, 2, 3]

# Barème salaire prof GROUPE (Besoin 3, "Règles cibles") — montant fixe par
# élève actif par mois, selon tranche_age × nb_slots.
TARIFS_GROUPE = [
    ('adulte', 1, 40),
    ('adulte', 2, 60),
    ('adulte', 3, 100),
    ('enfant', 1, 50),
    ('enfant', 2, 90),
    ('enfant', 3, 120),
]

# Tarif salaire prof INDIVIDUEL (Besoin 3) — 35 د.م. par séance réellement
# dispensée, IDENTIQUE pour les 2 tranches d'âge au moment du seed (valeur
# communiquée telle quelle par le client — voir TarifRemunerationIndividuel.__doc__
# pour la décision explicite de garder l'axe tranche_age malgré ce montant
# identique, afin de pouvoir les différencier plus tard sans migration).
TARIF_INDIVIDUEL = 35


def seed(apps, schema_editor):
    OptionNbSeances = apps.get_model('courses', 'OptionNbSeances')
    TarifRemunerationGroupe = apps.get_model('courses', 'TarifRemunerationGroupe')
    TarifRemunerationIndividuel = apps.get_model('courses', 'TarifRemunerationIndividuel')

    for ordre, valeur in enumerate(OPTIONS_NB_SEANCES, start=1):
        OptionNbSeances.objects.get_or_create(valeur=valeur, defaults={'ordre': ordre})

    for tranche_age, nb_slots, montant in TARIFS_GROUPE:
        TarifRemunerationGroupe.objects.get_or_create(
            tranche_age=tranche_age, nb_slots=nb_slots, defaults={'montant': montant},
        )

    for tranche_age in ('enfant', 'adulte'):
        TarifRemunerationIndividuel.objects.get_or_create(
            tranche_age=tranche_age, defaults={'montant': TARIF_INDIVIDUEL},
        )


def reverse_seed(apps, schema_editor):
    OptionNbSeances = apps.get_model('courses', 'OptionNbSeances')
    TarifRemunerationGroupe = apps.get_model('courses', 'TarifRemunerationGroupe')
    TarifRemunerationIndividuel = apps.get_model('courses', 'TarifRemunerationIndividuel')

    OptionNbSeances.objects.filter(valeur__in=OPTIONS_NB_SEANCES).delete()
    for tranche_age, nb_slots, _ in TARIFS_GROUPE:
        TarifRemunerationGroupe.objects.filter(tranche_age=tranche_age, nb_slots=nb_slots).delete()
    TarifRemunerationIndividuel.objects.filter(tranche_age__in=['enfant', 'adulte']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0039_optionnbseances_tarifs_groupe_individuel'),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
