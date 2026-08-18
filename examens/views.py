"""Vues d'Examens. Chaque vue qui touche un Examen/une Copie précis passe par
examens.permissions (jamais de condition d'accès recodée localement — même
règle que chat/views.py). Le serveur revalide TOUJOURS le chrono et le statut
avant toute écriture (§9/§16 du cahier des charges) : aucun champ hidden, id
ou statut envoyé par le client n'est jamais considéré comme fiable."""
from django.contrib import messages
from django.db.models import Count, Max
from django.http import HttpResponseForbidden, HttpResponseBadRequest, JsonResponse
from django.shortcuts import render, redirect, get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST, require_GET

from accounts.decorators import role_required
from .models import Examen, Question, ChoixQuestion, Copie, Reponse
from .permissions import (
    get_examens_accessibles, can_access_examen, can_gerer_examen, can_corriger_examen,
    can_access_copie, can_modifier_copie,
)
from .services import (
    parser_datetime_local, demarrer_ou_recuperer_copie, finaliser_si_expiree,
    soumettre_copie, enregistrer_correction_manuelle, motif_non_publiable,
    valider_fichier_audio, valider_fichier_video, statut_affichage_eleve,
)

NB_MAX_CHOIX = 6  # nombre maximum de propositions pour une question 'choix'

BASE_TEMPLATE_PAR_ROLE = {
    'admin': 'dashboard/base_admin.html',
    'prof': 'dashboard/base_prof.html',
    'eleve': 'dashboard/base_eleve.html',
    'superviseur': 'dashboard/base_superviseur.html',
    'mshrif': 'dashboard/base_mshrif.html',
}


def _base_template(request):
    return BASE_TEMPLATE_PAR_ROLE[request.user.role]


# ==================== Prof — gestion des examens ====================


@role_required('prof')
def prof_examens_liste(request):
    prof = request.user.prof
    examens = (
        Examen.objects.filter(groupe__prof=prof)
        .select_related('groupe')
        .annotate(
            nb_questions_annot=Count('questions', distinct=True),
            nb_copies_annot=Count('copies', distinct=True),
        )
        .order_by('-date_creation')
    )
    return render(request, 'examens/prof_liste.html', {'examens': examens})


@role_required('prof')
def examen_ajouter(request):
    prof = request.user.prof
    groupes = prof.groupes.filter(statut='actif')

    if request.method == 'POST':
        erreur, examen = _valider_et_enregistrer_examen(request, prof, groupes, examen=None)
        if erreur:
            messages.error(request, erreur)
            return render(request, 'examens/prof_form.html', {
                'groupes': groupes, 'examen': None, 'valeurs': request.POST,
            })
        messages.success(request, 'تم إنشاء الاختبار كمسودة. أضف الأسئلة ثم انشره.')
        return redirect('examens_prof_detail', examen.id)

    return render(request, 'examens/prof_form.html', {'groupes': groupes, 'examen': None})


@role_required('prof')
def examen_modifier(request, examen_id):
    examen = get_object_or_404(Examen, id=examen_id)
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية تعديل هذا الاختبار.')
    prof = request.user.prof
    groupes = prof.groupes.filter(statut='actif')

    if request.method == 'POST':
        erreur, examen = _valider_et_enregistrer_examen(request, prof, groupes, examen=examen)
        if erreur:
            messages.error(request, erreur)
            return render(request, 'examens/prof_form.html', {
                'groupes': groupes, 'examen': examen, 'valeurs': request.POST,
            })
        messages.success(request, 'تم حفظ التعديلات.')
        return redirect('examens_prof_detail', examen.id)

    return render(request, 'examens/prof_form.html', {'groupes': groupes, 'examen': examen})


def _valider_et_enregistrer_examen(request, prof, groupes_autorises, examen):
    """Cœur commun à examen_ajouter/examen_modifier. Renvoie (erreur, examen) —
    erreur=None si la sauvegarde a réussi. titre/instructions sont TOUJOURS
    modifiables (non concernés par le verrou de structure, §5 du cahier des
    charges). groupe/date_debut/date_limite/duree_minutes ne sont acceptés
    que si examen est None (création) ou examen.chrono_modifiable (aucune
    copie démarrée) — décision validée le 2026-08-16 : silencieusement
    ignorés sinon, jamais une erreur bloquante sur les champs non concernés
    (titre/instructions) de la même soumission."""
    titre = (request.POST.get('titre') or '').strip()
    instructions = request.POST.get('instructions', '').strip()
    if not titre:
        return "يجب إدخال عنوان للاختبار.", examen

    chrono_modifiable = examen is None or examen.chrono_modifiable
    if chrono_modifiable:
        groupe_id = request.POST.get('groupe')
        groupe = groupes_autorises.filter(id=groupe_id).first()
        date_debut = parser_datetime_local(request.POST.get('date_debut'))
        date_limite = parser_datetime_local(request.POST.get('date_limite'))
        duree_minutes_raw = request.POST.get('duree_minutes')

        if not groupe:
            return "يجب اختيار إحدى حلقاتك.", examen
        if not date_debut or not date_limite:
            return "يجب تحديد تاريخ البداية والتاريخ النهائي.", examen
        if date_limite <= date_debut:
            return "التاريخ النهائي يجب أن يكون بعد تاريخ البداية.", examen
        try:
            duree_minutes = int(duree_minutes_raw)
            if duree_minutes < 1:
                raise ValueError
        except (TypeError, ValueError):
            return "يجب إدخال مدة صحيحة بالدقائق.", examen

    if examen is None:
        examen = Examen.objects.create(
            groupe=groupe, prof=prof, titre=titre, instructions=instructions,
            date_debut=date_debut, date_limite=date_limite, duree_minutes=duree_minutes,
        )
        return None, examen

    examen.titre = titre
    examen.instructions = instructions
    champs = ['titre', 'instructions']
    if chrono_modifiable:
        examen.groupe = groupe
        examen.date_debut = date_debut
        examen.date_limite = date_limite
        examen.duree_minutes = duree_minutes
        champs += ['groupe', 'date_debut', 'date_limite', 'duree_minutes']
    examen.save(update_fields=champs)
    return None, examen


@role_required('prof')
def examen_detail(request, examen_id):
    examen = get_object_or_404(Examen.objects.select_related('groupe'), id=examen_id)
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذا الاختبار.')

    questions = examen.questions.prefetch_related('choix')
    copies_soumises = list(examen.copies.filter(statut='soumise').prefetch_related('reponses'))
    nb_a_corriger = sum(1 for c in copies_soumises if not c.correction_complete)

    return render(request, 'examens/prof_detail.html', {
        'examen': examen,
        'questions': questions,
        'nb_copies': examen.copies.count(),
        'nb_copies_soumises': len(copies_soumises),
        'nb_a_corriger': nb_a_corriger,
    })


@role_required('prof')
@require_POST
def examen_publier(request, examen_id):
    examen = get_object_or_404(Examen, id=examen_id)
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية نشر هذا الاختبار.')
    if examen.statut != 'brouillon':
        messages.error(request, "لا يمكن نشر اختبار ليس في حالة مسودة.")
        return redirect('examens_prof_detail', examen.id)

    motif = motif_non_publiable(examen)
    if motif:
        messages.error(request, motif)
        return redirect('examens_prof_detail', examen.id)

    examen.statut = 'publie'
    examen.date_publication = timezone.now()
    examen.save(update_fields=['statut', 'date_publication'])
    messages.success(request, 'تم نشر الاختبار. أصبح مرئياً لطلاب الحلقة.')
    return redirect('examens_prof_detail', examen.id)


@role_required('prof')
@require_POST
def examen_fermer(request, examen_id):
    examen = get_object_or_404(Examen, id=examen_id)
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية إغلاق هذا الاختبار.')
    if examen.statut != 'publie':
        messages.error(request, "لا يمكن إغلاق اختبار ليس منشوراً.")
        return redirect('examens_prof_detail', examen.id)

    examen.statut = 'ferme'
    examen.save(update_fields=['statut'])
    messages.success(request, 'تم إغلاق الاختبار. لن يتمكن أي طالب من بدء محاولة جديدة.')
    return redirect('examens_prof_detail', examen.id)


def _valider_et_enregistrer_question(request, examen, question=None):
    """Cœur commun à question_ajouter/question_modifier — voir docstrings des
    2 vues. Renvoie un message d'erreur arabe, ou None si la sauvegarde a
    réussi."""
    type_question = request.POST.get('type_question')
    enonce = (request.POST.get('enonce') or '').strip()
    points_raw = request.POST.get('points')

    if type_question not in dict(Question.TYPE_CHOICES):
        return "نوع السؤال غير صالح."
    if not enonce:
        return "يجب إدخال نص السؤال."
    try:
        points = int(points_raw)
        if points < 1:
            raise ValueError
    except (TypeError, ValueError):
        return "يجب إدخال عدد نقاط صحيح (1 على الأقل)."

    reponse_correcte_bool = None
    choix_valides = []
    index_correct = None

    if type_question == 'vrai_faux':
        valeur = request.POST.get('reponse_correcte_bool')
        if valeur not in ('true', 'false'):
            return "يجب تحديد الإجابة الصحيحة (صح أو خطأ)."
        reponse_correcte_bool = (valeur == 'true')

    elif type_question == 'choix':
        for i in range(NB_MAX_CHOIX):
            texte = (request.POST.get(f'choix_texte_{i}') or '').strip()
            if texte:
                choix_valides.append((i, texte))
        if len(choix_valides) < 2:
            return "يجب إدخال مقترحين على الأقل."
        indices_valides = {i for i, _ in choix_valides}
        try:
            index_correct = int(request.POST.get('choix_correct'))
        except (TypeError, ValueError):
            index_correct = None
        if index_correct not in indices_valides:
            return "يجب تحديد إجابة صحيحة واحدة من بين المقترحات المدخلة."

    if question is None:
        dernier_ordre = examen.questions.aggregate(m=Max('ordre'))['m'] or 0
        question = Question(examen=examen, ordre=dernier_ordre + 1)

    question.type_question = type_question
    question.enonce = enonce
    question.points = points
    question.reponse_correcte_bool = reponse_correcte_bool
    question.save()

    question.choix.all().delete()
    if type_question == 'choix':
        for i, texte in choix_valides:
            ChoixQuestion.objects.create(
                question=question, texte=texte, ordre=i, est_correct=(i == index_correct),
            )

    return None


def _lignes_choix_contexte(request_post=None, question=None):
    """Construit NB_MAX_CHOIX lignes {index, texte, correct} pour préremplir
    le formulaire d'une question 'choix' dans le template — depuis les
    valeurs POST si une soumission vient d'échouer (réaffichage fidèle de ce
    que le prof avait tapé), sinon depuis les ChoixQuestion existants
    (édition) ou vide (création)."""
    if request_post is not None:
        try:
            index_correct = int(request_post.get('choix_correct'))
        except (TypeError, ValueError):
            index_correct = None
        return [
            {'index': i, 'texte': request_post.get(f'choix_texte_{i}', ''), 'correct': i == index_correct}
            for i in range(NB_MAX_CHOIX)
        ]

    choix_existants = list(question.choix.all()) if question else []
    lignes = []
    for i in range(NB_MAX_CHOIX):
        if i < len(choix_existants):
            lignes.append({'index': i, 'texte': choix_existants[i].texte, 'correct': choix_existants[i].est_correct})
        else:
            lignes.append({'index': i, 'texte': '', 'correct': False})
    return lignes


@role_required('prof')
def question_ajouter(request, examen_id):
    examen = get_object_or_404(Examen, id=examen_id)
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية تعديل هذا الاختبار.')
    if not examen.structure_modifiable:
        messages.error(request, "لا يمكن تعديل أسئلة اختبار توجد له نسخ مُقدَّمة بالفعل.")
        return redirect('examens_prof_detail', examen.id)

    if request.method == 'POST':
        erreur = _valider_et_enregistrer_question(request, examen)
        if erreur:
            messages.error(request, erreur)
            return render(request, 'examens/question_form.html', {
                'examen': examen, 'question': None, 'valeurs': request.POST,
                'lignes_choix': _lignes_choix_contexte(request_post=request.POST),
            })
        messages.success(request, 'تمت إضافة السؤال.')
        return redirect('examens_prof_detail', examen.id)

    return render(request, 'examens/question_form.html', {
        'examen': examen, 'question': None, 'lignes_choix': _lignes_choix_contexte(),
    })


@role_required('prof')
def question_modifier(request, question_id):
    question = get_object_or_404(Question.objects.select_related('examen'), id=question_id)
    examen = question.examen
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية تعديل هذا الاختبار.')
    if not examen.structure_modifiable:
        messages.error(request, "لا يمكن تعديل أسئلة اختبار توجد له نسخ مُقدَّمة بالفعل.")
        return redirect('examens_prof_detail', examen.id)

    if request.method == 'POST':
        erreur = _valider_et_enregistrer_question(request, examen, question=question)
        if erreur:
            messages.error(request, erreur)
            return render(request, 'examens/question_form.html', {
                'examen': examen, 'question': question, 'valeurs': request.POST,
                'lignes_choix': _lignes_choix_contexte(request_post=request.POST),
            })
        messages.success(request, 'تم حفظ التعديلات على السؤال.')
        return redirect('examens_prof_detail', examen.id)

    return render(request, 'examens/question_form.html', {
        'examen': examen, 'question': question, 'lignes_choix': _lignes_choix_contexte(question=question),
    })


@role_required('prof')
@require_POST
def question_supprimer(request, question_id):
    question = get_object_or_404(Question.objects.select_related('examen'), id=question_id)
    examen = question.examen
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية تعديل هذا الاختبار.')
    if not examen.structure_modifiable:
        messages.error(request, "لا يمكن حذف أسئلة اختبار توجد له نسخ مُقدَّمة بالفعل.")
        return redirect('examens_prof_detail', examen.id)

    examen_id = examen.id
    question.delete()
    messages.success(request, 'تم حذف السؤال.')
    return redirect('examens_prof_detail', examen_id)


def _deplacer_question(request, question_id, sens):
    question = get_object_or_404(Question.objects.select_related('examen'), id=question_id)
    examen = question.examen
    if not can_gerer_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية تعديل هذا الاختبار.')
    if not examen.structure_modifiable:
        messages.error(request, "لا يمكن إعادة ترتيب أسئلة اختبار توجد له نسخ مُقدَّمة بالفعل.")
        return redirect('examens_prof_detail', examen.id)

    questions = list(examen.questions.all())
    index = next((i for i, q in enumerate(questions) if q.id == question.id), None)
    if index is not None:
        index_voisin = index + sens
        if 0 <= index_voisin < len(questions):
            voisin = questions[index_voisin]
            question.ordre, voisin.ordre = voisin.ordre, question.ordre
            Question.objects.bulk_update([question, voisin], ['ordre'])
    return redirect('examens_prof_detail', examen.id)


@role_required('prof')
@require_POST
def question_monter(request, question_id):
    return _deplacer_question(request, question_id, sens=-1)


@role_required('prof')
@require_POST
def question_descendre(request, question_id):
    return _deplacer_question(request, question_id, sens=1)


@role_required('prof')
def examen_copies(request, examen_id):
    examen = get_object_or_404(Examen, id=examen_id)
    if not can_corriger_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى نسخ هذا الاختبار.')

    copies = (
        examen.copies.select_related('eleve__user')
        .prefetch_related('reponses')
        .order_by('eleve__user__first_name', 'eleve__user__last_name')
    )
    return render(request, 'examens/prof_copies.html', {'examen': examen, 'copies': copies})


@role_required('prof')
def copie_correction(request, copie_id):
    copie = get_object_or_404(Copie.objects.select_related('examen__groupe', 'eleve__user'), id=copie_id)
    if not can_corriger_examen(request.user, copie.examen):
        return HttpResponseForbidden('ليس لديك صلاحية تصحيح هذه النسخة.')
    if copie.statut != 'soumise':
        messages.error(request, "لا يمكن تصحيح نسخة لم تُقدَّم بعد.")
        return redirect('examens_prof_copies', copie.examen_id)

    if request.method == 'POST':
        reponse = get_object_or_404(Reponse, id=request.POST.get('reponse_id'), copie=copie)
        if reponse.question.type_question not in ('texte', 'audio', 'video'):
            return HttpResponseBadRequest('لا يمكن تصحيح هذا النوع من الأسئلة يدوياً — يتم تصحيحه تلقائياً.')

        try:
            points = float(request.POST.get('points_obtenus'))
        except (TypeError, ValueError):
            messages.error(request, "يجب إدخال عدد نقاط صحيح.")
            return redirect('examens_copie_correction', copie.id)
        if points < 0 or points > float(reponse.question.points):
            messages.error(request, f"النقاط يجب أن تكون بين 0 و {reponse.question.points}.")
            return redirect('examens_copie_correction', copie.id)

        commentaire = request.POST.get('commentaire', '').strip()
        enregistrer_correction_manuelle(reponse, points, commentaire)
        messages.success(request, 'تم حفظ التصحيح.')
        return redirect('examens_copie_correction', copie.id)

    reponses = copie.reponses.select_related('question', 'reponse_choix').order_by('question__ordre')
    return render(request, 'examens/copie_correction.html', {'copie': copie, 'examen': copie.examen, 'reponses': reponses})


# ==================== Élève ====================


@role_required('eleve')
def eleve_examens_liste(request):
    eleve = request.user.eleve
    examens = list(get_examens_accessibles(request.user).select_related('groupe').order_by('-date_debut'))
    copies_par_examen = {
        c.examen_id: c for c in Copie.objects.filter(eleve=eleve, examen__in=examens)
    }
    for examen in examens:
        copie = copies_par_examen.get(examen.id)
        examen.copie_utilisateur = copie
        examen.statut_affichage = statut_affichage_eleve(examen, copie)

    return render(request, 'examens/eleve_liste.html', {'examens': examens})


@role_required('eleve')
def eleve_examen_avant(request, examen_id):
    examen = get_object_or_404(Examen.objects.select_related('groupe'), id=examen_id)
    if not can_access_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذا الاختبار.')
    eleve = request.user.eleve

    copie = Copie.objects.filter(examen=examen, eleve=eleve).first()
    if copie:
        copie = finaliser_si_expiree(copie)
        if copie.statut == 'en_cours':
            return redirect('examens_passage', copie.id)
        return redirect('examens_eleve_resultat', copie.id)

    if request.method == 'POST':
        if not examen.peut_etre_commence:
            messages.error(request, "هذا الاختبار غير متاح حالياً.")
            return redirect('examens_eleve_liste')
        copie, _ = demarrer_ou_recuperer_copie(examen, eleve)
        return redirect('examens_passage', copie.id)

    return render(request, 'examens/eleve_avant.html', {
        'examen': examen,
        'statut_affichage': statut_affichage_eleve(examen, None),
    })


@role_required('eleve')
def examen_passage(request, copie_id):
    copie = get_object_or_404(Copie.objects.select_related('examen__groupe'), id=copie_id)
    if not can_access_copie(request.user, copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذه النسخة.')

    copie = finaliser_si_expiree(copie)
    if copie.statut != 'en_cours':
        return redirect('examens_eleve_resultat', copie.id)

    questions = copie.examen.questions.prefetch_related('choix')
    reponses = {r.question_id: r for r in copie.reponses.all()}

    return render(request, 'examens/passage.html', {
        'copie': copie,
        'examen': copie.examen,
        'questions': questions,
        'reponses': reponses,
        'temps_restant_secondes': copie.temps_restant_secondes,
    })


@role_required('eleve')
@require_POST
def reponse_autosave(request, copie_id, question_id):
    copie = get_object_or_404(Copie, id=copie_id)
    if not can_access_copie(request.user, copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذه النسخة.')

    copie = finaliser_si_expiree(copie)
    if not can_modifier_copie(request.user, copie):
        return JsonResponse({'ok': False, 'erreur': 'انتهت مهلة الاختبار أو تم تسليمه بالفعل.'}, status=409)

    question = get_object_or_404(Question, id=question_id, examen_id=copie.examen_id)
    reponse, _ = Reponse.objects.get_or_create(copie=copie, question=question)

    if question.type_question == 'choix':
        choix_id = request.POST.get('choix_id')
        reponse.reponse_choix = question.choix.filter(id=choix_id).first() if choix_id else None
        reponse.save(update_fields=['reponse_choix', 'date_reponse'])

    elif question.type_question == 'vrai_faux':
        valeur = request.POST.get('valeur')
        reponse.reponse_bool = {'true': True, 'false': False}.get(valeur)
        reponse.save(update_fields=['reponse_bool', 'date_reponse'])

    elif question.type_question == 'texte':
        reponse.reponse_texte = request.POST.get('reponse_texte', '')
        reponse.save(update_fields=['reponse_texte', 'date_reponse'])

    elif question.type_question == 'audio':
        if request.POST.get('supprimer') == '1':
            if reponse.reponse_audio:
                reponse.reponse_audio.delete(save=False)
            reponse.reponse_audio = None
            reponse.nom_fichier_audio_original = ''
            reponse.save(update_fields=['reponse_audio', 'nom_fichier_audio_original', 'date_reponse'])
        else:
            fichier = request.FILES.get('reponse_audio')
            if not fichier:
                return JsonResponse({'ok': False, 'erreur': 'لم يتم إرفاق أي ملف.'}, status=400)
            erreur = valider_fichier_audio(fichier)
            if erreur:
                return JsonResponse({'ok': False, 'erreur': erreur}, status=400)
            if reponse.reponse_audio:
                reponse.reponse_audio.delete(save=False)
            reponse.reponse_audio = fichier
            reponse.nom_fichier_audio_original = fichier.name
            reponse.save(update_fields=['reponse_audio', 'nom_fichier_audio_original', 'date_reponse'])

    elif question.type_question == 'video':
        if request.POST.get('supprimer') == '1':
            if reponse.reponse_video:
                reponse.reponse_video.delete(save=False)
            reponse.reponse_video = None
            reponse.nom_fichier_video_original = ''
            reponse.save(update_fields=['reponse_video', 'nom_fichier_video_original', 'date_reponse'])
        else:
            fichier = request.FILES.get('reponse_video')
            if not fichier:
                return JsonResponse({'ok': False, 'erreur': 'لم يتم إرفاق أي ملف.'}, status=400)
            erreur = valider_fichier_video(fichier)
            if erreur:
                return JsonResponse({'ok': False, 'erreur': erreur}, status=400)
            if reponse.reponse_video:
                reponse.reponse_video.delete(save=False)
            reponse.reponse_video = fichier
            reponse.nom_fichier_video_original = fichier.name
            reponse.save(update_fields=['reponse_video', 'nom_fichier_video_original', 'date_reponse'])
    else:
        return HttpResponseBadRequest('نوع سؤال غير معروف.')

    return JsonResponse({'ok': True, 'temps_restant_secondes': copie.temps_restant_secondes})


@role_required('eleve')
@require_POST
def examen_soumettre(request, copie_id):
    copie = get_object_or_404(Copie, id=copie_id)
    if not can_access_copie(request.user, copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذه النسخة.')

    copie = finaliser_si_expiree(copie)
    if copie.statut != 'en_cours':
        messages.info(request, "تم تسليم هذا الاختبار مسبقاً.")
        return redirect('examens_eleve_resultat', copie.id)

    copie = soumettre_copie(copie, automatique=False)
    # Pas de messages.success() ici (bug de duplication du 2026-08-16) :
    # examens_eleve_resultat affiche déjà sa propre carte de statut
    # ("📩 تم تسليم إجاباتك" / note si déjà corrigée) — une bannière de
    # succès en plus aurait fait doublon avec cette carte, en plus du
    # doublon structurel qu'avait la page elle-même (voir templates/
    # examens/eleve_resultat.html, qui incluait _messages.html deux fois).
    return redirect('examens_eleve_resultat', copie.id)


@role_required('eleve')
def eleve_copie_resultat(request, copie_id):
    copie = get_object_or_404(Copie.objects.select_related('examen__groupe'), id=copie_id)
    if not can_access_copie(request.user, copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذه النسخة.')

    reponses = copie.reponses.select_related('question', 'reponse_choix').order_by('question__ordre')
    return render(request, 'examens/eleve_resultat.html', {'copie': copie, 'examen': copie.examen, 'reponses': reponses})


# ==================== Audio protégé (élève, prof, superviseur, admin, mshrif) ====================

ROLES_AVEC_ACCES_EXAMENS = ('eleve', 'prof', 'superviseur', 'admin', 'mshrif')


@role_required(*ROLES_AVEC_ACCES_EXAMENS)
@require_GET
def reponse_audio(request, reponse_id):
    """Accès sécurisé à un fichier audio de réponse — l'URL réelle du fichier
    (Cloudinary en prod, /media/ en dev) n'est JAMAIS imprimée directement
    dans un template Examens : seule cette vue, après vérification
    can_access_copie, redirige vers le fichier. Même patron que
    chat.views.chat_fichier."""
    reponse = get_object_or_404(Reponse.objects.select_related('copie__examen', 'copie__eleve'), id=reponse_id)
    if not can_access_copie(request.user, reponse.copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذا الملف الصوتي.')
    if not reponse.reponse_audio:
        return HttpResponseBadRequest('لا يوجد ملف صوتي مرفق بهذه الإجابة.')
    return redirect(reponse.reponse_audio.url)


@role_required(*ROLES_AVEC_ACCES_EXAMENS)
@require_GET
def reponse_video(request, reponse_id):
    """Accès sécurisé à un fichier vidéo de réponse — même patron que
    reponse_audio ci-dessus (l'URL réelle du fichier n'est jamais imprimée
    directement dans un template)."""
    reponse = get_object_or_404(Reponse.objects.select_related('copie__examen', 'copie__eleve'), id=reponse_id)
    if not can_access_copie(request.user, reponse.copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذا الملف.')
    if not reponse.reponse_video:
        return HttpResponseBadRequest('لا يوجد ملف فيديو مرفق بهذه الإجابة.')
    return redirect(reponse.reponse_video.url)


# ==================== Consultation (admin/mshrif/superviseur — lecture seule) ====================


@role_required('admin', 'mshrif', 'superviseur')
def consultation_examens_liste(request):
    examens = (
        get_examens_accessibles(request.user)
        .select_related('groupe', 'prof__user')
        .order_by('-date_creation')
    )
    return render(request, 'examens/consultation_liste.html', {
        'examens': examens, 'base_template': _base_template(request),
    })


@role_required('admin', 'mshrif', 'superviseur')
def consultation_examen_detail(request, examen_id):
    examen = get_object_or_404(Examen.objects.select_related('groupe', 'prof__user'), id=examen_id)
    if not can_access_examen(request.user, examen):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذا الاختبار.')

    questions = examen.questions.prefetch_related('choix')
    copies = examen.copies.select_related('eleve__user').order_by('eleve__user__first_name')
    return render(request, 'examens/consultation_detail.html', {
        'examen': examen, 'questions': questions, 'copies': copies,
        'base_template': _base_template(request),
    })


@role_required('admin', 'mshrif', 'superviseur')
def consultation_copie_detail(request, copie_id):
    copie = get_object_or_404(Copie.objects.select_related('examen__groupe', 'eleve__user'), id=copie_id)
    if not can_access_copie(request.user, copie):
        return HttpResponseForbidden('ليس لديك صلاحية الوصول إلى هذه النسخة.')

    reponses = copie.reponses.select_related('question', 'reponse_choix').order_by('question__ordre')
    return render(request, 'examens/consultation_copie.html', {
        'copie': copie, 'examen': copie.examen, 'reponses': reponses,
        'base_template': _base_template(request),
    })
