from django.conf import settings
from django.contrib.postgres.indexes import GinIndex
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
    # Depuis la correction 4 du 2026-08-22 (page مدير, suite au test local) :
    # `label` ne répète PLUS le type d'offre (ex: "شهر", jamais "جماعي -
    # شهر") — ce dernier est déjà visible ailleurs partout où `label` est
    # affiché seul (section dédiée de la liste مدير, voir correction 5 du
    # même cycle ; étape précédente du wizard public). Migration 0025 a
    # nettoyé les libellés existants en base (best-effort, réversible).
    # Avant cette correction, `label` portait le nom complet ("جماعي -
    # شهر") — voir `duree`, ajouté un cycle plus tôt pour le même problème
    # mais uniquement à l'AFFICHAGE (jamais persisté) ; les 2 corrections
    # se recoupent maintenant : `duree` reste un champ à part (jamais
    # dérivé de `label`), simplement rarement nécessaire aujourd'hui que
    # `label` est déjà court.
    label = models.CharField(max_length=100)
    duree = models.CharField(max_length=50, blank=True, default='')
    prix = models.DecimalField(max_digits=8, decimal_places=2)
    # Utilisé pour comparer un abonnement choisi à l'inscription au type_capacite
    # d'un Groupe (courses.utils.raison_incompatibilite_groupe*).
    type_offre = models.CharField(max_length=10, choices=TYPE_OFFRE_CHOICES, default='groupe')
    cible_age = models.CharField(max_length=10, choices=CIBLE_AGE_CHOICES, default='les_deux')
    est_actif = models.BooleanField(default=True)
    ordre = models.IntegerField(default=0)

    def __str__(self):
        # get_type_offre_display() plutôt que `label` seul (depuis la
        # correction 4, `label` ne porte plus le type d'offre) — utile
        # notamment dans l'admin Django natif (inscriptions.admin), qui
        # n'a pas de section dédiée par type comme la liste مدير.
        return f"{self.get_type_offre_display()} - {self.label} ({self.prix} درهم)"

    @property
    def duree_affichee(self):
        """Texte à afficher là où le type d'offre est déjà connu par le
        parcours (wizard public étape Abonnement, admin_eleve_ajouter_
        manuel) — `duree` si le مدير l'a renseignée, sinon `label` en
        entier (jamais un texte vide)."""
        return self.duree or self.label

    class Meta:
        ordering = ['ordre']
        verbose_name = "Type d'abonnement"
        verbose_name_plural = "Types d'abonnement"


class GrillePrixAbonnement(models.Model):
    """Prix EXACT d'un TypeAbonnement pour un nombre de séances/semaine donné
    (Étape 9 du chantier "moteur d'inscription configurable", 2026-08-21) —
    PAS de calcul de supplément : le مدير configure directement le montant
    final de chaque combinaison (type_abonnement, nb_slots), lu tel quel.

    PAS de champ type_offre ici (décision explicite, voir résumé de session) :
    TypeAbonnement.type_offre reste TEL QUEL le seul axe groupe/individuel —
    chaque TypeAbonnement reste dédié à un seul type d'offre (ex: "Mensuel
    Individuel" et "Mensuel Groupe" restent 2 lignes TypeAbonnement séparées,
    comme aujourd'hui). Ajouter type_offre ici aurait permis la contradiction
    d'une ligne de grille pour un type_offre différent de celui de son
    TypeAbonnement — nb_slots suffit donc comme seul axe supplémentaire.

    Si aucune ligne active ne correspond au nb_slots demandé pour un
    TypeAbonnement donné, TypeAbonnement.prix sert de repli — voir
    registration.utils.prix_effectif() : l'élève voit TOUJOURS un prix,
    jamais un blocage silencieux du wizard le temps que le مدير configure
    chaque combinaison. registration.utils.couverture_grille_prix() sert de
    son côté à avertir le مدير (non bloquant) des combinaisons encore
    couvertes seulement par ce repli."""
    type_abonnement = models.ForeignKey(TypeAbonnement, on_delete=models.CASCADE, related_name='grille_prix')
    nb_slots = models.PositiveSmallIntegerField()
    prix = models.DecimalField(max_digits=8, decimal_places=2)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        # str(self.type_abonnement) plutôt que .label seul (depuis la
        # correction 4, .label ne porte plus le type d'offre جماعي/فردي).
        return f"{self.type_abonnement} — {self.nb_slots} حصص/أسبوع ({self.prix} درهم)"

    class Meta:
        unique_together = ('type_abonnement', 'nb_slots')
        ordering = ['type_abonnement__ordre', 'nb_slots']
        verbose_name = "Prix de grille (abonnement × nb séances)"
        verbose_name_plural = "Grille de prix des abonnements"


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
    # "nom" = NOM COMPLET (prénom + nom de famille ensemble) — le formulaire
    # public (eleve_formulaire.html) ne demande qu'une seule case, labellisée
    # "الاسم الكامل" ("nom complet"). Contrairement à InscriptionProf (où
    # nom/prenom sont une vraie paire de champs séparés — voir sa docstring
    # pour la confusion de nommage propre à ce modèle-là, hors sujet ici),
    # côté élève "prenom" n'a jamais existé dans le formulaire : aucun input
    # ne le cible, inscriptions/views.py ne le lit jamais depuis
    # request.POST. Toujours vide en production (audit du 2026-08-09 :
    # 0/26 candidatures avec prenom non vide). Ajouté puis retiré de
    # l'affichage le même jour (admin_inscription_detail.html /
    # admin_eleve_detail.html) pour la même raison que veut_contribuer plus
    # bas : afficher un champ structurellement toujours vide serait
    # trompeur. Champ laissé tel quel dans le modèle (pas de migration) —
    # aucune régression à corriger, juste rien à faire avec pour l'instant.
    prenom = models.CharField(max_length=100, blank=True)
    nom_parent = models.CharField(max_length=100, blank=True)
    date_naissance = models.DateField()
    sexe = models.CharField(max_length=10)
    telephone = models.CharField(max_length=20)
    email = models.EmailField()
    # Profession — un SEUL champ, pas deux colonnes séparées (Tâche du
    # 2026-08-05) : sa signification ("العمل الحالي" du candidat lui-même, ou
    # "عمل ولي الأمر" si c'est un enfant) se déduit sans ambiguïté de
    # nom_parent (rempli <=> inscription enfant, même discriminant déjà
    # utilisé partout ailleurs dans ce formulaire) — jamais les deux à la
    # fois pour une même ligne, donc aucune perte de clarté à les fusionner.
    # Optionnel (blank=True) : contrairement à InscriptionProf.job_actuel
    # (obligatoire), rien ici n'a demandé de le rendre requis.
    job_actuel = models.CharField(max_length=100, blank=True, default='')
    # Nouveau champ structurel ajouté le 2026-08-22 (chantier "champs
    # structurels configurables") — même statut que job_actuel : une vraie
    # colonne, jamais migrée vers l'EAV, optionnelle par défaut (obligatoire
    # géré par registration.models.ConfigurationChampStructurel, pas ici).
    niveau_scolaire = models.CharField(max_length=100, blank=True, default='')

    # Programme
    creneau_souhaite = models.ForeignKey(
        'courses.Creneau',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='inscriptions'
    )
    # Chantier du moteur d'inscription configurable (registration.utils.inscrire_eleve)
    # — le nouveau parcours "Groupe" choisit un groupe PRÉCIS dès l'étape 3 de la
    # candidature, avant toute validation admin. Contrairement à creneau_souhaite
    # ci-dessus (vestige de l'ancien formulaire, jamais rempli par
    # inscription_eleve_formulaire depuis longtemps), ce champ EST activement écrit
    # par inscrire_eleve() dès qu'un groupe est choisi. Un Eleve n'existe pas encore
    # à ce stade (Groupe.eleves est un M2M vers accounts.Eleve, créé seulement à la
    # validation) — ce FK mémorise donc le choix jusqu'à la validation admin, qui
    # devra le lire pour rattacher automatiquement le nouvel Eleve à CE groupe
    # (câblage laissé à un chantier ultérieur — non modifié ici, voir
    # dashboard.views.admin_valider_eleve, existant, non touché par ce commit).
    # SET_NULL : la suppression du groupe ne doit jamais faire échouer/perdre la
    # candidature, seulement oublier le choix (même raisonnement que
    # creneau_souhaite juste au-dessus).
    groupe_choisi = models.ForeignKey(
        'courses.Groupe',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='candidatures_le_choisissant',
    )
    # Étape 7 du chantier du moteur d'inscription configurable — trace QUI a
    # créé la candidature quand ce n'est PAS l'élève lui-même (ajout manuel
    # par le Directeur ou le مشرف via dashboard.views.admin_eleve_ajouter_
    # manuel, registration.utils.inscrire_eleve(cree_par=request.user)).
    # None = formulaire public (l'écrasante majorité des candidatures) — la
    # valeur par défaut de inscrire_eleve() est cree_par=None, donc ce champ
    # ne se remplit QUE quand un membre du staff est explicitement à
    # l'origine de la création. SET_NULL : la suppression du compte staff ne
    # doit jamais faire perdre la candidature elle-même, seulement la trace
    # de qui l'a créée (même raisonnement que groupe_choisi ci-dessus).
    cree_par = models.ForeignKey(
        'accounts.User',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='candidatures_eleve_creees_manuellement',
    )
    programme = models.CharField(max_length=20, choices=PROGRAMME_CHOICES, blank=True, default='')
    riwaya = models.CharField(max_length=10, choices=RIWAYA_CHOICES, blank=True, default='')
    # blank/default ajoutés au chantier du moteur d'inscription configurable :
    # "وسيلة الحضور" ne fait pas encore partie du nouveau parcours (registration.
    # utils.inscrire_eleve) — laissé vide pour toute candidature créée par ce
    # nouveau chemin, jusqu'à ce qu'un chantier ultérieur décide où il doit vivre
    # (champ informatif générique, ou critère filtrable dédié). Comportement de
    # l'ancien formulaire à une page totalement inchangé (outil reste rempli comme
    # avant pour ce chemin-là, seule la contrainte "obligatoire" est relâchée).
    outil = models.CharField(max_length=20, choices=OUTIL_CHOICES, blank=True, default='')
    abonnement = models.CharField(max_length=30)

    # Extras
    accepte_conditions = models.BooleanField(default=False)
    # NOTE (audit du 2026-08-09) : ce champ n'est jamais rempli. Le formulaire
    # public (templates/inscriptions/eleve_formulaire.html) ne pose pas cette
    # question et inscriptions/views.py ne le lit jamais depuis request.POST
    # à la création — il vaut donc toujours False, pour toute candidature,
    # passée et future, tant que ces deux endroits ne sont pas modifiés
    # ensemble. Volontairement PAS affiché sur les pages détail (candidature
    # / fiche élève) : afficher "❌ لا" sur 100% des candidatures serait
    # trompeur (ça a l'air d'une vraie réponse alors que la question n'a
    # jamais été posée). Pour l'activer un jour : ajouter le champ au
    # formulaire, le lire dans la vue, PUIS l'afficher.
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
    # Chantier du 2026-08-14 (refus avec motif) : texte FIGÉ au moment du
    # refus — totalement indépendant de PhraseRefus (voir ce modèle plus
    # bas). Même si la phrase-modèle qui a servi de base est modifiée ou
    # supprimée ensuite, ce texte-ci ne change jamais : il est COPIÉ, pas
    # référencé (aucune FK vers PhraseRefus).
    motif_refus = models.TextField(blank=True)

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

    def abonnement_obj(self):
        """L'instance TypeAbonnement choisie, ou None si supprimée depuis —
        ajouté le 2026-08-22 (audit page détail candidature) pour afficher le
        prix effectif SANS dupliquer la requête déjà faite par abonnement_
        label()/abonnement_type_offre() (chacune reste inchangée, existait déjà
        avant cet ajout)."""
        return TypeAbonnement.objects.filter(code=self.abonnement).first()

    def nb_slots_choisi(self):
        """Nombre de séances/semaine RÉELLEMENT répondu par le candidat au
        nouveau parcours (registration.models.ReponseInscription, critère
        backend='nb_slots', chantier "liberté totale du nombre de séances") —
        None si jamais répondu (masqué par une règle, ou candidature de
        l'ANCIEN formulaire à une page, qui n'a jamais eu ce concept — aucune
        ReponseInscription n'existe alors pour cette candidature)."""
        reponse = self.reponses.filter(critere__backend='nb_slots').exclude(valeur_texte='').first()
        if reponse is None:
            return None
        try:
            return int(reponse.valeur_texte)
        except (ValueError, TypeError):
            return None

    def prix_effectif_calcule(self):
        """Prix RÉELLEMENT applicable à cette candidature (registration.utils.
        prix_effectif, même fonction que le wizard/l'ajout manuel) — None si
        l'abonnement a été supprimé depuis (voir abonnement_obj). Ajouté le
        2026-08-22 (audit page détail candidature, point 6) : jusque-là la
        page affichait le nom de l'abonnement sans aucun prix."""
        from registration.utils import prix_effectif

        type_abo = self.abonnement_obj()
        if type_abo is None:
            return None
        return prix_effectif(type_abo, self.nb_slots_choisi())

    class Meta:
        verbose_name = "Inscription Élève"
        verbose_name_plural = "Inscriptions Élèves"
        # Recherche globale (Chantier du 2026-08-14) — nom_parent recherché via
        # Eleve.inscription (FK nullable, SET_NULL) pour le "nom du parent" de
        # la fiche élève. Voir accounts.models.User.Meta.indexes.
        indexes = [
            GinIndex(fields=['nom_parent'], name='inscriptions_ins_parent_trgm', opclasses=['gin_trgm_ops']),
        ]


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
    # Chantier du 2026-08-14 — voir InscriptionEleve.motif_refus (même
    # principe exact : texte figé, indépendant de PhraseRefus). Un seul
    # champ ici même si le refus peut survenir à 2 étapes différentes
    # (مدير étape 1, مشرف étape 2) : un dossier n'est jamais refusé aux
    # DEUX étapes (voir docstring de PhraseRefus) — un seul refus possible
    # par dossier, donc un seul motif à stocker.
    motif_refus = models.TextField(blank=True)

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
    # Chantier du nouveau parcours d'inscription — anciennement "10 jours" en dur nulle
    # part dans le code (aucune trace trouvée lors de l'audit : ce délai n'existait
    # encore dans aucun modèle avant ce chantier). Lu par le nouveau parcours pour
    # calculer la date limite de paiement affichée à l'élève (aujourd'hui + ce délai),
    # jamais recalculé en dur ailleurs.
    delai_paiement_jours = models.PositiveIntegerField(default=10)
    # Délai annoncé dans le message de confirmation (registration.models.
    # PresentationInscription.message_bienvenue) : "l'équipe vous contactera sous
    # {delai_contact_heures}h" — injecté au rendu, jamais recopié en dur dans le texte.
    delai_contact_heures = models.PositiveIntegerField(default=24)
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

class PhraseRefus(models.Model):
    """Phrase-modèle réutilisable pour motiver un refus de candidature —
    Chantier du 2026-08-14. Liée au CONTEXTE (donc au RÔLE qui l'utilise, pas
    à un compte individuel) : si plusieurs comptes مدير existent un jour, ils
    partagent la même liste pour un même contexte — aucune FK vers User.

    3 contextes strictement cloisonnés, correspondant exactement aux 3
    endroits où un refus peut avoir lieu (voir InscriptionEleve.motif_refus/
    InscriptionProf.motif_refus — un dossier n'est JAMAIS refusé à 2 endroits,
    donc ces 3 listes ne se recoupent jamais pour un même refus) :
    - refus_eleve : مدير refuse une candidature élève (seul palier, définitif).
    - refus_prof_etape1 : مدير refuse une candidature prof à l'étape 1
      (définitif — le مشرف ne voit jamais ce dossier si refusé ici).
    - refus_prof_etape2 : مشرف refuse une candidature prof déjà pré-validée
      par مدير, à l'étape 2 (définitif aussi, pas de retour au مدير).

    Totalement indépendant du texte figé sur motif_refus une fois un refus
    effectué : le texte y est COPIÉ au moment du refus, jamais référencé par
    FK — supprimer une phrase ici n'affecte donc jamais l'historique des
    refus déjà passés."""
    CONTEXTE_CHOICES = [
        ('refus_eleve', 'رفض طلب طالب (المدير)'),
        ('refus_prof_etape1', 'رفض طلب أستاذ - المرحلة الأولى (المدير)'),
        ('refus_prof_etape2', 'رفض طلب أستاذ - المرحلة الثانية (المشرف)'),
    ]
    contexte = models.CharField(max_length=30, choices=CONTEXTE_CHOICES)
    texte = models.TextField()
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.texte[:60]

    class Meta:
        ordering = ['-date_creation']
        verbose_name = "Phrase de refus"
        verbose_name_plural = "Phrases de refus"
