import datetime

from django.conf import settings
from django.db import models
from django.utils import timezone
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