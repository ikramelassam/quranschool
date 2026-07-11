from django.db import models


class TypeAbonnement(models.Model):
    """Option de tarif/abonnement proposée à l'inscription, modifiable par l'admin
    (remplace l'ancienne liste codée en dur dans InscriptionEleve.ABONNEMENT_CHOICES)."""
    code = models.SlugField(max_length=30, unique=True)
    label = models.CharField(max_length=100)
    prix = models.DecimalField(max_digits=8, decimal_places=2)
    est_actif = models.BooleanField(default=True)
    ordre = models.IntegerField(default=0)

    def __str__(self):
        return f"{self.label} ({self.prix} درهم)"

    class Meta:
        ordering = ['ordre']
        verbose_name = "Type d'abonnement"
        verbose_name_plural = "Types d'abonnement"


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
    abonnement = models.CharField(max_length=30)

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

    def abonnement_label(self):
        """Libellé lisible de l'abonnement, lu depuis TypeAbonnement (dynamique).
        Retombe sur le code brut si le type a été supprimé depuis."""
        type_abo = TypeAbonnement.objects.filter(code=self.abonnement).first()
        return type_abo.label if type_abo else self.abonnement

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
    disponibilites = models.JSONField(
        default=list,
        help_text="Stockage temporaire de la matrice de disponibilités saisie à la candidature "
                   "(ex: ['lun_14:00', 'mar_15:00']), copiée vers DisponibiliteProf à la validation."
    )
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_attente')
    date_soumission = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.nom} {self.prenom}"

    class Meta:
        verbose_name = "Inscription Professeur"
        verbose_name_plural = "Inscriptions Professeurs"