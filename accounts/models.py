
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.translation import gettext_lazy as _


class User(AbstractUser):
    ROLE_CHOICES = [
        ('eleve', 'طالب'),
        ('prof', 'معلم'),
        ('superviseur', 'مؤطر'),
        ('admin', 'الإدارة'),
        ('mshrif', 'المشرف'),
    ]
    telephone = models.CharField(max_length=20, blank=True)
    date_naissance = models.DateField(null=True, blank=True)
    # Description courte affichée aux élèves/profs/مؤطرين sur les sections
    # "التواصل مع الإدارة" / "جهات الاتصال" (utilisée pour le compte مدير —
    # Tâche du 2026-07-28). Générique sur User plutôt que réservée à un rôle
    # précis, comme telephone/date_naissance déjà partagés par tous les rôles.
    description_courte = models.CharField(max_length=300, blank=True, default='')
    role = models.CharField(
        max_length=20,
        choices=ROLE_CHOICES,
        default='eleve'
    )
    # True tant que l'utilisateur n'a pas changé son mot de passe temporaire
    # (voir dashboard.views.generer_mot_de_passe_temporaire). Le middleware
    # accounts.middleware.ForcerChangementMotDePasseMiddleware redirige tout
    # utilisateur avec ce champ à True vers le changement de mot de passe
    # avant tout accès au reste du site.
    doit_changer_mot_de_passe = models.BooleanField(default=True)
    # Traçabilité de la réinitialisation par مدير/مشرف (Points 13/14/17,
    # Tâche du 2026-08-04) — related_name='+' comme les autres FK d'audit du
    # projet (ParametresInscriptions.derniere_modification_par), pas de
    # related_name inverse nécessaire.
    mot_de_passe_reinitialise_par = models.ForeignKey(
        'self', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    date_reinitialisation_mot_de_passe = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.first_name} {self.last_name}"

    class Meta:
        # Recherche globale (Chantier du 2026-08-14) : un index GIN trigram
        # par champ (pas un seul multi-colonnes) — trigram_similar/similarity
        # opèrent colonne par colonne, et first_name/last_name/email/telephone
        # sont recherchés indépendamment (voir dashboard.recherche). Nécessite
        # l'extension pg_trgm, activée par la migration qui précède celle-ci
        # (accounts.migrations : TrigramExtension avant tout AddIndex ici).
        indexes = [
            GinIndex(fields=['first_name'], name='accounts_user_fn_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['last_name'], name='accounts_user_ln_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['email'], name='accounts_user_email_trgm', opclasses=['gin_trgm_ops']),
            GinIndex(fields=['telephone'], name='accounts_user_tel_trgm', opclasses=['gin_trgm_ops']),
        ]


class CompteurMotDePasseSequentiel(models.Model):
    """Fournit un compteur strictement croissant pour le nouveau format de
    mot de passe "zidanieilman<N>@@" (élève/prof/مؤطر — décision du
    directeur du 2026-08-05, remplace la génération aléatoire précédente).
    Chaque appel à generer_mot_de_passe_sequentiel() crée une ligne ici et
    utilise son id comme N — s'appuie sur l'auto-incrément natif de la base
    (séquence Postgres), atomique et sans risque de collision même en cas
    d'accès concurrents, plutôt qu'un simple COUNT() (non atomique, et qui
    régresserait si un compte était supprimé). Compteur UNIQUE et PARTAGÉ
    entre les 3 catégories (pas un compteur séparé par rôle) — choix le plus
    simple à maintenir, aucune information de rôle n'est encodée dans le
    mot de passe de toute façon. Les lignes ne sont jamais supprimées, même
    si le mot de passe qu'elles ont servi à générer est ensuite remplacé —
    seule leur existence compte, pas leur contenu."""
    date_creation = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = "Compteur de mot de passe séquentiel"
        verbose_name_plural = "Compteur de mot de passe séquentiel"


class EleveActifsManager(models.Manager):
    """Exclut les élèves archivés — à utiliser pour toute liste/sélecteur où un
    compte archivé ne doit jamais apparaître (listes actives, groupes, formulaires).
    Ne PAS utiliser pour une fiche/détail par ID déjà connu (ex: page de réactivation),
    qui doit rester accessible même pour un élève archivé — utiliser Eleve.objects
    dans ce cas. Ne remplace PAS le manager par défaut (Eleve.objects reste complet,
    inchangé) précisément pour ne jamais casser un get_object_or_404(Eleve, id=...)
    existant ni le comportement des relations M2M/FK inversées (groupe.eleves.all()
    reste volontairement non filtré — voir accounts/services.py pour le détail de
    la décision Option A/B du chantier d'archivage du 2026-08-03)."""
    def get_queryset(self):
        return super().get_queryset().exclude(statut='archive')


class Eleve(models.Model):
    # gettext_lazy (pas gettext) : ces choices sont évaluées au chargement du
    # module, avant qu'une requête/langue ne soit connue — gettext_lazy retarde
    # la traduction réelle jusqu'au rendu (voir eleve_profil.html, get_statut_display).
    STATUT_CHOICES = [
        ('actif', _('نشط')),
        ('suspendu', _('موقوف')),
        ('archive', _('مؤرشف')),
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
    # Rempli uniquement quand statut='suspendu' (voir dashboard.views.admin_eleve_suspendre),
    # remis à None à la réactivation — permet d'afficher "موقوف منذ X يوم" partout où
    # l'élève apparaît sans qu'un badge statique masque une suspension oubliée depuis
    # des mois (voir Tâche 3 du 2026-07-25).
    date_suspension = models.DateField(null=True, blank=True)
    inscription = models.ForeignKey(
        'inscriptions.InscriptionEleve',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='eleve_valide'
    )

    objects = models.Manager()
    actifs = EleveActifsManager()

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Élève"
        verbose_name_plural = "Élèves"


class ProfActifsManager(models.Manager):
    """Exclut les professeurs archivés — même principe et mêmes précautions
    que EleveActifsManager ci-dessus (voir sa docstring)."""
    def get_queryset(self):
        return super().get_queryset().exclude(statut='archive')


class Prof(models.Model):
    STATUT_CHOICES = [
        ('actif', 'نشط'),
        ('archive', 'مؤرشف'),
    ]
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE
    )
    # Archivage réversible (Tâche du 2026-08-03) — contrairement à Eleve, pas de
    # 'suspendu' pour le prof: seule l'archivation a été demandée pour ce chantier,
    # volontairement hors périmètre pour ne pas ajouter une fonctionnalité non requise.
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='actif'
    )
    ville = models.CharField(max_length=100)
    # Copié depuis InscriptionProf.job_actuel à la validation (Tâche du
    # 2026-08-04) — blank=True ici (contrairement à l'inscription où il est
    # obligatoire) pour ne pas bloquer les profs déjà validés avant ce champ.
    job_actuel = models.CharField(max_length=100, blank=True, default='')
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
    agence_bancaire = models.CharField(max_length=100)
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
    # Infos complémentaires ajoutées par le مدير APRÈS la validation — jamais
    # mélangées avec les champs ci-dessus (ceux-là viennent tels quels du
    # formulaire de candidature d'origine, historique figé, non modifiable
    # depuis la plateforme). Même principe que majoration_mensuelle plus haut.
    notes_admin = models.TextField(blank=True, default='')
    date_debut_effectif = models.DateField(null=True, blank=True)

    objects = models.Manager()
    actifs = ProfActifsManager()

    def __str__(self):
        return str(self.user)

    class Meta:
        verbose_name = "Professeur"
        verbose_name_plural = "Professeurs"
        # Recherche globale (Chantier du 2026-08-14) — voir User.Meta.indexes.
        indexes = [
            GinIndex(fields=['ville'], name='accounts_prof_ville_trgm', opclasses=['gin_trgm_ops']),
        ]


class ElementHakiba(models.Model):
    """Élément de la "حقيبة الأستاذ" ajouté par مدير/مشرف depuis la page centrale
    "إدارة حقيبة الأستاذ" (refonte du 2026-08-05, remplace la v1 du
    2026-08-04 qui vivait sur la fiche de CHAQUE prof individuellement, avec
    un choix de type texte/fichier/vidéo mutuellement exclusif).
    Un élément peut désormais combiner titre + texte + fichier librement (au
    moins texte OU fichier requis — validé côté vue, voir
    dashboard.views._valider_fichier_hakiba et admin_hakiba_ajouter). La vidéo
    n'est plus un type à part : une vidéo s'attache comme n'importe quel
    fichier (voir EXTENSIONS_HAKIBA_AUTORISEES dans dashboard/views.py).
    Ciblage : soit tous les profs (par défaut), soit une sélection précise via
    profs_cibles — remplace l'ancien ForeignKey vers un seul prof (migration
    0029, sans perte : aucune ligne n'existait encore en base au moment de la
    refonte)."""
    titre = models.CharField(max_length=200, blank=True)
    contenu_texte = models.TextField(blank=True)
    fichier = models.FileField(upload_to='hakiba_prof/', null=True, blank=True)
    # True = visible par tous les profs actifs (valeur par défaut, la plus
    # courante d'après le besoin exprimé — ex: ميثاق التدريس, une note générale).
    # False = uniquement les profs listés dans profs_cibles.
    tous_les_profs = models.BooleanField(default=True)
    profs_cibles = models.ManyToManyField(Prof, blank=True, related_name='elements_hakiba')
    # Trace qui a ajouté/modifié cet élément — مدير ET مشرف interviennent tous
    # les deux sur la même حقيبة, contrairement aux autres réglages du projet
    # où un seul rôle édite (voir ParametresInscriptions.derniere_modification_par,
    # même patron FK nullable/SET_NULL repris ici).
    ajoute_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    date_ajout = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.titre or (self.contenu_texte[:40] if self.contenu_texte else 'عنصر بدون عنوان')

    class Meta:
        ordering = ['-date_ajout']
        verbose_name = "Élément de حقيبة الأستاذ"
        verbose_name_plural = "Éléments de حقيبة الأستاذ"


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
    """البرنامج العام لمقرأة زدني علماً — en DEUX versions distinctes (أطفال/بالغون),
    modifiable par مدير ET مشرف (élargi depuis مدير seul — voir Tâche 6b du
    2026-07-25). Chaque version reprend le même patron qu'UNE section de
    CharteEnseignement (titre/intro/items, voir accounts.templatetags.charte_tags.
    parse_items, réutilisé tel quel) plutôt qu'un texte libre unique — champ vide
    avant cette migration, donc aucune donnée à préserver. Affichage conditionnel :
    élève voit sa version selon son âge (courses.utils.tranche_age_depuis_naissance),
    prof voit la/les version(s) selon le type de ses groupes, مؤطر voit les deux en
    lecture seule (voir dashboard.views.programme_general_detail)."""
    titre_enfants = models.CharField(max_length=200, blank=True)
    intro_enfants = models.TextField(blank=True)
    items_enfants = models.TextField(blank=True)

    titre_adultes = models.CharField(max_length=200, blank=True)
    intro_adultes = models.TextField(blank=True)
    items_adultes = models.TextField(blank=True)

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


class NotePersonnelle(models.Model):
    """Carnet de notes personnelles (Tâche du 2026-08-18) qu'un مدير/مشرف tient
    sur le profil d'un élève/prof/مؤطر qu'il consulte — historique horodaté
    (plusieurs notes dans le temps, jamais un champ unique écrasé), STRICTEMENT
    PRIVÉ à son auteur : chaque lecteur ne voit que SES PROPRES notes sur ce
    profil, jamais celles écrites par un autre مدير/مشرف qui aurait aussi accès
    à la même fiche (confirmé explicitement par la cliente).

    Système INDÉPENDANT de accounts.Prof.notes_admin (champ unique partagé,
    objectif différent : suivi RH/évaluation du prof) — ne le remplace pas.

    profil_user (pas un FK direct vers Eleve/Prof/Superviseur) : les 3 modèles
    de profil ont chacun déjà un user = OneToOneField(User) — cler sur User
    couvre les 3 cas avec un seul modèle, sans ContentType ni 3 modèles
    dupliqués, cohérent avec le reste du projet qui clé déjà l'auteur de ce
    genre de contenu sur User (Annonce.cree_par, CommentaireMensuel.redige_par)."""
    profil_user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notes_personnelles_recues'
    )
    auteur = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='notes_personnelles_ecrites'
    )
    # Titre optionnel (Tâche du 2026-08-19) — sert UNIQUEMENT à l'affichage
    # dans la liste (jamais le contenu complet, voir templates/dashboard/
    # _carnet_notes_personnelles.html) : si vide, la liste retombe sur
    # "ملاحظة بتاريخ dd/mm/yyyy" formaté depuis date_creation, jamais sur le
    # contenu. Le contenu complet reste consultable seulement au clic (mode
    # édition), inchangé.
    titre = models.CharField(max_length=200, blank=True, default='')
    contenu = models.TextField()
    date_creation = models.DateTimeField(auto_now_add=True)
    # Modification/suppression réservées à l'auteur (vérifié STRICT côté vue,
    # auteur == request.user — même principe que chat.views.chat_supprimer_message).
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Note de {self.auteur} sur {self.profil_user} ({self.date_creation:%Y-%m-%d})"

    class Meta:
        ordering = ['-date_creation']
        verbose_name = "Note personnelle"
        verbose_name_plural = "Notes personnelles"


class DocumentEleve(models.Model):
    """Cartable élève (Tâche du 2026-08-18) — équivalent, côté élève, du
    accounts.ElementHakiba ("cartable prof") : مدير/مشرف y déposent des fichiers
    (PDF, images, textes...) pour UN élève précis, visibles par cet élève sur
    sa propre page (comme prof_hakiba.html pour ElementHakiba). Contrairement à
    ElementHakiba (un même élément peut cibler tous les profs ou une sélection
    via M2M — mécanisme de DIFFUSION), un DocumentEleve appartient à un seul
    élève : simple FK, pas de M2M — mécanisme de DOSSIER PERSONNEL.
    Upload/suppression réservés à مدير/مشرف (pas le prof, décision confirmée
    du 2026-08-18, cohérent avec ElementHakiba déjà réservé à مدير/مشرف)."""
    eleve = models.ForeignKey('accounts.Eleve', on_delete=models.CASCADE, related_name='documents_cartable')
    titre = models.CharField(max_length=200, blank=True)
    fichier = models.FileField(upload_to='cartable_eleve/%Y/%m/')
    ajoute_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    date_ajout = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre or self.fichier.name

    class Meta:
        ordering = ['-date_ajout']
        verbose_name = "Document du cartable élève"
        verbose_name_plural = "Documents du cartable élève"


class VisibiliteProf(models.Model):
    """Réglage global (مدير + مشرف, mêmes permissions que ProgrammeGeneral) de
    quels champs du profil professeur restent visibles côté élève — singleton
    comme CharteEnseignement/ProgrammeGeneral/LogoConfig (Tâche du 2026-08-03,
    étendue le même jour : couvre désormais TOUTES les sections de la fiche,
    y compris le contact direct — la décision de le bloquer en dur a été
    remplacée par un réglage configurable, pas supprimée définitivement).
    Lu uniquement par eleve_prof_detail.html (seule page où ces sections
    s'affichent désormais — voir sa docstring de vue) au moment du rendu.
    afficher_contact/langues/outils_communication/parcours_scolaire/
    parcours_educatif sont de nouveaux champs, tous à False par défaut (la
    migration qui les ajoute ne change rien au comportement existant tant
    que مدير/مشرف n'y touchent pas) ; afficher_ville/certifications/
    niveau_memorisation/type_eleve_preference existaient déjà, inchangés."""
    afficher_contact = models.BooleanField(default=False)
    afficher_ville = models.BooleanField(default=True)
    afficher_certifications = models.BooleanField(default=True)
    afficher_niveau_memorisation = models.BooleanField(default=True)
    afficher_type_eleve_preference = models.BooleanField(default=True)
    afficher_langues = models.BooleanField(default=False)
    afficher_outils_communication = models.BooleanField(default=False)
    afficher_parcours_scolaire = models.BooleanField(default=False)
    afficher_parcours_educatif = models.BooleanField(default=False)
    # Nouveau champ (Tâche du 2026-08-04), même patron : False par défaut,
    # rien ne change tant que مدير/مشرف n'active pas explicitement.
    afficher_travail_actuel = models.BooleanField(default=False)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "إعدادات ظهور بيانات الأستاذ للطالب"

    class Meta:
        verbose_name = "Visibilité du profil professeur (élève)"
        verbose_name_plural = "Visibilité du profil professeur (élève)"


def get_visibilite_prof():
    """Renvoie l'unique instance de VisibiliteProf, en la créant (valeurs par
    défaut: tout visible, comportement actuel préservé) si elle n'existe pas
    encore — même patron singleton que get_charte()/get_programme_general()."""
    visibilite, _ = VisibiliteProf.objects.get_or_create(pk=1)
    return visibilite


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


class DerniereVisiteNotification(models.Model):
    """Horodatage de dernière visite d'une page cible, PAR TYPE (pas par
    notification individuelle) — repère de lecture du panneau 🔔 الإشعارات
    (Chantier notifications du 2026-08-19). Architecture "Simple" validée
    explicitement (Option A) : un seul timestamp par (user, cle) suffit à
    déterminer ce qui est "nouveau depuis la dernière visite" de cette page —
    pas de table de lecture par objet individuel (pas de LectureConversation-
    like ici). Visiter la page cible marque TOUT ce type comme lu d'un coup ;
    voir dashboard.notifications.marquer_visite.

    cle identifie la PAGE cible, pas le rôle ni le modèle exact source —
    'examens' (examens_eleve_liste), 'notes_seances' (eleve_seances),
    'cartable' (eleve_cartable), 'evaluations_recues'
    (evaluations_prof_recues), 'hakiba' (prof_hakiba). Voir
    dashboard.notifications pour le calcul complet."""
    user = models.ForeignKey(
        User, on_delete=models.CASCADE, related_name='dernieres_visites_notification'
    )
    cle = models.CharField(max_length=30)
    date_visite = models.DateTimeField()

    def __str__(self):
        return f"{self.user} - {self.cle} - {self.date_visite:%Y-%m-%d %H:%M}"

    class Meta:
        unique_together = ('user', 'cle')
        verbose_name = "Dernière visite de notification"
        verbose_name_plural = "Dernières visites de notification"