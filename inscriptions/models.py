from django.db import models




class InscriptionEleve(models.Model):
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('valide', 'Validé'),
        ('rejete', 'Rejeté'),
    ]
    PROGRAMME_CHOICES = [
        ('hifz', 'الحفظ والمراجعة وتعلم أحكام التجويد'),
        ('tathbit', 'التثبيت وتعلم أحكام التجويد'),
    ]
    RIWAYA_CHOICES = [
        ('warsh', 'ورش'),
        ('hafs', 'حفص'),
    ]
    OUTIL_CHOICES = [
        ('whatsapp', 'واتساب'),
        ('meet', 'Google Meet'),
        ('les_deux', 'كلاهما'),
    ]
    ABONNEMENT_CHOICES = [
        ('groupe_1mois', 'جماعي - شهر (80 درهم)'),
        ('groupe_3mois', 'جماعي - 3 أشهر (220 درهم)'),
        ('individuel_1mois', 'فردي - شهر (400 درهم)'),
        ('individuel_3mois', 'فردي - 3 أشهر (1100 درهم)'),
    ]

    # Infos personnelles
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100, blank=True)
    nom_parent = models.CharField(max_length=100, blank=True)
    date_naissance = models.DateField()
    sexe = models.CharField(max_length=10)
    telephone = models.CharField(max_length=20)
    email = models.EmailField()

    # Programme
    creneau_souhaite = models.ForeignKey(
        'courses.Creneau',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inscriptions'
    )
    programme = models.CharField(max_length=20, choices=PROGRAMME_CHOICES)
    riwaya = models.CharField(max_length=10, choices=RIWAYA_CHOICES)
    outil = models.CharField(max_length=20, choices=OUTIL_CHOICES)
    abonnement = models.CharField(max_length=30, choices=ABONNEMENT_CHOICES)

    # Extras
    accepte_conditions = models.BooleanField(default=False)
    veut_contribuer = models.BooleanField(default=False)
    remarques = models.TextField(blank=True)
    disponibilites_libres = models.TextField(
        blank=True,
        help_text="Rempli par l'élève quand aucun créneau actif ne correspond à son profil (âge/sexe)."
    )

    # Statut
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente')
    date_soumission = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} {self.prenom}"

    class Meta:
        verbose_name = "Inscription Élève"
        verbose_name_plural = "Inscriptions Élèves"


class InscriptionProf(models.Model):
    STATUT_CHOICES = [
        ('en_attente', 'En attente'),
        ('valide', 'Validé'),
        ('rejete', 'Rejeté'),
    ]
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    date_naissance = models.DateField()
    ville = models.CharField(max_length=100)
    statut_familial = models.CharField(max_length=50)
    job_actuel = models.CharField(max_length=100)
    certifications = models.TextField()
    niveau_memorisation = models.CharField(max_length=100)
    type_eleve_preference = models.JSONField(default=list)
    contrainte_genre = models.JSONField(default=list)
    langues = models.JSONField(default=list)
    outils_maitrises = models.JSONField(default=list)
    parcours_scolaire = models.TextField()
    parcours_enseignant = models.TextField()
    compte_bancaire = models.CharField(max_length=50)
    rib = models.CharField(max_length=50)
    audio_enregistrement = models.FileField(
        upload_to='audio_inscriptions/',
        null=True,
        blank=True
    )
    gestion_eleve_faible = models.TextField()
    gestion_eleve_absent = models.TextField()
    email = models.EmailField()
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente')
    date_soumission = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} {self.prenom}"

    class Meta:
        verbose_name = "Inscription Professeur"
        verbose_name_plural = "Inscriptions Professeurs"


class DisponibiliteInscription(models.Model):
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
    inscription_prof = models.ForeignKey(
        InscriptionProf,
        on_delete=models.CASCADE,
        related_name='disponibilites'
    )
    jour = models.CharField(max_length=10, choices=JOUR_CHOICES)
    heure = models.CharField(max_length=5, choices=HEURE_CHOICES)

    def __str__(self):
        return f"{self.inscription_prof} - {self.jour} {self.heure}"

    class Meta:
        verbose_name = "Disponibilité Inscription"
        unique_together = ('inscription_prof', 'jour', 'heure')