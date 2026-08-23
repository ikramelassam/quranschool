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
  GroupeCritereValeur) = PROTECT : dès qu'un critère ou une option a servi ne
  serait-ce qu'une fois, sa suppression est bloquée — seule la désactivation
  (est_actif=False) reste possible, cohérent avec le principe déjà établi
  partout ailleurs dans ce projet (archivage réversible plutôt que suppression
  destructive dès qu'une donnée réelle est en jeu, voir courses.utils.
  creneau_peut_etre_supprime/groupe_peut_etre_supprime).

RegleCondition (règles conditionnelles génériques de masquage, "SI critère X
ALORS masquer étape/champ Y") a existé dans ce fichier jusqu'au chantier du
2026-08-23 — retirée après audit : 0 ligne créée depuis sa mise en place
(aucune migration de seed, base réelle vide), le seul cas d'usage qui aurait
pu la justifier (masquer l'étape "اختيار المجموعة" quand l'élève choisit
فردي) n'est en réalité PAS géré par elle mais par une condition Python fixe
dans registration.views.wizard_groupe (voir sa docstring) — jamais modifiable
depuis le dashboard, par choix. Aucun autre besoin réel identifié à ce jour
(voir la clarification Système A/critères filtrables vs Système B/étapes de
contenu statique, ni l'un ni l'autre n'a besoin de masquage conditionnel
entre champs). Si un vrai besoin de ce type apparaît plus tard, un chantier
séparé le réintroduira consciemment plutôt que de laisser du code générique
non testé en pratique."""

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
    texte de présentation libre.

    Chantier du 2026-08-22 (correction 8, "navigation dynamique") : représente
    désormais les 7 VRAIES étapes du parcours public (catégorie d'âge, identité,
    programme, groupe, abonnement, paiement, confirmation) — pas seulement
    identite/programme comme avant cette correction. `ordre` pilote RÉELLEMENT
    la page suivante visitée par l'élève (voir registration.utils.
    etape_suivante), plus une simple valeur cosmétique pour trier les
    ChampInscription à l'intérieur d'une étape. L'étape 0 (ميثاق/wizard_intro)
    reste HORS de ce modèle : un simple écran de présentation
    (PresentationInscription), jamais une étape avec `ordre`/`est_actif` à
    reconfigurer.

    CODES_VERROUILLES : 5 des 7 étapes ne peuvent PAS être désactivées (save()
    y réécrit silencieusement est_actif=True, même défense en profondeur que
    ConfigurationChampStructurel.CLES_VERROUILLEES) car chacune est un VRAI
    prérequis dur ailleurs dans le code, pas juste une préférence d'affichage :
    - categorie_age : porte d'entrée du parcours — sans elle, aucune tranche
      d'âge connue pour filtrer quoi que ce soit.
    - identite : sexe/date_naissance/email y sont eux-mêmes verrouillés
      (contraintes structurelles, voir ConfigurationChampStructurel) —
      désactiver l'ÉTAPE entière les rendrait invisibles ET non validés
      (champs_structurels_actifs filtre sur etape__est_actif), cassant leur
      propre verrouillage par la bande.
    - abonnement : inscrire_eleve() EXIGE toujours un abonnement_code valide
      (aucun repli "abonnement par défaut") — désactiver cette étape rendrait
      TOUTE inscription impossible à finaliser, un vrai blocage silencieux.
    - paiement : héberge le POST qui déclenche réellement inscrire_eleve()
      (_wizard_confirmer_inscription) — aucune autre vue ne le fait, la
      désactiver reviendrait à supprimer le bouton "s'inscrire" lui-même.
    - confirmation : rien après elle, purement l'écran de succès.
    'programme' et 'groupe' restent librement activables/désactivables ET
    réordonnables : 'groupe' est déjà conditionnel (ignoré si type_offre=
    'individuel', voir registration.utils.etape_est_active) et 'programme'
    dégrade déjà proprement à vide si désactivée (champs_structurels_actifs
    style, jamais une exception)."""

    code = models.SlugField(max_length=50, unique=True)
    titre = models.CharField(max_length=200)
    ordre = models.IntegerField(default=0)
    est_actif = models.BooleanField(default=True)

    CODES_VERROUILLES = {'categorie_age', 'identite', 'abonnement', 'paiement', 'confirmation'}

    def save(self, *args, **kwargs):
        if self.code in self.CODES_VERROUILLES:
            self.est_actif = True
        super().save(*args, **kwargs)

    def __str__(self):
        return self.titre

    @property
    def est_verrouillee(self):
        """Utilisé côté template (pas de lookup de dict par variable, même
        principe que ConfigurationChampStructurel.est_verrouille)."""
        return self.code in self.CODES_VERROUILLES

    class Meta:
        ordering = ['ordre', 'id']
        verbose_name = "Étape d'inscription"
        verbose_name_plural = "Étapes d'inscription"


class ConfigurationChampStructurel(models.Model):
    """Configuration d'AFFICHAGE (jamais de stockage) des champs structurels
    fixes de InscriptionEleve — nom/nom_parent/sexe/telephone/date_naissance/
    email/job_actuel/niveau_scolaire restent de VRAIES colonnes du modèle,
    jamais migrées vers l'EAV/ReponseInscription (décision actée le
    2026-08-22, chantier "champs structurels configurables") : cette table
    ne configure QUE label/ordre/étape/obligatoire/actif/placeholder/aide/
    validation — jamais où la donnée est stockée ni son type Python réel.

    sexe/date_naissance/email sont VERROUILLÉS (CLES_VERROUILLEES) : ils
    cassent une vraie logique métier si rendus optionnels/masqués/déplacés —
    sexe et date_naissance sont des contraintes STRUCTURELLES du filtrage de
    groupes (registration.utils.groupes_compatibles_avec_age, jamais
    relâchées même par confirme_override, voir RegressionSexeGroupesTests
    du 2026-08-22), email est la clé de dédoublonnage ET la convention
    username=email à la création du compte élève (accounts app). Pour ces 3
    UNIQUEMENT : label et ordre restent modifiables, rien d'autre — save()
    réécrit silencieusement obligatoire=True/est_actif=True/etape=l'étape
    déjà en base pour eux à chaque sauvegarde, jamais une confiance aveugle
    dans le formulaire d'édition seul (même défense en profondeur que
    Groupe.eleves.count() revérifié serveur malgré le filtrage d'affichage).

    Un NOUVEAU champ structurel (= une VRAIE colonne Django) nécessite
    TOUJOURS un développeur (migration) — techniquement impossible à éviter,
    une colonne ne s'invente pas depuis un formulaire (niveau_scolaire,
    ajouté au 2026-08-22, en est un exemple). Pour un champ que le مدير veut
    ajouter LUI-MÊME, sans aucun code : le mécanisme déjà existant et déjà
    100% fonctionnel est le "champ informatif" (ChampInscription avec
    critere=None, voir registration.views._champs_informatifs_actifs,
    stocké via ReponseInscription comme n'importe quelle réponse EAV) — CE
    modèle-ci ne le remplace pas, il configure uniquement les colonnes déjà
    câblées en dur dans le code Python (wizard_identite,
    admin_eleve_ajouter_manuel, inscrire_eleve)."""

    CHAMP_CLE_CHOICES = [
        ('nom', 'الاسم الكامل'),
        ('nom_parent', 'اسم ولي الأمر'),
        ('sexe', 'الجنس'),
        ('telephone', 'الهاتف'),
        ('date_naissance', 'تاريخ الميلاد'),
        ('email', 'البريد الإلكتروني'),
        ('job_actuel', 'المهنة'),
        ('niveau_scolaire', 'المستوى الدراسي'),
    ]
    TYPE_CHAMP_CHOICES = [
        ('texte', 'نص قصير'),
        ('texte_multiligne', 'نص طويل'),
    ]
    # sexe/date_naissance/email : voir la docstring ci-dessus — jamais
    # optionnels/masquables/déplaçables, seuls label/ordre restent éditables.
    CLES_VERROUILLEES = {'sexe', 'date_naissance', 'email'}
    # telephone (widget indicatif+numéro+confirmation WhatsApp, PAS un
    # <input> simple) rejoint sexe/date_naissance/email pour type_champ/
    # placeholder/regex uniquement (il reste, lui, déplaçable/masquable/
    # optionnel — juste pas un champ texte configurable comme les 4 autres).
    CLES_SANS_TYPE_CHAMP = CLES_VERROUILLEES | {'telephone'}

    champ_cle = models.CharField(max_length=30, choices=CHAMP_CLE_CHOICES, unique=True)
    label = models.CharField(max_length=100)
    ordre = models.IntegerField(default=0)
    etape = models.ForeignKey(EtapeInscription, on_delete=models.PROTECT, related_name='champs_structurels')
    obligatoire = models.BooleanField(default=True)
    est_actif = models.BooleanField(default=True)
    # Non pertinent pour CLES_SANS_TYPE_CHAMP (widget/type Python fixe) —
    # laissé blank pour eux, jamais lu par le rendu dans ce cas.
    type_champ = models.CharField(max_length=20, choices=TYPE_CHAMP_CHOICES, default='texte', blank=True)
    placeholder = models.CharField(max_length=200, blank=True, default='')
    texte_aide = models.CharField(max_length=300, blank=True, default='')
    # Regex Python optionnelle (re.fullmatch), appliquée UNIQUEMENT si non
    # vide ET valeur non vide déjà présente — jamais pour CLES_SANS_TYPE_CHAMP
    # (leur validation dédiée existante reste seule autorité).
    regex_validation = models.CharField(max_length=200, blank=True, default='')
    message_erreur_regex = models.CharField(max_length=200, blank=True, default='')

    def save(self, *args, **kwargs):
        if self.champ_cle in self.CLES_VERROUILLEES:
            self.obligatoire = True
            self.est_actif = True
            if self.pk:
                self.etape_id = ConfigurationChampStructurel.objects.get(pk=self.pk).etape_id
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.label} ({self.get_champ_cle_display()})"

    @property
    def est_verrouille(self):
        """Utilisé côté template (pas de lookup de dict par variable, voir le
        bug historique documenté ailleurs dans ce chantier) plutôt que de
        passer un set brut dans le contexte de chaque vue."""
        return self.champ_cle in self.CLES_VERROUILLEES

    class Meta:
        ordering = ['etape__ordre', 'ordre', 'id']
        verbose_name = "Configuration de champ structurel"
        verbose_name_plural = "Configuration des champs structurels"


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
    # Chantier du 2026-08-22 ("liberté totale du nombre de séances") — affiché
    # à wizard_groupe quand AUCUN groupe n'existe pour la combinaison EXACTE
    # de critères choisis (voir DemandeNonSatisfaite ci-dessous) : un défaut
    # raisonnable est fourni par get_presentation_inscription() si vide,
    # jamais un texte brut codé en dur dans le template.
    message_aucun_groupe_exact = models.TextField(blank=True)
    date_modification = models.DateTimeField(auto_now=True)

    def __str__(self):
        return "تقديم صفحة التسجيل"

    class Meta:
        verbose_name = "Présentation d'inscription"
        verbose_name_plural = "Présentation d'inscription"


def get_presentation_inscription():
    """Renvoie l'unique instance de PresentationInscription, en la créant (vide) si
    elle n'existe pas encore — même patron singleton que accounts.models.get_charte().
    message_aucun_groupe_exact reçoit un texte par défaut raisonnable À LA CRÉATION
    seulement (jamais réécrit après coup si le مدير le vide volontairement) — même
    logique que TypeAbonnement.prix ou n'importe quel champ éditable avec une
    valeur de départ sensée."""
    presentation, cree = PresentationInscription.objects.get_or_create(
        pk=1,
        defaults={'message_aucun_groupe_exact': (
            'لم نجد أي حلقة تجمع بالضبط بين كل المعايير التي اخترتها (البرنامج، '
            'الرواية، عدد الحصص...). يمكنك الانضمام إلى إحدى الحلقات القريبة '
            'أدناه، أو اختيار الانتظار حتى يتم إنشاء حلقة تناسبك تماماً.'
        )},
    )
    return presentation


class DemandeNonSatisfaite(models.Model):
    """Trace chaque fois qu'AUCUN groupe n'existe pour la combinaison EXACTE
    de critères choisie par un candidat (chantier du 2026-08-22, "liberté
    totale du nombre de séances" — le nombre de séances n'est plus limité
    à ce qui existe déjà, donc ce cas devient possible pour n'importe quelle
    combinaison, pas seulement le nombre de séances). Objectif : que le
    مدير/مشرف identifie, depuis le dashboard, les combinaisons les plus
    demandées pour décider quels nouveaux groupes ouvrir.

    criteres_json : {code_critere: valeur_ou_liste_de_codes} — snapshot BRUT
    des réponses filtrables au moment de la demande. Les labels humains sont
    recalculés à la LECTURE (Critere/CritereOption restent la seule source
    de vérité) — jamais dupliqués ici, un critère renommé après coup ne doit
    pas laisser d'anciens libellés figés et incohérents.

    inscription : renseigné a posteriori si le candidat choisit malgré tout
    de continuer (voir registration.utils.inscrire_eleve) — None tant que
    la candidature n'est pas allée au bout, ou si le visiteur abandonne en
    cours de route (SET_NULL : la suppression d'une candidature ne doit
    jamais faire disparaître la trace statistique de la demande elle-même)."""
    criteres_json = models.JSONField(default=dict)
    type_offre = models.CharField(max_length=20, blank=True, default='')
    nb_slots = models.IntegerField(null=True, blank=True)
    age = models.IntegerField(null=True, blank=True)
    sexe = models.CharField(max_length=10, blank=True, default='')
    date_demande = models.DateTimeField(auto_now_add=True)
    inscription = models.ForeignKey(
        'inscriptions.InscriptionEleve', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='demandes_non_satisfaites',
    )

    def __str__(self):
        return f"طلب غير ملبى — {self.date_demande.strftime('%Y-%m-%d')}"

    class Meta:
        ordering = ['-date_demande']
        verbose_name = "Demande non satisfaite"
        verbose_name_plural = "Demandes non satisfaites"
