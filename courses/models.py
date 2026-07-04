from django.db import models
from accounts.models import Prof, Eleve, Superviseur


class Disponibilite(models.Model):
    JOUR_CHOICES = [
        ('lun', 'Lundi'), ('mar', 'Mardi'),
        ('mer', 'Mercredi'), ('jeu', 'Jeudi'),
        ('ven', 'Vendredi'), ('sam', 'Samedi'),
        ('dim', 'Dimanche'),
    ]
    HEURE_CHOICES = [
        ('07h', '07:00'), ('09h', '09:00'),
        ('11h', '11:00'), ('13h', '13:00'),
        ('15h', '15:00'), ('17h', '17:00'),
        ('19h', '19:00'), ('21h', '21:00'),
    ]
    prof = models.ForeignKey(
        Prof,
        on_delete=models.CASCADE,
        related_name='disponibilites'
    )
    jour = models.CharField(max_length=10, choices=JOUR_CHOICES)
    heure = models.CharField(max_length=5, choices=HEURE_CHOICES)

    def __str__(self):
        return f"{self.prof} - {self.jour} {self.heure}"

    class Meta:
        unique_together = ('prof', 'jour', 'heure')


class Creneau(models.Model):
    JOUR_CHOICES = [
        ('lun', 'الاثنين'),
        ('mar', 'الثلاثاء'),
        ('mer', 'الأربعاء'),
        ('jeu', 'الخميس'),
        ('ven', 'الجمعة'),
        ('sam', 'السبت'),
        ('dim', 'الأحد'),
    ]
    SEXE_CHOICES = [
        ('homme', 'ذكر'),
        ('femme', 'أنثى'),
        ('mixte', 'مختلط'),
    ]

    sexe_cible = models.CharField(max_length=10, choices=SEXE_CHOICES, default='mixte')
    age_min = models.IntegerField()
    age_max = models.IntegerField()
    jour_1 = models.CharField(max_length=5, choices=JOUR_CHOICES)
    heure_debut_1 = models.TimeField()
    heure_fin_1 = models.TimeField()
    jour_2 = models.CharField(max_length=5, choices=JOUR_CHOICES)
    heure_debut_2 = models.TimeField()
    heure_fin_2 = models.TimeField()
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return (
            f"{self.get_jour_1_display()} {self.heure_debut_1.strftime('%H:%M')}"
            f" + {self.get_jour_2_display()} {self.heure_debut_2.strftime('%H:%M')}"
        )

    class Meta:
        verbose_name = "Créneau"
        verbose_name_plural = "Créneaux"

class Groupe(models.Model):
    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    eleves = models.ManyToManyField(
        'accounts.Eleve',
        blank=True,
        related_name='groupes'
    )
    prof = models.ForeignKey(
        Prof,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='groupes'
    )
    creneau = models.ForeignKey(
        Creneau,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='groupes'
    )
    capacite_max = models.IntegerField(default=10)
    statut = models.CharField(
        max_length=20,
        choices=[('actif', 'Actif'), ('archive', 'Archivé')],
        default='actif'
    )

    def __str__(self):
        return self.nom

    class Meta:
        verbose_name = "Groupe"
        verbose_name_plural = "Groupes"
        
class Seance(models.Model):
    TYPE_CHOICES = [
        ('normal', 'Normal'),
        ('rattrapage', 'Rattrapage'),
        ('revision', 'Révision'),
    ]
    STATUT_CHOICES = [
        ('planifiee', 'Planifiée'),
        ('terminee', 'Terminée'),
        ('annulee', 'Annulée'),
    ]
    groupe = models.ForeignKey(
        Groupe,
        on_delete=models.CASCADE,
        related_name='seances'
    )
    date = models.DateField()
    heure = models.TimeField()
    type = models.CharField(max_length=20, choices=TYPE_CHOICES)
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='planifiee'
    )
    superviseur = models.ForeignKey(
        Superviseur,
        on_delete=models.SET_NULL,
        null=True,
        blank=True
    )
    remarque = models.TextField(
        blank=True,
        help_text="Raison d'une exception: annulation ou déplacement (prof malade, vacances...)."
    )

    def __str__(self):
        return f"{self.groupe} - {self.date}"

    class Meta:
        verbose_name = "Séance"
        verbose_name_plural = "Séances"

class Presence(models.Model):
    STATUT_CHOICES = [
        ('present', 'حاضر'),
        ('absent_excuse', 'غائب بعذر'),
        ('absent', 'غائب بدون عذر'),
    ]
    NOTE_CHOICES = [
        ('mumtaz', 'ممتاز'),
        ('hasan', 'حسن'),
        ('mutawassit', 'متوسط'),
        ('yuid', 'يعيد'),
    ]
    seance = models.ForeignKey(
        Seance,
        on_delete=models.CASCADE,
        related_name='presences'
    )
    eleve = models.ForeignKey(
        Eleve,
        on_delete=models.CASCADE,
        related_name='presences'
    )
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='present'
    )
    quantite_memorisee = models.CharField(max_length=200, blank=True)
    quantite_revisee = models.CharField(max_length=200, blank=True)
    note_memorisation = models.CharField(
        max_length=20,
        choices=NOTE_CHOICES,
        blank=True
    )
    note_revision = models.CharField(
        max_length=20,
        choices=NOTE_CHOICES,
        blank=True
    )
    remarque = models.TextField(blank=True)

    def __str__(self):
        return f"{self.eleve} - {self.seance}"

    class Meta:
        unique_together = ('seance', 'eleve')
        verbose_name = "Présence"
        verbose_name_plural = "Présences"