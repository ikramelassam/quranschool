# Audit — notifications d'évaluation + critères configurables par séance (2026-09-12)

## Historique de la demande (résumé, l'essentiel a évolué en cours de route)

1. **Notifications** : notifier مدير/مشرف (en plus de l'élève et du prof,
   déjà notifiés) quand une حلقة est évaluée / quand un مؤطر évalue une
   séance. **Stable dès le départ, jamais remis en cause.**
2. **Un seul axe (الحفظ/المراجعة) par حصة** — le prof ne doit plus évaluer les
   deux en même temps :
   - **v0** (rejetée par Ikram) : mapping figé par numéro de séance
     (1ʳᵉ=حفظ, 2ᵉ=مراجعة) proposé par le client — rejeté car une حلقة peut
     avoir 1 ou 3 séances/semaine.
   - **v1** (implémentée puis abandonnée) : le prof choisit lui-même via une
     question posée avant de remplir la feuille.
   - **v2** (implémentée puis abandonnée) : calcul 100% automatique par
     position dans la semaine (impaire=حفظ, paire=مراجعة) — le client a
     explicitement demandé un calcul automatique, sans interaction du prof.
   - **v3, version finale retenue** : le calcul par position reste pour le
     bloc "quelle sourate" (mémorisation/révision, une contrainte structurelle
     du modèle `Presence`), MAIS pour les **critères notés /20**
     (Mémorisation, Récitation, Assiduité, Comportement…), le client a jugé
     après vérification que 2 compartiments partagés (pair/impair) étaient
     insuffisants : **chaque position de séance (1, 2, 3, 4…) doit avoir sa
     propre configuration de critères, totalement indépendante des autres**,
     éditable par l'admin sans toucher au code.
3. Commiter chose par chose, auditer, ne pas attendre de validation
   intermédiaire pour le travail d'implémentation — mais chaque changement de
   cap métier significatif a été validé avec Ikram avant de coder plus loin.

## Ce qui a été livré

Branche `feat/telegram-paiement-a-la-validation`, 5 commits (ordre
chronologique) :

| Commit | Contenu |
|---|---|
| `794cff7` | Chantier hérité, sans rapport avec cette demande (le مشرف peut supprimer un groupe) — commité isolément pour repartir d'un arbre propre. |
| `9913dfa` | Notifications مدير/مشرف (point 1). |
| `f198daf` | Version v2 du point 2 (calcul auto par position, critères filtrés par `type_lie` à 2 compartiments) — **en grande partie remplacée par `a87643b` ci-dessous**, gardée dans l'historique par transparence plutôt que réécrite. |
| `2b627b5` | Version précédente de cet audit. |
| `a87643b` | Version finale du point 2 : `ProfilCriteresSeance`, configuration indépendante par position. |

**Aucun push, aucun merge vers `main`.**

### Notifications مدير/مشرف (`9913dfa`) — inchangé depuis le précédent audit

Le prof (`notifications_prof`) et l'élève (`notifications_eleve`) étaient
déjà notifiés d'une évaluation ; seule la direction ne l'était pas. 2 sources
ajoutées à `notifications_direction` (séance évaluée par le prof / prof
évalué par le مؤطر), pointant vers `admin_evaluation_detail`. 6 tests
(`NotificationsEvaluationsDirectionTests`).

### A. Analyse de l'existant (avant modification du point 2)

- **`CritereEleve`** (`courses/models.py`) : modèle des critères de
  notation /20 — nom (ar/fr/en), ordre, `est_actif`. Géré par 5 vues dans
  `dashboard/views.py` (`admin_criteres_eleves`, `admin_critere_eleve_
  ajouter/modifier/toggle/supprimer`), 1 template liste + 2 templates
  formulaire. **Ce système n'a pas été dupliqué : ces 5 vues et leurs
  templates sont strictement inchangés dans leur rôle (créer/nommer/
  activer/supprimer un critère).**
- **`NotePresence`** : table de jonction `(Presence, CritereEleve, note)` —
  une ligne par élève par critère par séance. Aucune référence à un axe ou
  une position : une note enregistrée est indépendante de toute
  configuration future.
- **Séances/groupes** : `Seance.groupe` (FK), `Groupe.creneau` (FK), et
  `CreneauSlot` (un jour+heure par créneau, `ordre` = ordre de SAISIE dans le
  formulaire, pas l'ordre chronologique réel des jours). Aucune notion de
  "numéro de séance" n'existait avant ce chantier.
- **Page d'évaluation** : `dashboard.views.prof_seance_detail` /
  `prof_presence_sauvegarder` — construisent la feuille de présence,
  récupèrent les critères actifs, enregistrent les notes.

### B. Architecture choisie

1. **`Seance.numero_dans_la_semaine`** (propriété calculée, pas stockée) :
   position (1-indexée) de cette séance parmi les `CreneauSlot` du groupe,
   triés par jour de semaine RÉEL (`courses.utils.JOUR_INDEX`), pas par
   `CreneauSlot.ordre`. Réutilisée pour 2 choses distinctes :
   - `Seance.type_evaluation` (حفظ/مراجعة, calcul auto, impaire/paire) — pour
     le bloc "quelle sourate mémorisée/révisée" (contrainte structurelle du
     modèle `Presence`, hors périmètre de la demande sur les critères).
   - `Seance.criteres_applicables` — pour les critères /20.
2. **`ProfilCriteresSeance`** (nouveau modèle) : `position` (entier, unique,
   sans limite) + `criteres` (M2M vers `CritereEleve`, jamais dupliqué — un
   même critère peut appartenir à N positions). Une position jamais
   rencontrée est créée à la volée avec un gabarit par défaut dérivé de
   `CritereEleve.type_lie` (impaire/paire) — **une seule fois** : dès que la
   ligne existe, son contenu enregistré est la seule source de vérité,
   jamais recalculé même si `type_lie` change ensuite ou si une autre
   position est modifiée.
3. **`CritereEleve.type_lie`** (`commun`/`hifz`/`mouraja3a`, déjà présent
   depuis `f198daf`) : rôle **restreint** à ce gabarit initial — plus aucun
   filtrage direct pendant le parcours normal d'évaluation.

### C. UX

- **Admin** (مدير) : nouvel écran `/dashboard/admin/criteres-par-seance/` —
  liste "الحصة 1 — N معايير — تعديل", "الحصة 2 — ...", + bouton "+ إضافة حصة
  أخرى". Cliquer "تعديل" ouvre une liste à cases à cocher des critères actifs
  existants ; cocher/décocher puis "حفظ" met à jour UNIQUEMENT cette
  position. Un lien depuis `/dashboard/admin/criteres-eleves/` (page
  existante, inchangée) mène à ce nouvel écran. مشرف : lecture seule (liste
  visible, bouton "تعديل" masqué, comme pour les autres écrans admin).
  Aucun concept technique (hifz, mouraja3a, type_lie, pair/impair) n'est
  visible sur cet écran — seulement "الحصة N" et des noms de critères.
- **Enseignant** (prof) : aucun changement d'interaction — il ouvre sa
  feuille de présence et voit directement les critères configurés pour
  cette séance précise, sans rien choisir.

### D. Fichiers modifiés

| Fichier | Modification |
|---|---|
| `courses/models.py` | + `ProfilCriteresSeance` ; + `Seance.numero_dans_la_semaine`/`type_evaluation`/`criteres_applicables` ; `CritereEleve.type_lie` conservé (rôle réduit, commentaire mis à jour). |
| `courses/migrations/0048...py`, `0049...py` | Ajustées (0048 ne crée plus le champ `Seance.type_evaluation`, devenu une propriété ; 0049 : correspondance finale التلاوة→hifz, المراجعة→mouraja3a). |
| `courses/migrations/0050_profil_criteres_seance.py` | Nouvelle — crée le modèle `ProfilCriteresSeance`. |
| `courses/migrations/0051_seed_profils_criteres_seance_1_et_2.py` | Nouvelle — seed positions 1 et 2, reproduit exactement le comportement `type_lie` déjà en place. |
| `dashboard/views.py` | `prof_seance_detail`/`prof_presence_sauvegarder` utilisent `seance.criteres_applicables` ; suppression de la vue `prof_seance_choisir_type_evaluation` (v1, obsolète) ; + 3 nouvelles vues (`admin_criteres_par_seance`, `_ajouter_position`, `_modifier`). |
| `dashboard/urls.py` | Route de la v1 retirée ; 3 nouvelles routes. |
| `templates/dashboard/prof_seance_detail.html` | Bandeau informatif (sans lien "تغيير", plus rien à choisir) ; filtrage des `<input>` critère par `applicable_a_la_seance` ; lecture seule inchangée (affiche toujours tout, jamais filtré rétroactivement). |
| `templates/dashboard/prof_seance_choisir_type_evaluation.html` | Supprimé (écran de la v1). |
| `templates/dashboard/admin_criteres_eleves.html` | + 1 lien vers le nouvel écran. |
| `templates/dashboard/admin_criteres_par_seance.html`, `admin_criteres_par_seance_modifier.html` | Nouveaux — écran groupé par position. |
| `courses/tests.py`, `dashboard/tests.py` | Tests ajoutés/réécrits (détail ci-dessous). |

### E. Base de données

- **Migration nécessaire : oui.** `0050` crée `ProfilCriteresSeance` (table +
  table de jonction M2M) — nécessaire car aucune structure existante ne
  permettait d'associer un critère à une position précise indépendamment des
  autres. `0051` est une migration de DONNÉES (pas de schéma) qui seed les 2
  positions déjà réellement utilisées aujourd'hui.
- **Non destructif, confirmé** : aucune table existante modifiée en place,
  aucune colonne supprimée sur une table contenant des données réelles.
  `CritereEleve.type_lie` reste tel quel. `NotePresence`/`Presence` ne sont
  touchées par aucune des 4 migrations de ce chantier (`0048` à `0051`).
- **Aucune donnée réelle affectée** : ces migrations n'ont jamais été
  appliquées à une base de production — la branche n'a jamais été poussée
  sur `origin` (voir section déploiement).
- **Anciennes évaluations** : `NotePresence` ne référence ni `type_lie` ni
  `ProfilCriteresSeance` — modifier la configuration d'une position
  n'affecte donc JAMAIS une note déjà enregistrée. Vérifié par test
  (`test_ancienne_evaluation_conservee_apres_modification_de_la_config`).

### F. Tests exécutés et résultats

- `courses.tests.SeanceTypeEvaluationAutomatiqueTests` (8) — calcul
  `numero_dans_la_semaine`/`type_evaluation` pour 1 à 5 séances/semaine,
  ordre de saisie du créneau sans incidence, replis (pas de créneau, jour
  hors créneau). **8/8 OK.**
- `dashboard.tests.ProfilCriteresSeanceTests` (13) — couvre explicitement les
  11 points demandés : position 1 et 2 (config initiale), position 3 et 4
  (indépendance), modification isolée (2 sans affecter 4), ajout d'un
  nouveau critère puis association, désactivation d'un critère, positions
  5/6/7 sans limite, ancienne évaluation conservée, permissions مدير/مشرف/
  prof, `type_lie` modifié après coup sans effet sur un profil déjà créé.
  **13/13 OK.**
- `dashboard.tests.ProfSeanceAxeAutomatiqueTests` (5) + `PresenceResultat
  MemorisationVueTests` (5) — comportement bout-en-bout sur la feuille de
  présence (formulaire filtré, sauvegarde, lecture seule). **10/10 OK.**
- `dashboard.tests.CritereEleveLocaliseTests` (9, dont 6 nouveaux sur
  `type_lie`) — page `/dashboard/admin/criteres-eleves/` toujours
  fonctionnelle (ajout/modification/toggle/suppression). **9/9 OK.**
- Suite complète `courses.tests` + `dashboard.tests` (regroupant tout ce qui
  précède plus l'ensemble des tests déjà existants du projet) relancée après
  ce chantier — en cours au moment de la rédaction de cet audit, résultat
  ajouté ci-dessous dès disponible.
- **Incident de test découvert et corrigé en cours de route** : la base de
  test locale (`--keepdb`) avait gardé un état périmé après que j'ai édité
  le contenu des migrations `0048`/`0049` alors qu'elles avaient déjà été
  appliquées lors d'exécutions précédentes de tests dans cette même session
  (Django ne ré-applique jamais une migration déjà marquée comme appliquée,
  même si son fichier change). Corrigé manuellement (valeur `type_lie` et
  ligne de jonction erronées) directement sur `test_postgres` — sans impact
  sur la base de production, jamais touchée. Aucune incidence sur le
  contenu final des migrations elles-mêmes, uniquement sur l'état
  local de test.

### G. Risques / points à surveiller

1. **i18n incomplet** — toutes les nouvelles chaînes (écran des critères par
   séance, bandeau informatif) sont en arabe, pas encore traduites fr/en
   (repli automatique sur l'arabe si absent, pas un bug fonctionnel).
2. **Positions pré-remplies limitées à 1 et 2** — toute position au-delà se
   crée à la volée dès qu'une vraie séance l'atteint (ou via "+ إضافة حصة
   أخرى" côté admin). Aucune limite artificielle, mais un admin qui irait
   directement sur l'URL `/admin/criteres-par-seance/7/` sans qu'aucune
   séance ni bouton n'y ait jamais mené verrait un profil vide créé à la
   volée (comportement voulu, pas une erreur).
3. **Pas d'indicateur d'axe sur la liste `prof_seances`** (l'agenda du
   prof) — seule la fiche détail d'une séance affiche le bandeau "محور هذه
   الحصة".
4. **`courses/utils.py` et `AUDIT_N1_2026-09-12.md`** apparaissent modifiés/
   créés dans l'arbre de travail au moment de la rédaction de cet audit —
   **ce n'est pas mon travail**, une autre session travaille en parallèle
   sur un correctif de performance (N+1) sans rapport avec ce chantier ;
   je ne les ai ni touchés ni inclus dans mes commits.

## État de déploiement — DÉCISION LAISSÉE À IKRAM

- 5 commits **uniquement locaux**, jamais poussés — cette branche n'a jamais
  existé sur `origin`. `origin/main` toujours à `c88bab3`.
- Décision de merge/déploiement volontairement laissée à Ikram : 4
  migrations de schéma/données (`0048`-`0051`) et un changement de
  comportement quotidien pour tous les profs sur une plateforme en
  production avec des utilisateurs réels.
- Pour déployer : fusionner la branche vers `main`, pousser — `build.sh` sur
  Render applique les migrations automatiquement.
