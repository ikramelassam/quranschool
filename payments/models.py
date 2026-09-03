from django.db import models
from django.contrib.auth import get_user_model
from django.utils.translation import gettext_lazy as _, get_language
from accounts.models import Eleve

User = get_user_model()


class MoyenPaiement(models.Model):
    """Un moyen de paiement proposé à l'étape paiement du nouveau parcours
    d'inscription (ex: "CIH", "Barid Bank") — même patron que
    inscriptions.models.TypeAbonnement (liste ordonnée, toggle actif, aucun modèle
    parallèle). `coordonnees` est affiché à l'élève dès qu'il sélectionne ce moyen
    (RIB, instructions de virement...) — texte libre pour rester adaptable sans
    migration à chaque nouveau moyen de paiement ou changement de RIB."""

    code = models.SlugField(max_length=30, unique=True)
    label = models.CharField(max_length=100)
    # _fr/_en (chantier i18n du 2026-08-29, bug signalé : noms de banques et
    # coordonnées restent arabes même en session FR/EN) — même patron que
    # Groupe.nom_fr/Prof.presentation_publique_fr (contenu saisi à la main par
    # مدير/مشرف, PAS un texte fixe du code : `{% trans %}` ne peut rien pour
    # lui, contrairement au libellé "waliy amr" du catalogue système). Saisie
    # manuelle PAR LANGUE, optionnelle, jamais une traduction automatique.
    label_fr = models.CharField(max_length=100, blank=True, default='')
    label_en = models.CharField(max_length=100, blank=True, default='')
    coordonnees = models.TextField(blank=True)
    coordonnees_fr = models.TextField(blank=True, default='')
    coordonnees_en = models.TextField(blank=True, default='')
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.label

    def _localise(self, champ_base):
        """Voir Groupe._localise/Prof._localise — même logique (repli
        arabe automatique tant que la traduction n'est pas saisie)."""
        langue = get_language()
        if langue in ('fr', 'en'):
            valeur = getattr(self, f'{champ_base}_{langue}', '')
            if valeur:
                return valeur
        return getattr(self, champ_base)

    @property
    def label_localise(self):
        return self._localise('label')

    @property
    def coordonnees_localise(self):
        return self._localise('coordonnees')

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Moyen de paiement"
        verbose_name_plural = "Moyens de paiement"


class Paiement(models.Model):
    STATUT_CHOICES = [
        ('en_attente', _('قيد المراجعة')),
        ('valide', _('مقبول')),
        ('rejete', _('مرفوض')),
    ]
    eleve = models.ForeignKey(
        Eleve,
        on_delete=models.CASCADE,
        related_name='paiements'
    )
    montant = models.DecimalField(max_digits=8, decimal_places=2)
    mois_reference = models.DateField()
    date = models.DateTimeField(auto_now_add=True)
    # Optionnel depuis Tâche 7 (2026-07-25) : un مدير peut créer un paiement
    # directement (espèces reçues en personne), sans justificatif numérique —
    # avant, seul l'élève créait un Paiement (toujours avec reçu obligatoire).
    screenshot = models.FileField(upload_to='paiements/', blank=True, null=True)
    statut = models.CharField(
        max_length=20,
        choices=STATUT_CHOICES,
        default='en_attente'
    )
    valide_par = models.ForeignKey(
        User,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='paiements_valides'
    )
    # Corrigé Tâche 7 (2026-07-25) : auto_now_add se déclenchait à la CRÉATION
    # de l'objet (donc dès la soumission par l'élève), jamais au moment réel
    # de la validation/rejet par le مدير — le champ était donc toujours rempli
    # même pour un paiement encore 'en_attente'. Désormais posé explicitement
    # dans admin_paiement_valider/admin_paiement_rejeter/paiement_panel_sauvegarder.
    date_validation = models.DateTimeField(null=True, blank=True)

    def __str__(self):
        return f"{self.eleve} - {self.mois_reference}"

    class Meta:
        unique_together = ('eleve', 'mois_reference')
        verbose_name = "Paiement"
        verbose_name_plural = "Paiements"


class CycleAbonnement(models.Model):
    """Suivi des échéances de paiement de l'abonnement d'un élève — chantier
    « relances de paiement » du 2026-09-01.

    RÈGLE D'ÉCHÉANCE (décidée par le client) — PÉRIODES ROULANTES ancrées sur
    le jour d'inscription (chantier du 2026-09-03, en remplacement du découpage
    en mois calendaires) :
    - Cycle 1 : créé à la validation de l'inscription (dashboard.views.
      admin_valider_eleve) ou au désarchivage (admin_eleve_reactiver).
      `date_debut` = ce jour-là (= jour d'ancrage de TOUTES les périodes),
      `date_echeance` = `date_debut + ParametresInscriptions.
      delai_paiement_jours` (10 par défaut).
    - Cycle N = période N = `date_debut(cycle 1) + (N-1) mois` (élève inscrit
      le 10 -> 10→10, 10→10…). Cycle N réglé dès qu'un Paiement `valide` porte
      sur le MOIS de début de sa période (mois_reference au mois près) ; le
      cycle N+1 est alors ouvert avec `date_debut = date_debut(cycle 1) + N
      mois` et `date_echeance = date_debut + delai_paiement_jours`.
      `date_fin_couverte` du cycle réglé = veille du début de la période
      suivante. L'élève choisit COMBIEN de mois il règle (payments.views.
      eleve_paiements), pas leur date de début — chaque mois payé règle un
      cycle de plus, à la file.

    EN RETARD (calculé à la volée, jamais stocké — voir payments.cycles.
    est_en_retard) : `aujourd'hui > cycle_courant.date_echeance` ET aucun
    Paiement non-rejeté (`valide` OU `en_attente`) ne couvre encore le 1er mois
    du cycle. Un Paiement `en_attente` (« j'ai dit que j'ai payé ») suspend la
    relance sans faire avancer le cycle — seule la validation par le مدير
    l'avance (payments.cycles.reconcilier, appelée après chaque
    validation/modification de Paiement).

    PAS de cron / Telegram / e-mail (décision du client) : uniquement le
    panneau 🔔. Le badge 🔔 suit le mécanisme habituel DerniereVisiteNotification
    (clés 'paiements_retard' côté élève, 'paiements_retard_eleves' côté
    مدير/مشرف) : « nouveau » tant que la page cible (eleve_paiements /
    paiements_retards) n'a pas été visitée DEPUIS que le cycle est devenu échu ;
    visiter cette page éteint le badge. Un NOUVEAU cycle qui repasse en retard
    plus tard relance la notification. L'ÉTAT « en retard » lui-même, lui,
    reste toujours visible sur ces pages (badge éteint ou non). Le مدير voit la
    liste sur payments.views.paiements_retards avec 2 boutons par ligne :
    « الانتظار » (aucun effet, cosmétique) et « أرشفة » (archivage réversible,
    مدير uniquement)."""

    eleve = models.ForeignKey(
        'accounts.Eleve', on_delete=models.CASCADE, related_name='cycles_abonnement'
    )
    numero = models.PositiveIntegerField()
    date_debut = models.DateField()
    date_echeance = models.DateField()
    date_fin_couverte = models.DateField(null=True, blank=True)
    date_reglement = models.DateField(null=True, blank=True)
    montant_regle = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    regle = models.BooleanField(default=False)

    def __str__(self):
        etat = 'réglé' if self.regle else 'à payer'
        return f"{self.eleve} — cycle {self.numero} ({etat})"

    class Meta:
        unique_together = ('eleve', 'numero')
        ordering = ['eleve', 'numero']
        # Requête chaude : payments.cycles.cycles_ouverts_en_retard() tourne à
        # chaque affichage de la page d'accueil مدير/مشرف (panneau 🔔) et de la
        # page paiements_retards — filtre (regle=False, date_echeance < today).
        indexes = [
            models.Index(fields=['regle', 'date_echeance'], name='cycle_abo_retard_idx'),
        ]
        verbose_name = "Cycle d'abonnement"
        verbose_name_plural = "Cycles d'abonnement"


# Espaces réservés remplacés à l'affichage de chaque ligne de la page
# paiements_retards (voir payments.views._message_relance_whatsapp).
MESSAGE_RELANCE_WHATSAPP_DEFAUT = (
    'السلام عليكم ورحمة الله وبركاته\n'
    'نذكّركم بأن اشتراك الطالب {nom} قد تجاوز أجل الدفع بتاريخ {date_echeance} '
    '(متأخر بـ {jours_retard} يوماً).\n'
    'نرجو تسوية الوضعية في أقرب وقت وجزاكم الله خيراً.'
)


class ReglageRelanceWhatsApp(models.Model):
    """Message WhatsApp pré-rempli proposé sur chaque ligne de la page
    « متأخرون عن دفع الاشتراك » (payments.views.paiements_retards) — modifiable
    par le مدير ET le مشرف (dashboard.views.admin_reglage_relance_whatsapp),
    même patron singleton que courses.models.ReglageLienSeance.

    La plateforme n'envoie JAMAIS ce message : le clic sur l'icône ouvre
    seulement la conversation WhatsApp avec le texte pré-saisi (paramètre
    ?text= de wa.me — voir templates/dashboard/_whatsapp_icon.html), l'envoi
    reste 100 % manuel. Espaces réservés remplacés à l'affichage :
    {nom}, {date_echeance}, {jours_retard} (voir
    payments.views._message_relance_whatsapp)."""

    message = models.TextField(blank=True)
    derniere_modification_par = models.ForeignKey(
        'accounts.User', null=True, blank=True, on_delete=models.SET_NULL, related_name='+'
    )
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "رسالة تذكير الدفع عبر واتساب"

    class Meta:
        verbose_name = "Réglage relance WhatsApp"
        verbose_name_plural = "Réglage relance WhatsApp"


def get_reglage_relance_whatsapp():
    """Renvoie l'unique instance de ReglageRelanceWhatsApp, en la créant avec le
    message par défaut si elle n'existe pas encore — même patron singleton que
    courses.models.get_reglage_lien_seance()."""
    reglage, _cree = ReglageRelanceWhatsApp.objects.get_or_create(
        pk=1, defaults={'message': MESSAGE_RELANCE_WHATSAPP_DEFAUT}
    )
    return reglage