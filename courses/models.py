import datetime

from django.contrib.postgres.indexes import GinIndex
from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.utils import timezone
from accounts.models import Prof, Eleve, Superviseur
from annonces.models import Annonce


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
        ('en_attente', 'قيد الانتظار'),
        ('approuvee', 'موافَق عليها'),
        ('rejetee', 'مرفوضة'),
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


class CreneauActifsManager(models.Manager):
    """Exclut les créneaux archivés (Tâche du 2026-08-08) — même principe
    que EleveActifsManager/ProfActifsManager (accounts.models) : à utiliser
    pour toute liste/sélecteur où un créneau archivé ne doit jamais
    apparaître par défaut. 'Archivé' ici réutilise le champ est_actif déjà
    existant (est_actif=False) plutôt que d'ajouter un nouveau champ
    redondant — il n'y a pas de distinction utile dans ce projet entre
    'désactivé temporairement' et 'archivé', les deux ont toujours désigné
    la même chose (ne plus apparaître dans les nouveaux formulaires/listes,
    sans toucher aux groupes/séances déjà existants qui en dépendent).
    Ne remplace PAS le manager par défaut (Creneau.objects reste complet)."""
    def get_queryset(self):
        return super().get_queryset().exclude(est_actif=False)


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
    # Mêmes codes que InscriptionEleve.RIWAYA_CHOICES.
    RIWAYA_CHOICES = [
        ('warsh', 'ورش'),
        ('hafs', 'حفص'),
    ]

    # Nom personnalisé optionnel (Tâche du 2026-08-18) — vide par défaut,
    # auquel cas __str__ retombe sur le format jour/heure historique (voir
    # ci-dessous). Ajouté pour que مدير/مشرف puisse reconnaître une حلقة
    # d'un coup d'œil (ex: "حلقة الأطفال - الصباح") plutôt que seulement par
    # son horaire, notamment dans le <select> d'assignation d'un Groupe.
    nom = models.CharField(max_length=100, blank=True, default='')
    sexe_cible = models.CharField(max_length=10, choices=SEXE_CHOICES, default='mixte')
    type_seance = models.CharField(max_length=20, choices=TYPE_SEANCE_CHOICES, default='hifz')
    riwaya = models.CharField(max_length=10, choices=RIWAYA_CHOICES, default='hafs')
    age_min = models.IntegerField()
    age_max = models.IntegerField()
    jour_1 = models.CharField(max_length=5, choices=JOUR_CHOICES)
    heure_debut_1 = models.TimeField()
    heure_fin_1 = models.TimeField()
    jour_2 = models.CharField(max_length=5, choices=JOUR_CHOICES)
    heure_debut_2 = models.TimeField()
    heure_fin_2 = models.TimeField()
    est_actif = models.BooleanField(default=True)

    objects = models.Manager()
    actifs = CreneauActifsManager()

    def __str__(self):
        if self.nom:
            return self.nom
        return (
            f"{self.get_jour_1_display()} {self.heure_debut_1.strftime('%H:%M')}"
            f" + {self.get_jour_2_display()} {self.heure_debut_2.strftime('%H:%M')}"
        )

    class Meta:
        verbose_name = "Créneau"
        verbose_name_plural = "Créneaux"

class CreneauSlot(models.Model):
    """Une occurrence hebdomadaire réelle d'un Creneau (jour + heure de début/fin) —
    remplace progressivement le couple figé jour_1/heure_debut_1/heure_fin_1 +
    jour_2/heure_debut_2/heure_fin_2 ci-dessus, qui supposait exactement 2 séances par
    semaine pour TOUT créneau (chantier de généralisation N séances/semaine). Même
    principe que DisponibiliteProf/DisponibiliteEleve (lignes jour+heure, déjà sans
    limite de nombre dans ce projet) — CreneauSlot est la version "avec durée"
    (heure_fin en plus) de ce même patron, appliquée à Creneau plutôt qu'à une
    personne.

    Migration (voir courses/migrations, chantier N séances/semaine) : les colonnes
    jour_1.../jour_2... de Creneau sont conservées EN LECTURE le temps de la bascule
    complète du code (aucune perte de donnée, aucune régénération de Seance) — chaque
    Creneau existant obtient exactement 2 CreneauSlot (ordre=1 depuis le bloc "_1",
    ordre=2 depuis le bloc "_2"), ni plus ni moins. Un Creneau peut désormais avoir
    1, 2, 3, 4 ou N slots — le nombre de séances hebdomadaires d'un groupe est
    TOUJOURS lu depuis groupe.creneau.slots.count(), jamais stocké séparément (voir
    registration.models.Critere.backend='nb_slots' — une seule source de vérité)."""

    creneau = models.ForeignKey('Creneau', on_delete=models.CASCADE, related_name='slots')
    jour = models.CharField(max_length=5, choices=Creneau.JOUR_CHOICES)
    heure_debut = models.TimeField()
    heure_fin = models.TimeField()
    ordre = models.PositiveIntegerField(default=0)

    def __str__(self):
        return f"{self.creneau} - {self.get_jour_display()} {self.heure_debut.strftime('%H:%M')}"

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Créneau hebdomadaire (occurrence)"
        verbose_name_plural = "Créneaux hebdomadaires (occurrences)"


class GroupeActifsManager(models.Manager):
    """Exclut les groupes archivés (Tâche du 2026-08-08) — même principe que
    EleveActifsManager/ProfActifsManager (accounts.models). Groupe.statut a
    déjà le choix 'archive' depuis le début (jamais exploité par un manager
    dédié jusqu'ici, seulement modifiable via le formulaire d'édition) —
    ajouté ici pour de vrai. Ne remplace PAS le manager par défaut
    (Groupe.objects reste complet, une fiche/détail par ID déjà connu doit
    rester accessible même pour un groupe archivé)."""
    def get_queryset(self):
        return super().get_queryset().exclude(statut='archive')


class LienMeet(models.Model):
    """Un lien Google Meet du مدير, enregistré UNE FOIS puis réutilisable par
    plusieurs groupes (Tâche du 2026-08-17) — TANT QUE leurs créneaux hebdo
    ne se chevauchent jamais (voir courses.utils.liens_meet_disponibles).
    Pool centralisé, distinct de Groupe.lien_reunion (champ historique en
    texte libre, conservé tel quel pour compatibilité — voir Groupe.lien_meet
    ci-dessous). Pas de notion de réservation: la disponibilité est toujours
    recalculée à la volée à partir des groupes ACTIFS qui utilisent déjà ce
    lien, jamais stockée."""
    url = models.URLField(unique=True)
    libelle = models.CharField(max_length=100, blank=True)
    est_actif = models.BooleanField(default=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return self.libelle or self.url

    class Meta:
        ordering = ['libelle', 'id']
        verbose_name = "Lien Google Meet"
        verbose_name_plural = "Liens Google Meet"


class Groupe(models.Model):
    TYPE_CAPACITE_CHOICES = [
        ('groupe', 'جماعي'),
        ('individuel', 'فردي'),
    ]
    # Sous-catégorie d'un groupe COLLECTIF (type_capacite='groupe') pour la
    # navigation par filtres de admin_groupes.html (Chantier du 2026-08-15).
    # Volontairement PAS un champ de modèle : voir categorie_collectif
    # ci-dessous, entièrement dérivée de creneau.sexe_cible/age_min/age_max
    # (déjà la seule source de vérité du projet pour âge/sexe d'un groupe,
    # voir avertissements_groupe/avertissements_prof_creneau) — stocker un
    # 2e champ redondant risquerait de se désynchroniser si le créneau du
    # groupe change.
    CATEGORIE_COLLECTIF_CHOICES = [
        ('hommes', 'الرجال'),
        ('femmes', 'النساء'),
        ('enfants', 'الأطفال'),
    ]
    # Catégorie de classification du groupe, choisie EXPLICITEMENT par le مدير
    # (Tâche du 2026-08-17 "photo + catégorie de groupe") — réutilise TEL QUEL
    # Annonce.CIBLE_CHOICES (annonces.models), les mêmes 3 catégories métier
    # déjà utilisées pour cibler les annonces (النساء البالغات/الرجال البالغون/
    # القاصرون), pour ne jamais avoir 2 façons différentes de classer la même
    # population dans le projet — demande explicite du client. Contrairement à
    # categorie_collectif ci-dessus (dérivée du créneau, non éditable, réservée
    # aux groupes COLLECTIFS), ce champ est un vrai champ de modèle, saisi
    # directement, disponible pour N'IMPORTE QUEL groupe (individuel compris),
    # et n'a AUCUN lien de calcul avec le créneau — les deux classifications
    # coexistent sans se remplacer.
    CATEGORIE_CHOICES = Annonce.CIBLE_CHOICES

    nom = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    type_capacite = models.CharField(max_length=10, choices=TYPE_CAPACITE_CHOICES, default='groupe')
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
        choices=[('actif', 'نشط'), ('archive', 'مؤرشف')],
        default='actif'
    )
    # Champ historique en texte libre — CONSERVÉ tel quel pour compatibilité
    # avec tout le code déjà branché dessus (lien_seance_est_actif,
    # _meet_icon.html, prof_seance_detail.html, eleve_seance_detail.html,
    # superviseur_seance_detail.html...). Continue de contenir n'importe quel
    # lien de session (WhatsApp, Meet non géré, etc.) tel que saisi par
    # l'admin AVANT ce chantier — ces valeurs ne sont ni migrées ni écrasées
    # automatiquement (Tâche du 2026-08-17, voir LienMeet ci-dessus). Quand
    # lien_meet (ci-dessous) est renseigné, lien_reunion est maintenu
    # synchronisé sur lien_meet.url par les vues groupe_ajouter/
    # groupe_modifier — c'est ce champ, PAS lien_meet, que lit tout le code
    # d'affichage/activation existant.
    lien_reunion = models.URLField(blank=True)
    # Lien Meet du pool centralisé assigné à ce groupe (Tâche du 2026-08-17).
    # Un groupe a AU PLUS un lien_meet. SET_NULL : la désactivation/absence du
    # lien ne doit jamais supprimer le groupe ni son historique de séances.
    lien_meet = models.ForeignKey(
        LienMeet,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='groupes'
    )
    categorie = models.CharField(max_length=20, choices=CATEGORIE_CHOICES, blank=True, default='')
    # Photo de profil du groupe (Tâche du 2026-08-17) — même patron que
    # accounts.models.LogoConfig.logo : storage par défaut du projet
    # (Cloudinary en production, disque local en dev/tests), rien de
    # spécifique à créer. Affichage toujours carré/recadré en CSS
    # (object-fit:cover) — jamais recadrée au stockage. Validée côté serveur
    # par courses.utils.valider_photo_groupe (extension + taille + ouverture
    # réelle via Pillow), jamais sur la seule confiance du <input accept=...>.
    photo = models.ImageField(upload_to='groupes_photos/', null=True, blank=True)

    objects = models.Manager()
    actifs = GroupeActifsManager()

    def __str__(self):
        return self.nom

    @property
    def categorie_collectif(self):
        """'hommes'/'femmes'/'enfants' pour un groupe COLLECTIF dont le créneau
        permet de trancher sans ambiguïté, sinon None : groupe individuel
        (n'a jamais de catégorie, demande explicite du client), groupe sans
        créneau assigné, ou créneau à cheval enfants/adultes ou visant les
        deux sexes chez les adultes (aucun cas réel de ce type observé lors
        de l'audit du 2026-08-15, mais gardé None plutôt que de deviner —
        un groupe non classifiable doit rester visible sous "الكل" sans
        apparaître sous une sous-catégorie qui ne lui correspond pas
        vraiment). Règle identique à celle déjà utilisée par
        courses.utils._categorie_age_creneau/avertissements_groupe : les
        mineurs (tous sexes confondus) ne sont JAMAIS séparés par sexe."""
        if self.type_capacite != 'groupe' or not self.creneau_id:
            return None
        from .utils import AGE_SEUIL_ADULTE
        creneau = self.creneau
        if creneau.age_max < AGE_SEUIL_ADULTE:
            return 'enfants'
        if creneau.age_min >= AGE_SEUIL_ADULTE:
            if creneau.sexe_cible == 'homme':
                return 'hommes'
            if creneau.sexe_cible == 'femme':
                return 'femmes'
        return None

    @property
    def categorie_collectif_display(self):
        """Libellé arabe de categorie_collectif (même patron que les
        get_FOO_display() générés par Django pour un champ choices — mais
        categorie_collectif n'est pas un champ, donc pas de méthode générée
        automatiquement). Chaîne vide si None (pas de sous-catégorie)."""
        return dict(self.CATEGORIE_COLLECTIF_CHOICES).get(self.categorie_collectif, '')

    class Meta:
        verbose_name = "Groupe"
        verbose_name_plural = "Groupes"
        # Recherche globale (Chantier du 2026-08-14) — voir accounts.models.User.Meta.indexes.
        indexes = [
            GinIndex(fields=['nom'], name='courses_groupe_nom_trgm', opclasses=['gin_trgm_ops']),
        ]


class ReglageLienSeance(models.Model):
    """Marge (en minutes) autour de l'horaire réel d'une séance pendant
    laquelle son lien de réunion (Groupe.lien_reunion) est cliquable —
    Point 15, Tâche du 2026-08-04. Singleton, même patron que
    ParametresInscriptions/VisibiliteProf (accounts.models). Valeurs par
    défaut (10 min avant, 10 min après) : le comportement précédent
    n'imposait AUCUNE restriction horaire, donc n'importe quelle valeur par
    défaut change ce comportement — 10 min de chaque côté est la marge la
    plus resserrée qui reste raisonnable (éviter un lien inutilisable pour
    un léger retard de connexion, sans pour autant le laisser actif toute la
    journée comme avant)."""
    marge_avant_minutes = models.PositiveIntegerField(default=10)
    marge_apres_minutes = models.PositiveIntegerField(default=10)
    derniere_modification_par = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "إعدادات هامش رابط الحصص"

    class Meta:
        verbose_name = "Réglage du lien de séance"
        verbose_name_plural = "Réglage du lien de séance"


def get_reglage_lien_seance():
    """Renvoie l'unique instance de ReglageLienSeance, en la créant (valeurs
    par défaut 10/10) si elle n'existe pas encore — même patron singleton
    que accounts.models.get_visibilite_prof()."""
    reglage, _ = ReglageLienSeance.objects.get_or_create(pk=1)
    return reglage


class HistoriqueGroupeEleve(models.Model):
    """Trace le passage d'un élève dans un groupe (dates d'entrée/de sortie),
    en complément de Groupe.eleves (M2M simple, qui ne reflète que
    l'appartenance ACTUELLE et n'a jamais eu de date). Alimenté par
    groupe_ajouter_eleve / groupe_retirer_eleve / groupe_transferer_eleve
    (Tâche 18 du 2026-07-26). Groupe.eleves reste intact et continue de
    faire foi pour l'appartenance actuelle (évite de casser les nombreux
    appels .eleves.add()/.remove()/.filter(eleves=...) déjà existants) —
    une ligne ici avec date_fin=None correspond à une entrée actuelle dans
    Groupe.eleves ; date_fin non nulle = l'élève est passé par ce groupe
    mais n'y est plus (retiré ou transféré ailleurs)."""
    eleve = models.ForeignKey('accounts.Eleve', on_delete=models.CASCADE, related_name='historique_groupes')
    groupe = models.ForeignKey(Groupe, on_delete=models.CASCADE, related_name='historique_eleves')
    date_debut = models.DateTimeField(auto_now_add=True)
    date_fin = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = "Historique d'appartenance à un groupe"
        verbose_name_plural = "Historiques d'appartenance aux groupes"
        ordering = ['-date_debut']


class TarifRemuneration(models.Model):
    """Grille tarifaire de rémunération des profs: 1 ligne par combinaison
    type_capacite × tranche_age (4 lignes fixes, jamais ajoutées/supprimées
    depuis l'admin — seul le montant est modifiable). Réutilise les mêmes
    codes que Groupe.type_capacite (pas Creneau.type_seance, un champ au
    nom proche mais qui désigne autre chose: hifz/tathbit)."""
    TRANCHE_AGE_CHOICES = [
        ('enfant', 'طفل'),
        ('adulte', 'بالغ'),
    ]

    type_capacite = models.CharField(max_length=10, choices=Groupe.TYPE_CAPACITE_CHOICES)
    tranche_age = models.CharField(max_length=10, choices=TRANCHE_AGE_CHOICES)
    montant = models.DecimalField(max_digits=8, decimal_places=2)

    def __str__(self):
        return f"{self.get_type_capacite_display()} / {self.get_tranche_age_display()} — {self.montant} د.م."

    class Meta:
        unique_together = ('type_capacite', 'tranche_age')
        verbose_name = "Tarif de rémunération"
        verbose_name_plural = "Tarifs de rémunération"


class Seance(models.Model):
    TYPE_CHOICES = [
        ('normal', 'عادية'),
        ('rattrapage', 'حصة تعويضية'),
        ('revision', 'مراجعة'),
    ]
    # Mêmes libellés que dashboard/_seance_statut_badge.html (مخططة/منتهية/ملغاة),
    # affichés partout où get_statut_display() est appelé (ex: message d'erreur
    # d'admin_seance_annuler) — une seule et même formulation dans tout le projet.
    STATUT_CHOICES = [
        ('planifiee', 'مخططة'),
        ('terminee', 'منتهية'),
        ('annulee', 'ملغاة'),
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
    # Exception de lien Meet pour CETTE séance uniquement (Tâche du 2026-08-17)
    # — jamais un remplacement de Groupe.lien_meet/lien_reunion (qui restent le
    # défaut permanent du groupe, inchangés). Posé typiquement quand un
    # déplacement exceptionnel (admin_seance_deplacer) rend le lien par défaut
    # du groupe indisponible à la nouvelle date/heure (voir courses.utils.
    # lien_effectif_disponible_pour_seance) ; la séance SUIVANTE (générée
    # normalement pour la semaine d'après) n'a pas cette exception et revient
    # donc automatiquement au lien du groupe. SET_NULL : la désactivation du
    # lien exceptionnel ne doit jamais faire disparaître la séance.
    lien_meet_exceptionnel = models.ForeignKey(
        'LienMeet',
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='seances_exceptionnelles',
    )
    remarque = models.TextField(
        blank=True,
        help_text="Raison d'une exception: annulation ou déplacement (prof malade, vacances...)."
    )
    remarque_generale = models.TextField(
        blank=True,
        help_text="Remarque du prof sur la séance dans son ensemble (distincte des remarques par élève)."
    )

    FENETRE_EVALUATION_PRESENCE_HEURES = 24  # même principe que evaluations.Evaluation
    # (مؤطر -> prof) : passé ce délai depuis le DÉBUT de la séance (aucune durée de
    # séance n'est stockée, l'heure de début sert donc de référence), le prof perd
    # définitivement le droit de remplir la feuille de présence si ce n'est pas déjà
    # fait — la séance reste "non évaluée" pour toujours, ce n'est pas juste un rappel.

    def __str__(self):
        return f"{self.groupe} - {self.date}"

    @property
    def debut_datetime(self):
        """Datetime aware combinant date+heure — référence pour la fenêtre de 24h."""
        naive = datetime.datetime.combine(self.date, self.heure)
        return timezone.make_aware(naive) if timezone.is_naive(naive) else naive

    @property
    def fin_datetime(self):
        """Datetime aware de la fin RÉELLE de cette séance — Seance ne stocke pas
        sa propre durée, elle est donc dérivée du Creneau du groupe : DURÉE
        (heure_fin - heure_debut) du créneau 1 ou 2 selon le jour de la semaine
        de cette séance, appliquée à l'heure RÉELLE de cette séance (self.heure)
        — PAS une heure de fin fixe recopiée telle quelle (corrigé le
        2026-08-17 : une séance déplacée exceptionnellement à une autre heure
        LE MÊME JOUR, ex. Seance.heure=16:00 alors que jour_1=14:00-15:00,
        obtenait auparavant une fin à 15:00, soit AVANT son propre début —
        strictement identique à l'ancien calcul pour toute séance non déplacée,
        où self.heure == heure_debut_1/2 par construction). Retombe sur la
        durée du créneau 1 si aucun des 2 jours ne correspond (créneau modifié
        depuis la génération de cette séance, ou déplacée sur un jour
        totalement différent — voir Tâche 19 Bug 1) ou None si le groupe n'a
        plus de créneau du tout (voir evaluable_par_prof, Tâche 19 Bug 2 du
        2026-07-26)."""
        from .utils import JOUR_INDEX

        creneau = self.groupe.creneau
        if not creneau:
            return None

        jour_seance = self.date.weekday()
        if jour_seance == JOUR_INDEX.get(creneau.jour_2):
            heure_debut_slot, heure_fin_slot = creneau.heure_debut_2, creneau.heure_fin_2
        else:
            heure_debut_slot, heure_fin_slot = creneau.heure_debut_1, creneau.heure_fin_1

        duree = (
            datetime.datetime.combine(self.date, heure_fin_slot)
            - datetime.datetime.combine(self.date, heure_debut_slot)
        )
        naive = datetime.datetime.combine(self.date, self.heure) + duree
        return timezone.make_aware(naive) if timezone.is_naive(naive) else naive

    @property
    def lien_effectif(self):
        """Lien Meet à utiliser pour REJOINDRE cette séance précise (Tâche du
        2026-08-17) : le lien exceptionnel de la séance s'il est posé, sinon
        le lien par défaut du groupe (Groupe.lien_reunion, jamais modifié par
        une exception ponctuelle). Seule source à lire pour "quel lien
        rejoindre maintenant" — voir dashboard.views.rejoindre_seance et
        courses.utils.lien_seance_est_actif, qui l'utilisent à la place de
        seance.groupe.lien_reunion directement. Identique à
        seance.groupe.lien_reunion tant qu'aucune exception n'est posée :
        aucun changement de comportement pour toute séance normale."""
        if self.lien_meet_exceptionnel_id:
            return self.lien_meet_exceptionnel.url
        return self.groupe.lien_reunion

    @property
    def evaluable_par_prof(self):
        """False tant que l'heure de fin réelle de la séance n'est pas encore
        passée (Tâche 19 Bug 2 du 2026-07-26) — sans fin_datetime connue (pas
        de créneau), on se rabat sur le début par précaution plutôt que
        d'autoriser une évaluation trop tôt."""
        fin = self.fin_datetime
        reference = fin if fin is not None else self.debut_datetime
        return timezone.now() >= reference

    @property
    def delai_evaluation_depasse(self):
        """True si plus de 24h se sont écoulées depuis le DÉBUT de la séance."""
        return timezone.now() - self.debut_datetime > datetime.timedelta(hours=self.FENETRE_EVALUATION_PRESENCE_HEURES)

    @property
    def modifiable_par_prof(self):
        """Le prof peut encore remplir/soumettre la feuille de présence : la séance est
        encore 'planifiee' (pas déjà soumise -> 'terminee', pas 'annulee'), sa fin réelle
        est déjà passée (Tâche 19 Bug 2 — pas d'évaluation avant la fin réelle) ET le délai
        de 24h depuis le début n'est pas dépassé. Une fois soumise OU le délai dépassé
        sans soumission, cet état est définitif — jamais réversible dans les deux cas."""
        return self.statut == 'planifiee' and self.evaluable_par_prof and not self.delai_evaluation_depasse

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
        ('hasan_jiddan', 'حسن جدا'),
        ('hasan', 'حسن'),
        ('mustahsan', 'مستحسن'),
        ('mutawassit', 'متوسط'),
        ('doun_mutawassit', 'دون متوسط'),
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
    # Ancienne échelle qualitative — conservée telle quelle en LECTURE SEULE pour
    # l'historique déjà en base (voir Tâche 9 du 2026-07-25, option B "coexistence"
    # choisie explicitement : aucune donnée existante n'est remappée/perdue).
    # N'est plus jamais écrite depuis prof_presence_sauvegarder — remplacée par
    # les 4 critères numériques /20 ci-dessous pour toute nouvelle évaluation.
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

    # Critère "ينتقل / يعيد" (Tâche du 2026-08-18) — décision explicite du
    # prof : le passage couvert cette séance est-il acquis (ينتقل, compte
    # dans la progression) ou doit-il être repassé (يعيد, ne compte pas) ?
    # default='valide' (PAS null) : tout Presence antérieur à ce champ garde
    # exactement le même comportement qu'avant son ajout — aucune régression
    # rétroactive sur la progression déjà calculée. Seule resultat_memorisation
    # est lue par courses.utils._couverture_ayat_par_sourate/
    # calculer_progression_eleve (le حزب se calcule sur la mémorisation, pas
    # la révision) : resultat_revision reste donc purement indicatif pour le
    # suivi du prof, sans effet sur aucun calcul existant.
    RESULTAT_CHOICES = [
        ('valide', 'ينتقل'),
        ('a_refaire', 'يعيد'),
    ]
    resultat_memorisation = models.CharField(
        max_length=10, choices=RESULTAT_CHOICES, default='valide', blank=True
    )
    resultat_revision = models.CharField(
        max_length=10, choices=RESULTAT_CHOICES, default='valide', blank=True
    )

    # 4 critères numériques /20 (Tâche 9 du 2026-07-25), remplacent l'ancienne
    # échelle qualitative (ممتاز/حسن جدا/...) pour toute évaluation à partir de
    # maintenant. Nullable: null pour tout Presence antérieur à cette migration
    # (jamais aucune valeur inventée) et pour un élève marqué absent (rien à noter).
    note_hifz = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    note_muraja3a = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    note_tilawa = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    note_mouwazaba = models.PositiveSmallIntegerField(
        null=True, blank=True,
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )
    # Remplace consigne_prochaine_seance (un seul champ combiné, jamais rempli
    # en pratique — 0 Presence sur 8 lors de l'audit Tâche 9 — donc rien à
    # migrer) par deux champs dédiés, désormais obligatoires côté formulaire.
    consigne_memorisation = models.TextField(blank=True)
    consigne_revision = models.TextField(blank=True)

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


class CritereEleve(models.Model):
    """Critère d'évaluation élève, éditable dynamiquement par le مدير — miroir
    exact de evaluations.models.Critere (critères d'évaluation PROF par le
    مؤطر), Tâche du 2026-08-04 (Point 7) : avant ce modèle, les 4 critères
    (الحفظ/المراجعة/التلاوة/المواظبة) étaient des champs fixes sur Presence
    (note_hifz/note_muraja3a/note_tilawa/note_mouwazaba, voir plus bas —
    conservés en lecture seule pour l'historique, jamais plus écrits)."""
    nom_ar = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.nom_ar

    class Meta:
        ordering = ['ordre']
        verbose_name = "Critère d'évaluation élève"
        verbose_name_plural = "Critères d'évaluation élève"


class NotePresence(models.Model):
    """Note /20 d'un élève pour un critère donné, sur une Presence donnée —
    table de jonction dynamique remplaçant les 4 champs fixes note_hifz/
    note_muraja3a/note_tilawa/note_mouwazaba (Tâche du 2026-08-04, Point 7),
    même patron que evaluations.models.NoteEvaluation. Échelle /20 (pas la
    même échelle 0-4 que NoteEvaluation, qui évalue les PROFS) — cohérente
    avec l'échelle des 4 anciens champs fixes qu'elle remplace."""
    presence = models.ForeignKey(
        Presence,
        on_delete=models.CASCADE,
        related_name='notes_criteres'
    )
    critere = models.ForeignKey(
        CritereEleve,
        on_delete=models.CASCADE
    )
    note = models.PositiveSmallIntegerField(
        validators=[MinValueValidator(1), MaxValueValidator(20)],
    )

    def __str__(self):
        return f"{self.critere} → {self.note}"

    class Meta:
        unique_together = ('presence', 'critere')
        verbose_name = "Note par critère (élève)"
        verbose_name_plural = "Notes par critère (élève)"


class BilanMensuel(models.Model):
    """Synthèse mensuelle par élève, rédigée par le prof en fin de mois (mémorisation,
    révision, remarques de discipline/comportement) — un bilan par élève par mois par
    prof. Les champs memorisation/revision sont pré-remplis à la création à partir des
    Presence du mois (voir courses.utils.generer_brouillon_bilan_mensuel), mais restent
    un brouillon librement modifiable, pas une valeur recalculée en direct : une fois
    sauvegardé, le texte n'est plus jamais regénéré automatiquement."""
    eleve = models.ForeignKey(Eleve, on_delete=models.CASCADE, related_name='bilans_mensuels')
    # SET_NULL (pas CASCADE) depuis le chantier de suppression définitive du prof
    # (2026-08-12) : ce bilan concerne l'ÉLÈVE (côté eleve ci-dessus, resté en
    # CASCADE à raison — c'est bien SON compte qui, si supprimé, doit tout
    # emporter). Le prof n'en est que l'auteur — le supprimer ne doit jamais
    # effacer un contenu qui appartient au dossier de l'élève. Le bilan reste
    # donc visible sur la fiche de l'élève, avec un auteur devenu vide.
    prof = models.ForeignKey(Prof, on_delete=models.SET_NULL, null=True, blank=True, related_name='bilans_mensuels')
    mois_reference = models.DateField()
    memorisation = models.TextField(blank=True)
    revision = models.TextField(blank=True)
    remarques_discipline = models.TextField(blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)
    date_modification = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('eleve', 'prof', 'mois_reference')
        ordering = ['-mois_reference']
        verbose_name = "Bilan mensuel"
        verbose_name_plural = "Bilans mensuels"

    def __str__(self):
        return f"{self.eleve} - {self.mois_reference:%Y-%m}"

    @property
    def modifiable_par_prof(self):
        """Le prof qui l'a rédigé peut le modifier jusqu'à la fin du mois SUIVANT
        mois_reference (ex: bilan de juillet modifiable jusqu'au 31 août inclus)."""
        from django.utils import timezone
        total_mois = (self.mois_reference.year * 12 + (self.mois_reference.month - 1)) + 2
        annee_limite = total_mois // 12
        mois_limite = total_mois % 12 + 1
        date_limite = datetime.date(annee_limite, mois_limite, 1)
        return timezone.localdate() < date_limite

# JournalSuppression (construit le 2026-08-08 pour tracer les suppressions
# définitives de Groupe/Creneau) a été retiré le même jour, sur décision
# explicite du client : la suppression définitive doit rester réellement
# définitive, sans aucune trace conservée après coup. Voir la migration
# 0025_delete_journalsuppression.