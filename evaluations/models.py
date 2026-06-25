from django.db import models
from accounts.models import Superviseur, Prof
from courses.models import Seance


class Critere(models.Model):
    nom_ar = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)

    def __str__(self):
        return self.nom_ar

    class Meta:
        ordering = ['ordre']
        verbose_name = "Critère"
        verbose_name_plural = "Critères"


class Evaluation(models.Model):
    superviseur = models.ForeignKey(
        Superviseur,
        on_delete=models.CASCADE,
        related_name='evaluations'
    )
    seance = models.OneToOneField(
        Seance,
        on_delete=models.CASCADE,
        related_name='evaluation'
    )
    commentaire = models.TextField(blank=True)
    date = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Évaluation {self.seance} par {self.superviseur}"

    class Meta:
        verbose_name = "Évaluation"
        verbose_name_plural = "Évaluations"


class NoteEvaluation(models.Model):
    NOTE_CHOICES = [
        (0, 'منعدم'),
        (1, 'ضعيف'),
        (2, 'متوسط'),
        (3, 'حسن'),
        (4, 'حسن جدا'),
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