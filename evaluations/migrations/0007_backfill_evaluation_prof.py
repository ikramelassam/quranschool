from django.db import migrations


def backfiller_prof_depuis_seance(apps, schema_editor):
    """Renseigne Evaluation.prof pour les évaluations déjà en base (créées
    avant l'ajout du champ), à partir de evaluation.seance.groupe.prof —
    seule source disponible pour reconstituer rétroactivement qui était
    évalué. Ne peut pas garantir 100% : si le groupe n'a déjà plus de prof
    aujourd'hui (SET_NULL déjà survenu avant cette migration), la ligne
    reste à prof=None — affiché explicitement ci-dessous, pas silencieux."""
    Evaluation = apps.get_model('evaluations', 'Evaluation')

    a_traiter = Evaluation.objects.filter(prof__isnull=True).select_related('seance__groupe')
    total_avant = a_traiter.count()

    non_backfillables = 0
    for evaluation in a_traiter:
        prof_id = evaluation.seance.groupe.prof_id if evaluation.seance and evaluation.seance.groupe_id else None
        if prof_id:
            evaluation.prof_id = prof_id
            evaluation.save(update_fields=['prof'])
        else:
            non_backfillables += 1

    restant_apres = Evaluation.objects.filter(prof__isnull=True).count()
    print(
        f'\n  [backfill Evaluation.prof] {total_avant} évaluation(s) sans prof avant — '
        f'{total_avant - restant_apres} rattachée(s) via seance.groupe.prof — '
        f'{restant_apres} encore à prof=None après (groupe déjà sans prof à ce jour, '
        f'attendu={non_backfillables}).'
    )


class Migration(migrations.Migration):

    dependencies = [
        ('evaluations', '0006_evaluation_prof'),
    ]

    operations = [
        migrations.RunPython(backfiller_prof_depuis_seance, reverse_code=migrations.RunPython.noop),
    ]
