from django.db.models import Avg


def moyenne_mensuelle_prof(prof, annee, num_mois):
    """{'moyenne': .../4 ou None, 'nb_evaluations': int} pour un prof sur un
    mois donné — moyenne des moyennes par critères notés, une évaluation par
    séance. Seule implémentation de ce calcul, réutilisée par
    dashboard.views.classement_mensuel_profs ET superviseur_profil (Tâche 13
    du 2026-07-25) — ne jamais dupliquer cette requête ailleurs."""
    from .models import Evaluation

    evaluations = Evaluation.objects.filter(
        seance__groupe__prof=prof,
        seance__date__year=annee,
        seance__date__month=num_mois,
    ).annotate(moyenne_evaluation=Avg('notes__note'))
    moyennes = [e.moyenne_evaluation for e in evaluations if e.moyenne_evaluation is not None]
    return {
        'moyenne': round(sum(moyennes) / len(moyennes), 2) if moyennes else None,
        'nb_evaluations': len(moyennes),
    }
