
from django.contrib.auth.models import AbstractUser
from django.contrib.postgres.indexes import GinIndex
from django.db import models
from django.utils.translation import gettext_lazy as _, get_language


class User(AbstractUser):
    ROLE_CHOICES = [
        ('eleve', _('طالب')),
        ('prof', _('معلم')),
        ('superviseur', _('مؤطر')),
        ('admin', _('الإدارة')),
        ('mshrif', _('المشرف')),
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
            # Correctif perf (audit du 2026-09-02) : le GIN trigram ci-dessus sert
            # la recherche floue (dashboard.recherche), pas l'égalité stricte —
            # Postgres ne l'utilise jamais pour un simple `WHERE email = ...`. Or
            # accounts.backend.EmailBackend.authenticate() (donc CHAQUE connexion,
            # accounts.views.login_view) fait exactement ça. Sans index btree
            # dédié, EXPLAIN ANALYZE confirme un Seq Scan sur toute la table à
            # chaque login. Pas unique=True : plusieurs comptes peuvent
            # légitimement partager le même email (voir docstring EmailBackend,
            # chantier du 2026-08-10).
            models.Index(fields=['email'], name='accounts_user_email_btree'),
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
        ('actif', _('نشط')),
        ('archive', _('مؤرشف')),
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
    # Acceptation du ميثاق التدريس (voir CharteEnseignement ci-dessous) — Chantier
    # du 2026-08-27 : DÉSORMAIS renseignée au moment de la CANDIDATURE (voir
    # inscriptions.models.InscriptionProf.charte_acceptee, copiée telle quelle
    # ici par dashboard.views._creer_compte_prof à la création du compte),
    # jamais depuis l'espace prof — cocher la case y était auparavant possible
    # (dashboard.views.prof_charte) mais SANS bloquer l'inscription; ce n'est
    # plus le cas: un candidat qui ne coche pas à la candidature ne peut plus
    # finaliser son inscription du tout, donc ce champ est garanti True pour
    # tout Prof créé depuis ce chantier. Reste False pour les comptes créés
    # AVANT (jamais rétroactivement rempli — aucune demande en ce sens).
    charte_acceptee = models.BooleanField(default=False)
    date_acceptation_charte = models.DateTimeField(null=True, blank=True)
    # Infos complémentaires ajoutées par le مدير APRÈS la validation — jamais
    # mélangées avec les champs ci-dessus (ceux-là viennent tels quels du
    # formulaire de candidature d'origine, historique figé, non modifiable
    # depuis la plateforme). Même principe que majoration_mensuelle plus haut.
    notes_admin = models.TextField(blank=True, default='')
    date_debut_effectif = models.DateField(null=True, blank=True)
    # Paragraphe de présentation généré UNE FOIS à la création du compte
    # (accounts.services.generer_presentation_publique, appelé depuis
    # dashboard.views._creer_compte_prof — même point pour la validation
    # classique du مشرف et l'ajout manuel direct, Chantier du 2026-08-27),
    # à partir des champs déjà remplis à la candidature (parcours_scolaire,
    # certifications, niveau_memorisation...). JAMAIS régénéré automatiquement
    # ensuite — même patron que registration.models.PresentationInscription.
    # texte_attente_groupe : مدير/مشرف peuvent l'affiner à la main via
    # dashboard.views.admin_prof_presentation_modifier, sans qu'une nouvelle
    # génération n'écrase leur texte. Affiché dans les cartes halaka du wizard
    # d'inscription (templates/inscriptions/wizard_groupe.html), gated par
    # VisibiliteProf.afficher_presentation_wizard ci-dessous.
    presentation_publique = models.TextField(blank=True, default='')
    # _fr/_en (chantier i18n du 2026-08-29, bug signalé : cette nubdha reste
    # arabe même en session FR/EN) — même patron que registration.models.
    # PresentationInscription/Groupe.nom_fr ci-dessus : saisie manuelle par
    # le مدير/مشرف (dashboard.views.admin_prof_presentation_modifier),
    # jamais une traduction automatique. Optionnels : `presentation_publique_
    # localise` retombe sur l'arabe si la traduction n'est pas encore saisie.
    presentation_publique_fr = models.TextField(blank=True, default='')
    presentation_publique_en = models.TextField(blank=True, default='')

    objects = models.Manager()
    actifs = ProfActifsManager()

    def __str__(self):
        return str(self.user)

    def _localise(self, champ_base):
        """Voir registration.models.PresentationInscription._localise —
        même logique (repli arabe automatique), appliquée ici à
        presentation_publique."""
        langue = get_language()
        if langue in ('fr', 'en'):
            valeur = getattr(self, f'{champ_base}_{langue}', '')
            if valeur:
                return valeur
        return getattr(self, champ_base)

    @property
    def presentation_publique_localise(self):
        return self._localise('presentation_publique')

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
    titre_fr = models.CharField(max_length=200, blank=True, default='')
    titre_en = models.CharField(max_length=200, blank=True, default='')
    contenu_texte = models.TextField(blank=True)
    contenu_texte_fr = models.TextField(blank=True, default='')
    contenu_texte_en = models.TextField(blank=True, default='')
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

    def _localise(self, champ_base):
        """Repli langue active -> arabe (chantier i18n contenu-DB, 2026-08-31)
        — voir Prof._localise. Contenu vu par les profs (حقيبة الأستاذ)."""
        langue = get_language()
        if langue in ('fr', 'en'):
            valeur = getattr(self, f'{champ_base}_{langue}', '')
            if valeur:
                return valeur
        return getattr(self, champ_base)

    @property
    def titre_localise(self):
        return self._localise('titre')

    @property
    def contenu_texte_localise(self):
        return self._localise('contenu_texte')

    @property
    def fichier_apercu_type(self):
        """'image'/'video'/'audio'/'embed' selon ce que le navigateur sait
        afficher en aperçu intégré, '' sinon. Voir core.media_proxy.type_apercu."""
        from core.media_proxy import type_apercu
        return type_apercu(self.fichier.name) if self.fichier else ''

    @property
    def fichier_affichable_navigateur(self):
        """True si le fichier joint peut s'afficher (aperçu intégré : PDF,
        image, audio, vidéo, texte) — le template affiche alors "فتح" en plus
        de "تحميل"."""
        return bool(self.fichier_apercu_type)

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

    # Chantier i18n du 2026-08-28 (trouvaille de la session parallèle pendant
    # son propre chantier — même profil que registration.models.
    # PresentationInscription : contenu rédigé par le مشرف/مدير, `{% trans %}`
    # ne peut rien pour lui). Décision produit identique (voir
    # PresentationInscription.__doc__) : saisie manuelle par langue, PAS de
    # traduction automatique.
    #
    # PresentationInscription (6 champs) a reçu une paire de colonnes _fr/_en
    # PAR CHAMP — ici, 27 champs texte (voir _CHAMPS_LOCALISABLES) auraient
    # demandé 54 colonnes supplémentaires, un formulaire d'admin illisible et
    # une migration disproportionnée pour le même besoin. Un seul JSONField
    # {"fr": {"section1_titre": "...", ...}, "en": {...}} scale au nombre de
    # champs sans ajouter de colonne à chaque nouvelle section de la charte —
    # même idiome que Prof.langues/type_eleve_preference (JSONField déjà
    # utilisé ailleurs dans ce projet pour des données structurées variables),
    # simplement appliqué ici à des chaînes de traduction plutôt qu'à des
    # listes de codes. Le formulaire (mshrif_charte.html) garde les MÊMES noms
    # d'input "{champ}_fr"/"{champ}_en" que PresentationInscription — seule la
    # colonne de stockage change, pas l'UX ni la convention de nommage.
    traductions = models.JSONField(default=dict, blank=True)

    # Les 27 champs texte de la charte (hors sanctions, gérées à part sur
    # CharteSanctionLigne) — seule liste de référence, jamais dupliquée
    # ailleurs (dashboard.views.mshrif_charte et _charte_contenu.html/
    # mshrif_charte.html s'appuient tous les deux dessus indirectement via
    # localise()).
    _CHAMPS_LOCALISABLES = (
        'intro', 'verset_ouverture', 'titre_bunud',
        'section1_titre', 'section1_intro', 'section1_items',
        'section2_titre', 'section2_intro', 'section2_items',
        'section3_titre', 'section3_intro', 'section3_items',
        'verset_rahma_texte', 'verset_rahma_reference', 'section3_conclusion',
        'section4_titre', 'section4_intro', 'section4_items',
        'section5_titre', 'section5_intro', 'section5_note',
        'section6_titre', 'section6_intro', 'section6_items',
        'section7_titre', 'section7_intro', 'section7_items',
    )

    def _localise(self, champ):
        """Renvoie la valeur de `champ` dans la langue active de la session,
        avec repli automatique sur l'arabe (le champ lui-même) si la
        traduction FR/EN correspondante n'a pas encore été saisie — jamais de
        texte manquant à l'affichage. Appelé depuis les templates via le
        filtre {{ charte|localise:"champ" }} (voir accounts.templatetags.
        charte_tags.localise), pas directement — Django ne permet pas
        d'appeler une méthode avec un argument depuis un template."""
        langue = get_language()
        if langue in ('fr', 'en'):
            valeur = (self.traductions.get(langue) or {}).get(champ, '')
            if valeur:
                return valeur
        return getattr(self, champ)

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
        ('immediate', _('الإعفاء الفوري')),
        ('progressive', _('إنذار أول ← إنذار ثاني ← خصم من الراتب')),
    ]
    charte = models.ForeignKey(CharteEnseignement, on_delete=models.CASCADE, related_name='sanctions')
    ordre = models.PositiveIntegerField(default=0)
    violation = models.CharField(max_length=300)
    # _fr/_en (chantier i18n du 2026-08-28) : ici colonnes explicites (comme
    # PresentationInscription), pas de JSONField comme CharteEnseignement
    # ci-dessus — un seul champ à traduire par ligne, pas 27, donc pas la même
    # disproportion. Toute la table est de toute façon rechargée à chaque
    # sauvegarde (voir dashboard.views.mshrif_charte), les traductions
    # suivent le même sort.
    violation_fr = models.CharField(max_length=300, blank=True, default='')
    violation_en = models.CharField(max_length=300, blank=True, default='')
    severite = models.CharField(max_length=20, choices=SEVERITE_CHOICES, default='progressive')

    class Meta:
        ordering = ['ordre', 'id']

    def _localise(self, champ):
        """Même mécanisme que CharteEnseignement._localise (repli arabe si
        FR/EN vide) — colonnes explicites ici plutôt que JSONField, voir
        violation_fr/violation_en ci-dessus."""
        langue = get_language()
        if langue in ('fr', 'en'):
            valeur = getattr(self, f'{champ}_{langue}', '')
            if valeur:
                return valeur
        return getattr(self, champ)

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

    # Traductions FR/EN manuelles (chantier i18n contenu-DB, 2026-08-31) —
    # même patron que registration.PresentationInscription : optionnelles,
    # repli automatique sur l'arabe via _localise / <champ>_localise. Contenu
    # vu par l'élève et le prof.
    titre_enfants_fr = models.CharField(max_length=200, blank=True, default='')
    titre_enfants_en = models.CharField(max_length=200, blank=True, default='')
    intro_enfants_fr = models.TextField(blank=True, default='')
    intro_enfants_en = models.TextField(blank=True, default='')
    items_enfants_fr = models.TextField(blank=True, default='')
    items_enfants_en = models.TextField(blank=True, default='')
    titre_adultes_fr = models.CharField(max_length=200, blank=True, default='')
    titre_adultes_en = models.CharField(max_length=200, blank=True, default='')
    intro_adultes_fr = models.TextField(blank=True, default='')
    intro_adultes_en = models.TextField(blank=True, default='')
    items_adultes_fr = models.TextField(blank=True, default='')
    items_adultes_en = models.TextField(blank=True, default='')

    date_modification = models.DateTimeField(auto_now=True)

    _CHAMPS_LOCALISABLES = (
        'titre_enfants', 'intro_enfants', 'items_enfants',
        'titre_adultes', 'intro_adultes', 'items_adultes',
    )

    def __str__(self):
        return "البرنامج العام"

    def _localise(self, champ_base):
        """Repli langue active -> arabe — voir Prof._localise / PresentationInscription._localise."""
        langue = get_language()
        if langue in ('fr', 'en'):
            valeur = getattr(self, f'{champ_base}_{langue}', '')
            if valeur:
                return valeur
        return getattr(self, champ_base)

    @property
    def titre_enfants_localise(self):
        return self._localise('titre_enfants')

    @property
    def intro_enfants_localise(self):
        return self._localise('intro_enfants')

    @property
    def items_enfants_localise(self):
        return self._localise('items_enfants')

    @property
    def titre_adultes_localise(self):
        return self._localise('titre_adultes')

    @property
    def intro_adultes_localise(self):
        return self._localise('intro_adultes')

    @property
    def items_adultes_localise(self):
        return self._localise('items_adultes')

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


CLE_CACHE_LOGO_CONFIG = 'logo_config'


def get_logo_config():
    """Renvoie l'unique instance de LogoConfig, en la créant (vide -> logo=None,
    donc fallback sur le logo statique par défaut) si elle n'existe pas encore.

    Mise en cache 5 min (Correctif perf du 2026-08-30) : appelée par
    accounts.context_processors.logo_context sur ABSOLUMENT CHAQUE page du
    site (dashboard ET pages publiques : connexion, inscription) — sans
    cache, c'est une requête DB en plus sur chaque page, pour une donnée qui
    ne change qu'à chaque changement de logo par le المشرف (voir
    invalider_cache_logo_config, appelée depuis dashboard.views.mshrif_logo).
    Même patron que chat.services.total_messages_non_lus (déjà caché 15s)."""
    from django.core.cache import cache

    config = cache.get(CLE_CACHE_LOGO_CONFIG)
    if config is not None:
        return config
    config, _ = LogoConfig.objects.get_or_create(pk=1)
    cache.set(CLE_CACHE_LOGO_CONFIG, config, 300)
    return config


def invalider_cache_logo_config():
    """À appeler juste après tout config.save() sur LogoConfig (voir
    dashboard.views.mshrif_logo) — sinon l'ancien logo resterait affiché
    partout jusqu'à expiration du cache (5 min)."""
    from django.core.cache import cache

    cache.delete(CLE_CACHE_LOGO_CONFIG)


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
    """Cartable élève (Tâche du 2026-08-18, refondue le 2026-08-30) —
    équivalent, côté élève, du accounts.ElementHakiba ("cartable prof") :
    مدير/مشرف y déposent des fichiers (PDF, images, textes...) visibles par
    le(s) élève(s) concerné(s) sur leur propre page (comme prof_hakiba.html
    pour ElementHakiba).

    Refonte du 2026-08-30 (demande explicite du client) : à l'origine, un
    DocumentEleve appartenait à un seul élève (simple FK, "mécanisme de
    DOSSIER PERSONNEL") — cibler "كل الطلاب"/"فئة معينة" à l'ajout créait
    donc une COPIE par élève déjà inscrit à ce moment-là. Conséquence non
    voulue : un élève inscrit APRÈS coup ne voyait jamais ces fichiers tant
    que مدير/مشرف ne refaisait pas l'ajout manuellement. Désormais UN SEUL
    enregistrement par fichier ajouté, avec un ciblage RECALCULÉ À CHAQUE
    AFFICHAGE (voir pour_eleve() ci-dessous) — même principe que
    ElementHakiba.tous_les_profs/profs_cibles, étendu d'un mode "catégorie"
    (mêmes 3 modes que l'ancien formulaire d'ajout, voir dashboard.views.
    admin_eleve_cartable_ajouter) :
      - 'tous' : visible par tous les élèves, y compris ceux inscrits après
        l'ajout du fichier ;
      - 'categorie' : visible par tout élève ayant au moins un groupe ACTIF
        dont Groupe.categorie == categorie_cible (recalculé à chaque
        affichage — un élève qui change de groupe change donc aussi ce
        qu'il voit, pas figé à l'ajout) ;
      - 'specifique' : visible seulement par les élèves listés dans
        eleves_cibles (M2M, plusieurs élèves possibles par fichier).
    Migration 0038 : les DocumentEleve déjà en base (chacun lié à un seul
    élève via l'ancien FK) sont passés en 'specifique' avec ce même élève
    dans eleves_cibles — comportement inchangé pour l'existant, seuls les
    NOUVEAUX ajouts profitent du ciblage dynamique 'tous'/'categorie'.
    Upload/suppression réservés à مدير/مشرف (pas le prof, décision confirmée
    du 2026-08-18, cohérent avec ElementHakiba déjà réservé à مدير/مشرف)."""
    CIBLE_TOUS = 'tous'
    CIBLE_CATEGORIE = 'categorie'
    CIBLE_SPECIFIQUE = 'specifique'
    CIBLE_CHOICES = [
        (CIBLE_TOUS, 'كل الطلاب'),
        (CIBLE_CATEGORIE, 'فئة معينة'),
        (CIBLE_SPECIFIQUE, 'طلاب محددون'),
    ]
    cible_type = models.CharField(max_length=20, choices=CIBLE_CHOICES, default=CIBLE_SPECIFIQUE)
    # Rempli seulement si cible_type == 'categorie' — une des 3 valeurs de
    # annonces.services.CANAUX (même source que Groupe.categorie).
    categorie_cible = models.CharField(max_length=20, blank=True, default='')
    # Rempli seulement si cible_type == 'specifique'.
    eleves_cibles = models.ManyToManyField(
        'accounts.Eleve', blank=True, related_name='documents_cartable_cibles'
    )
    titre = models.CharField(max_length=200, blank=True)
    titre_fr = models.CharField(max_length=200, blank=True, default='')
    titre_en = models.CharField(max_length=200, blank=True, default='')
    fichier = models.FileField(upload_to='cartable_eleve/%Y/%m/')
    ajoute_par = models.ForeignKey(
        User, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    date_ajout = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.titre or self.fichier.name

    @property
    def titre_localise(self):
        """Repli langue active -> arabe (chantier i18n contenu-DB, 2026-08-31).
        Vu par l'élève (حقيبتي / cartable)."""
        langue = get_language()
        if langue == 'fr' and self.titre_fr:
            return self.titre_fr
        if langue == 'en' and self.titre_en:
            return self.titre_en
        return self.titre

    @property
    def fichier_apercu_type(self):
        """'image'/'video'/'audio'/'embed' selon ce que le navigateur sait
        afficher en aperçu intégré, '' sinon. Voir core.media_proxy.type_apercu."""
        from core.media_proxy import type_apercu
        return type_apercu(self.fichier.name) if self.fichier else ''

    @property
    def fichier_affichable_navigateur(self):
        """True si le fichier peut s'afficher (aperçu intégré : PDF, image,
        audio, vidéo, texte) — le template affiche alors "فتح" en plus de
        "تحميل"."""
        return bool(self.fichier_apercu_type)

    def description_cible(self):
        """Libellé arabe lisible du ciblage, pour l'affichage dans
        admin_eleve_cartable_gestion.html (remplace l'ancien doc.eleve.user.
        get_full_name, qui n'a plus de sens pour un fichier partagé)."""
        if self.cible_type == self.CIBLE_TOUS:
            return 'كل الطلاب'
        if self.cible_type == self.CIBLE_CATEGORIE:
            from annonces.services import canal_pour_code
            canal = canal_pour_code(self.categorie_cible)
            return f'فئة: {canal["nom"]}' if canal else 'فئة معينة'
        noms = [e.user.get_full_name() for e in self.eleves_cibles.all()]
        if not noms:
            return '—'
        if len(noms) == 1:
            return noms[0]
        return f'{len(noms)} طلاب: ' + '، '.join(noms)

    @classmethod
    def pour_eleve(cls, eleve):
        """Tous les DocumentEleve visibles par cet élève, tous modes de
        ciblage confondus — SEULE façon correcte de lister le cartable d'un
        élève désormais (voir docstring de classe). Recalculée à chaque
        appel, jamais mise en cache : un fichier 'tous'/'categorie' ajouté
        avant l'inscription de cet élève apparaît donc dès son premier
        appel, sans action manuelle de مدير/مشرف."""
        from django.db.models import Q

        categories = set(
            eleve.groupes.filter(statut='actif')
            .exclude(categorie='')
            .values_list('categorie', flat=True)
        )
        q = Q(cible_type=cls.CIBLE_TOUS) | Q(cible_type=cls.CIBLE_SPECIFIQUE, eleves_cibles=eleve)
        if categories:
            q |= Q(cible_type=cls.CIBLE_CATEGORIE, categorie_cible__in=categories)
        return cls.objects.filter(q).distinct()

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
    # Chantier du 2026-08-27 : contrôle l'affichage du paragraphe Prof.
    # presentation_publique dans les cartes halaka du wizard d'inscription
    # (templates/inscriptions/wizard_groupe.html) — SEUL réglage de ce
    # modèle qui ne s'applique pas à eleve_prof_detail.html (voir sa
    # docstring). True par défaut (contrairement aux champs plus personnels
    # ci-dessus) : ce paragraphe est pensé comme une information de
    # présentation généraliste, utile dès la première visite d'un candidat
    # qui ne connaît pas encore l'école, pas une donnée sensible masquée par
    # prudence.
    afficher_presentation_wizard = models.BooleanField(default=True)
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
    (evaluations_prof_recues), 'hakiba' (prof_hakiba), 'demandes_inscription'
    (admin_inscriptions, مدير ET مشرف), 'demandes_inscription_prof'
    (admin_inscriptions + admin_inscription_prof_detail, مدير uniquement —
    nouvelle candidature prof en attente de pré-validation étape 1),
    'profs_en_attente_validation'
    (mshrif_inscriptions_profs, مشرف uniquement — Fonctionnalité 3,
    2026-08-27), 'demandes_changement_halaka' (admin_demandes_changement_
    halaka, مدير ET مشرف — Fonctionnalité 4, 2026-08-27),
    'paiements_retard' (eleve_paiements, élève — retard de paiement de son
    abonnement, chantier du 2026-09-01), 'paiements_retard_eleves'
    (paiements_retards, مدير ET مشرف — élèves en retard de paiement),
    'nouveaux_paiements' (admin_paiements + admin_paiement_detail, مدير ET
    مشرف — nouveau paiement soumis par un élève, chantier du 2026-09-04).
    Voir dashboard.notifications pour le calcul complet."""
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