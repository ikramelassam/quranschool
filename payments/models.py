from django.db import models
from django.contrib.auth import get_user_model
from accounts.models import Eleve

User = get_user_model()


class Paiement(models.Model):
    STATUT_CHOICES = [
        ('en_attente', 'قيد المراجعة'),
        ('valide', 'مقبول'),
        ('rejete', 'مرفوض'),
    ]
    eleve = models.ForeignKey(
        Eleve,
        on_delete=models.CASCADE,
        related_name='paiements'
    )
    montant = models.DecimalField(max_digits=8, decimal_places=2)
    mois_reference = models.DateField()
    date = models.DateTimeField(auto_now_add=True)
    # Optionnel depuis Tâche 7 (2026-07-25) : un مدير peut créer un paiement
    # directement (espèces reçues en personne), sans justificatif numérique —
    # avant, seul l'élève créait un Paiement (toujours avec reçu obligatoire).
    screenshot = models.FileField(upload_to='paiements/', blank=True, null=True)
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
    # Corrigé Tâche 7 (2026-07-25) : auto_now_add se déclenchait à la CRÉATION
    # de l'objet (donc dès la soumission par l'élève), jamais au moment réel
    # de la validation/rejet par le مدير — le champ était donc toujours rempli
    # même pour un paiement encore 'en_attente'. Désormais posé explicitement
    # dans admin_paiement_valider/admin_paiement_rejeter/paiement_panel_sauvegarder.
    date_validation = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.eleve} - {self.mois_reference}"

    class Meta:
        unique_together = ('eleve', 'mois_reference')
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"