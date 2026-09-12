# Rattache 2 des 4 critères historiques (seedés par
# 0022_seed_criteres_eleves_et_backfill.py) à leur axe respectif, selon la
# répartition EXACTE donnée par le client le 2026-09-12 :
#   séance impaire (الحفظ)    : الحفظ + التلاوة + المواظبة والسلوك
#   séance paire   (المراجعة) : المراجعة + الحفظ + المواظبة والسلوك
# "الحفظ" et "المواظبة والسلوك" restent 'commun' (valeur par défaut du champ,
# jamais touchée ici) : présents dans les 2 cas d'après le client. Seuls
# "التلاوة" (absente des séances de révision) et "المراجعة" (absente des
# séances de حفظ) sont basculés ici.
from django.db import migrations

CORRESPONDANCE = {
    'التلاوة': 'hifz',
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
