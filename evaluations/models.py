import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _
from accounts.models import Superviseur, Prof
from courses.models import Seance

FENETRE_MODIFICATION_EVALUATION_HEURES = 24  # confirmé par le client : le مؤطر ne peut plus
# corriger son évaluation du prof passé ce délai depuis l'envoi initial.


class Critere(models.Model):
    nom_ar = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom_ar

    class Meta:
        ordering = ['ordre']
        verbose_name = "Critère"
        verbose_name_plural = "Critères"


class Evaluation(models.Model):
    # SET_NULL (pas CASCADE) depuis le chantier de suppression définitive du
    # مؤطر (2026-08-12) : cette évaluation concerne le PROF évalué, pas le
    # مؤطر qui l'a rédigée — le supprimer ne doit jamais effacer l'historique
    # de performance d'un prof qui, lui, garde son compte. Reste visible sur
    # la fiche du prof (via seance.groupe), avec un auteur devenu vide.
    superviseur = models.ForeignKey(
        Superviseur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='evaluations'
    )
    seance = models.OneToOneField(
        Seance,
        on_delete=models.CASCADE,
        related_name='evaluation'
    )
    # CASCADE (chantier du 2026-08-12, audit de cohérence) : contrairement à
    # .superviseur ci-dessus (l'auteur), .prof est le SUJET réel de
    # l'évaluation — l'écran s'appelle littéralement "تقييم المعلم" (évaluation
    # DU prof), pas "évaluation de la séance". Si le prof est supprimé, son
    # évaluation doit disparaître avec lui, comme Presence/BilanMensuel
    # disparaissent avec l'élève qu'ils décrivent. Toujours renseigné à la
    # création (voir evaluations.views.superviseur_evaluer, qui ne peut créer
    # une évaluation que pour un groupe ayant un prof réel) — mais null=True
    # conservé en permanence : Groupe.prof est lui-même SET_NULL, donc le
    # backfill des évaluations déjà existantes (migration 0006) ne peut pas
    # garantir un prof pour 100% des lignes historiques.
    prof = models.ForeignKey(
        Prof,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name='evaluations_recues'
    )
    commentaire = models.TextField()
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Évaluation {self.seance} par {self.superviseur}"

    @property
    def modifiable(self):
        """True tant que la fenêtre de correction (voir FENETRE_MODIFICATION_EVALUATION_HEURES)
        n'est pas dépassée depuis l'envoi initial. `date` est auto_now_add donc ne bouge jamais
        après coup, y compris si l'évaluation est ensuite modifiée — la fenêtre se compte bien
        depuis le premier envoi, pas depuis la dernière modification."""
        return timezone.now() - self.date < datetime.timedelta(hours=FENETRE_MODIFICATION_EVALUATION_HEURES)

    class Meta:
        verbose_name = "Évaluation"
        verbose_name_plural = "Évaluations"


class NoteEvaluation(models.Model):
    NOTE_CHOICES = [
        (0, _('منعدم')),
        (1, _('ضعيف')),
        (2, _('متوسط')),
        (3, _('حسن')),
        (4, _('حسن جدا')),
    ]
    evaluation = models.ForeignKey(
        Evaluation,
        on_delete=models.CASCADE,
        related_name='notes'
    )
    critere = models.ForeignKey(
        Critere,
        on_delete=models.CASCADE
    )
    note = models.IntegerField(choices=NOTE_CHOICES)

    def __str__(self):
        return f"{self.critere} → {self.note}"

    class Meta:
        unique_together = ('evaluation', 'critere')
        verbose_name = "Note Évaluation"


class CommentaireMensuel(models.Model):
    """Commentaire libre du مؤطر (superviseur) ou مدير (admin) sur un prof,
    un par prof par mois — voir la page de classement mensuel. Même patron
    que payments.Paiement.mois_reference: toujours stocké au 1er du mois."""
    prof = models.ForeignKey(Prof, on_delete=models.CASCADE, related_name='commentaires_mensuels')
    mois_reference = models.DateField()
    commentaire = models.TextField(blank=True)
    redige_par = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Commentaire {self.prof} - {self.mois_reference:%Y-%m}"

    class Meta:
        unique_together = ('prof', 'mois_reference')
        verbose_name = "Commentaire mensuel"
        verbose_name_plural = "Commentaires mensuels"