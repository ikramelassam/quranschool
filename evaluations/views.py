from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from accounts.decorators import role_required
from accounts.models import Superviseur
from courses.models import Seance
from .models import Critere, Evaluation, NoteEvaluation


@role_required('superviseur')
def superviseur_evaluer(request, seance_id):
    superviseur = get_object_or_404(Superviseur, user=request.user)
    seance = get_object_or_404(Seance, id=seance_id)
    criteres = Critere.objects.all()

    evaluation = Evaluation.objects.filter(seance=seance).first()
    notes_existantes = {}
    if evaluation:
        notes_existantes = {n.critere_id: n.note for n in evaluation.notes.all()}

    if request.method == 'POST':
        evaluation, _ = Evaluation.objects.update_or_create(
            seance=seance,
            defaults={
                'superviseur': superviseur,
                'commentaire': request.POST.get('commentaire', ''),
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
    })
