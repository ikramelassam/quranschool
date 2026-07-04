
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = [
        ('eleve', 'Élève'),
        ('prof', 'Professeur'),
        ('superviseur', 'Superviseur'),
        ('admin', 'Administrateur'),
    ]
    telephone = models.CharField(max_length=20, blank=True)
    date_naissance = models.DateField(null=True, blank=True)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='eleve'
    )

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Eleve(models.Model):
    STATUT_CHOICES = [
        ('actif', 'Actif'),
        ('suspendu', 'Suspendu'),
        ('ancien', 'Ancien'),
        ('nouveau','NOUVEAU'),
    ]
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    sexe = models.CharField(max_length=10)

    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='actif'
    )
    inscription = models.ForeignKey(
        'inscriptions.InscriptionEleve',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eleve_valide'
    )

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Élève"
        verbose_name_plural = "Élèves"


class Prof(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )
    ville = models.CharField(max_length=100)
    certifications = models.TextField(blank=True)
    niveau_memorisation = models.CharField(max_length=100)
    type_eleve_preference = models.JSONField(default=list)
    contrainte_genre = models.JSONField(default=list)
    langues = models.JSONField(default=list)
    outils_maitrises = models.JSONField(default=list)
    parcours_scolaire = models.TextField()
    parcours_enseignant = models.TextField()
    gestion_eleve_faible = models.TextField(blank=True)
    gestion_eleve_absent = models.TextField(blank=True)
    compte_bancaire = models.CharField(max_length=50)
    rib = models.CharField(max_length=50)
    inscription = models.ForeignKey(
        'inscriptions.InscriptionProf',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='prof_valide'
    )

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Professeur"
        verbose_name_plural = "Professeurs"


class Superviseur(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Superviseur"
        verbose_name_plural = "Superviseurs"