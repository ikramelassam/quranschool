from django.conf import settings
from django.db import models


class TypeAbonnement(models.Model):
    """Option de tarif/abonnement proposée à l'inscription, modifiable par l'admin
    (remplace l'ancienne liste codée en dur dans InscriptionEleve.ABONNEMENT_CHOICES)."""
    TYPE_OFFRE_CHOICES = [
        ('groupe', 'جماعي'),
        ('individuel', 'فردي'),
    ]
    # Mêmes codes que courses.utils.tranche_age_depuis_naissance / le paramètre
    # type_age du formulaire d'inscription élève — mêmes valeurs que
    # Creneau.SEXE_CHOICES pour le principe (une cible + une valeur "les deux"),
    # voir Tâche 16 du 2026-07-26.
    CIBLE_AGE_CHOICES = [
        ('enfant', 'أطفال'),
        ('adulte', 'بالغون'),
        ('les_deux', 'الجميع'),
    ]

    code = models.SlugField(max_length=30, unique=True)
    label = models.CharField(max_length=100)
    prix = models.DecimalField(max_digits=8, decimal_places=2)
    # Utilisé pour comparer un abonnement choisi à l'inscription au type_capacite
    # d'un Groupe (courses.utils.raison_incompatibilite_groupe*).
    type_offre = models.CharField(max_length=10, choices=TYPE_OFFRE_CHOICES, default='groupe')
    cible_age = models.CharField(max_length=10, choices=CIBLE_AGE_CHOICES, default='les_deux')
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
        ('en_attente', 'قيد الانتظار'),
        ('valide', 'مقبول'),
        ('rejete', 'مرفوض'),
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
    # Optionnel (contrairement à InscriptionProf.job_actuel, obligatoire) —
    # un enfant n'a généralement pas de travail actuel (Tâche du 2026-08-04).
    job_actuel = models.CharField(max_length=100, blank=True)

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
    disponibilites = models.JSONField(
        default=list,
        help_text="Stockage temporaire de la matrice de disponibilités saisie à la candidature "
                   "(ex: ['lun_14:00', 'mar_15:00']), copiée vers DisponibiliteEleve à la validation."
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

    def abonnement_type_offre(self):
        """'individuel' ou 'groupe', lu depuis TypeAbonnement. None si le type
        a été supprimé depuis (empêche toute suggestion de groupe erronée)."""
        type_abo = TypeAbonnement.objects.filter(code=self.abonnement).first()
        return type_abo.type_offre if type_abo else None

    class Meta:
        verbose_name = "Inscription Élève"
        verbose_name_plural = "Inscriptions Élèves"


class InscriptionProf(models.Model):
    STATUT_CHOICES = [
        ('en_attente', 'قيد الانتظار'),
        ('validee_directeur', 'مقبول من المدير — بانتظار تصديق المشرف'),
        ('valide', 'مقبول نهائياً'),
        ('rejete', 'مرفوض'),
    ]
    nom = models.CharField(max_length=100)
    prenom = models.CharField(max_length=100)
    date_naissance = models.DateField()
    telephone = models.CharField(max_length=20, blank=True)
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
    agence_bancaire = models.CharField(max_length=100)
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


class ParametresInscriptions(models.Model):
    """Réglage global (مدير + مشرف) d'ouverture/fermeture des inscriptions
    publiques, par catégorie — singleton comme VisibiliteProf/ProgrammeGeneral
    (Tâche du 2026-08-04). Trois interrupteurs indépendants : élève adulte,
    élève enfant (même modèle InscriptionEleve, distingués uniquement par le
    paramètre d'URL type_age — voir inscriptions.views.inscription_eleve_formulaire,
    aucun champ 'catégorie' séparé n'existe sur InscriptionEleve) et professeur.
    Lu par inscriptions.views.inscription_eleve_formulaire/inscription_prof
    AVANT tout traitement GET/POST : catégorie fermée = même écran public
    (templates/inscriptions/inscription_fermee.html) quel que soit le chemin
    d'accès (bouton normal ou requête directe/POST). N'affecte jamais les
    candidatures déjà soumises ni leur traitement admin/مشرف — uniquement la
    création de nouvelles candidatures.

    derniere_modification_par: contrairement aux autres singletons du projet
    (qui ne tracent que date_modification), le format demandé ici ("آخر
    تعديل: [utilisateur] — [date]") nécessite de savoir QUI a fait le dernier
    changement, pas seulement quand — nouveau champ, pas une simple reprise
    du patron existant."""
    ouverte_eleve_adulte = models.BooleanField(default=True)
    ouverte_eleve_enfant = models.BooleanField(default=True)
    ouverte_prof = models.BooleanField(default=True)
    derniere_modification_par = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True, blank=True,
        on_delete=models.SET_NULL,
        related_name='+',
    )
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "إعدادات فتح/إغلاق التسجيل"

    class Meta:
        verbose_name = "Paramètres d'inscription"
        verbose_name_plural = "Paramètres d'inscription"


def get_parametres_inscriptions():
    """Renvoie l'unique instance de ParametresInscriptions, en la créant
    (valeurs par défaut: tout ouvert, comportement actuel préservé) si elle
    n'existe pas encore — même patron singleton que get_charte()/
    get_programme_general()/get_visibilite_prof()."""
    parametres, _ = ParametresInscriptions.objects.get_or_create(pk=1)
    return parametres