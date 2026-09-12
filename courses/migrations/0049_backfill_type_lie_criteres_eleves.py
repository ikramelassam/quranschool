# Rattache le critère historique المراجعة (seedé par
# 0022_seed_criteres_eleves_et_backfill.py) à l'axe مراجعة — c'est le SEUL
# critère numérique masqué quand le prof choisit "الحفظ" pour la séance (voir
# Seance.type_evaluation). Les 3 autres (الحفظ، التلاوة، المواظبة والسلوك)
# restent 'commun' (valeur par défaut du champ, jamais touchée ici) :
# précision demandée par le client le 2026-09-12 — la qualité de récitation
# par cœur (الحفظ) reste évaluée même une séance où le contenu du jour est de
# la révision (on y récite justement DU DÉJÀ-mémorisé), donc ce critère ne
# doit jamais disparaître, contrairement à la ZONE "quelle sourate/ayat" (elle,
# bien basculée par Seance.type_evaluation — voir dashboard.views.
# prof_seance_detail/prof_presence_sauvegarder).
from django.db import migrations

CORRESPONDANCE = {
    'المراجعة': 'mouraja3a',
}


def backfill(apps, schema_editor):
    CritereEleve = apps.get_model('courses', 'CritereEleve')
    for nom_ar, type_lie in CORRESPONDANCE.items():
        CritereEleve.objects.filter(nom_ar=nom_ar).update(type_lie=type_lie)


def revert(apps, schema_editor):
    CritereEleve = apps.get_model('courses', 'CritereEleve')
    CritereEleve.objects.filter(nom_ar__in=CORRESPONDANCE.keys()).update(type_lie='commun')


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0048_seance_type_evaluation_et_critere_eleve_type_lie'),
    ]

    operations = [
        migrations.RunPython(backfill, revert),
    ]
