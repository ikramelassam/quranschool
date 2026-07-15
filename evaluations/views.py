from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import role_required
from accounts.models import Superviseur
from courses.models import Seance, Presence
from .models import Critere, Evaluation, NoteEvaluation


def _metadonnees_seance(seance):
    """Infos contextuelles de la fiche d'évaluation, dérivées de la séance
    (pas ressaisies à la main par le superviseur)."""
    return {
        'date': seance.date,
        'halqa': seance.groupe.nom,
        'prof': seance.groupe.prof.user.get_full_name() if seance.groupe.prof else None,
        'nb_apprenants_presents': Presence.objects.filter(seance=seance, statut='present').count(),
    }


@role_required('superviseur')
def superviseur_evaluation_detail(request, seance_id):
    """Consultation en lecture seule d'une évaluation déjà soumise. Séparée
    du formulaire d'édition (superviseur_evaluer) pour que 'voir' et
    'modifier' restent deux actions distinctes."""
    superviseur = get_object_or_404(Superviseur, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof__in=superviseur.profs_assignes.all())
    evaluation = get_object_or_404(Evaluation, seance=seance)
    notes = evaluation.notes.select_related('critere').order_by('critere__ordre')

    return render(request, 'dashboard/superviseur_evaluation_detail.html', {
        'seance': seance,
        'evaluation': evaluation,
        'notes': notes,
        'metadonnees': _metadonnees_seance(seance),
    })


@role_required('superviseur')
def superviseur_evaluer(request, seance_id):
    superviseur = get_object_or_404(Superviseur, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id, groupe__prof__in=superviseur.profs_assignes.all())
    criteres = Critere.objects.filter(est_actif=True)

    evaluation = Evaluation.objects.filter(seance=seance).first()
    notes_existantes = {}
    if evaluation:
        notes_existantes = {n.critere_id: n.note for n in evaluation.notes.all()}

    if request.method == 'POST':
        commentaire = request.POST.get('commentaire', '').strip()

        if not commentaire:
            messages.error(request, 'حقل "ملاحظات وتوجيهات" إلزامي — يرجى تعبئته قبل الحفظ.')
            criteres_notes = [
                {
                    'critere': critere,
                    'note': int(request.POST[f'note_{critere.id}']) if request.POST.get(f'note_{critere.id}') else None,
                }
                for critere in criteres
            ]
            return render(request, 'dashboard/superviseur_evaluer.html', {
                'seance': seance,
                'evaluation': evaluation,
                'criteres_notes': criteres_notes,
                'commentaire_initial': commentaire,
                'metadonnees': _metadonnees_seance(seance),
            })

        evaluation, _ = Evaluation.objects.update_or_create(
            seance=seance,
            defaults={
                'superviseur': superviseur,
                'commentaire': commentaire,
            }
        )
        for critere in criteres:
            note = request.POST.get(f'note_{critere.id}')
            if note:
                NoteEvaluation.objects.update_or_create(
                    evaluation=evaluation,
                    critere=critere,
                    defaults={'note': note},
                )
        messages.success(request, 'تم حفظ تقييم المعلم بنجاح.')
        return redirect('superviseur_seance_detail', seance_id=seance.id)

    criteres_notes = [
        {'critere': critere, 'note': notes_existantes.get(critere.id)}
        for critere in criteres
    ]

    return render(request, 'dashboard/superviseur_evaluer.html', {
        'seance': seance,
        'evaluation': evaluation,
        'criteres_notes': criteres_notes,
        'commentaire_initial': evaluation.commentaire if evaluation else '',
        'metadonnees': _metadonnees_seance(seance),
    })
