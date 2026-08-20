"""Moteur d'inscription configurable — app SANS logique d'affichage (comme dashboard
n'a pas de modèles, registration n'a pas de gabarits figés par critère).

Principe central (validé en amont du code, voir historique du chantier) : un critère
(Riwaya, Objectif, Mode d'apprentissage, ou n'importe quel critère futur jamais prévu
aujourd'hui) doit pouvoir être créé, doté d'options, ajouté à une étape du formulaire,
rendu obligatoire, rendu filtrant, et utilisé pour filtrer les groupes — le tout depuis
le dashboard (Directeur ET مشرف, permissions strictement identiques), SANS jamais
ajouter de code Python spécifique à ce critère.

Backend de stockage (Critere.backend) — un ensemble FERMÉ à 3 valeurs, jamais un cas
par nom de critère métier :
- 'eav'          : valeur libre, stockée dans GroupeCritereValeur/ReponseInscription.
                   C'est le comportement PAR DÉFAUT pour tout critère, y compris tout
                   critère jamais imaginé aujourd'hui (Mode d'apprentissage, Langue...).
- 'champ_groupe' : le critère correspond en réalité à un champ RÉEL déjà existant sur
                   Groupe (ex: 'type_offre' -> Groupe.type_capacite) — évite de dupliquer
                   une donnée déjà structurellement embarquée ailleurs dans le projet
                   (TarifRemuneration, capacité...). Aucune ligne GroupeCritereValeur
                   n'est jamais écrite pour ce backend.
- 'nb_slots'     : le critère est ENTIÈREMENT dérivé du nombre réel de CreneauSlot d'un
                   groupe (courses.models.CreneauSlot) — jamais stocké nulle part par
                   groupe, jamais configuré manuellement. Une seule source de vérité :
                   le planning réel du groupe. Aucune CritereOption ni GroupeCritereValeur
                   n'est jamais créée pour ce backend, les valeurs possibles sont
                   recalculées à la volée (voir registration.utils.groupes_compatibles).

Ces 3 backends sont fixés UNE FOIS à l'architecture, pas par critère métier à l'infini —
c'est ce qui permet au moteur de filtrage de rester générique (voir registration.utils)
tout en couvrant les 2 cas structurels déjà identifiés dans ce projet (type_offre,
nb_seances_hebdo) sans jamais réintroduire de deuxième source de vérité pour eux.

Suppression (on_delete) — politique décidée explicitement par le client : "un Critere
déjà utilisé -> PROTECT, jamais de CASCADE silencieux sur des réponses d'élèves".
Appliquée ainsi dans tout ce fichier :
- CritereOption.critere = CASCADE : une option n'est que la liste de valeurs d'un
  critère, sans existence indépendante — supprimer un critère jamais accroché à un
  formulaire/une réponse/un groupe doit rester un VRAI nettoyage possible (ex: critère
  créé par erreur, jamais publié).
- Toute FK représentant un USAGE réel d'un Critere/CritereOption (attaché à un
  ChampInscription, répondu dans une ReponseInscription, assigné à un
  GroupeCritereValeur, référencé par une RegleCondition) = PROTECT : dès qu'un critère
  ou une option a servi ne serait-ce qu'une fois, sa suppression est bloquée — seule la
  désactivation (est_actif=False) reste possible, cohérent avec le principe déjà établi
  partout ailleurs dans ce projet (archivage réversible plutôt que suppression
  destructive dès qu'une donnée réelle est en jeu, voir courses.utils.
  creneau_peut_etre_supprime/groupe_peut_etre_supprime)."""

from django.contrib.contenttypes.fields import GenericForeignKey
from django.contrib.contenttypes.models import ContentType
from django.db import models


class Critere(models.Model):
    """Un critère configurable — de filtrage (Riwaya, Objectif...) ou purement
    informatif (filtrable=False). Voir la politique de backend dans le docstring
    du module ci-dessus."""

    TYPE_CHAMP_CHOICES = [
        ('texte', 'نص'),
        ('email', 'بريد إلكتروني'),
        ('telephone', 'هاتف'),
        ('nombre', 'رقم'),
        ('date', 'تاريخ'),
        ('choix_unique', 'اختيار واحد'),
        ('choix_multiple', 'اختيار متعدد'),
        ('booleen', 'نعم/لا'),
    ]
    BACKEND_CHOICES = [
        ('eav', 'قيمة حرة (الافتراضي)'),
        ('champ_groupe', 'مرتبط بحقل حقيقي في نموذج المجموعة'),
        ('nb_slots', 'مشتق تلقائياً من عدد الحصص الأسبوعية الحقيقية'),
    ]

    code = models.SlugField(max_length=50, unique=True)
    label = models.CharField(max_length=200)
    type_champ = models.CharField(max_length=20, choices=TYPE_CHAMP_CHOICES, default='choix_unique')
    # 'eav' pour tout critère par défaut, y compris tout critère futur jamais prévu
    # aujourd'hui. 'champ_groupe'/'nb_slots' sont réservés aux 2 cas structurels déjà
    # identifiés (type_offre, nb_seances_hebdo) — voir docstring du module.
    backend = models.CharField(max_length=20, choices=BACKEND_CHOICES, default='eav')
    # Rempli uniquement si backend='champ_groupe' — nom du champ réel sur
    # courses.models.Groupe (ex: 'type_capacite'). Lu dynamiquement par
    # registration.utils, jamais comparé par nom de critère.
    champ_modele_groupe = models.CharField(max_length=50, blank=True, default='')
    # Participe au filtrage des groupes compatibles (registration.utils.groupes_compatibles).
    # Un critère purement informatif (ex: futur "comment nous avez-vous connus ?")
    # reste filtrable=False pour toujours.
    filtrable = models.BooleanField(default=False)
    # Incompatibilité BLOQUANTE (comme l'âge aujourd'hui) si True, simple avertissement
    # contournable par confirmation explicite (comme riwaya/programme aujourd'hui,
    # voir courses.utils.avertissements_groupe) si False. Configurable par critère,
    # au lieu d'être figé dans le code comme c'était le cas jusqu'ici.
    bloquant = models.BooleanField(default=False)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.label

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Critère d'inscription"
        verbose_name_plural = "Critères d'inscription"


class CritereOption(models.Model):
    """Une option d'un critère à choix (unique ou multiple). Sans objet pour les
    critères backend='nb_slots' (options calculées à la volée, jamais stockées ici —
    voir registration.utils.groupes_compatibles)."""

    critere = models.ForeignKey(Critere, on_delete=models.CASCADE, related_name='options')
    code = models.SlugField(max_length=50)
    label = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.label

    class Meta:
        ordering = ['ordre', 'id']
        unique_together = ('critere', 'code')
        verbose_name = "Option de critère"
        verbose_name_plural = "Options de critère"


class EtapeInscription(models.Model):
    """Une étape du parcours d'inscription (المعلومات الشخصية، اختيار البرنامج...).
    Le contenu texte de l'étape 0 (présentation/ميثاق) vit dans PresentationInscription,
    pas ici — une EtapeInscription ne porte que la structure du formulaire, jamais du
    texte de présentation libre."""

    code = models.SlugField(max_length=50, unique=True)
    titre = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.titre

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Étape d'inscription"
        verbose_name_plural = "Étapes d'inscription"


class ChampInscription(models.Model):
    """Un champ affiché dans une étape. Deux cas, distingués par critere :
    - critere renseigné : champ de filtrage/critère dynamique, type_champ/options lus
      depuis critere (le champ type_champ ci-dessous reste vide dans ce cas, pour ne
      jamais risquer une divergence entre les deux sources).
    - critere=NULL : champ purement informatif à l'Étape 1, au-delà du socle
      structurel déjà fixe sur InscriptionEleve (nom/email/téléphone/sexe/date de
      naissance, qui ne passent jamais par ce modèle — voir la docstring de
      inscriptions.models.InscriptionEleve). Exemple concret déjà décidé : "Pays",
      au même titre que "Niveau scolaire"/"Profession". type_champ ci-dessous précise
      alors le type de saisie ; pas de CritereOption possible dans ce cas (pas de
      Critere auquel les rattacher) — un champ informatif à choix fermé nécessiterait
      un vrai Critere (filtrable=False), pas ce mécanisme."""

    etape = models.ForeignKey(EtapeInscription, on_delete=models.PROTECT, related_name='champs')
    critere = models.ForeignKey(
        Critere, on_delete=models.PROTECT, null=True, blank=True, related_name='champs'
    )
    # Rempli SEULEMENT si critere est NULL (champ informatif). Sinon laissé vide —
    # le type vient alors de critere.type_champ, jamais dupliqué ici.
    type_champ = models.CharField(max_length=20, choices=Critere.TYPE_CHAMP_CHOICES, blank=True, default='')
    label = models.CharField(max_length=200)
    obligatoire = models.BooleanField(default=False)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return self.label

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Champ d'inscription"
        verbose_name_plural = "Champs d'inscription"


class RegleCondition(models.Model):
    """Règle conditionnelle générique : SI la réponse à critere_condition correspond
    (selon operateur/valeurs) ALORS cible (une EtapeInscription ou un ChampInscription,
    via GenericForeignKey) est masquée. cible_content_type est volontairement limité en
    pratique à ces 2 modèles (appliqué au niveau du formulaire d'administration, pas
    d'une contrainte DB — django.contrib.contenttypes ne permet pas de restreindre le
    type au niveau du champ). critere_condition en CASCADE (pas PROTECT, contrairement
    au reste du fichier) : une règle est de la pure configuration sans valeur
    historique propre, sa perte à la suppression d'un critère n'efface aucune donnée
    d'élève — voir la distinction PROTECT/CASCADE dans le docstring du module."""

    OPERATEUR_CHOICES = [
        ('egal', 'يساوي'),
        ('different', 'يختلف عن'),
        ('dans', 'ضمن'),
    ]

    cible_content_type = models.ForeignKey(ContentType, on_delete=models.CASCADE)
    cible_object_id = models.PositiveIntegerField()
    cible = GenericForeignKey('cible_content_type', 'cible_object_id')

    critere_condition = models.ForeignKey(Critere, on_delete=models.CASCADE, related_name='regles')
    operateur = models.CharField(max_length=20, choices=OPERATEUR_CHOICES, default='egal')
    # Codes de CritereOption (ex: ['individuel']) — comparés aux réponses de l'élève
    # par registration.utils, jamais par nom de critère en dur.
    valeurs = models.JSONField(default=list)
    est_actif = models.BooleanField(default=True)

    def __str__(self):
        return f'قاعدة على {self.critere_condition}'

    class Meta:
        verbose_name = "Règle conditionnelle"
        verbose_name_plural = "Règles conditionnelles"


class ReponseInscription(models.Model):
    """Réponse d'UNE candidature à UN champ — IMMUABLE une fois créée. Aucune vue de
    modification n'existe nulle part sur ce modèle dans tout le projet (voir
    registration.views) : une réponse historique erronée se corrige par une nouvelle
    candidature ou une intervention directement en base, jamais par un formulaire
    d'édition. Modifier la configuration du formulaire (ChampInscription/Critere)
    après coup ne modifie jamais rétroactivement une ReponseInscription déjà créée."""

    inscription = models.ForeignKey(
        'inscriptions.InscriptionEleve', on_delete=models.CASCADE, related_name='reponses'
    )
    champ = models.ForeignKey(ChampInscription, on_delete=models.PROTECT, related_name='reponses')
    # NULL pour un champ informatif (critere=NULL sur le ChampInscription associé) —
    # dupliqué depuis champ.critere_id au moment de la création plutôt que de le
    # déduire via une jointure à chaque lecture, pour rester correct même si le champ
    # est modifié après coup.
    critere = models.ForeignKey(
        Critere, on_delete=models.PROTECT, null=True, blank=True, related_name='reponses'
    )
    option = models.ForeignKey(
        CritereOption, on_delete=models.PROTECT, null=True, blank=True, related_name='reponses'
    )
    # Texte libre / nombre en texte (ex: nb_seances_hebdo en parcours Individuel,
    # purement indicatif, voir Critere.backend='nb_slots') / valeur d'un champ
    # informatif sans option. Vide si option est renseignée.
    valeur_texte = models.TextField(blank=True)
    date_creation = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f'{self.champ} -> {self.valeur_texte or self.option}'

    class Meta:
        ordering = ['champ__etape__ordre', 'champ__ordre']
        verbose_name = "Réponse d'inscription"
        verbose_name_plural = "Réponses d'inscription"


class GroupeCritereValeur(models.Model):
    """La valeur d'UN critère pour UN groupe (ex: Groupe A / Riwaya = Hafs). Jamais
    créée pour un critère backend='champ_groupe' (déjà porté par le vrai champ sur
    Groupe) ni backend='nb_slots' (dérivé de CreneauSlot, jamais stocké séparément).
    unique_together permet plusieurs lignes (groupe, critere) pour un critère
    choix_multiple — l'unicité pour un critère choix_unique (une seule valeur active à
    la fois) est une règle applicative, pas une contrainte DB (voir
    registration.utils, qui remplace toujours l'ensemble existant plutôt que
    d'accumuler, même idiome que courses.utils.matrice_vers_lignes)."""

    groupe = models.ForeignKey('courses.Groupe', on_delete=models.CASCADE, related_name='valeurs_criteres')
    critere = models.ForeignKey(Critere, on_delete=models.PROTECT, related_name='valeurs_groupes')
    option = models.ForeignKey(
        CritereOption, on_delete=models.PROTECT, null=True, blank=True, related_name='valeurs_groupes'
    )

    def __str__(self):
        return f'{self.groupe} - {self.critere}: {self.option}'

    class Meta:
        unique_together = ('groupe', 'critere', 'option')
        verbose_name = "Valeur de critère (groupe)"
        verbose_name_plural = "Valeurs de critère (groupes)"


class PresentationInscription(models.Model):
    """Contenu configurable de l'Étape 0 (présentation/ميثاق avant le formulaire) et du
    message final après confirmation — singleton, même patron que
    accounts.models.ProgrammeGeneral/CharteEnseignement (get_or_create sur pk=1),
    éditable par مدير ET مشرف (permissions identiques, voir accounts.decorators.
    role_required('admin', 'mshrif'))."""

    titre = models.CharField(max_length=200, blank=True)
    intro = models.TextField(blank=True)
    bouton_texte = models.CharField(max_length=100, default='متابعة التسجيل')
    # Affiché après confirmation (Partie 14 du cahier des charges) — le délai de
    # contact (ParametresInscriptions.delai_contact_heures, inscriptions/models.py)
    # est injecté dans ce texte au rendu, jamais recopié en dur ici.
    message_bienvenue = models.TextField(blank=True)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "تقديم صفحة التسجيل"

    class Meta:
        verbose_name = "Présentation d'inscription"
        verbose_name_plural = "Présentation d'inscription"


def get_presentation_inscription():
    """Renvoie l'unique instance de PresentationInscription, en la créant (vide) si
    elle n'existe pas encore — même patron singleton que accounts.models.get_charte()."""
    presentation, _ = PresentationInscription.objects.get_or_create(pk=1)
    return presentation
