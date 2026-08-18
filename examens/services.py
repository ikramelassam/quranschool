"""Logique métier d'Examens indépendante du HTTP : chrono, auto-correction,
démarrage/soumission d'une copie, validation des pièces audio, validation de
publication. Séparé de views.py pour rester testable sans client HTTP, même
principe que chat.services / courses.utils dans le reste du projet.

Validation des fichiers audio DUPLIQUÉE depuis chat.services (mêmes valeurs :
15 Mo, mêmes extensions) plutôt qu'importée — décision explicite du
2026-08-16 : ne créer AUCUNE dépendance entre examens et chat, chacun des
deux chantiers restant modifiable indépendamment sans risque d'effet de bord
sur l'autre. Si une factorisation devient un jour souhaitable, elle devra
passer par un module commun neutre (ex: core/), jamais par un import direct
d'une app vers l'autre."""
import os

from django.db import transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .models import Copie, Reponse

# ==================== Chrono ====================


def parser_datetime_local(valeur):
    """Parse une valeur de <input type="datetime-local"> ('AAAA-MM-JJTHH:MM')
    en datetime AWARE (heure locale du projet, Africa/Casablanca) — jamais
    une simple assignation de chaîne brute au champ modèle (qui déclenche un
    avertissement Django et repose sur une conversion implicite). Renvoie
    None si la valeur est vide/invalide, jamais une exception : la
    validation d'erreur reste à la charge de l'appelant (voir
    examens.views.examen_ajouter/examen_modifier)."""
    if not valeur:
        return None
    naive = parse_datetime(valeur)
    if naive is None:
        return None
    return timezone.make_aware(naive) if timezone.is_naive(naive) else naive


def demarrer_ou_recuperer_copie(examen, eleve):
    """Point d'entrée UNIQUE de création d'une Copie — même principe que
    chat._conversation_ou_403 : un seul chemin de code pour une opération
    sensible. get_or_create protège contre un double-clic/double-onglet ;
    la contrainte unique_together (examen, eleve) empêche de toute façon tout
    doublon en base, même en cas de requêtes concurrentes. date_debut posée
    UNE SEULE fois, au tout premier accès — jamais réinitialisée par un accès
    ultérieur : c'est précisément ce qui fait démarrer le chrono de façon
    irréversible (§3 : fermer le navigateur ou revenir plus tard ne redonne
    jamais une nouvelle durée)."""
    copie, cree = Copie.objects.get_or_create(
        examen=examen, eleve=eleve,
        defaults={'date_debut': timezone.now()},
    )
    return copie, cree


def finaliser_si_expiree(copie):
    """À appeler à CHAQUE accès serveur à une copie 'en_cours' (chargement de
    la page de passage, autosave, poll de statut) — si le temps est écoulé,
    la copie est soumise automatiquement AVANT que la requête en cours ne
    soit traitée plus loin (§3 : 'le serveur doit déterminer si la copie est
    encore active', 'aucune manipulation JS ne doit permettre de
    continuer'). Renvoie la copie (éventuellement mise à jour)."""
    if copie.statut == 'en_cours' and copie.est_expiree:
        return soumettre_copie(copie, automatique=True)
    return copie


# ==================== Correction ====================


def corriger_automatiquement(reponse):
    """Corrige une Reponse aux types auto-corrigeables (choix/vrai_faux) et
    renvoie les points attribués. Ne touche JAMAIS une réponse texte/audio/
    video — elle reste 'a_corriger', correction manuelle obligatoire (§10 du
    cahier des charges, aucune correction IA en V1)."""
    question = reponse.question
    if question.type_question == 'choix':
        correct = reponse.reponse_choix_id is not None and reponse.reponse_choix.est_correct
        reponse.points_obtenus = question.points if correct else 0
        reponse.statut_correction = 'auto'
        reponse.save(update_fields=['points_obtenus', 'statut_correction'])
    elif question.type_question == 'vrai_faux':
        correct = (
            reponse.reponse_bool is not None
            and question.reponse_correcte_bool is not None
            and reponse.reponse_bool == question.reponse_correcte_bool
        )
        reponse.points_obtenus = question.points if correct else 0
        reponse.statut_correction = 'auto'
        reponse.save(update_fields=['points_obtenus', 'statut_correction'])
    # texte/audio/video : rien à faire, reste 'a_corriger' — voir Reponse par défaut.
    return reponse.points_obtenus


def recalculer_note_totale(copie):
    """Recalcule Copie.note_totale — UNIQUEMENT si TOUTES les réponses ont un
    statut_correction != 'a_corriger' (§10 : 'éviter une note finale
    trompeuse lorsque seulement les QCM ont été corrigés'). Sinon,
    note_totale reste explicitement None, jamais une somme partielle."""
    reponses = list(copie.reponses.all())
    if any(r.statut_correction == 'a_corriger' for r in reponses):
        if copie.note_totale is not None:
            copie.note_totale = None
            copie.save(update_fields=['note_totale'])
        return None
    total = sum((r.points_obtenus or 0) for r in reponses)
    copie.note_totale = total
    copie.save(update_fields=['note_totale'])
    return total


@transaction.atomic
def soumettre_copie(copie, automatique=False):
    """Soumission d'une copie — TOUJOURS revérifiée serveur (§9 : jamais
    confiance à un statut/ID envoyé par le client). Idempotent : une copie
    déjà 'soumise' n'est jamais re-traitée (pas de double soumission, pas de
    double auto-correction, pas d'écrasement de date_soumission).
    select_for_update() protège contre une double soumission concurrente
    (ex: deux onglets, ou l'autosave et la soumission qui arrivent en même
    temps). Garantit une Reponse par Question de l'examen AVANT correction
    (une question restée sans réponse est corrigée comme "non répondue" —
    0 point si auto-corrigeable, 'à corriger' avec contenu vide sinon),
    verrouille la copie, lance l'auto-correction QCM/VF, recalcule la note
    (reste None tant qu'il reste une correction manuelle à faire, §10)."""
    copie = Copie.objects.select_for_update().get(pk=copie.pk)
    if copie.statut == 'soumise':
        return copie

    for question in copie.examen.questions.all():
        Reponse.objects.get_or_create(copie=copie, question=question)

    copie.statut = 'soumise'
    # Si finalisée par expiration, la date de soumission "réelle" est
    # l'instant d'expiration calculé, pas l'instant du traitement serveur
    # (qui peut survenir plus tard, ex: au prochain accès qui détecte
    # l'expiration) — cohérent avec "le serveur doit déterminer si la copie
    # est encore active" sur la base du chrono, pas de l'horloge de
    # traitement de la requête qui le détecte.
    copie.date_soumission = copie.date_expiration_effective if automatique else timezone.now()
    copie.soumission_automatique = automatique
    copie.save(update_fields=['statut', 'date_soumission', 'soumission_automatique'])

    for reponse in copie.reponses.select_related('question', 'reponse_choix'):
        if reponse.question.type_question in ('choix', 'vrai_faux'):
            corriger_automatiquement(reponse)

    recalculer_note_totale(copie)
    return copie


@transaction.atomic
def enregistrer_correction_manuelle(reponse, points_obtenus, commentaire):
    """Enregistre la correction manuelle (texte/audio) d'une réponse par le
    prof, puis recalcule la note totale de la copie — jamais l'inverse
    (recalcul systématique après CHAQUE correction individuelle, jamais un
    bouton séparé "recalculer" oublié par erreur)."""
    reponse.points_obtenus = points_obtenus
    reponse.commentaire_prof = commentaire
    reponse.statut_correction = 'corrigee'
    reponse.save(update_fields=['points_obtenus', 'commentaire_prof', 'statut_correction'])
    recalculer_note_totale(reponse.copie)
    return reponse


# ==================== Publication ====================


def motif_non_publiable(examen):
    """Renvoie un message d'erreur arabe si l'examen ne peut PAS être publié
    en l'état, None s'il est publiable. Validation serveur systématique
    (§9/§16) : jamais de confiance dans le seul fait que le bouton "publier"
    ait été cliqué. Vérifie qu'il y a au moins une question, et que chaque
    question auto-corrigeable a bien une bonne réponse définie (une question
    'choix' sans proposition correcte, ou 'vrai_faux' sans bonne réponse,
    rendrait la correction automatique silencieusement fausse pour tous les
    élèves)."""
    questions = list(examen.questions.prefetch_related('choix'))
    if not questions:
        return "لا يمكن نشر اختبار بدون أي سؤال."

    for question in questions:
        if question.type_question == 'choix':
            choix = list(question.choix.all())
            if len(choix) < 2:
                return f'السؤال "{question.enonce[:40]}" يجب أن يحتوي على مقترحين على الأقل.'
            if sum(1 for c in choix if c.est_correct) != 1:
                return f'السؤال "{question.enonce[:40]}" يجب أن يحتوي على إجابة صحيحة واحدة بالضبط.'
        elif question.type_question == 'vrai_faux':
            if question.reponse_correcte_bool is None:
                return f'يجب تحديد الإجابة الصحيحة (صح/خطأ) للسؤال "{question.enonce[:40]}".'

    if examen.date_debut is None or examen.date_limite is None:
        return "يجب تحديد تاريخ البداية والتاريخ النهائي قبل النشر."
    if examen.date_limite <= examen.date_debut:
        return "التاريخ النهائي يجب أن يكون بعد تاريخ البداية."

    return None


# ==================== Affichage élève ====================


def statut_affichage_eleve(examen, copie):
    """Statut d'affichage pour la carte élève (§6 du cahier des charges :
    'à venir / disponible / en cours / soumis / fermé / corrigé') — dérivé de
    l'état ACTUEL de l'examen et de la copie de CET élève (ou None s'il n'a
    pas encore commencé). Purement informatif (affichage), jamais utilisé
    pour une décision de permission (voir examens.permissions, seule source
    de vérité pour l'accès)."""
    if copie:
        if copie.statut == 'soumise':
            return 'corrigee' if copie.correction_complete else 'soumise'
        if copie.est_expiree:
            # Pas encore finalisée en base (aucune requête n'a encore déclenché
            # finaliser_si_expiree), mais le sera au prochain accès réel —
            # affichage anticipé cohérent, jamais une "en cours" trompeuse.
            return 'soumise'
        return 'en_cours'

    if examen.statut == 'ferme':
        return 'ferme'
    if timezone.now() < examen.date_debut:
        return 'a_venir'
    if examen.est_disponible_maintenant:
        return 'disponible'
    return 'ferme'


# ==================== Validation audio ====================

EXTENSIONS_AUDIO_AUTORISEES = (
    '.mp3', '.wav', '.m4a', '.ogg', '.oga', '.webm', '.aac', '.opus',
)
TAILLE_MAX_AUDIO_OCTETS = 15 * 1024 * 1024  # 15 Mo — même limite que chat (décision validée le 2026-08-16)


def valider_fichier_audio(fichier):
    """Renvoie un message d'erreur arabe si le fichier est refusé, None s'il
    est accepté. Ne fait JAMAIS confiance au seul attribut 'accept' du
    <input> côté client : extension en liste blanche + taille max +
    rejet d'un fichier vide (même principe que chat.services.
    valider_piece_jointe, dupliqué ici sans dépendance — voir docstring du
    module)."""
    if not fichier:
        return "لم يتم إرفاق أي ملف صوتي."
    if fichier.size == 0:
        return "الملف الصوتي فارغ أو تالف."
    extension = os.path.splitext(fichier.name)[1].lower()
    if extension not in EXTENSIONS_AUDIO_AUTORISEES:
        return f'صيغة الملف "{extension}" غير مقبولة.'
    if fichier.size > TAILLE_MAX_AUDIO_OCTETS:
        return f'حجم الملف كبير جداً ({fichier.size // (1024 * 1024)} م.ب). الحد الأقصى 15 م.ب.'
    return None


# ==================== Validation vidéo ====================
# Tâche du 2026-08-18 : même patron que valider_fichier_audio ci-dessus
# (dupliqué depuis chat/annonces, mêmes valeurs — 40 Mo, mêmes extensions
# que le type 'video' de annonces.services, nettement plus lourd qu'un
# audio) — même décision de ne créer aucune dépendance entre examens et les
# autres apps (voir docstring du module).

EXTENSIONS_VIDEO_AUTORISEES = ('.mp4', '.webm', '.mov')
TAILLE_MAX_VIDEO_OCTETS = 40 * 1024 * 1024  # 40 Mo


def valider_fichier_video(fichier):
    """Renvoie un message d'erreur arabe si le fichier est refusé, None s'il
    est accepté — même logique que valider_fichier_audio (extension en liste
    blanche + taille max + rejet d'un fichier vide)."""
    if not fichier:
        return "لم يتم إرفاق أي ملف فيديو."
    if fichier.size == 0:
        return "الملف فارغ أو تالف."
    extension = os.path.splitext(fichier.name)[1].lower()
    if extension not in EXTENSIONS_VIDEO_AUTORISEES:
        return f'صيغة الملف "{extension}" غير مقبولة.'
    if fichier.size > TAILLE_MAX_VIDEO_OCTETS:
        return f'حجم الملف كبير جداً ({fichier.size // (1024 * 1024)} م.ب). الحد الأقصى 40 م.ب.'
    return None
