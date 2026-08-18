import datetime

from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import Sum
from django.utils import timezone


class Examen(models.Model):
    """Un examen créé par un prof pour UN groupe précis — même patron que
    courses.Seance.groupe (FK simple, pas M2M) : un examen suit un groupe,
    exactement comme une séance. Cycle de vie à 3 statuts (brouillon/publié/
    fermé) dont le passage est TOUJOURS déclenché explicitement par une vue
    (examens.views.examen_publier/examen_fermer), jamais par un signal ou une
    tâche planifiée — même choix que Seance.statut='terminee', posé
    explicitement par prof_presence_sauvegarder plutôt que recalculé en
    arrière-plan.

    Deux verrous distincts, tous deux calculés depuis l'état ACTUEL des
    Copie (jamais un booléen stocké qui pourrait se désynchroniser) :
    - a_copie_demarree (verrou du CHRONO : groupe/date_debut/date_limite/
      duree_minutes) dès qu'une Copie existe, même 'en_cours' — décision
      validée le 2026-08-16 : modifier la durée/l'échéance après qu'un élève
      a commencé casserait le calcul de Copie.date_expiration_effective déjà
      engagé pour lui.
    - a_copie_soumise (verrou de la STRUCTURE notée : questions/choix/bonnes
      réponses/points) dès qu'une Copie est 'soumise' — §5 du cahier des
      charges. titre/instructions ne sont volontairement PAS concernés (non
      listés au §5), modifiables à tout moment."""
    STATUT_CHOICES = [
        ('brouillon', 'مسودة'),
        ('publie', 'منشور'),
        ('ferme', 'مغلق'),
    ]

    groupe = models.ForeignKey(
        'courses.Groupe', on_delete=models.CASCADE, related_name='examens'
    )
    # SET_NULL (pas CASCADE) : même patron que evaluations.Evaluation.superviseur
    # et courses.BilanMensuel.prof — si le compte du prof qui a créé l'examen
    # est un jour supprimé définitivement, l'examen et les copies déjà notées
    # des élèves doivent survivre (ce n'est pas SA donnée, c'est celle du
    # groupe/des élèves qui l'ont passé).
    prof = models.ForeignKey(
        'accounts.Prof', on_delete=models.SET_NULL, null=True, blank=True, related_name='examens'
    )
    titre = models.CharField(max_length=200)
    instructions = models.TextField(blank=True)
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='brouillon')

    date_creation = models.DateTimeField(auto_now_add=True)
    date_publication = models.DateTimeField(null=True, blank=True)

    # Chrono — exigence essentielle et non optionnelle du cahier des charges
    # (§3) : période de disponibilité + durée maximale de passage. Toujours
    # renseignés (pas de valeur par défaut permissive), contrairement à
    # certains champs optionnels de Creneau : un examen sans période/durée
    # n'a pas de sens dans ce cahier des charges.
    date_debut = models.DateTimeField(help_text="Disponible à partir de.")
    date_limite = models.DateTimeField(help_text="Disponible jusqu'à.")
    duree_minutes = models.PositiveIntegerField(
        validators=[MinValueValidator(1)],
        help_text="Durée maximale de passage, en minutes, une fois l'examen commencé par un élève.",
    )

    def __str__(self):
        return f"{self.titre} - {self.groupe}"

    @property
    def a_copie_demarree(self):
        """Verrou du CHRONO (voir docstring de la classe)."""
        return self.copies.exists()

    @property
    def a_copie_soumise(self):
        """Verrou de la STRUCTURE notée (voir docstring de la classe)."""
        return self.copies.filter(statut='soumise').exists()

    @property
    def structure_modifiable(self):
        return not self.a_copie_soumise

    @property
    def chrono_modifiable(self):
        return not self.a_copie_demarree

    @property
    def est_disponible_maintenant(self):
        """True si la période de disponibilité couvre l'instant présent —
        condition nécessaire (mais pas suffisante, il faut aussi
        statut='publie') pour qu'un élève puisse commencer une copie."""
        maintenant = timezone.now()
        return self.date_debut <= maintenant <= self.date_limite

    @property
    def peut_etre_commence(self):
        return self.statut == 'publie' and self.est_disponible_maintenant

    @property
    def nb_questions(self):
        return self.questions.count()

    @property
    def points_max(self):
        return self.questions.aggregate(total=Sum('points'))['total'] or 0

    class Meta:
        verbose_name = "Examen"
        verbose_name_plural = "Examens"
        ordering = ['-date_creation']


class Question(models.Model):
    """Une question d'un examen, dans un ordre explicite et jamais aléatoire
    (§2 du cahier des charges — 'ordre' fait foi, pas de mélange à
    l'affichage ni en base)."""
    TYPE_CHOICES = [
        ('choix', 'اختيار من متعدد'),
        ('vrai_faux', 'صح / خطأ'),
        ('texte', 'إجابة نصية'),
        ('audio', 'إجابة صوتية'),
        # Tâche du 2026-08-18 : même patron que 'audio' (upload élève,
        # stockage via le storage par défaut du projet, correction manuelle
        # uniquement) — voir Reponse.reponse_video ci-dessous.
        ('video', 'إجابة فيديو'),
    ]
    examen = models.ForeignKey(Examen, on_delete=models.CASCADE, related_name='questions')
    type_question = models.CharField(max_length=10, choices=TYPE_CHOICES)
    enonce = models.TextField()
    ordre = models.PositiveIntegerField(default=0)
    points = models.PositiveSmallIntegerField(default=1, validators=[MinValueValidator(1)])
    # Uniquement pour type_question='vrai_faux' — None pour les 4 autres types :
    # pour 'choix', la bonne réponse est portée par ChoixQuestion.est_correct ;
    # pour 'texte'/'audio'/'video', aucune correction automatique n'existe
    # (§1/§10), donc aucune bonne réponse à stocker.
    reponse_correcte_bool = models.BooleanField(null=True, blank=True)

    def __str__(self):
        return f"{self.examen.titre} - Q{self.ordre}: {self.enonce[:50]}"

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Question"
        verbose_name_plural = "Questions"


class ChoixQuestion(models.Model):
    """Une proposition d'une question type_question='choix'. Une seule
    proposition avec est_correct=True par question en V1 (choix unique
    confirmé — §1 du cahier des charges)."""
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='choix')
    texte = models.CharField(max_length=300)
    ordre = models.PositiveIntegerField(default=0)
    est_correct = models.BooleanField(default=False)

    def __str__(self):
        return self.texte

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Choix de question"
        verbose_name_plural = "Choix de questions"


class Copie(models.Model):
    """Une participation d'un élève à un examen — UNE SEULE par (examen,
    eleve), contrainte UNIQUE en base (même patron que
    courses.Presence.unique_together). Pas de champ 'tentative' ni de
    mécanisme de reprise : décision confirmée du 2026-08-16, aucune
    tentative multiple en V1."""
    STATUT_CHOICES = [
        ('en_cours', 'قيد الإنجاز'),
        ('soumise', 'مُقدَّمة'),
    ]
    examen = models.ForeignKey(Examen, on_delete=models.CASCADE, related_name='copies')
    eleve = models.ForeignKey('accounts.Eleve', on_delete=models.CASCADE, related_name='copies_examens')
    statut = models.CharField(max_length=20, choices=STATUT_CHOICES, default='en_cours')

    # Posée UNE SEULE FOIS, au tout premier accès à la page de passage (voir
    # examens.services.demarrer_ou_recuperer_copie, point d'entrée unique de
    # création d'une Copie) — jamais réinitialisée par un accès ultérieur :
    # c'est précisément ce qui fait démarrer le chrono de façon irréversible
    # (§3 : fermer le navigateur ou revenir plus tard ne redonne jamais une
    # nouvelle durée).
    date_debut = models.DateTimeField(null=True, blank=True)
    date_soumission = models.DateTimeField(null=True, blank=True)
    # True si la copie a été finalisée par le serveur (expiration du temps ou
    # de la période) plutôt que par un clic explicite de l'élève sur
    # "Soumettre" — affiché au prof en correction pour qu'il distingue les
    # deux cas. Les deux cas suivent EXACTEMENT les mêmes règles de
    # verrouillage/correction, cette valeur n'a qu'un rôle d'affichage.
    soumission_automatique = models.BooleanField(default=False)

    # None tant que la correction n'est pas COMPLÈTE (voir
    # examens.services.recalculer_note_totale) — jamais une somme partielle
    # qui laisserait croire à une note définitive alors que des réponses
    # texte/audio restent à corriger (§10 du cahier des charges).
    note_totale = models.DecimalField(max_digits=6, decimal_places=2, null=True, blank=True)

    def __str__(self):
        return f"{self.eleve} - {self.examen}"

    @property
    def date_expiration_effective(self):
        """min(date_debut + duree_examen, date_limite_examen) — formule
        imposée par le client (§3) : la date limite globale de l'examen
        reste TOUJOURS prioritaire sur la durée individuelle accordée à
        l'élève. None tant que la copie n'a pas démarré."""
        if not self.date_debut:
            return None
        fin_par_duree = self.date_debut + datetime.timedelta(minutes=self.examen.duree_minutes)
        return min(fin_par_duree, self.examen.date_limite)

    @property
    def est_expiree(self):
        """True si le temps imparti (ou la date limite de l'examen) est
        dépassé — calculé À CHAQUE appel depuis des valeurs serveur, jamais
        mis en cache, jamais dérivé d'une valeur envoyée par le client."""
        expiration = self.date_expiration_effective
        return expiration is not None and timezone.now() > expiration

    @property
    def temps_restant_secondes(self):
        """Secondes restantes avant expiration (0 si déjà expirée/non
        démarrée) — seule donnée que le JS reçoit pour afficher le chrono ;
        le compte à rebours affiché est ensuite une simple décrémentation
        visuelle côté client, jamais une nouvelle source de vérité (le
        serveur revalide systématiquement à chaque autosave/soumission)."""
        expiration = self.date_expiration_effective
        if expiration is None:
            return 0
        return max(0, int((expiration - timezone.now()).total_seconds()))

    @property
    def modifiable(self):
        """True si l'élève peut encore répondre/modifier ses réponses : la
        copie n'est pas déjà soumise ET son temps n'est pas écoulé. Source de
        vérité UNIQUE utilisée par la vue d'autosave ET la vue de soumission
        — jamais un contrôle recodé localement."""
        return self.statut == 'en_cours' and not self.est_expiree

    @property
    def correction_complete(self):
        return not self.reponses.filter(statut_correction='a_corriger').exists()

    class Meta:
        unique_together = ('examen', 'eleve')
        verbose_name = "Copie"
        verbose_name_plural = "Copies"


class Reponse(models.Model):
    """Réponse d'un élève à UNE question de SA copie — contrainte UNIQUE
    (copie, question) en base. Sert aussi de stockage d'autosave : une ligne
    est créée/mise à jour dès la première saisie de l'élève sur cette
    question (voir examens.views.reponse_autosave), pas seulement à la
    soumission finale — décision validée du 2026-08-16 : pas de table de
    brouillon séparée, ce modèle suffit."""
    STATUT_CORRECTION_CHOICES = [
        ('auto', 'مصححة تلقائياً'),
        ('a_corriger', 'بانتظار التصحيح'),
        ('corrigee', 'مصححة'),
    ]
    copie = models.ForeignKey(Copie, on_delete=models.CASCADE, related_name='reponses')
    question = models.ForeignKey(Question, on_delete=models.CASCADE, related_name='reponses')

    # related_name='+' : aucun accès inverse nécessaire depuis ChoixQuestion
    # (même convention que les FK d'audit du projet, ex:
    # accounts.User.mot_de_passe_reinitialise_par).
    reponse_choix = models.ForeignKey(
        ChoixQuestion, on_delete=models.SET_NULL, null=True, blank=True, related_name='+'
    )
    reponse_bool = models.BooleanField(null=True, blank=True)
    reponse_texte = models.TextField(blank=True)
    reponse_audio = models.FileField(upload_to='examens_audio/%Y/%m/', null=True, blank=True)
    nom_fichier_audio_original = models.CharField(max_length=255, blank=True, default='')
    # Tâche du 2026-08-18 : même patron que reponse_audio ci-dessus (stockage
    # via le storage par défaut du projet — Cloudinary en prod/media en dev,
    # voir examens.services.valider_fichier_video).
    reponse_video = models.FileField(upload_to='examens_video/%Y/%m/', null=True, blank=True)
    nom_fichier_video_original = models.CharField(max_length=255, blank=True, default='')

    statut_correction = models.CharField(max_length=20, choices=STATUT_CORRECTION_CHOICES, default='a_corriger')
    points_obtenus = models.DecimalField(max_digits=5, decimal_places=2, null=True, blank=True)
    commentaire_prof = models.TextField(blank=True)

    date_reponse = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.copie} - Q{self.question_id}"

    class Meta:
        unique_together = ('copie', 'question')
        verbose_name = "Réponse"
        verbose_name_plural = "Réponses"
