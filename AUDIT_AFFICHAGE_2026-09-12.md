# Audit affichage — 2026-09-12

Audit en 2 passes sur les bugs d'affichage (valeurs mal affichées ou perdues
à l'écran) : (1) un grep exhaustif ciblé sur les patterns déjà connus dans ce
projet, puis (2) une relecture manuelle, template par template, des 232
fichiers `templates/**/*.html` du projet (4 lots parallèles), dans la
continuité de deux bugs déjà corrigés :
1. Prix d'abonnement vides dans « تعديل الاشتراك » (virgule décimale locale +
   `<input type="number">`, corrigé le 2026-09-10 par des filtres `|unlocalize`).
2. Chantier en cours (autre session, non commité au moment de cet audit) :
   critères d'évaluation configurables par position de séance / séances mixtes
   حفظ+مراجعة.

**Tous les problèmes listés ci-dessous ont été corrigés** (voir « Correctifs
appliqués » en fin de fichier). L'audit initial était en lecture seule ; les
correctifs ont été appliqués dans une étape séparée, à la demande d'Ikram.

---

## 🔴 Critique

### `templates/examens/_form_correction.html:9-10` — note de correction manuelle vidée par la virgule décimale arabe/française

```html
<input type="number" name="points_obtenus" min="0" max="{{ reponse.question.points }}" step="0.5"
       value="{{ reponse.points_obtenus|default_if_none:'' }}" class="form-control" style="width:100px;" required>
```

`Reponse.points_obtenus` (`examens/models.py:285`) est un
`DecimalField(max_digits=5, decimal_places=2)`. Or **la langue par défaut du
site est l'arabe** (`core/settings.py:221`, imposée à tout visiteur sans
cookie de langue par `LangueParDefautArabeMiddleware`), et le format
Arabic de Django utilise **la virgule comme séparateur décimal**
(`django.conf.locale.ar.formats.DECIMAL_SEPARATOR = ','`, vérifié en
exécution) — exactement comme le français.

**Scénario concret** : un prof corrige une réponse texte/audio/vidéo et met
`4.5` (accepté, `step="0.5"`). En base c'est stocké `4.50`. S'il rouvre
`copie_correction.html` pour ajuster cette note (ou si la page est
re-rendue après une autre correction sur la même copie), Django rend
`{{ reponse.points_obtenus }}` → `"4,50"` (locale arabe, par défaut, sans
rien configurer). `<input type="number" value="4,50">` est une valeur
invalide pour ce type de champ → **le navigateur vide silencieusement le
champ à l'affichage**. Le prof voit un champ vide au lieu de la note déjà
donnée, exactement le même bug que celui déjà corrigé sur les prix
d'abonnement (`project_bug_2026-09-10_input_number_virgule_locale.md`).

C'est un cas manqué par le correctif du 2026-09-10 : celui-ci a couvert les
templates de prix/tarifs/majoration (5 fichiers), mais pas ceux de l'app
`examens`, qui contient elle aussi un `DecimalField` rendu dans un
`<input type="number">`.

**Fix** : `value="{{ reponse.points_obtenus|default_if_none:''|unlocalize }}"`
(charger `{% load l10n %}` en tête de fichier si absent).

---

## 🟡 Mineur / préventif

### Numéro de téléphone affiché sans isolation, glué à d'autres infos dans le même flux de texte

Le correctif du 2026-09-09 (`project_etat_2026-09-09_copie_email_texte_voisin.md`)
a ajouté une classe `.email-copiable` (`static/css/tokens.css:71`,
`user-select:all` + `unicode-bidi:isolate` + `direction:ltr`) sur ~24
gabarits, mais **uniquement pour les adresses e-mail**. Le numéro de
téléphone est un contenu de la même nature (chaîne latine/numérique
insérée dans un flux de texte arabe RTL) et souffre en théorie du même
risque de sélection/bidi, mais reste non traité partout où il est **glué
dans le même nœud de texte** que d'autres éléments plutôt qu'isolé dans son
propre `<span>` de fiche :

- `templates/dashboard/refuser_inscription.html:39` — `📞 {{ telephone_personne }}` dans un `<span class="rf-entete-tel">` accolé au nom (`rf-entete-nom`) sur la même ligne d'en-tête.
- `templates/dashboard/_carte_demande_non_satisfaite.html:23-25` — `📞 {{ d.telephone_contact }} — ✉️ {{ d.email_contact }}` dans le **même** `<div>`/nœud de texte, séparés seulement par un tiret littéral, le tout dans un `<a>` cliquable (toute la carte navigue au clic).

Impact plus faible que le bug e-mail déjà corrigé (ce ne sont pas les
écrans de fiche principaux où l'e-mail a été isolé), mais le même geste de
copie (double-clic / glisser-sélection) sur ces cartes peut encore
embarquer l'emoji, le tiret ou l'adresse voisine.

**Fix appliqué** : nouvelle classe `.tel-copiable` (identique à
`.email-copiable`) ajoutée dans `static/css/tokens.css`, posée sur ces deux
emplacements ainsi que sur `admin_demande_non_satisfaite_detail.html` (trouvé
lors de la relecture manuelle, § ci-dessous) et 7 emplacements supplémentaires
trouvés dans la relecture manuelle (`prof_profil.html`, `superviseur_profil.html`,
`eleve_profil.html`, `eleve_prof_detail.html`, `mshrif_inscription_prof_detail.html`).

---

## 🔴 Critique (trouvé lors de la relecture manuelle template-par-template)

### Notes des critères dynamiques d'évaluation invisibles sur TOUTES les pages d'historique — seuls les 4 anciens champs fixes (jamais plus écrits depuis le 2026-08-04) étaient testés

**Fichiers concernés (corrigés) :**
- `templates/dashboard/eleve_seance_detail.html`
- `templates/dashboard/eleve_seances.html`
- `templates/dashboard/eleve_progression.html` (×2 blocs)
- `templates/dashboard/superviseur_seance_detail.html`
- `templates/dashboard/prof_evaluations.html` (×2 blocs + moyennes par critère)
- `templates/dashboard/admin_evaluation_detail.html`
- `templates/dashboard/admin_evaluations.html`

**Description :** `courses/models.py:1189-1208` et `:1246-1252` documentent
explicitement que `note_hifz`/`note_muraja3a`/`note_tilawa`/`note_mouwazaba`
sont gelés (« conservés en lecture seule pour l'historique, jamais plus
écrits ») depuis que `NotePresence` (relation `Presence.notes_criteres`) les a
remplacés, Point 7 de la Tâche du 2026-08-04. Ces 7 templates conditionnaient
encore tout leur bloc de notation sur `{% if presence.note_hifz %}` (toujours
`None` depuis plus d'un mois pour toute nouvelle Presence), et certaines vues
(`eleve_seances`, `eleve_seance_detail`, `superviseur_seance_detail`,
`admin_evaluations`, `admin_evaluation_detail`) ne préchargeaient même pas
`notes_criteres`.

**Scénario concret :** un élève évalué par son prof via `prof_seance_detail.html`
(seule page qui affichait correctement les critères dynamiques) ouvre ensuite
« حصصي وتقييماتي » ou le détail de sa séance : la section notation était
silencieusement absente, alors que le prof l'avait bien noté. Idem pour le
مؤطر, le مدير/مشرف, et le prof consultant son propre historique
(`prof_evaluations.html`, où les « moyennes » par critère étaient aussi
calculées sur les champs gelés → toujours vides).

**Fix appliqué :** dans chaque template, remplacement du bloc conditionné sur
`note_hifz` par une boucle sur `presence.notes_criteres.all` (ou `item.notes_criteres`/
`h.notes_criteres` selon la structure de la vue), sur le modèle de
`prof_seance_detail.html`. Ajout de `prefetch_related('notes_criteres__critere')`
dans les 7 vues concernées (`dashboard/views.py`) pour éviter un N+1. Dans
`prof_evaluations`, les 4 moyennes fixes (`moyenne_hifz`/...) ont été
remplacées par un calcul dynamique `moyennes_criteres` (regroupement par
`critere_id`, moyenne par critère réellement noté, quel que soit son nombre
ou son nom).

### `templates/dashboard/_ring_hizb.html:7` — l'anneau de progression du hifz affichait toujours 100%, même bug de virgule décimale que les prix

`stroke-dashoffset="{{ ring_dashoffset }}"` reçoit un `float` calculé par
`courses/utils.py:972` (`round(452.39*(1-n/60), 1)`), non protégé par
`|unlocalize`. En locale arabe (virgule décimale), la plupart des valeurs
s'affichaient `"444,8"` → attribut SVG invalide → le navigateur ignore
l'offset → l'anneau de progression (accueil élève + page « تقدمي في الحفظ »)
apparaissait **toujours plein**, quel que soit le nombre réel de hizb
mémorisés. Même mécanisme que le bug des prix, jamais couvert car ce n'est
pas un `<input>`. **Fix appliqué** : `{% load l10n %}` + `{{ ring_dashoffset|unlocalize }}`.

---

## Vérifications effectuées sans anomalie trouvée

- **Tous les `<input type="number">` du projet** (37 fichiers, ~40
  occurrences) passés en revue un par un : les seuls champs pré-remplis
  depuis un `DecimalField`/`FloatField` (prix abonnement, tarifs
  rémunération, majoration prof, montant paiement) ont bien `|unlocalize`
  depuis le correctif du 2026-09-10. Tous les autres champs pré-remplis
  (`ordre`, `age_min`/`age_max`, `capacite_max`, `duree_retention_jours`,
  `marge_avant/apres_minutes`, `points` du QCM, `options.count|add:1`…) sont
  des `IntegerField`/`PositiveSmallIntegerField` — insensibles à la virgule
  décimale locale (`USE_THOUSAND_SEPARATOR` n'est pas activé dans
  `settings.py`), donc pas de risque.
- **Tous les `<input type="date">`** (18 occurrences) : soit rendus avec un
  filtre explicite `|date:'Y-m-d'` (format ISO forcé, indépendant de la
  langue), soit pré-remplis depuis une chaîne déjà postée
  (`request.POST`/session, jamais reformatée par Django) plutôt que depuis un
  objet `date` Python brut — pas de risque de bug de locale équivalent à
  celui des prix.
- **Critères d'évaluation par position de séance** (diff non commité de
  l'autre session : `courses/models.py`, `dashboard/views.py`,
  `templates/dashboard/admin_criteres_par_seance*.html`,
  `templates/dashboard/admin_groupe_criteres_par_seance*.html`,
  `templates/dashboard/prof_seance_detail.html`) : logique cohérente,
  `bloc_memorisation`/`bloc_revision` pilotent à la fois le bandeau
  informatif et les 2 blocs de saisie (plus jamais désynchronisés comme
  avant la régression corrigée le même jour) ; les cases à cocher de
  personnalisation (`admin_groupe_criteres_par_seance_modifier.html`,
  `admin_criteres_par_seance_modifier.html`) sont pré-remplies depuis un set
  d'IDs cochés calculé côté vue (`c.id in ids_membres`), pas de mismatch de
  casse/accents comme le bug historique آ/ا. Aucun bug d'affichage repéré
  dans ce chantier en cours.
- **Chaînes arabes codées en dur** : balayage heuristique de tous les
  gabarits (110 lignes contenant de l'arabe hors `{% trans %}`) — après
  vérification, toutes sont soit des commentaires HTML/JS/`{% comment %}`,
  soit déjà traduites via l'idiome `_("...")` (raccourci `gettext` importé
  dans le contexte du template, ex. `default:_("— بدون اسم —")`,
  `texte=_('نشط ✅')`), qui est fonctionnellement équivalent à `{% trans %}`.
  Aucune chaîne réellement non traduisible trouvée.

---

## Synthèse

| Sévérité | Nombre | Statut |
|---|---|---|
| 🔴 Critique | 3 (note d'examen vidée, anneau hifz toujours plein, notes d'évaluation invisibles sur 7 pages) | ✅ Tous corrigés |
| 🟠 Moyen | 0 | — |
| 🟡 Mineur | 10 (téléphone non isolé, 10 emplacements au total) | ✅ Tous corrigés |

Deux familles de bugs distinctes, toutes deux issues du même mécanisme
racine (une valeur calculée côté serveur, jamais mise à jour dans le
template après un changement de modèle de données) :
1. **Virgule décimale locale** dans un `<input type="number">` ou un attribut
   SVG (`_form_correction.html`, `_ring_hizb.html`) — même famille que le bug
   des prix d'abonnement du 2026-09-10, non couvert par ce correctif car
   situé dans d'autres apps (`examens`) ou hors d'un `<input>` (SVG).
2. **Champs de notation gelés depuis la migration du 2026-08-04** vers les
   critères dynamiques (`NotePresence`) — 7 templates continuaient de lire
   les 4 anciens champs fixes `note_hifz`/`note_muraja3a`/`note_tilawa`/
   `note_mouwazaba`, qui ne sont plus jamais écrits. C'est très probablement
   le bug « évaluation » d'affichage évoqué par Ikram en tête de conversation,
   distinct du chantier en cours de l'autre session (qui ne touche que la
   configuration des critères par position de séance, pas leur affichage
   historique).

## Correctifs appliqués (2026-09-12)

- `templates/examens/_form_correction.html` : `{% load l10n %}` + `|unlocalize` sur `points_obtenus`.
- `templates/dashboard/_ring_hizb.html` : `{% load l10n %}` + `|unlocalize` sur `ring_dashoffset`.
- `static/css/tokens.css` : nouvelle classe `.tel-copiable` (identique à `.email-copiable`).
- 10 templates avec téléphone/e-mail non isolé → classe `.tel-copiable`/`.email-copiable` ajoutée : `refuser_inscription.html`, `_carte_demande_non_satisfaite.html`, `admin_demande_non_satisfaite_detail.html`, `prof_profil.html` (×2), `superviseur_profil.html` (×2), `eleve_profil.html`, `eleve_prof_detail.html`, `mshrif_inscription_prof_detail.html`.
- 7 templates + 7 vues (`dashboard/views.py`) : migration de l'affichage des notes de `note_hifz`/... (gelés) vers `presence.notes_criteres`/`item.notes_criteres` (dynamique), avec `prefetch_related('notes_criteres__critere')` ajouté à chaque vue concernée pour éviter un N+1 — `eleve_seances`, `eleve_seance_detail`, `eleve_progression` (pas de changement de vue, la donnée `notes_criteres` était déjà construite côté `courses/utils.calculer_progression_eleve`, seul le template était en retard), `superviseur_seance_detail`, `prof_evaluations` (+ recalcul des moyennes par critère dynamique), `admin_evaluation_detail`, `admin_evaluations`.

Aucun fichier du chantier en cours de l'autre session (`admin_criteres_par_seance*.html`, `admin_groupe_criteres_par_seance*.html`, `courses/migrations/0052_*`) n'a été modifié.

## Note hors périmètre (pas un bug d'affichage)

`templates/inscriptions/eleve_choix.html` correspond à une vue qui n'est plus
routée (template mort) alors que `/eleve/formulaire/<type_age>/` reste
accessible et contourne les règles du wizard actuel. Signalé pour
information — aucune action prise, hors du périmètre "affichage" de cet
audit.
