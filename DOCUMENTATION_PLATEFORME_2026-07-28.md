# Documentation complète de la plateforme — état réel au 28/07/2026

Ce document décrit ce que voit et fait réellement chaque type d'utilisateur sur la plateforme, tel que vérifié directement dans le code (pas de suppositions, pas de mémoire d'anciennes versions). Il est écrit en français simple, sans détails techniques, pour servir de base à un guide utilisateur en arabe destiné au directeur de l'école.

Les 5 rôles : **مدير** (directeur), **مشرف** (superviseur général de la plateforme), **مؤطر** (encadrant pédagogique des professeurs), **أستاذ** (professeur), **طالب** (élève).

---

# PARTIE 1 — Ce qu'il faut absolument savoir avant de lire le reste (écarts et points de vigilance)

Cette section répond directement à la question « est-ce que la plateforme actuelle correspond à ce que vous pensiez avoir construit ? ». Chaque point ci-dessous a été vérifié dans le code, pas supposé.

### 1. Le mot de passe oublié n'envoie JAMAIS d'email — il passe par Telegram
Quand un utilisateur clique sur « mot de passe oublié », le système génère un nouveau mot de passe et **l'envoie uniquement au مدير via Telegram** (jamais par email — le code indique explicitement que l'envoi d'email n'est pas assez fiable pour ce cas précis). C'est ensuite au مدير de transmettre ce mot de passe à la personne concernée, par WhatsApp, téléphone, etc. C'est différent de la création de compte (voir point 2), qui elle tente bien un envoi par email.

### 2. La création de compte (après acceptation d'une candidature), elle, tente un envoi par email — mais le mot de passe est aussi affiché au مدير
Quand le مدير (ou le مشرف, pour les professeurs) accepte définitivement une candidature, le système essaie d'envoyer un email de bienvenue avec le mot de passe temporaire. Mais comme cet envoi n'est pas garanti, **le mot de passe temporaire est systématiquement affiché à l'écran au مدير/مشرف au moment de l'acceptation**, avec la mention « à transmettre manuellement à la personne — aucun envoi automatique fiable par email ». Il faut donc toujours prévoir que le مدير communique lui-même ce mot de passe.

### 3. La candidature d'un professeur passe par DEUX validations, pas une seule
- **Élève** : le مدير valide (ou rejette) directement. Une seule étape, le compte est créé immédiatement à l'acceptation.
- **Professeur** : c'est un processus en deux temps :
  1. Le **مدير** examine le dossier et donne un premier accord (« قبول أولي »). **Aucun compte n'est encore créé à ce stade.**
  2. Le dossier passe alors dans la liste du **مشرف**, qui donne l'accord final. **C'est SEULEMENT à cette étape que le compte du professeur est réellement créé** et que le mot de passe temporaire est généré.
  - Si le مدير rejette avant que le مشرف n'ait validé, le dossier s'arrête là.
  - Le مشرف peut aussi rejeter à sa propre étape, même après l'accord du مدير.

### 4. Le مشرف n'est PAS un simple rôle « consultation » — il a de vrais pouvoirs de modification sur 5 zones précises
L'image générale du مشرف est « il voit tout ce que voit le مدير, mais en lecture seule ». C'est vrai pour la grande majorité des pages, MAIS il a un pouvoir de modification réel et complet sur :
1. **La validation finale des candidatures de professeurs** (voir point 3) — c'est même la seule décision structurante qu'il prend sur toute la plateforme.
2. **Le ميثاق التدريس** (charte/règlement des professeurs) — édition complète, comme le مدير.
3. **Le البرنامج العام** (programme pédagogique général) — édition complète, comme le مدير.
4. **Le logo de la plateforme** — c'est même une page exclusive au مشرف, que le مدير n'a pas.
5. **Les types d'abonnement** (tarifs proposés aux familles à l'inscription) — ajout, modification, activation/désactivation, exactement comme le مدير.

Sur toutes les autres pages qu'il partage avec le مدير (élèves, professeurs, groupes, créneaux, séances, paiements, évaluations, etc.), le مشرف est en **lecture seule stricte** : les boutons d'action (modifier, supprimer, valider, refuser...) sont simplement absents de son écran.

### 5. Un bouton visible mais qui ne fonctionne pas, pour le مشرف
Sur la fiche d'une candidature de professeur, si l'email du candidat entre en conflit avec un ancien compte de test resté orphelin en base, un bouton « supprimer le compte orphelin » est affiché au مشرف — mais ce bouton ne fonctionne en réalité que pour le مدير. Si le مشرف clique dessus, rien ne se passe (il est renvoyé silencieusement à son tableau de bord, sans message d'erreur). Dans ce cas de figure précis, ni le مدير (qui ne voit plus ce dossier une fois pré-validé) ni le مشرف ne peuvent débloquer la situation depuis l'interface — il faudrait une intervention technique. À signaler comme un vrai point faible si ce cas se présente un jour.

### 6. La majoration mensuelle du professeur (منحة) n'est JAMAIS visible par le professeur lui-même
C'est un point de confidentialité volontaire et vérifié dans le code à plusieurs endroits : la page « راتبي » du professeur n'affiche que le calcul automatique de base (nombre d'élèves × tarif), jamais la majoration/prime que le مدير peut ajouter manuellement. Cette majoration n'est visible que par le مدير (qui peut la modifier), le مشرف (en lecture seule) et le مؤطر (dans le classement mensuel des professeurs). Le professeur ne voit ni le montant, ni même le fait qu'une majoration existe.

### 7. L'élève n'a AUCUN moyen de voir son bilan mensuel
Le bilan mensuel (rédigé par le professeur, avec ce qui a été mémorisé/révisé dans le mois et des remarques de comportement) est consultable par le مدير, le مشرف et le مؤطر, et modifiable par le professeur — mais **il n'existe aucun lien, aucune page, nulle part dans l'espace élève pour le consulter**. Si le directeur pensait que l'élève (ou son parent) pouvait voir ce bilan, ce n'est pas le cas actuellement.

### 8. Deux pages différentes gèrent les mêmes paiements
Il existe actuellement deux pages côté مدير pour gérer les paiements des familles (« المدفوعات » et « متابعة مدفوعات الطلاب »). Elles ne sont pas redondantes par erreur : la seconde est une nouvelle vue plus pratique (calendrier mois par mois par élève, modification directe en un clic), mais l'ancienne n'a pas été retirée. Cela peut créer une confusion pour le directeur qui verrait deux endroits différents pour la même tâche — à expliquer clairement dans le guide, en recommandant d'utiliser en priorité « متابعة مدفوعات الطلاب ».

### 9. Aucune suspension possible pour un professeur
Un élève peut être marqué « actif / suspendu / archivé » avec des boutons dédiés. **Un professeur, lui, n'a aucun statut de ce type** — la seule action de gestion de compte disponible pour un professeur est de changer son adresse email. Il n'y a pas non plus de moyen de retirer ou désactiver un مؤطر une fois qu'il a été créé (seule la liste des professeurs qui lui sont assignés peut être modifiée).

### 10. Le libellé « تقييم الطلاب » n'est PAS tronqué
Une inquiétude avait été soulevée sur une possible troncature de ce libellé dans la sidebar du مشرف. Vérification faite : le texte complet « تقييم الطلاب » s'affiche bien partout (menu, titre de page, onglet du navigateur). Aucun problème à ce niveau.

### 11. Deux compteurs de « séances en retard » qui ne se valent pas toujours chez le مؤطر
Sur la page d'accueil du مؤطر, le nombre de « حصص متأخرة » inclut les séances passées jamais évaluées, qu'elles soient officiellement « terminées » ou qu'elles soient restées bloquées au statut « planifiée » (oubli du professeur). Sur sa page de profil, le compteur équivalent ne compte que les séances officiellement « terminées ». Les deux chiffres peuvent donc légitimement être différents pour la même situation réelle — ce n'est pas une erreur, mais il faut le dire clairement dans le guide pour éviter toute confusion du type « pourquoi ces deux nombres ne sont pas pareils ».

### 12. Petit écart de titre sur une page du مدير/مشرف
Sur la page « استثناءات الحصص », le titre affiché dans l'onglet du navigateur est simplement « الحصص », alors que le titre affiché sur la page elle-même est « استثناءات الحصص ». Purement cosmétique, sans impact sur l'utilisation.

---

# PARTIE 2 — Chaque rôle, page par page

## 2.1 — مدير (Directeur)

La sidebar du مدير est organisée en 6 blocs : un lien direct (tableau de bord), puis 5 catégories dépliables, puis un lien « mon compte » et la déconnexion.

**Lien direct**
- **لوحة التحكم** : écran d'accueil avec 4 chiffres clés (total élèves, total professeurs, groupes actifs, demandes en attente) et les 3 dernières candidatures élèves + les 3 dernières candidatures professeurs, avec un lien pour voir le détail de chacune.

**Catégorie « إدارة المستخدمين » (Gestion des utilisateurs)**
- **الطلاب** : liste de tous les élèves déjà acceptés, avec recherche par nom/email et filtres (statut, groupe, dates d'inscription, afficher ou non les élèves archivés). En cliquant sur un élève : sa fiche complète (infos, groupe actuel, groupes précédents, groupes compatibles suggérés avec bouton pour l'y ajouter directement, toutes les infos de son dossier de candidature d'origine, et sa progression de mémorisation du Coran). Depuis cette fiche : boutons pour suspendre, réactiver ou archiver l'élève, changer son email, et consulter/modifier son tableau de disponibilités.
- **المعلمون** : liste des professeurs (recherche par nom/ville). Fiche détail : infos générales, préférences d'enseignement, parcours, calcul automatique de sa rémunération du mois (détaillé groupe par groupe), un champ pour ajouter une **majoration mensuelle personnelle** (jamais visible par le professeur — voir point 6 de la Partie 1), infos bancaires, liste de ses groupes, boutons pour changer son email et consulter/modifier ses disponibilités.
- **طلبات التسجيل** : file d'attente unique regroupant toutes les candidatures (élèves et professeurs) en attente, avec un filtre par type. Pour chaque candidature : voir le détail, accepter ou refuser. Accepter une candidature élève crée son compte immédiatement. Accepter une candidature professeur ne fait que la faire passer à l'étape suivante (voir Partie 1, point 3) — le compte n'est pas encore créé.
- **إسناد المؤطرين** : liste des مؤطرين avec le nombre de professeurs assignés à chacun. Bouton pour ajouter un nouveau مؤطر (crée son compte immédiatement) et pour gérer, pour chaque مؤطر, la liste des professeurs qu'il doit suivre (cases à cocher).

**Catégorie « الحصص والجدولة » (Séances et planification)**
- **استثناءات الحصص** : les séances sont créées automatiquement à partir de l'horaire de chaque groupe (voir Partie 3, workflow créneau → groupe → séance) ; cette page sert uniquement à gérer les exceptions — annuler une séance précise ou la reporter à une autre date/heure (absence du professeur, jour férié, etc.).
- **التقويم الأسبوعي** : vue calendrier semaine par semaine de toutes les séances (passées, prévues, annulées), navigable et filtrable par professeur. Uniquement pour consulter, aucune action possible ici.
- **المجموعات** : liste des groupes (« halqas »), avec filtre par statut/professeur/créneau. Création d'un nouveau groupe (nom, professeur, créneau — obligatoire, car c'est lui qui détermine l'horaire des séances générées automatiquement —, type individuel/collectif, capacité, lien de réunion en ligne). Fiche détail d'un groupe : liste des élèves avec possibilité de transférer un élève vers un autre groupe ou de le retirer, et d'en ajouter un nouveau.
- **الحلقات** : gestion des créneaux horaires-types (jusqu'à 2 jours/heures par semaine, public visé par âge et sexe, type d'enseignement, وrécitation حفص/ورش). Ajout, modification, activation/désactivation. **Important : modifier l'horaire d'un créneau régénère automatiquement toutes les séances futures de tous les groupes qui l'utilisent.**
- **طلبات تعديل الأوقات المتاحة للتدريس** : les professeurs ne peuvent pas changer eux-mêmes leur grille de disponibilité — ils soumettent une demande, que le مدير accepte (applique immédiatement) ou refuse ici.

**Catégorie « الماليات » (Finances)**
- **المدفوعات** : liste de tous les paiements envoyés par les familles (avec la capture d'écran de preuve), à accepter ou refuser.
- **متابعة مدفوعات الطلاب** : vue plus pratique, groupe par groupe puis élève par élève, avec une pastille verte/rouge par mois pour voir d'un coup d'œil qui a payé ou non depuis son inscription. Cliquer sur une pastille ouvre directement un mini-formulaire pour créer/modifier ce paiement (voir Partie 1, point 8 sur la coexistence de ces deux pages).
- **أنواع الاشتراك** : gestion des formules d'abonnement proposées aux familles (prix, libellé, public visé), avec activation/désactivation.
- **شبكة رواتب المعلمين** : la grille officielle qui définit combien un professeur est payé par élève actif et par mois, selon le type de groupe (individuel/collectif) et la tranche d'âge (enfant/adulte). Seuls les montants sont modifiables (la structure de la grille est fixe).

**Catégorie « التقييم والمتابعة » (Évaluation et suivi)**
- **معايير تقييم المعلمين** : gestion des critères qui apparaissent dans le formulaire que le مؤطر remplit pour noter un professeur (ajout, modification, activation/désactivation, suppression si jamais utilisé).
- **التقييمات** : vue centralisée en deux colonnes — les notes données par les professeurs à leurs élèves séance par séance, et les évaluations données par les مؤطرين à leurs professeurs — avec filtres, purement pour consulter.
- **الترتيب الشهري للمعلمين** : classement des professeurs par note moyenne du mois (jamais visible par les professeurs eux-mêmes), avec un champ pour laisser un commentaire libre par professeur et par mois.
- **تقييم الطلاب** : consultation des bilans mensuels rédigés par les professeurs pour chacun de leurs élèves (mémorisation du mois, révision du mois, comportement) — en lecture seule pour le مدير, la rédaction est réservée au professeur.

**Catégorie « حقيبة المدير » (Le dossier du directeur)**
- **ميثاق التدريس** : rédaction/modification complète de la charte remise aux professeurs (règles, sanctions).
- **البرنامج العام** : rédaction/modification du programme pédagogique général, dans une version pour enfants et une version pour adultes.

**Hors catégorie**
- **حسابي** : changer son propre email ou son propre mot de passe.

---

## 2.2 — مشرف (Superviseur général de la plateforme)

Le مشرف voit presque tout ce que voit le مدير (mêmes pages, sidebar organisée en catégories similaires), mais avec des droits très différents selon la page — voir la synthèse au point 4 de la Partie 1. Ci-dessous, seules les différences par rapport au مدير sont détaillées ; tout ce qui n'est pas mentionné fonctionne à l'identique en lecture seule.

- **نظرة عامة** (équivalent du tableau de bord) : 4 chiffres clés + des raccourcis de consultation rapide vers toutes les autres pages du مدير.
- **الطلاب / المعلمون** : mêmes listes, mais fiches détail en lecture seule (pas de suspension/archivage, pas de changement d'email, disponibilités non modifiables). La majoration mensuelle d'un professeur est visible mais non modifiable.
- **طلبات التسجيل** : consultation uniquement (pas de bouton accepter/refuser) — ces décisions restent réservées au مدير, sauf pour l'étape finale des professeurs (voir ci-dessous).
- **طلبات الأساتذة** : **la seule vraie décision du مشرف sur toute la plateforme.** Liste des candidatures de professeurs déjà pré-validées par le مدير, en attente de l'accord final. Accepter ici crée réellement le compte du professeur ; refuser arrête le dossier.
- **إسناد المؤطرين** : consultation uniquement de qui supervise qui (pas d'ajout de مؤطر, pas de modification des assignations).
- **استثناءات الحصص / المجموعات / الحلقات / طلبات تعديل الأوقات** : consultation uniquement, aucun bouton d'action.
- **الاستحقاقات وشبكة التعرفات** : version lecture seule de la page rémunération du مدير (le مشرف ne peut pas modifier les tarifs ni les majorations).
- **تقارير المؤطرين** (= classement mensuel des professeurs) : consultation uniquement, pas de champ de commentaire.
- **تقييم الطلاب** : consultation uniquement des bilans mensuels.
- **ميثاق التدريس / البرنامج العام** : édition complète, comme le مدير.
- **شعار المنصة** : page exclusive au مشرف — upload du logo affiché sur toute la plateforme.
- **الإعدادات** : changer son propre mot de passe.

---

## 2.3 — مؤطر (Encadrant pédagogique des professeurs)

Le مؤطر ne voit et ne gère que les professeurs qui lui ont été assignés par le مدير.

**لوحة التحكم** (page d'accueil) : la page la plus riche du rôle.
- Un bandeau en haut montre la séance en cours en ce moment même (s'il y en a une), ou sinon la toute prochaine séance à venir, avec le nom du groupe, du professeur, ses coordonnées cliquables, et le lien de la réunion en ligne.
- Un bandeau d'alerte apparaît s'il existe des séances passées jamais évaluées, avec un raccourci pour y aller directement.
- Deux façons de voir ses séances : soit toutes mélangées par ordre chronologique (aujourd'hui / passées / à venir), soit regroupées professeur par professeur.
- Filtres disponibles : par professeur, par groupe, par plage de dates.

**ملفي الشخصي** : ses informations, un résumé (nombre de professeurs assignés, nombre d'évaluations en attente), la liste de ses professeurs assignés avec leur note moyenne du mois, et une section pour contacter directement le(s) مدير(s) par email/WhatsApp.

**الترتيب الشهري للمعلمين** : classement de SES professeurs assignés uniquement (contrairement au مدير/مشرف qui voient tous les professeurs), avec un champ de commentaire libre modifiable par professeur et par mois.

**ميثاق التدريس** et **البرنامج العام** : consultation uniquement (ces pages sont éditables uniquement par le مدير et le مشرف).

**تقييم الطلاب** : consultation uniquement des bilans mensuels des élèves de ses professeurs (jamais de rédaction, réservée au professeur).

**Détail d'une séance** (accessible en cliquant depuis le tableau de bord, pas dans le menu) : toutes les présences et notes saisies par le professeur pour cette séance, en lecture seule. Si la séance est terminée mais pas encore évaluée par le مؤطر, un bouton permet d'ouvrir le formulaire d'évaluation du professeur (voir Partie 3, workflow d'évaluation).

---

## 2.4 — أستاذ (Professeur)

La sidebar du professeur est une liste simple (pas de catégories), avec 9 entrées environ.

- **لوحة التحكم** : accueil avec 3 compteurs (mes groupes, total élèves, dernières séances), un bandeau qui rappelle d'accepter le ميثاق التدريس tant que ce n'est pas fait, la prochaine séance à venir, et les 5 dernières séances.
- **مجموعاتي** : liste de ses groupes, avec pour chacun le nombre d'élèves et la liste de leurs noms. Clic → détail du groupe.
- **سجل الحصص** : historique complet de ses séances, organisé en aujourd'hui/passées/à venir, avec un bloc spécial mis en avant pour les séances en retard (jamais soumises).
- **تقييماتي** : historique de toutes ses évaluations déjà envoyées, regroupées par élève, avec filtres par élève/groupe/date.
- **جدولي** : son emploi du temps sous forme de grille jours × heures, en lecture seule.
- **البيانات الشهرية للطلاب** : pour chaque élève de ses groupes, rédaction (ou consultation) du bilan mensuel — ce qui a été mémorisé et révisé dans le mois (pré-rempli automatiquement à partir des séances, modifiable), plus des remarques de comportement libres. **Modifiable jusqu'à la fin du mois suivant le mois concerné, puis verrouillé définitivement.**
- **الأوقات المتاحة للتدريس** : le professeur propose sa grille de disponibilité hebdomadaire, mais elle ne devient active qu'après validation du مدير. Une seule demande en attente possible à la fois.
- **ملفي الشخصي** : ses informations (téléphone modifiable, reste en lecture seule), changement de mot de passe, coordonnées de son مؤطر et du/des مدير(s) pour les contacter directement.
- **راتبي** : voir Partie 3, workflow rémunération — il ne voit QUE le calcul automatique de base, jamais la majoration éventuelle.
- **حقيبة الأستاذ** : page d'accès rapide vers le ميثاق التدريس (à lire et accepter — accusé de lecture non bloquant, le professeur garde accès à tout le reste même sans avoir coché) et le البرنامج العام (lecture seule, filtré automatiquement selon qu'il enseigne à des enfants, des adultes, ou les deux).

**Remplir une séance** (feuille de présence et d'évaluation, accessible depuis سجل الحصص) : voir en détail le workflow n°4 de la Partie 3.

---

## 2.5 — طالب (Élève)

La sidebar de l'élève est une liste simple de 6 entrées.

- **لوحة التحكم** : accueil avec un anneau de progression (nombre de hizb du Coran mémorisés sur 60), un rappel de ce qui a été demandé lors de la dernière séance (à mémoriser/réviser pour la prochaine fois), la prochaine séance prévue, et ses 3 dernières évaluations.
- **حصصي وتقييماتي** : historique complet de toutes ses séances passées (avec toutes les notes et remarques du professeur) et aperçu de ses prochaines séances.
- **تقدمي في الحفظ** : le détail complet de sa progression — l'anneau des hizb mémorisés, la progression sourate par sourate (quelles parties de chaque sourate sont acquises), et un historique séance par séance de toute sa mémorisation.
- **ملفي الشخصي** : ses informations (téléphone modifiable, email non modifiable par lui-même), changement de mot de passe, la liste de son ou ses groupe(s) actuel(s) avec le contact de son/ses professeur(s), l'historique de ses groupes précédents, et une section pour contacter directement le(s) مدير(s).
- **مدفوعاتي** : formulaire pour envoyer la preuve d'un paiement mensuel (montant, mois concerné, capture d'écran), et l'historique de tous ses paiements avec leur statut (accepté / refusé / en attente de vérification).
- **البرنامج العام** : le programme pédagogique général, filtré automatiquement selon son âge (moins de 18 ans → version enfants, 18 ans et plus → version adultes ; si l'âge est inconnu, les deux versions sont montrées par prudence).

**Ce que l'élève ne peut PAS faire** : voir son bilan mensuel (voir Partie 1, point 7), modifier son propre paiement une fois envoyé, changer son email lui-même.

---

# PARTIE 3 — Les grands parcours de bout en bout

## 3.1 — De la candidature à la création du compte : élève

1. Un futur élève (ou son parent) remplit le formulaire public d'inscription en ligne.
2. Le مدير reçoit automatiquement une notification sur Telegram avec un lien direct vers le dossier.
3. Le مدير examine le dossier dans « طلبات التسجيل » et clique **قبول** ou **رفض**.
4. Si accepté : le compte élève est créé **immédiatement**, un mot de passe temporaire est généré. Le système tente d'envoyer un email avec ce mot de passe, mais le مدير le voit aussi affiché à l'écran et doit prévoir de le transmettre lui-même à la famille en cas de doute sur la réception de l'email.
5. L'élève peut alors se connecter avec son email et ce mot de passe temporaire.

## 3.2 — De la candidature à la création du compte : professeur (en deux étapes)

1. Un futur professeur remplit le formulaire public d'inscription (dossier plus complet : parcours, préférences, infos bancaires, enregistrement audio de récitation).
2. Le مدير reçoit une notification Telegram, examine le dossier.
3. Le مدير donne un **premier accord** (« قبول أولي »). **Aucun compte n'existe encore à ce stade.** Le dossier disparaît de la liste du مدير et apparaît dans une liste dédiée chez le مشرف.
4. Le **مشرف** examine à son tour le dossier et donne l'**accord final**. C'est à ce moment précis que le compte professeur est réellement créé, avec un mot de passe temporaire (même principe que pour l'élève : email tenté + mot de passe affiché au مشرف).
5. Si le مدير ou le مشرف rejette à sa propre étape, le processus s'arrête (aucun compte créé).

## 3.3 — Créneau → Groupe → Séances : dans quel ordre travailler

1. **D'abord créer une « حلقة » / créneau** (Gestion des séances → الحلقات) : c'est un modèle d'horaire hebdomadaire (jusqu'à 2 jours par semaine), avec un public cible (âge, sexe) et un type d'enseignement.
2. **Ensuite créer un groupe** (المجموعات) en lui assignant ce créneau (obligatoire) et, si souhaité dès le départ, un professeur.
3. **Les séances sont alors générées automatiquement**, chaque semaine, sur un horizon glissant d'environ 8 semaines à l'avance — il n'y a rien à créer à la main. Le système prolonge cet horizon à chaque fois qu'un admin consulte les pages séances/calendrier.
4. Si on annule ou reporte une séance précise, elle ne sera jamais recréée automatiquement à la même date (le système ne revient jamais en arrière).
5. **Si on change l'horaire d'un créneau, ou le créneau d'un groupe**, toutes les séances futures pas encore données sont automatiquement supprimées et régénérées avec le nouvel horaire — les séances déjà données restent intactes dans l'historique.

## 3.4 — Comment le professeur évalue une séance (règles de blocage)

1. Le professeur ne peut remplir la feuille de présence/évaluation **qu'après l'heure de fin réelle** de la séance (calculée à partir de l'horaire du créneau) — impossible de la remplir en avance, même de quelques minutes.
2. Pour chaque élève présent, il doit obligatoirement remplir : la mémorisation (sourate + versets), la révision (sourate + versets), et 4 notes sur 20 (mémorisation, révision, récitation, assiduité/comportement), plus deux consignes obligatoires pour la prochaine séance (à mémoriser / à réviser). Un élève absent ne nécessite aucune de ces informations.
3. **Passé un délai de 24 heures depuis le DÉBUT de la séance**, si elle n'a pas été (entièrement) remplie, elle reste définitivement bloquée — impossible de la compléter ou de la corriger après coup, même pour un administrateur.
4. **Une fois soumise, la feuille est verrouillée définitivement** — le professeur ne peut plus rien modifier, même s'il reste du temps dans la fenêtre des 24 heures.

## 3.5 — Comment le مؤطر évalue un professeur (règles de blocage)

1. Même principe que pour le professeur : le مؤطر ne peut évaluer une séance qu'**après son heure de fin réelle**.
2. Il remplit un formulaire avec une note (de « منعدم » à « حسن جدا ») pour chaque critère défini par l'administration, plus un commentaire écrit obligatoire.
3. Contrairement au professeur, **le مؤطر peut modifier son évaluation pendant 24 heures après son premier envoi**. Passé ce délai, elle est verrouillée définitivement (consultable mais plus modifiable, même par un administrateur).
4. Ce classement des professeurs (moyenne des notes du مؤطر) n'est **jamais visible par les professeurs eux-mêmes**.

## 3.6 — Rémunération des professeurs : qui voit quoi

Le calcul de base est automatique : pour chaque groupe du professeur, (nombre d'élèves enfants actifs × tarif enfant) + (nombre d'élèves adultes actifs × tarif adulte), selon une grille tarifaire officielle définie par l'administration (individuel/collectif × enfant/adulte).

En plus de ce calcul de base, le مدير peut ajouter manuellement une **majoration mensuelle** personnelle par professeur (une sorte de prime discrétionnaire).

| Qui | Calcul de base | Majoration mensuelle |
|---|---|---|
| مدير | Voit et modifie | Voit et modifie |
| مشرف | Voit (lecture seule) | Voit (lecture seule) |
| مؤطر | Voit (dans le classement de ses profs) | Voit (dans le classement de ses profs) |
| **أستاذ (le professeur concerné)** | **Voit uniquement ceci** | **Ne voit JAMAIS cette information — ni le montant, ni son existence** |

C'est un choix de confidentialité volontaire et vérifié à plusieurs endroits du système : la page de rémunération du professeur ne reçoit techniquement même pas cette donnée, elle ne peut donc pas apparaître par erreur, même fondue dans un total.

## 3.7 — Le système de notification Telegram : comment ça marche et comment l'activer

**Ce qui déclenche une notification Telegram vers le مدير** :
- Une nouvelle candidature (élève ou professeur) est soumise — avec un lien direct vers le dossier.
- Un utilisateur clique sur « mot de passe oublié » — le مدير reçoit alors le nouveau mot de passe généré, à charge pour lui de le transmettre à la personne concernée.
- Un utilisateur déjà connecté réinitialise lui-même son mot de passe depuis son profil — même principe, le مدير reçoit le nouveau mot de passe.

**Pour activer ce système**, il faut :
1. Créer un bot Telegram (via le compte Telegram officiel « BotFather ») pour obtenir un identifiant technique de bot.
2. Récupérer l'identifiant de conversation Telegram (« chat ID ») du compte Telegram du مدير qui doit recevoir les messages.
3. Renseigner ces deux informations dans la configuration du serveur.

**Si l'une des deux informations n'est pas renseignée, les notifications sont silencieusement désactivées** — aucune erreur n'apparaît nulle part, le système continue de fonctionner normalement, simplement sans notification. C'est donc une fonctionnalité optionnelle qu'il faut activer volontairement, mais son absence ne bloque jamais l'utilisation de la plateforme.

---

# PARTIE 4 — Règles importantes à retenir (résumé)

- Un professeur qui rate le délai de 24h pour remplir une séance ne peut PLUS JAMAIS la compléter — ni lui, ni un administrateur.
- Une fois qu'un professeur a soumis une séance, il ne peut plus jamais la modifier (verrouillage immédiat et définitif).
- Un مؤطر a 24h après son premier envoi pour corriger son évaluation d'un professeur, ensuite c'est définitif.
- La majoration de salaire d'un professeur ne lui est jamais montrée, à aucun endroit de la plateforme.
- Le mot de passe oublié passe par Telegram vers le مدير, jamais par email direct à l'utilisateur.
- Une candidature de professeur nécessite DEUX accords (مدير puis مشرف) avant que le compte n'existe ; une candidature d'élève n'en nécessite qu'un seul (مدير).
- Modifier l'horaire d'un créneau ou changer le créneau d'un groupe régénère automatiquement toutes les séances futures non encore données.
- L'élève ne peut actuellement pas consulter son bilan mensuel, malgré son existence côté professeur/administration.
- Le مشرف a de vrais pouvoirs de modification sur 5 zones précises (candidatures profs, charte, programme général, logo, types d'abonnement) — partout ailleurs il est en lecture seule stricte.
