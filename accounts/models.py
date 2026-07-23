
from django.contrib.auth.models import AbstractUser
from django.db import models


class User(AbstractUser):
    ROLE_CHOICES = [
        ('eleve', 'طالب'),
        ('prof', 'معلم'),
        ('superviseur', 'مؤطر'),
        ('admin', 'مدير'),
        ('mshrif', 'المشرف'),
    ]
    telephone = models.CharField(max_length=20, blank=True)
    date_naissance = models.DateField(null=True, blank=True)
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='eleve'
    )
    # True tant que l'utilisateur n'a pas changé son mot de passe temporaire
    # (voir dashboard.views.MOT_DE_PASSE_TEMPORAIRE). Le middleware
    # accounts.middleware.ForcerChangementMotDePasseMiddleware redirige tout
    # utilisateur avec ce champ à True vers le changement de mot de passe
    # avant tout accès au reste du site.
    doit_changer_mot_de_passe = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"


class Eleve(models.Model):
    STATUT_CHOICES = [
        ('actif', 'نشط'),
        ('suspendu', 'موقوف'),
        ('ancien', 'قديم'),
        ('nouveau', 'جديد'),
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
    # Montant ajouté manuellement au virement réel par le مدير, en dehors de la
    # plateforme (ex: prime, ancienneté). Visible en lecture seule par مدير et
    # مؤطر (superviseur) — jamais montré ni additionné dans ce que le prof voit
    # sur sa propre page de rémunération (courses.utils.calculer_remuneration_prof
    # ne la connaît pas du tout).
    majoration_mensuelle = models.DecimalField(max_digits=8, decimal_places=2, null=True, blank=True)
    # Acceptation du ميثاق التدريس (voir CharteEnseignement ci-dessous) — un simple
    # accusé de lecture, pas un blocage: le prof garde l'accès au site même sans avoir coché.
    charte_acceptee = models.BooleanField(default=False)
    date_acceptation_charte = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Professeur"
        verbose_name_plural = "Professeurs"


class CharteEnseignement(models.Model):
    """ميثاق التدريس — singleton (une seule ligne en base, toujours pk=1, voir
    get_charte() ci-dessous), éditable uniquement par le rôle مشرف. Contenu structuré en
    champs texte simples (pas de HTML) pour que le مشرف — sans compétences HTML — puisse
    modifier le texte sans jamais toucher à la mise en page, qui reste fixée dans
    templates/dashboard/mshrif_charte.html et templates/dashboard/_charte_contenu.html.
    Chaque champ *_items est une liste de points, un par ligne, au format libre
    "التسمية: الوصف" (le ':' est optionnel) — voir accounts.templatetags.charte_tags.parse_items."""
    intro = models.TextField(blank=True)
    verset_ouverture = models.CharField(max_length=300, blank=True)
    titre_bunud = models.CharField(max_length=300, blank=True)

    section1_titre = models.CharField(max_length=200, blank=True)
    section1_intro = models.TextField(blank=True)
    section1_items = models.TextField(blank=True)

    section2_titre = models.CharField(max_length=200, blank=True)
    section2_intro = models.TextField(blank=True)
    section2_items = models.TextField(blank=True)

    section3_titre = models.CharField(max_length=200, blank=True)
    section3_intro = models.TextField(blank=True)
    section3_items = models.TextField(blank=True)
    verset_rahma_texte = models.TextField(blank=True)
    verset_rahma_reference = models.CharField(max_length=100, blank=True)
    section3_conclusion = models.TextField(blank=True)

    section4_titre = models.CharField(max_length=200, blank=True)
    section4_intro = models.TextField(blank=True)
    section4_items = models.TextField(blank=True)

    section5_titre = models.CharField(max_length=200, blank=True)
    section5_intro = models.TextField(blank=True)
    section5_note = models.TextField(blank=True)

    section6_titre = models.CharField(max_length=200, blank=True)
    section6_intro = models.TextField(blank=True)
    section6_items = models.TextField(blank=True)

    section7_titre = models.CharField(max_length=200, blank=True)
    section7_intro = models.TextField(blank=True)
    section7_items = models.TextField(blank=True)

    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "ميثاق التدريس"

    class Meta:
        verbose_name = "Charte d'enseignement"
        verbose_name_plural = "Charte d'enseignement"


class CharteSanctionLigne(models.Model):
    """Une ligne du tableau des sanctions (section خامساً de la charte). Modèle à part
    (plutôt qu'un TextField comme les autres sections) car le مشرف doit pouvoir
    ajouter/retirer des lignes — un simple champ texte multi-lignes ne permet pas
    d'associer un ordre stable + une sévérité à chaque ligne de façon fiable."""
    SEVERITE_CHOICES = [
        ('immediate', 'الإعفاء الفوري'),
        ('progressive', 'إنذار أول ← إنذار ثاني ← خصم من الراتب'),
    ]
    charte = models.ForeignKey(CharteEnseignement, on_delete=models.CASCADE, related_name='sanctions')
    ordre = models.PositiveIntegerField(default=0)
    violation = models.CharField(max_length=300)
    severite = models.CharField(max_length=20, choices=SEVERITE_CHOICES, default='progressive')

    class Meta:
        ordering = ['ordre', 'id']

    def __str__(self):
        return self.violation


def get_charte():
    """Renvoie l'unique instance de CharteEnseignement, en la créant (vide) si elle
    n'existe pas encore — patron singleton simple (toujours pk=1)."""
    charte, _ = CharteEnseignement.objects.get_or_create(pk=1)
    return charte


class ProgrammeGeneral(models.Model):
    """البرنامج العام لمقرأة زدني علماً — contenu texte libre, modifiable UNIQUEMENT
    par le مدير (contrairement à ميثاق التدريس qui est géré par le المشرف), visible en
    lecture seule par le prof et l'élève. Singleton comme CharteEnseignement, mais
    volontairement un seul champ texte : contenu plus simple que la charte, pas de
    structure en sections nécessaire."""
    contenu = models.TextField(blank=True)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "البرنامج العام"

    class Meta:
        verbose_name = "Programme général"
        verbose_name_plural = "Programme général"


def get_programme_general():
    """Renvoie l'unique instance de ProgrammeGeneral, en la créant (vide) si elle
    n'existe pas encore — même patron singleton que get_charte()."""
    programme, _ = ProgrammeGeneral.objects.get_or_create(pk=1)
    return programme


class LogoConfig(models.Model):
    """Logo de la plateforme, modifiable UNIQUEMENT par le المشرف (mshrif_logo) — une
    fois uploadé, remplace automatiquement le logo par défaut partout (header,
    connexion, favicon, pages d'inscription) via le context processor
    accounts.context_processors.logo_context. Stocké via le storage par défaut du
    projet (Cloudinary en production, disque local en dev) comme les autres fichiers
    média (Paiement.screenshot, InscriptionProf.audio_enregistrement). Singleton comme
    CharteEnseignement/ProgrammeGeneral."""
    logo = models.ImageField(upload_to='logo/', blank=True, null=True)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "شعار المنصة"

    class Meta:
        verbose_name = "Logo de la plateforme"
        verbose_name_plural = "Logo de la plateforme"


def get_logo_config():
    """Renvoie l'unique instance de LogoConfig, en la créant (vide -> logo=None,
    donc fallback sur le logo statique par défaut) si elle n'existe pas encore."""
    config, _ = LogoConfig.objects.get_or_create(pk=1)
    return config


class Superviseur(models.Model):
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )
    profs_assignes = models.ManyToManyField(
        Prof,
        related_name='superviseurs',
        blank=True
    )

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Superviseur"
        verbose_name_plural = "Superviseurs"