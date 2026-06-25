from django.db import models
from django.contrib.auth import get_user_model
from accounts.models import Eleve

User = get_user_model()


class Paiement(models.Model):
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('valide', 'Validé'),
        ('rejete', 'Rejeté'),
    ]
    eleve = models.ForeignKey(
        Eleve,
        on_delete=models.CASCADE,
        related_name='paiements'
    )
    montant = models.DecimalField(max_digits=8, decimal_places=2)
    mois_reference = models.DateField()
    date = models.DateTimeField(auto_now_add=True)
    screenshot = models.FileField(upload_to='paiements/')
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_attente'
    )
    valide_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_valides'
    )
    date_validation = models.DateTimeField(auto_now_add=True,null=True, blank=True)

    def __str__(self):
        return f"{self.eleve} - {self.mois_reference}"

    class Meta:
        unique_together = ('eleve', 'mois_reference')
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"