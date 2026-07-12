from django.db import models
from accounts.models import Prof, Eleve, Superviseur


class DisponibiliteProf(models.Model):
    """Une case de la matrice de disponibilités d'un prof: ce jour, à partir de
    cette heure pleine, pour 1h (ex: lun 14:00 = disponible de 14h à 15h)."""
    prof = models.ForeignKey(
        Prof,
        on_delete=models.CASCADE,
        related_name='disponibilites'
    )
    jour_semaine = models.CharField(max_length=3, choices=[
        ('lun', 'الاثنين'), ('mar', 'الثلاثاء'), ('mer', 'الأربعاء'),
        ('jeu', 'الخميس'), ('ven', 'الجمعة'), ('sam', 'السبت'), ('dim', 'الأحد'),
    ])
    heure_debut = models.TimeField()

    class Meta:
        unique_together = ('prof', 'jour_semaine', 'heure_debut')
        verbose_name = "Disponibilité du professeur"
        verbose_name_plural = "Disponibilités des professeurs"

    def __str__(self):
        return f"{self.prof} - {self.get_jour_semaine_display()} {self.heure_debut.strftime('%H:%M')}"


class DisponibiliteEleve(models.Model):
    """Une case de la matrice de disponibilités d'un élève, même principe que
    DisponibiliteProf. Contrairement au prof, l'élève ne peut pas la modifier
    lui-même après la validation de son inscription — seul l'admin l'édite."""
    eleve = models.ForeignKey(
        Eleve,
        on_delete=models.CASCADE,
        related_name='disponibilites'
    )
    jour_semaine = models.CharField(max_length=3, choices=[
        ('lun', 'الاثنين'), ('mar', 'الثلاثاء'), ('mer', 'الأربعاء'),
        ('jeu', 'الخميس'), ('ven', 'الجمعة'), ('sam', 'السبت'), ('dim', 'الأحد'),
    ])
    heure_debut = models.TimeField()

    class Meta:
        unique_together = ('eleve', 'jour_semaine', 'heure_debut')
        verbose_name = "Disponibilité de l'élève"
        verbose_name_plural = "Disponibilités des élèves"

    def __str__(self):
        return f"{self.eleve} - {self.get_jour_semaine_display()} {self.heure_debut.strftime('%H:%M')}"


class DemandeModificationDisponibilite(models.Model):
    """Proposition de nouvelle matrice de disponibilités par un prof, en attente
    d'approbation admin. Tant que non approuvée, DisponibiliteProf reste inchangé."""
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('approuvee', 'Approuvée'),
        ('rejetee', 'Rejetée'),
    ]
    prof = models.ForeignKey(
        Prof,
        on_delete=models.CASCADE,
        related_name='demandes_disponibilite'
    )
    nouvelle_matrice = models.JSONField(default=list)  # ex: ["lun_14:00", "mar_15:00"]
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente')
    date_demande = models.DateTimeField(auto_now_add=True)
    date_traitement = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"Demande de {self.prof} - {self.get_statut_display()}"


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
    # Mêmes codes que InscriptionEleve.PROGRAMME_CHOICES — un élève ayant choisi
    # "hifz"/"tathbit" à l'inscription est mis en correspondance avec ce même champ.
    TYPE_SEANCE_CHOICES = [
        ('hifz', 'الحفظ والمراجعة وتعلم أحكام التجويد'),
        ('tathbit', 'التثبيت وتعلم أحكام التجويد'),
    ]

    sexe_cible = models.CharField(max_length=10, choices=SEXE_CHOICES, default='mixte')
    type_seance = models.CharField(max_length=20, choices=TYPE_SEANCE_CHOICES, default='hifz')
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
    sourate_memorisee = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_debut_memorisation = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_fin_memorisation = models.PositiveSmallIntegerField(null=True, blank=True)
    note_memorisation = models.CharField(
        max_length=20,
        choices=NOTE_CHOICES,
        blank=True
    )
    sourate_revisee = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_debut_revision = models.PositiveSmallIntegerField(null=True, blank=True)
    ayah_fin_revision = models.PositiveSmallIntegerField(null=True, blank=True)
    note_revision = models.CharField(
        max_length=20,
        choices=NOTE_CHOICES,
        blank=True
    )
    remarque = models.TextField(blank=True)

    def __str__(self):
        return f"{self.eleve} - {self.seance}"

    @property
    def nom_sourate_memorisee(self):
        from courses.quran_data import SOURATES_NOMS
        return SOURATES_NOMS.get(self.sourate_memorisee)

    @property
    def nom_sourate_revisee(self):
        from courses.quran_data import SOURATES_NOMS
        return SOURATES_NOMS.get(self.sourate_revisee)

    @property
    def nb_ayat_memorises(self):
        if self.ayah_debut_memorisation is not None and self.ayah_fin_memorisation is not None:
            return self.ayah_fin_memorisation - self.ayah_debut_memorisation + 1
        return 0

    @property
    def nb_ayat_revises(self):
        if self.ayah_debut_revision is not None and self.ayah_fin_revision is not None:
            return self.ayah_fin_revision - self.ayah_debut_revision + 1
        return 0

    class Meta:
        unique_together = ('seance', 'eleve')
        verbose_name = "Présence"
        verbose_name_plural = "Présences"