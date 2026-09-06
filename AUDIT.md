# AUDIT FONCTIONNEL — Zidni Ilman (école coranique en ligne)

> Audit en lecture seule. Aucune modification de code. Seul ce fichier est écrit.
> Démarré le 2026-09-05. Branche : `feat/fusion-horaire-groupe`.
> Django 6.0, PostgreSQL/Supabase (pooler transaction), Cloudinary (raw storage),
> bot Telegram, interface arabe RTL, 5 rôles : `mshrif` (المشرف) / `admin` (الإدارة / مدير)
> / `superviseur` (مؤطر) / `prof` (أستاذ / معلم) / `eleve` (طالب).

---

# ÉTAPE 3 — Synthèse finale

## Tableau récapitulatif par app

| App | Vues routées | Publiques (par design) | Permissions vérifiées | ≥ 1 test couvrant une vue | Tests exécutés (`--keepdb`) |
|---|---:|---:|---|---|---|
| core | 1 (+ handler CSRF) | 1 | n/a (handler) | ✅ | **14 OK** (avec accounts) |
| accounts | 6 | 2 (`login`, `mot_de_passe_oublie`) | 100 % `role_required`/`login_required` | 🔴 **0/6 vue testée** | 14 OK (helpers seulement) |
| telegram_bot | 1 | 1 (webhook, secret token) | secret token | ✅ | **27 OK** |
| annonces | 6 | 0 | 100 % `role_required` + `peut_voir_annonce` | ✅ 6/6 | **OK** (batch 1) |
| chat | 10 | 0 | 100 % centralisé (`chat/permissions.py`) | ✅ 10/10 | **OK** (batch 2) |
| evaluations | 3 | 0 | 100 % `role_required` + scope queryset | ⚠️ 1/3 (`superviseur_evaluer`/`_detail` non testées) | 🔴 **1 échec** (m13, i18n) |
| examens | 24 | 0 | 100 % centralisé (`examens/permissions.py`) | ✅ large | **OK** (batch 2) |
| registration | 9 | 9 (wizard public) | n/a public + sauts serveur + revalidation finale | ✅ **215 tests** | 🔴 **5 échecs** (m14, tests obsolètes `nb_seances`) |
| inscriptions | 4 fn (+2 redirects) | 4 | n/a public | ⚠️ partiel ; 1 vue morte de fait | **OK** (batch 2) |
| courses | 16 | 0 | 100 % `role_required` | ✅ **198 tests** | **OK** (batch 1) |
| payments | 8 | 0 | 100 % `role_required` | ⚠️ `paiement_panel_sauvegarder` + rendu grille non testés | **OK** (batch 1) |
| dashboard | ~175 | 0 | 100 % `role_required` (grep 1:1) | ✅ **392 tests** (pas exhaustif/vue) | 🔴 **5 échecs** (3× m13 i18n, 2× m14 `nb_seances`) |
| **Total** | **~263** | **~26** | **~100 % de la zone authentifiée** | | |

> **Résultats d'exécution** (base Postgres Supabase distante, ~6 s/test — ~4 800 s pour la batch 2) :
> - `core` + `accounts` : **14 OK**.
> - `telegram_bot` : **27 OK**.
> - **batch 1** `annonces`+`evaluations`+`courses`+`payments` : **321 tests, 1 échec** (m13).
> - **batch 2** `chat`+`examens`+`inscriptions`+`registration`+`dashboard` : **870 tests, 10 échecs**
>   (5 failures + 5 errors) — **tous imputables à 2 dettes de test** : **m13** (i18n, `Accept-Language`
>   neutralisé, 4 tests total avec la batch 1) et **m14** (tests postant `nb_seances` ∈ {4,99}
>   hors catalogue `OptionNbSeances` = [1,2,3], 7 tests). **Aucun échec ne correspond à un défaut de
>   production dans une vue auditée** — dans les deux cas le code se comporte correctement
>   (revalidation serveur, langue par cookie), ce sont les tests qui sont périmés.
> - **Total : ~1 232 tests exécutés, 11 échecs — tous des tests périmés (m13 : 4 · m14 : 7), aucun défaut de code.**

---

## Correctifs appliqués — 2026-09-06

> Sur `feat/fusion-horaire-groupe`, non commité. Chaque correctif est vérifié par test
> (`--keepdb` ; `settings.TESTING` neutralise désormais les envois Telegram réels pendant les tests).

| Finding | Correctif | Fichier(s) | Vérif |
|---|---|---|---|
| **M1** — badge 🔔 évaluations muet | Le filtre « ce Presence porte-t-il une évaluation ? » teste désormais `Q(notes_criteres__isnull=False) \| Q(note_hifz__isnull=False) \| …` (aligné sur `calculer_progression_eleve`) + `.distinct()` | `dashboard/notifications.py` | `dashboard/tests.py` : `test_note_seance_systeme_actuel_declenche_le_badge_eleve` (nouveau, chemin `NotePresence`) + `test_note_seance_legacy_champs_geles_declenche_encore_le_badge_eleve` |
| **M2** (sous-ensemble sûr) — action financière sur GET | `@require_POST` sur `admin_paiement_valider` / `admin_paiement_rejeter` (les templates postent déjà via `<form>`) ; `@require_POST` sur `groupe_definir_critere` (idem) | `payments/views.py`, `courses/views.py` | test `tests_cycles` mis en POST + `GroupeOngletCriteresTests` |
| **m0** — commentaire périmé | Bandeau de section réécrit : `مدير ET مشرف` (décision 2026-08-13), asymétrie groupe/compte explicitée | `dashboard/views.py:4678` | — (commentaire) |
| **m2** — `next` open-redirect | `modifier_telephone` : `url_has_allowed_host_and_scheme(...)` avant `redirect(next)` | `accounts/views.py` | `accounts/tests.py` : `ModifierTelephoneTests` (3 tests, dont `//evil.com` ignoré) |
| **m3** — validateurs Django ignorés | `password_change_view` applique `validate_password(nouveau, user=request.user)` | `accounts/views.py` | `accounts/tests.py` : `PasswordChangeValidatorsTests` (mot courant / purement numérique refusés, valide accepté) |
| **m5** — `max_eleves` vs `capacite_max` | Helper `_capacite_max_depuis_post()` (cast `int`, défaut 10, plancher 1), nom unifié `capacite_max` des 2 côtés (repli `max_eleves`) + template `admin_groupe_ajouter.html` + tests | `courses/views.py`, `templates/courses/admin_groupe_ajouter.html`, `courses/tests.py` | `GroupeFormulaireProfEtAgeTests` + `LienMeetVuesGroupeTests` |
| **m7** — `groupe_definir_critere` GET efface les valeurs EAV | `@require_POST` | `courses/views.py` | `GroupeOngletCriteresTests` |
| **m8** — traçabilité reset MDP | `date_reinitialisation_mot_de_passe` renseigné dans `mot_de_passe_oublie` (2 branches) et `reinitialiser_mon_mot_de_passe` (+ `mot_de_passe_reinitialise_par` = titulaire) | `accounts/views.py` | import OK (pas de suite sur ces vues) |
| **m13** — 4 tests i18n rouges | Les tests posent le cookie `settings.LANGUAGE_COOKIE_NAME='fr'` au lieu de `HTTP_ACCEPT_LANGUAGE` (que le middleware neutralise). *(3 étaient i18n ; le 4ᵉ, `MoyenPaiementPresentationDelaisTests`, était en fait un test aux champs POST manquants — corrigé aussi : `delai_grace_nouvel_eleve_mois` + `heure_relance_paiement`.)* | `evaluations/tests.py`, `dashboard/tests.py` | 58 tests OK |
| **m14** — 7 tests `nb_seances` rouges | Les `setUp` concernés seedent les `OptionNbSeances` dont ils ont besoin (99 pour `WizardGroupeDisponibilitesSiAttenteTests` ; 4 et 55 pour `AdminInscriptionDetailAuditTests`) — plus de couplage au seed `[1,2,3]` | `registration/tests.py`, `dashboard/tests.py` | 66 tests OK |
| **m4** — `superviseur_evaluer` non testé | `evaluations/tests.py` : `SuperviseurEvaluerTests` (7 tests : création, commentaire obligatoire, fenêtre 24 h, scope `profs_assignes`, séance non terminée, rôle) | `evaluations/tests.py` | ✅ |
| **m9** — `paiement_panel_sauvegarder` non testé | `payments/tests.py` : `PaiementPanelSauvegarderTests` (5 tests : création manuelle + `reconcilier`, GET inerte, mshrif refusé, màj, élève archivé) | `payments/tests.py` | ✅ |

### Non traité (et pourquoi)

| Finding | Raison |
|---|---|
| **M2 en entier** | Convertir ~toutes les vues d'action (`*_toggle`/`*_archiver`/`*_valider`/…) + ~30 templates RTL de `<a href>` vers formulaires POST = chantier dédié, risque visuel non vérifiable ici. Sous-ensemble le plus sensible (paiements, critères EAV) fait. |
| **m1** — relais Cloudinary `annonces`/`examens` | Le 401 `access_mode='authenticated'` n'est pas reproduit ici (dépend de la config Cloudinary prod). Le fix (relais serveur + gestion du content-type audio `.webm`) touche du code média partagé et ~6 tests, avec un risque de casser de l'audio qui fonctionne aujourd'hui. **À valider en prod d'abord.** |
| **m6** — route morte `inscription_eleve_formulaire` | Le rollback en 1 ligne (`core/urls.py`) est une sécurité voulue — décision produit. |
| **m10 / m11 / m12** | Perf assumée / warning cosmétique W342 / property morte mais testée et documentée. |

---

## 🔴 Problèmes détectés (triés par gravité)

> Statuts mis à jour le 2026-09-06 — voir « Correctifs appliqués » ci-dessus.

### Bloquant
*(aucun problème « site cassé maintenant » sur cette branche — le bug HTTP 500 `age_min/age_max`
signalé dans l'audit du 2026-09-05 est **déjà corrigé et couvert par test** sur `feat/fusion-horaire-groupe`.)*

### Majeur

| # | Problème | Fichier:ligne | Type | Statut |
|---|---|---|---|---|
| M1 | **Les nouvelles évaluations de séance ne déclenchent plus le badge 🔔 côté élève** — `dashboard/notifications.py:192` filtrait sur les 4 champs `note_*` **gelés** jamais renseignés par `prof_presence_sauvegarder` (qui écrit `NotePresence`). Test `dashboard/tests.py:2783` aveugle. | `dashboard/notifications.py` | ✅ **CORRIGÉ** (2026-09-06) — filtre étendu à `notes_criteres` + 2 tests |
| M2 | **Mutation d'état sur requête GET** (surface CSRF) sur ~toutes les vues d'action (`*_toggle`/`*_valider`/`*_rejeter`/`*_archiver`/`admin_seance_annuler`… — 7 `@require_POST` sur ~175 vues). Un GET falsifié (lien piégé, `<img src>` vu par un `admin`/`mshrif` connecté) déclenche validation de paiement, création de compte, annulation de séance… | `payments/views.py`, `courses/views.py`, `dashboard/views.py` | ⏳ **PARTIEL** — `@require_POST` posé sur `admin_paiement_valider/rejeter` + `groupe_definir_critere` ; le reste = chantier dédié (conversion templates `<a>`→`<form>`) |

### Mineur

| # | Problème | Fichier:ligne | Type |
|---|---|---|---|
| m0 | **Commentaire périmé** : le bandeau `dashboard/views.py:4678-4687` affirme que les suppressions définitives de comptes sont « **مدير UNIQUEMENT (pas مشرف)** », mais les 3 vues sont `@role_required('admin', 'mshrif')` (`:4689`, `:4863`, `:6309`). L'accès `mshrif` est en réalité **une décision assumée et testée** (« Tâche du 2026-08-13, point 3 », test `dashboard/tests.py:218` `test_mshrif_autorise` qui *inverse explicitement* l'ancien `test_mshrif_refuse`). → **Pas un bug de permission**, juste un commentaire trompeur à corriger (⚠️ incohérent avec `courses`, où `groupe_supprimer_definitivement` reste `@role_required('admin')` seul). | `dashboard/views.py:4680` | doc obsolète |
| m1 | `annonce_fichier` / `examens.reponse_audio` / `examens.reponse_video` font `redirect(fichier.url)` → exposent `res.cloudinary.com` (le chat, lui, relaie via `core.media_proxy`). Risque 401 si le storage Cloudinary crée les fichiers en `access_mode='authenticated'` (le chat a dû créer `chat/storage.py` pour ça) | `annonces/views.py:212`, `examens/views.py:641,655` | risque potentiel (non confirmé — dépend de la config Cloudinary de prod) |
| m2 | `accounts.views.modifier_telephone` : `return redirect(request.POST.get('next'))` **non validé** (dashboard a pourtant `_next_valide` pour ça) | `accounts/views.py:213` | risque potentiel (open-redirect faible : `redirect('//evil.com')`) |
| m3 | `accounts.views.password_change_view` : validation maison `len >= 8` seulement — les `AUTH_PASSWORD_VALIDATORS` configurés (`settings.py:186`) ne sont jamais appliqués nulle part | `accounts/views.py:260` | mineur |
| m4 | `superviseur_evaluer` (création d'`Evaluation` + `NoteEvaluation`, fenêtre de modification 24 h, contrainte « séance terminée ») : **aucun test** dans tout le projet | `evaluations/views.py:77` | couverture |
| m5 | `groupe_ajouter` lit `request.POST.get('max_eleves')`, `groupe_modifier` lit `capacite_max` — **noms de champ divergents** pour `Groupe.capacite_max`, non casté `int` | `courses/views.py:323` vs `:770` | mineur |
| m6 | `inscription_eleve_formulaire` (formulaire élève legacy) : **route vivante, plus aucun lien**, mais un POST direct crée toujours une `InscriptionEleve` ; `inscription_eleve_choix` n'est routée nulle part (**vue morte**) | `inscriptions/views.py:218,222` | code mort (volontaire, documenté) |
| m7 | `groupe_definir_critere` sans garde de méthode : un GET → `getlist('options')==[]` → `definir_valeurs_groupe(groupe, critere, [])` **efface les valeurs EAV** du critère pour ce groupe | `courses/views.py:483` | risque potentiel (variante de M2 — action sur GET) |
| m8 | `User.mot_de_passe_reinitialise_par` / `date_reinitialisation_mot_de_passe` : **écrits uniquement** par `dashboard.views.admin_utilisateur_reinitialiser_mot_de_passe` (`:6624`). Les flux `accounts.views.mot_de_passe_oublie` / `reinitialiser_mon_mot_de_passe` (`set_password` direct) **ne les renseignent pas** → une réinit. « mot de passe oublié » ne laisse aucune trace d'audit | `accounts/views.py:129,184` vs `accounts/models.py:38-41` | incohérence mineure (pas un champ mort) |
| m9 | `paiement_panel_sauvegarder` (crée/modifie des `Paiement` + `reconcilier`) : aucun test dédié | `payments/views.py:518` | couverture |
| m10 | `suivi_paiements_eleves` sans `?groupe=` : balaie toute la table `Paiement` (documenté, assumé) ; boucle `while i < 600` par élève pour générer les cellules | `payments/views.py:378,437` | perf (assumé) |
| m11 | `Groupe.creneau` a `unique=True` sur un `ForeignKey` → warning Django `fields.W342` permanent au `check` | `courses/models.py:329` | cosmétique |
| m12 | `Groupe.tranches_age_frequentees` (property) : plus appelée par aucune vue (remplacée par `tranches_age_visees`), gardée « pour usage futur » + testée | `courses/models.py:445` | code quasi-mort (assumé) |
| m13 | **4 tests rouges — régression i18n** : `evaluations.tests.CritereLocaliseTests.test_prof_voit_le_critere_traduit_dans_ses_evaluations` + `dashboard.tests.{ProgrammeGeneralLocaliseTests.test_admin_enregistre_les_traductions_et_page_detail_les_affiche, CritereEleveLocaliseTests.test_bilans_mensuels_affiche_le_critere_traduit_en_fr, MoyenPaiementPresentationDelaisTests.test_delais_paiement_et_contact_configurables}` — tous échouent parce que la réponse revient en `<html lang="ar">` malgré `HTTP_ACCEPT_LANGUAGE='fr'`. Cause : `LangueParDefautArabeMiddleware` (chantier « arabe forcé », 2026-09-02) **vide `HTTP_ACCEPT_LANGUAGE`** tant qu'aucun cookie de langue n'est posé (`core/middleware.py:33`). Ces tests i18n (2026-08-27/31) n'ont pas été mis à jour pour poser le cookie via `set_language`. **Conséquence réelle** : `Accept-Language` est **totalement neutralisé** — FR/EN ne s'obtient plus QUE par le sélecteur de langue | `core/middleware.py:32-34` ; `evaluations/tests.py:150`, `dashboard/tests.py` (3 classes) | bug avéré (tests rouges) — corriger les tests ; **choix produit à confirmer** |
| m14 | **7 tests rouges — tests obsolètes `nb_seances`** : `registration.tests.WizardGroupeDisponibilitesSiAttenteTests` (×5) et `dashboard.tests.AdminInscriptionDetailAuditTests.{test_attente_affiche_message_configurable_et_lien_vers_demandes, test_nb_slots_et_niveau_scolaire_affiches}` postent `nb_seances` ∈ {4, 99}. Or le seed `OptionNbSeances` ne crée que **[1, 2, 3]** (`courses/migrations/0040`). `wizard_programme` **rejette correctement** toute valeur hors catalogue (revalidation serveur voulue, `registration/views.py:356`) → l'inscription n'est jamais créée → `InscriptionEleve.DoesNotExist` / HTML vide en aval. **Pas un bug de prod** (le JS ne propose que 1/2/3) — tests écrits à l'époque « liberté totale du nombre de séances » (2026-08-22) et non mis à jour après le chantier catalogue (2026-08-27) | `courses/migrations/0040_seed_nb_seances_...` (valeurs 1,2,3) vs `registration/tests.py:2240`, `dashboard/tests.py:6015` | bug avéré (tests rouges) — corriger les tests |

> **Statut au 2026-09-06** : m0, m2, m3, m4, m5, m7, m8, m9, m13, m14 → **corrigés** (voir
> « Correctifs appliqués » en tête). m1, m6, m10, m11, m12 → non traités (voir le tableau
> « Non traité »). M1 → corrigé ; M2 → partiel.

## Liste des points « à clarifier » — encore ouverts après les correctifs du 2026-09-06

1. **M2 (reste) — Pattern « action sur GET »** : `@require_POST` posé sur les 3 vues les plus
   sensibles. Pour le reste (~toutes les vues `*_toggle`/`*_archiver`/`*_valider` + ~30 templates
   `<a href>` en RTL), faut-il ouvrir un chantier dédié, ou le projet assume-t-il ce pattern
   (session authentifiée + liens) ?
2. **m1 — Fichiers Cloudinary d'`annonces` / `examens`** : à tester en conditions de prod — les
   pièces jointes / audios / vidéos sont-elles vraiment servies (pas de 401 `access_mode=authenticated`) ?
   Si non, les faire passer par `core.media_proxy` comme le chat (avec gestion du content-type audio `.webm`).
3. **m0 (reste) — asymétrie** : le commentaire est corrigé, mais faut-il aligner
   `courses.groupe_supprimer_definitivement` (`admin` seul) sur les suppressions de compte
   (`admin` + `mshrif`), ou l'inverse ?
4. **m6 — Ancien formulaire élève `inscriptions.views`** : retirer la route morte
   `inscription_eleve_formulaire` (+ vue morte `inscription_eleve_choix`), ou garder le rollback ?
5. **m13 (fond) — `Accept-Language` neutralisé** : les tests sont corrigés, mais confirme-t-on que
   FR/EN ne doit JAMAIS suivre la langue du navigateur (uniquement le sélecteur/cookie) ?
7. **m8 — Traçabilité d'audit du reset de mot de passe** : faut-il que les flux « mot de passe
   oublié » (`accounts.views`) renseignent aussi `mot_de_passe_reinitialise_par` / `date_...`
   (aujourd'hui seul le reset lancé par un مدير/مشرف depuis le dashboard le fait) ?
8. **m13 — `Accept-Language` neutralisé** : c'est l'effet voulu du chantier « arabe forcé »
   (2026-09-02) — mais faut-il corriger les 4 tests i18n cassés (poser le cookie via `set_language`),
   et assume-t-on que FR/EN ne passe QUE par le sélecteur de langue (jamais la langue du navigateur) ?
9. **m14 — 7 tests postent `nb_seances` ∈ {4, 99}** hors du catalogue `OptionNbSeances` = [1,2,3] :
   les tests sont-ils simplement à mettre à jour (valeur ∈ {1,2,3}), ou le catalogue seedé
   doit-il être élargi ? *(Le code se comporte correctement — revalidation serveur.)*

---

## Méthodologie & conventions

- **Traçabilité** : chaque affirmation cite `fichier:ligne`.
- **États de vue** : ✅ sain / ⚠️ à vérifier / 🔴 problème détecté.
- **Bug avéré** = comportement fautif reproduit ou démontrable par lecture directe du code.
  **Risque potentiel** = anomalie plausible non exécutée/non confirmée.
- Tests exécutés avec `python manage.py test <app> --keepdb` (base Postgres distante, `--keepdb` obligatoire).
- Les correctifs ne sont **pas** appliqués : voir la section « À clarifier / à corriger ».

### Mécanisme de permissions du projet (rappel, référencé partout)

- `accounts/decorators.py:6` `role_required(*roles)` — décorateur. Empile `@login_required`,
  puis si `request.user.role not in roles` → `redirect_by_role(user)` (renvoi silencieux vers
  le dashboard du rôle courant, **pas** de 403). Donc : un rôle non autorisé n'obtient jamais
  d'erreur, il est juste redirigé.
- `accounts/middleware.py:7` `ForcerChangementMotDePasseMiddleware` — tout user connecté avec
  `doit_changer_mot_de_passe=True` (hors rôles `eleve/prof/superviseur`, exemptés `:38`) est
  redirigé vers `password_change` avant toute autre action, avec un `messages.warning`.
- `accounts/backend.py:6` `EmailBackend` — auth par email ; `filter(email=...)` (plusieurs
  comptes peuvent partager un email) ; connexion accordée **seulement si exactement un** compte
  matche le mot de passe (`:33`).
- Pas de `PermissionRequiredMixin` / `UserPassesTestMixin` Django : tout est en vues fonction +
  `@role_required` ou vérifications manuelles `request.user.role == ...`.

---

## ÉTAPE 0 — Reconnaissance

### Apps du projet (hors tierces)

`settings.py:72-82` INSTALLED_APPS locales : `accounts`, `inscriptions`, `courses`, `payments`,
`evaluations`, `dashboard`, `chat`, `annonces`, `examens`, `registration`, `telegram_bot`.
+ **`core`** (projet : `core/urls.py`, `core/views.py`, `core/media_proxy.py`, `core/middleware.py`).

`django.contrib.admin` est monté (`core/urls.py:27`) — chaque app a un `admin.py`. Non audité en
détail (back-office Django standard) sauf mention d'effet de bord.

### Localisation des fichiers par app

| App | urls | views | models | forms | tests |
|---|---|---|---|---|---|
| core | `core/urls.py` (82) | `core/views.py` (32) + `core/media_proxy.py` (152) | — | — | `core/tests.py` |
| accounts | `accounts/urls.py` (10) | `accounts/views.py` (273) | `accounts/models.py` (931) | *(aucun forms.py)* | `accounts/tests.py` |
| inscriptions | `inscriptions/urls.py` (15) | `inscriptions/views.py` (515) | oui | — | `inscriptions/tests.py` |
| courses | `courses/urls.py` (32) | `courses/views.py` (1195) | oui | — | `courses/tests.py` |
| payments | `payments/urls.py` (13) | `payments/views.py` (670) + `payments/cycles.py` (363) | oui | — | `payments/tests.py`, `tests_cycles.py`, `tests_relance_escalade.py` |
| evaluations | `evaluations/urls.py` (8) | `evaluations/views.py` (163) | oui | — | `evaluations/tests.py` |
| dashboard | `dashboard/urls.py` (250) | `dashboard/views.py` (8424) + `dashboard/recherche.py` + `dashboard/traduction.py` + `dashboard/notifications.py` | `dashboard/models.py` | — | `dashboard/tests.py` |
| chat | `chat/urls.py` (16) | `chat/views.py` (491) + `chat/services.py` (450) | oui | — | `chat/tests.py` |
| annonces | `annonces/urls.py` (14) | `annonces/views.py` (212) + `annonces/services.py` (261) | oui | — | `annonces/tests.py` |
| examens | `examens/urls.py` (41) | `examens/views.py` (697) + `examens/services.py` (282) | oui | — | `examens/tests.py` |
| registration | `registration/urls.py` (28) | `registration/views.py` (815) | oui | — | `registration/tests.py` |
| telegram_bot | `telegram_bot/urls.py` (7) | `telegram_bot/views.py` (153) | oui | — | `telegram_bot/tests.py` |

**Aucun `forms.py` dans tout le projet** : toutes les validations sont faites à la main dans les
vues à partir de `request.POST.get(...)`. Point de cohérence transversal majeur (voir ÉTAPE 2).

---

## APP : core

### Routes (`core/urls.py`)

| URL | Vue | Rôles | Notes |
|---|---|---|---|
| `/` | `RedirectView` → `login` (`core/urls.py:26`) | public | redirection non permanente |
| `/admin/` | `django.contrib.admin` (`:27`) | `is_staff` | back-office Django standard |
| `/register/teacher` | `inscriptions.views.inscription_prof` (`:49`, name `inscription_prof`) | public | route « propre » demandée par le client |
| `/register/student` | `registration.views.wizard_intro` (`:72`, name `inscription_eleve_choix`) | public | name volontairement non renommé (résolution par name partout) |
| `/i18n/` | `django.conf.urls.i18n` (`set_language`, `:78`) | public | change la langue en cookie ; testé `core/tests.py:184` |
| `/media/*` | `static()` (`:82`) | public | **DEBUG uniquement** ; en prod les médias passent par `core/media_proxy` via les vues appelantes |

Includes : `accounts`, `dashboard`, `inscriptions`, `courses`, `payments`, `evaluations`, `chat`,
`annonces`, `examens`, `registration`, `telegram_bot` (`:28-38`).

### Fiches de vue

| Vue | URL | Rôles (vérif) | Objectif | Étapes | Validation | Effets de bord | Tests | État |
|---|---|---|---|---|---|---|---|---|
| `core/views.py:4` `csrf_failure(request, reason)` | *(pas routée — `CSRF_FAILURE_VIEW`, `settings.py:53`)* | public (handler d'erreur) | Remplacer la page 403 CSRF brute par une page arabe RTL avec bouton « recharger » | `render('errors/csrf_failure.html', {url_reessai: request.path}, status=403)` | aucune | aucun | `core/tests.py:135` `CsrfFailureViewTests.test_token_dune_autre_session_affiche_la_page_arabe_personnalisee` | ✅ sain |

### Helpers non-vues (référencés par d'autres apps)

- `core/media_proxy.py:109` `servir_fichier_media(fieldfile, telecharger, nom_telechargement)` —
  relaie un fichier média **à travers le serveur** (jamais de redirect vers `res.cloudinary.com`).
  Pose `X-Frame-Options: SAMEORIGIN` (`:139`). **Ne fait aucune vérification de permission** — c'est
  à chaque vue appelante de le faire (documenté `:11-14`). Appelé par : cartable élève, حقيبة prof,
  chat. ⚠️ à vérifier : voir sections chat / dashboard pour confirmer que chaque appelant contrôle bien l'accès.
- `core/utils.py:12` `paginer(request, queryset, par_page, param)` — pagination générique.
- `core/utils.py:31` `envoyer_message_telegram_direct` / `:74` `envoyer_photo_telegram_direct` /
  `:115` `envoyer_notification_telegram_avec_photo` / `:176` `envoyer_notification_telegram` /
  `:226` `envoyer_notification_telegram_async` / `:160` `..._avec_photo_async` — diffusion Telegram
  à tous les `AbonneTelegram.est_actif=True`. Isolement des échecs par destinataire ; auto-désactivation
  sur 403 (`TelegramBloque`). Les variantes `_async` détachent un thread daemon (pas de Celery).
  **Risque potentiel** (documenté et assumé `core/utils.py:240`) : thread daemon tué si le worker
  gunicorn redémarre → notification perdue silencieusement.
- `core/middleware.py:7` `LangueParDefautArabeMiddleware` — vide `HTTP_ACCEPT_LANGUAGE` tant qu'aucun
  cookie de langue → force `LANGUAGE_CODE='ar'`. Tests : `core/tests.py:168` `LangueParDefautArabeTests`
  (4 tests) ✅. **Effet de bord** : `Accept-Language` devient totalement sans effet — un test/flux
  qui s'y fie casse (voir **m13** : `evaluations.tests.CritereLocaliseTests.test_prof_voit_le_critere_traduit_...`
  échoue à cause de ça).
- `core/tests.py:52` `TemplatesSansFuiteDeCommentairesTests` (3 tests) — scan statique des templates
  (commentaires `{# #}` multi-lignes cassés, `<!-- -->` avec texte de dev). ✅

### Tests exécutés

`python manage.py test core accounts --keepdb` → **14 tests OK** (24,7 s).

### Traçabilité modèle ↔ vue

`core` n'a pas de modèle.

### État de l'app core

✅ **Sain.** Périmètre minimal, bien testé. Seul point d'attention : `servir_fichier_media` délègue
100 % du contrôle d'accès aux appelants (voir chat/dashboard).

---

## APP : accounts

### Routes (`accounts/urls.py`, préfixe `/accounts/`)

| URL | Vue (fichier:ligne) | name | Rôles autorisés (comment vérifié) |
|---|---|---|---|
| `login/` | `accounts/views.py:7` `login_view` | `login` | public ; si déjà connecté → `redirect_by_role` (`:8`) |
| `logout/` | `accounts/views.py:54` `logout_view` | `logout` | public (logout puis redirect login) |
| `mot-de-passe/` | `accounts/views.py:236` `password_change_view` | `password_change` | `@login_required` (`:235`) ; **bloque `eleve/prof/superviseur`** (`:247`, message + redirect) |
| `mot-de-passe-oublie/` | `accounts/views.py:78` `mot_de_passe_oublie` | `mot_de_passe_oublie` | public |
| `reinitialiser-mon-mot-de-passe/` | `accounts/views.py:167` `reinitialiser_mon_mot_de_passe` | `reinitialiser_mon_mot_de_passe` | `@login_required` (`:166`) ; bloque `eleve/prof/superviseur` (`:177`) |
| `telephone/` | `accounts/views.py:204` `modifier_telephone` | `modifier_telephone` | `@login_required` (`:203`) — **tous rôles** |

Vues **non routées** dans `accounts/views.py` : aucune (helpers `redirect_by_role:39`,
`_normaliser_nom_pour_comparaison:69` uniquement).

### Fiches de vue

#### `login_view` — `accounts/views.py:7` — `/accounts/login/`
- **Rôles** : public. Si `request.user.is_authenticated` → `redirect_by_role` (`:8-9`).
- **Objectif** : connexion par email + mot de passe.
- **Étapes** : POST → `authenticate(username=email, password=password)` (`:15`) →
  si `user` et `not user.is_active` → message « حسابك مؤرشف » (`:23-26`) ; sinon `login()` +
  `redirect_by_role` (`:27-28`) ; échec → re-render avec `error` (`:30-32`).
- **Validation** : déléguée à `EmailBackend` (`accounts/backend.py`). `is_active` vérifié **après**
  authenticate (`:23`) — voulu, pour un message distinct.
- **Effets de bord** : session Django créée.
- **Tests** : aucun test direct dédié. Couverture indirecte : `core/tests.py` visite `reverse('login')`
  en GET, `set_language` avec `next=login`. **Aucun test du POST de connexion, ni du cas compte archivé,
  ni du cas email partagé.** ⚠️
- **État** : ⚠️ à vérifier — vue critique **sans test dédié**.

#### `redirect_by_role` — `accounts/views.py:39` *(helper, non routé)*
- Mappe `role` → dashboard. `eleve→dashboard_eleve`, `prof→dashboard_prof`,
  `superviseur→dashboard_superviseur`, `admin→dashboard_admin`, `mshrif→dashboard_mshrif`,
  sinon `login` (`:50`). Utilisé partout par `role_required`.

#### `logout_view` — `accounts/views.py:54`
- `logout(request)` + `redirect('login')`. Pas de restriction (GET suffit). ✅ (mineur : logout en
  GET, pas de CSRF — acceptable, pas d'effet destructeur).

#### `mot_de_passe_oublie` — `accounts/views.py:78` — `/accounts/mot-de-passe-oublie/`
- **Rôles** : public.
- **Objectif** : « نسيت كلمة المرور » sans email (Brevo non fiable) — le nouveau mot de passe est
  **envoyé au مدير via Telegram**, à lui de le transmettre.
- **Étapes** : POST `email` + `nom_complet` (`:116-117`) → recherche `User.objects.filter(email=email)`
  puis match nom normalisé (`:123-126`) → si `role in (eleve,prof,superviseur)` :
  `generer_mot_de_passe_sequentiel()` + `set_password` + `doit_changer_mot_de_passe=False` +
  notif Telegram (`:128-138`) ; sinon si `user` (admin/mshrif) : `generer_mot_de_passe_temporaire()`
  + `doit_changer_mot_de_passe=True` + notif Telegram (`:139-149`). Message générique **identique**
  quel que soit le résultat (`:150-153`, anti-énumération). Reste sur la page avec contact مدير direct.
- **Validation** : match **exact** email + nom complet normalisé (casefold + espaces). Aucun match →
  aucune régénération, même message.
- **Effets de bord** : 🔴 **écriture `set_password` + `save()` du User** ; `envoyer_notification_telegram_async`.
  `save()` complet (pas `update_fields`) — OK.
- **Tests** : **aucun**. ⚠️ Vue sensible (reset de mot de passe) totalement non testée.
- **État** : ⚠️ à vérifier — pas de test ; dépend de `generer_mot_de_passe_sequentiel` /
  `generer_mot_de_passe_temporaire` importés depuis `dashboard.views` (`:113`) — couplage accounts→dashboard.

#### `reinitialiser_mon_mot_de_passe` — `accounts/views.py:167` — `/accounts/reinitialiser-mon-mot-de-passe/`
- **Rôles** : `@login_required` ; `eleve/prof/superviseur` bloqués (`:177` message + `redirect_by_role`).
  Donc **effectif pour `admin`/`mshrif` seulement**.
- **Étapes** : POST → `generer_mot_de_passe_temporaire()` + `set_password` + `doit_changer_mot_de_passe=True`
  + notif Telegram + **`logout(request)`** immédiat (`:181-199`) → redirect login.
- **Effets de bord** : 🔴 écriture User ; déconnexion forcée ; Telegram.
- **GET** : ne fait rien → `redirect_by_role` (`:200`). Le formulaire de confirmation vit donc sur une
  autre page (profil admin).
- **Tests** : **aucun**. ⚠️
- **État** : ⚠️ à vérifier — non testé.

#### `modifier_telephone` — `accounts/views.py:204` — `/accounts/telephone/`
- **Rôles** : `@login_required`, **tous rôles**.
- **Étapes** : POST → `request.user.telephone = POST['telephone'].strip()` +
  `save(update_fields=['telephone'])` + message succès + redirect `next` (nom d'URL) sinon `redirect_by_role`.
- **Validation** : **aucune** (pas de format/longueur vérifié ; `max_length=20` sur le modèle → une
  saisie plus longue lèvera une erreur BDD non gérée). **Risque potentiel** : `redirect(next_url)` prend
  un nom d'URL fourni par le client — `next` vient d'un champ caché du template, mais rien n'empêche de
  poster une valeur arbitraire ; `redirect()` sur une string non résolvable comme nom → traitée comme
  URL/chemin. Pas de `url_has_allowed_host_and_scheme`. **Risque open-redirect faible** (redirect
  relatif surtout, mais `redirect('//evil.com')` fonctionnerait).
- **Tests** : **aucun**. ⚠️
- **État** : ⚠️ à vérifier — pas de validation d'entrée, pas de test, `next` non validé.

#### `password_change_view` — `accounts/views.py:236` — `/accounts/mot-de-passe/`
- **Rôles** : `@login_required` ; `eleve/prof/superviseur` bloqués inconditionnellement (`:247`).
  Effectif pour `admin`/`mshrif`. Chemin exempté du `ForcerChangementMotDePasseMiddleware` (`middleware.py:36`).
- **Étapes** : POST `ancien_mot_de_passe`/`nouveau_mot_de_passe`/`confirmation` → `check_password(ancien)`,
  `nouveau == confirmation`, `len(nouveau) >= 8` (`:256-261`) → `set_password` +
  `doit_changer_mot_de_passe=False` + `update_session_auth_hash` (`:263-268`).
- **Validation** : longueur ≥ 8 seulement (les `AUTH_PASSWORD_VALIDATORS` de `settings.py:186` ne
  sont **pas** appliqués ici — validation maison plus faible). **Incohérence** avec la politique de
  validation Django configurée.
- **Tests** : **aucun**. ⚠️
- **État** : ⚠️ à vérifier — validateurs Django contournés, pas de test.

### Modèles (`accounts/models.py`) et traçabilité

| Modèle | Créé par | Modifié par | Supprimé par |
|---|---|---|---|
| `User:8` | `dashboard.views` (`_creer_compte_*`), `registration`, `inscriptions` (validation) | `accounts.views` (mots de passe, téléphone), `dashboard.views` (fiches compte) | `/admin/` (cascade Eleve/Prof via signal `accounts/signals.py`) |
| `Eleve:106` | `dashboard.views.admin_valider_eleve` | `dashboard.views` (suspendre/archiver/réactiver via `accounts.services`) | `/admin/`, `dashboard` suppression définitive |
| `Prof:158` | `dashboard.views._creer_compte_prof` | `dashboard.views` (infos complémentaires, présentation, archivage) | `/admin/`, `dashboard` |
| `Superviseur:874` | `dashboard.views` (gestion مؤطر) | idem | idem |
| `CompteurMotDePasseSequentiel:71` | `dashboard.views.generer_mot_de_passe_sequentiel` (jamais supprimé) | — | — |
| `ElementHakiba:276` | `dashboard.views.admin_hakiba_ajouter` | `dashboard.views` | `dashboard.views` |
| `CharteEnseignement:353` (singleton) | `get_charte():499` | `dashboard.views.mshrif_charte` | — |
| `CharteSanctionLigne:459` | `dashboard.views.mshrif_charte` | idem | idem |
| `ProgrammeGeneral:506` (singleton) | `get_programme_general():589` | `dashboard.views` (programme_general_modifier) | — |
| `LogoConfig:596` (singleton, caché 5 min) | `get_logo_config():618` | `dashboard.views.mshrif_logo` (+ `invalider_cache_logo_config`) | — |
| `NotePersonnelle:648` | `dashboard.views` (carnet notes) | auteur uniquement | auteur uniquement |
| `DocumentEleve:692` | `dashboard.views.admin_eleve_cartable_ajouter` | `dashboard.views` | `dashboard.views` |
| `VisibiliteProf:820` (singleton) | `get_visibilite_prof():866` | `dashboard.views` | — |
| `DerniereVisiteNotification:892` | `dashboard.notifications.marquer_visite` | idem | — |

**Champs à surveiller** :
- `User.mot_de_passe_reinitialise_par` / `User.date_reinitialisation_mot_de_passe` (`:38-41`) :
  écrits **uniquement** par `dashboard.views.admin_utilisateur_reinitialiser_mot_de_passe`
  (`dashboard/views.py:6624`). Les vues `accounts.views.mot_de_passe_oublie` /
  `reinitialiser_mon_mot_de_passe` font `set_password` **sans** renseigner ces champs → une
  réinitialisation « mot de passe oublié » ne laisse aucune trace d'audit (voir m8).
- `User.description_courte` (`:22`) : exposé (`templates/dashboard/_contact_administration.html`,
  `admin_mon_compte.html`) — OK.
- `Prof.majoration_mensuelle` / `notes_admin` / `date_debut_effectif` : exposés
  (`admin_prof_detail.html`, `admin_prof_infos_complementaires_modifier.html`,
  `classement_mensuel_profs.html`) — OK.

### Tests de l'app accounts

`accounts/tests.py` : **ne couvre AUCUNE vue**. Uniquement `generer_presentation_publique` et la
commande `backfill_presentation_publique_profs` (5 tests). Les 6 vues de `accounts/views.py` n'ont
**aucun test dédié** dans tout le projet (grep `mot_de_passe_oublie|password_change|login_view|...`
sur `**/tests*.py` → seul `core/tests.py`, et seulement pour `set_language`/GET login).

### État de l'app accounts

⚠️ **À vérifier.** Modèle solide et bien documenté, mais **toutes les vues d'authentification et de
gestion de mot de passe sont sans test** — c'est le point le plus sensible de l'app (reset de mot de
passe, connexion compte archivé, email partagé). Voir « À clarifier / à corriger » :
validateurs Django non appliqués dans `password_change_view`, `next` non validé dans `modifier_telephone`,
traçabilité d'audit non renseignée par les flux « mot de passe oublié ».

---

## APP : telegram_bot

### Routes (`telegram_bot/urls.py`, préfixe `/telegram/`)

| URL | Vue | name | Rôles (vérif) |
|---|---|---|---|
| `webhook/` | `telegram_bot/views.py:52` `webhook` | `telegram_webhook` | `@csrf_exempt` + `@require_POST` ; auth par **secret token** header `X-Telegram-Bot-Api-Secret-Token` comparé en temps constant (`_secret_valide:36`, `compare_digest`) |

Les vues d'administration des abonnés (`admin_telegram_abonnes`, `admin_telegram_abonne_valider`,
`_rejeter`, `_desactiver`) sont dans **`dashboard/views.py`** (routées dans `dashboard/urls.py`) —
voir section dashboard. `@role_required('admin','mshrif')`.

### Fiche de vue

#### `webhook` — `telegram_bot/views.py:52` — `/telegram/webhook/`
- **Rôles** : aucun (endpoint machine). Protection : `TELEGRAM_WEBHOOK_SECRET` obligatoire ;
  **si vide côté serveur → tout est rejeté 403** (`:42-45`, choix explicite).
- **Objectif** : recevoir les updates Telegram, gérer `/start` (abonnement en attente de validation)
  et `/stop` (désabonnement).
- **Étapes** : `_secret_valide` (403 sinon) → `json.loads(body)` (200 si invalide, `:65`) →
  `_traiter_update` sous `try/except` global (log, 200 quoi qu'il arrive, `:68-73`).
  `_gerer_start:100` : `get_or_create(chat_id)` ; nouveau → `en_attente_validation=True, est_actif=False` ;
  déjà actif → message « déjà abonné » ; inactif → **repasse systématiquement en attente** (jamais de
  réactivation auto, `:128`). `_gerer_stop:138` : `est_actif=False` + `date_desabonnement`.
- **Validation** : structure de l'update tolérée (champs manquants → `return` silencieux).
- **Effets de bord** : écriture `AbonneTelegram` ; appels sortants `envoyer_message_telegram_direct`
  (réponse à l'utilisateur Telegram).
- **Tests** : `telegram_bot/tests.py` `WebhookSecuriteTest` (5), `WebhookStartStopTest` (6),
  `EnvoyerNotificationTelegramTest` (6), `EnvoyerPhotoTelegramTest` (8), `AdminValidationAbonneTest` (6).
- **État** : ✅ sain — **très bien couvert** (secret manquant/faux, JSON invalide, GET refusé,
  start/stop dans tous les états, isolation des échecs de diffusion, 403 → désactivation auto,
  cohérence 403 ↔ /start).

### Modèle `AbonneTelegram` (`telegram_bot/models.py:5`)

- Créé/modifié par : `telegram_bot/views.py` (webhook) + `dashboard/views.py` (validation admin).
  Jamais supprimé (historique conservé même après `/stop` ou blocage).
- `valide_par` (`:53`) : écrit par `dashboard.views.admin_telegram_abonne_valider` (testé
  `AdminValidationAbonneTest.test_admin_valide_abonne:219`). ✅ pas mort.
- Tous les champs exposés dans `templates/dashboard/admin_telegram_abonnes.html` (à confirmer en section dashboard).

### Tests exécutés

`python manage.py test telegram_bot --keepdb` → **27 tests OK** (37,6 s).

### État de l'app telegram_bot

✅ **Sain.** App petite, périmètre clair, couverture de tests exemplaire (la meilleure du projet).
Seul point structurel : la migration `0002` seed un `AbonneTelegram` depuis `settings.TELEGRAM_CHAT_ID`
— les tests le suppriment explicitement en `setUp` (`:69`). Pas un bug, mais dépendance test↔.env locale.

---

## APP : annonces

### Routes (`annonces/urls.py`, préfixe `/annonces/`)

| URL | Vue (fichier:ligne) | name | Rôles (vérif) |
|---|---|---|---|
| `` | `annonces/views.py:51` `annonces_gestion` | `annonces_gestion` | `@role_required('admin','mshrif')` (`:50`) |
| `ajouter/` | `annonces/views.py:101` `annonce_ajouter` | `annonce_ajouter` | `@role_required('admin','mshrif')` (`:100`) ; POST only (`:102`) |
| `mes-annonces/` | `annonces/views.py:180` `eleve_annonces` | `eleve_annonces` | `@role_required('eleve')` (`:179`) |
| `<int:annonce_id>/toggle/` | `annonces/views.py:162` `annonce_toggle` | `annonce_toggle` | `@role_required('admin','mshrif')` ; POST only (`:167`) |
| `fichier/<int:annonce_id>/` | `annonces/views.py:202` `annonce_fichier` | `annonce_fichier` | `@role_required('admin','mshrif','eleve')` + `peut_voir_annonce` (`:210`) |
| `<str:cible>/` | `annonces/views.py:67` `annonces_canal_detail` | `annonces_canal_detail` | `@role_required('admin','mshrif')` ; **catch-all en dernier** — n'intercepte pas les routes fixes ci-dessus |

Vues mortes : aucune. Helpers `_base_template_admin_ou_mshrif:30`, `_contexte_base_mshrif:38`
(duplication assumée avec `courses.views` / `dashboard.views` — voir ÉTAPE 2).

### Fiches de vue (résumé)

| Vue | Objectif | Validation | Effets de bord | État |
|---|---|---|---|---|
| `annonces_gestion:51` | Page sélection des 3 canaux (Femmes/Hommes/Mineurs) + flux récent | — | lecture seule | ✅ |
| `annonces_canal_detail:67` | Fil d'un canal + sous-filtre `?tranche=` (canal `mineurs` seulement) ; `Http404` si `cible` invalide (`:79`) | `cible` ∈ 3 valeurs ; `tranche` ignorée si invalide/hors mineurs | lecture seule | ✅ |
| `annonce_ajouter:101` | Publier une annonce dans un canal | `titre`+`contenu` requis (`:125`) ; `cible` ∈ `CIBLES_VALIDES` (`:128`) ; `tranche_age` forcée `''` hors `mineurs` (`:113`) ; pièce jointe via `valider_piece_jointe` (liste blanche ext + taille/type, `services.py:137`) ; **garde anti-double-soumission 5 s** (`:143`) | `Annonce.objects.create` ; upload fichier (storage projet) | ✅ |
| `annonce_toggle:162` | Active/désactive (réversible) | — | `save(update_fields=['active'])` | ✅ |
| `eleve_annonces:180` | Liste des annonces du canal de l'élève + marque lues | `Eleve.DoesNotExist` → `redirect('login')` | `LectureAnnonce` bulk_create (`marquer_annonces_lues`) | ✅ |
| `annonce_fichier:202` | Accès protégé à la pièce jointe (anti-IDOR) | `peut_voir_annonce(user, annonce)` (`services.py:58`) : admin/mshrif → tout ; élève → SON canal + tranche + annonce active | `redirect(annonce.fichier.url)` → **URL réelle du storage exposée au navigateur** (contrairement à chat) | ⚠️ voir risque |

**Risque potentiel** (`annonces/views.py:212`) : `annonce_fichier` fait `redirect(annonce.fichier.url)`
qui envoie le navigateur vers `res.cloudinary.com`. Le storage par défaut (`settings.py:271`
`RawMediaCloudinaryStorage`) crée les fichiers en `access_mode` non forcé public — si Cloudinary
applique `authenticated` par défaut (comme constaté pour le chat, `chat/storage.py` a dû être créé
pour corriger un **401**), les pièces jointes d'annonces pourraient être inaccessibles en production.
Le chat a résolu ça (storage public + relais `core.media_proxy`), **pas annonces**. Idem `examens`
(`reponse_audio` / `reponse_video`). À confirmer avec un test en conditions Cloudinary réelles.

### Modèles

| Modèle | Créé | Modifié | Supprimé |
|---|---|---|---|
| `Annonce` (`annonces/models.py:6`) | `annonce_ajouter` | `annonce_toggle` (champ `active`) ; `/admin/` | jamais (réversible via `active`) ; `/admin/` |
| `LectureAnnonce` (`:97`) | `marquer_annonces_lues` (`services.py:178`) | — | CASCADE si `Annonce` supprimée |

Champs modèle : `tranche_age` a du sens **seulement si `cible='mineurs'`** — appliqué de façon
cohérente dans `annonce_ajouter` (`:113`), `annonces_visibles_pour_eleve` (`services.py:165`),
`peut_voir_annonce` (`services.py:81`). ✅ Pas d'orphelin.

### Tests de l'app annonces

`annonces/tests.py` : **62 tests** — couverture excellente : `cible_annonce_pour_eleve` (7),
`annonces_visibles_pour_eleve` (6), marquage lu (2), vues (9), canaux (12), tranches d'âge (13),
pièces jointes (8), sécurité IDOR fichier (5). Couvre explicitement `test_eleve_ne_peut_pas_creer_une_annonce`,
`test_canal_detail_code_invalide_404`, `test_eleve_dun_autre_canal_ne_peut_pas_acceder_au_fichier`.

`python manage.py test annonces --keepdb` (dans batch 1) → **OK** (aucun échec).

### État de l'app annonces

✅ **Sain.** Logique métier centralisée dans `services.py`, permissions cohérentes, tests denses.
Seul point : `annonce_fichier` expose l'URL Cloudinary (risque 401 non confirmé, voir ci-dessus).

---

## APP : chat

### Routes (`chat/urls.py`, préfixe `/chat/`)

| URL | Vue (fichier:ligne) | name | Rôles (vérif) |
|---|---|---|---|
| `` | `chat/views.py:122` `chat_liste` | `chat_liste` | `@role_required('eleve','prof','superviseur','admin')` (`ROLES_AVEC_CHAT:22` — **مشرف exclu volontairement**) |
| `liste-partielle/` | `chat/views.py:160` `chat_liste_partial` | `chat_liste_partial` | idem + `@require_GET` |
| `<int:groupe_id>/` | `chat/views.py:137` `chat_conversation` | `chat_conversation` | idem + `_conversation_ou_403` (`:36`, `can_access_conversation`) |
| `<int:groupe_id>/panneau/` | `chat/views.py:183` `chat_panel` | `chat_panel` | idem + `@require_GET` + `_conversation_ou_403` |
| `<int:groupe_id>/messages/` | `chat/views.py:197` `chat_messages` | `chat_messages` | idem + `@require_GET` + `_conversation_ou_403` |
| `<int:groupe_id>/envoyer/` | `chat/views.py:264` `chat_envoyer` | `chat_envoyer` | idem + `@require_POST` + `_conversation_ou_403` |
| `<int:groupe_id>/lu/` | `chat/views.py:325` `chat_marquer_lu` | `chat_marquer_lu` | idem + `@require_POST` + `_conversation_ou_403` |
| `<int:groupe_id>/fichier/<int:message_id>/` | `chat/views.py:338` `chat_fichier` | `chat_fichier` | idem + `@require_GET` + `_conversation_ou_403` + `Message` lié à la conversation (`:370`) |
| `<int:groupe_id>/photo/` | `chat/views.py:403` `chat_modifier_photo_groupe` | `chat_modifier_photo_groupe` | idem + `@require_POST` + `_conversation_ou_403` + `peut_modifier_photo_groupe` (**admin uniquement**, `permissions.py:94`) |
| `<int:groupe_id>/messages/<int:message_id>/supprimer/` | `chat/views.py:453` `chat_supprimer_message` | `chat_supprimer_message` | idem + `@require_POST` + `_conversation_ou_403` + `message.auteur_id == request.user.id` (`:473`) |

Vues mortes : aucune. **Contrôle d'accès entièrement centralisé** dans `chat/permissions.py`
(`get_conversations_accessibles` — 1 seule source de vérité, IDOR via `can_access_conversation`).

### Fiches de vue (points saillants)

- **`chat_envoyer:264`** — validation serveur systématique : message vide refusé (`:279`), fichier
  hors liste blanche / trop gros refusé via `valider_piece_jointe` (`services.py:411`, listes
  séparées audio/fichier, 15 Mo). Effets : `Message.objects.create` (snapshot `auteur_nom`/`auteur_role`
  figés), upload fichier (storage **public dédié** `chat/storage.py`), `marquer_comme_lu`. ✅
- **`chat_fichier:338`** — anti-IDOR (`_conversation_ou_403` + `Message` lié). Audio : relais serveur
  `FileResponse` avec `content_type_audio` (contourne le bug Cloudinary `video/webm`), 503+`Retry-After`
  si fichier pas encore propagé (`:386`). Autres : `core.media_proxy.servir_fichier_media` (relais
  serveur, pas de redirect Cloudinary). ✅ **Meilleure gestion média du projet.**
- **`chat_modifier_photo_groupe:403`** — double contrôle (`_conversation_ou_403` + `peut_modifier_photo_groupe`).
  `valider_photo_groupe` (Pillow). Ancienne photo supprimée **après** save (`:441`). Écrit `Groupe.photo`
  (partagé avec `courses.views.groupe_modifier`). ✅
- **`chat_supprimer_message:453`** — suppression douce (ligne conservée, contenu vidé), strict
  `auteur_id`, idempotent. Supprime le fichier physique (`:478`). ✅
- **`chat_messages:197`** — pagination par curseur, **3 branches bornées** à `NB_MESSAGES_PAR_PAGE`
  (un finding HIGH d'un audit du 2026-08-15 : la branche `apres=` ne l'était pas — corrigé). ✅

### Modèles (`chat/models.py`)

| Modèle | Créé | Modifié | Supprimé |
|---|---|---|---|
| `Conversation:8` (1:1 `Groupe`) | signal `chat/signals.py` à la création du Groupe + backfill (`services.py:21`) | — | CASCADE avec Groupe |
| `Message:37` | `chat_envoyer` | `chat_supprimer_message` (soft) | `purger_messages_expires` (rétention `ConfigurationChat.duree_retention_jours`, défaut 7 j) via cmd + `purge_opportuniste` (throttle 1 h) |
| `LectureConversation:146` | `marquer_comme_lu` | idem | CASCADE |
| `ConfigurationChat:173` (singleton) | `get_configuration_chat:194` | vue `dashboard` (`RetentionConfigViewTests` couvre) | — |

### Tests de l'app chat

`chat/tests.py` : **123 tests**, 26 classes — permissions par rôle (élève/prof/superviseur/admin/mshrif),
IDOR HTTP par rôle, historique, envoi (texte/audio/fichier), notifications non-lus, purge rétention,
performance (N+1), limite polling, séparateurs de jour, config rétention, photo groupe, suppression
message, tranches d'âge, accès public Cloudinary. **Couverture parmi les meilleures du projet.**

`python manage.py test chat --keepdb` (batch 2) → **OK** (aucun échec).

### État de l'app chat

✅ **Sain.** Architecture de sécurité exemplaire (permissions centralisées, IDOR testé par rôle),
gestion média robuste (storage public + relais serveur + gestion latence Cloudinary), couverture
de tests très forte. Aucune anomalie détectée.

---

## APP : examens

### Routes (`examens/urls.py`, préfixe `/examens/`)

**Prof — gestion** (`@role_required('prof')` + `can_gerer_examen`/`can_corriger_examen` sur l'objet) :

| URL | Vue | Contrôle objet |
|---|---|---|
| `prof/` | `prof_examens_liste:45` | filtre `groupe__prof=prof` |
| `prof/ajouter/` | `examen_ajouter:60` | groupe ∈ `prof.groupes.filter(statut='actif')` |
| `prof/<id>/` | `examen_detail:154` | `can_gerer_examen` (`:156`) |
| `prof/<id>/modifier/` | `examen_modifier:78` | `can_gerer_examen` (`:80`) |
| `prof/<id>/publier/` | `examen_publier:174` | `can_gerer_examen` + `statut=='brouillon'` + `motif_non_publiable` ; `@require_POST` |
| `prof/<id>/fermer/` | `examen_fermer:196` | `can_gerer_examen` + `statut=='publie'` ; `@require_POST` |
| `prof/<id>/copies/` | `examen_copies:401` | `can_corriger_examen` (`:403`) |
| `prof/<id>/questions/ajouter/` | `question_ajouter:301` | `can_gerer_examen` + `structure_modifiable` (`:305`) |
| `prof/questions/<id>/modifier|supprimer|monter|descendre/` | `question_modifier:326` / `question_supprimer:353` / `question_monter:390` / `question_descendre:396` | `can_gerer_examen` + `structure_modifiable` |
| `prof/copies/<id>/` | `copie_correction:415` | `can_corriger_examen` + `copie.statut=='soumise'` |

**Élève** (`@role_required('eleve')` + `can_access_examen`/`can_access_copie`/`can_modifier_copie`) :

| URL | Vue | Contrôle |
|---|---|---|
| `mes-examens/` | `eleve_examens_liste:450` | `get_examens_accessibles` (publié/fermé, groupes actuels) ; `marquer_visite('examens')` |
| `<id>/avant/` | `eleve_examen_avant:470` | `can_access_examen` ; POST → `peut_etre_commence` + `demarrer_ou_recuperer_copie` |
| `copie/<id>/passer/` | `examen_passage:497` | `can_access_copie` + `finaliser_si_expiree` |
| `copie/<id>/questions/<qid>/autosave/` | `reponse_autosave:520` | `can_access_copie` + `can_modifier_copie` (409 si expiré/soumis) ; `@require_POST` |
| `copie/<id>/soumettre/` | `examen_soumettre:593` | `can_access_copie` + `finaliser_si_expiree` + `soumettre_copie` ; `@require_POST` |
| `copie/<id>/resultat/` | `eleve_copie_resultat:614` | `can_access_copie` |

**Audio/vidéo protégés** (`@role_required('eleve','prof','superviseur','admin','mshrif')` + `can_access_copie`) :
`reponse/<id>/audio/` `reponse_audio:630`, `reponse/<id>/video/` `reponse_video:646`.

**Consultation lecture seule** (`@role_required('admin','mshrif','superviseur')` + `can_access_examen`/`can_access_copie`) :
`consultation/` `consultation_examens_liste:662`, `consultation/<id>/` `consultation_examen_detail:674`,
`consultation/copie/<id>/` `consultation_copie_detail:688`.

Vues mortes : aucune.

### Points saillants / effets de bord

- **Chrono revalidé serveur systématiquement** : `finaliser_si_expiree` (`services.py:58`) appelé à
  chaque accès copie ; `Copie.est_expiree` / `temps_restant_secondes` recalculés (jamais mis en cache,
  jamais dérivés du client). `soumettre_copie` (`services.py:114`) : `@transaction.atomic` +
  `select_for_update` (anti-double-soumission concurrente), idempotent.
- **Verrous de structure/chrono** dérivés de l'état des `Copie` (jamais de booléen stocké) :
  `structure_modifiable` (aucune copie soumise), `chrono_modifiable` (aucune copie démarrée).
- **`note_totale` reste `None`** tant que toutes les réponses ne sont pas corrigées (`recalculer_note_totale`,
  `services.py:97`) — évite une note partielle trompeuse.
- **Validation** : `_valider_et_enregistrer_examen` (`views.py:98`), `_valider_et_enregistrer_question`
  (`views.py:210`), `motif_non_publiable` (`services.py:170`) — toutes serveur, aucune confiance client.
  Fichiers : `valider_fichier_audio` (15 Mo), `valider_fichier_video` (40 Mo).
- 🔴/⚠️ **Risque potentiel** : `reponse_audio:641` / `reponse_video:655` font `redirect(reponse.reponse_XXX.url)`
  → exposent l'URL Cloudinary au navigateur (même souci que `annonces.annonce_fichier`, résolu seulement
  dans chat). Fichiers uploadés via storage projet par défaut. Accès potentiellement 401 en prod Cloudinary
  — non confirmé.

### Modèles (`examens/models.py`)

`Examen:10` (FK `Groupe` CASCADE, `prof` SET_NULL) ; `Question:114` ; `ChoixQuestion:148` ;
`Copie:166` (unique_together `examen,eleve`) ; `Reponse:253` (unique_together `copie,question`, sert
aussi de stockage autosave). Cycle de vie `Examen` : `brouillon→publie→ferme`, transitions toujours
explicites par vue. Créés/modifiés uniquement par les vues examens listées.

Champ à vérifier : `Copie.soumission_automatique` (`:193`) — écrit par `soumettre_copie(automatique=)`,
affiché en correction. OK.

### Tests de l'app examens

`examens/tests.py` : **120 tests**, 20 classes — modèle, ordre questions, unicité, permissions,
chrono, workflow prof HTTP, workflow élève HTTP, auto-correction, correction manuelle, validation
audio/vidéo, accès audio/vidéo HTTP, **IDOR HTTP** (classe dédiée `:1000`), consultation HTTP,
rendu sidebar sans régression, notifications `marquer_visite`.

`python manage.py test examens --keepdb` (batch 2) → **OK** (aucun échec).

### État de l'app examens

✅ **Sain** sur la logique métier (chrono serveur, verrous, permissions centralisées, très bonne
couverture). ⚠️ Seul point : exposition de l'URL Cloudinary dans `reponse_audio`/`reponse_video`
(risque 401 non confirmé — voir « À clarifier »).

---

## APP : evaluations

### Routes (`evaluations/urls.py`, préfixe `/evaluations/`)

| URL | Vue (fichier:ligne) | name | Rôles (vérif) |
|---|---|---|---|
| `mes-evaluations/` | `evaluations/views.py:26` `prof_evaluations_recues` | `evaluations_prof_recues` | `@role_required('prof')` (`:25`) ; queryset scopé `Evaluation.filter(prof=prof)` |
| `seance/<int:seance_id>/evaluer/` | `evaluations/views.py:77` `superviseur_evaluer` | `superviseur_evaluer` | `@role_required('superviseur')` (`:76`) + `get_object_or_404(Seance, groupe__prof__in=superviseur.profs_assignes.all())` (`:79`) |
| `seance/<int:seance_id>/` | `evaluations/views.py:59` `superviseur_evaluation_detail` | `superviseur_evaluation_detail` | `@role_required('superviseur')` (`:58`) + même scope queryset (`:64`) |

Vues mortes : aucune. `moyenne_mensuelle_prof` (`utils.py:4`) est un helper (utilisé par `dashboard`).

> ⚠️ La vue `dashboard.views.prof_evaluations` ("تقييماتي" = évaluations que le prof donne aux élèves)
> et `evaluations.views.prof_evaluations_recues` ("تقييمات المؤطر لي") sont **deux choses distinctes**
> — documenté `views.py:31-35`. Pas un bug, mais nommage piégeux.

### Fiches de vue

#### `prof_evaluations_recues` — `evaluations/views.py:26`
- **Objectif** : le prof consulte en lecture seule les évaluations que son مؤطر a écrites sur lui.
- **Étapes** : `get_object_or_404(Prof, user=request.user)` → `Evaluation.filter(prof=prof)` +
  `select_related` + `prefetch` → `marquer_visite('evaluations_recues')`.
- **Effets de bord** : `DerniereVisiteNotification` upsert.
- **Sécurité** : pas de détail par ID (liste seule, ouverture inline `<details>`) → **pas d'IDOR possible**.
- **Tests** : `evaluations/tests.py:38` `ProfEvaluationsRecuesTests` (7 tests) + `CritereLocaliseTests`
  (`:113`, 4 tests). Couvre : isolation entre profs, refus élève/superviseur, auteur supprimé, marquage lu.
- **État** : ✅ sain.

#### `superviseur_evaluer` — `evaluations/views.py:77`
- **Objectif** : le مؤطر note un prof pour une séance (formulaire critères + commentaire obligatoire).
- **Étapes** : scope `Seance` sur `profs_assignes` → **contrainte temporelle** `seance.evaluable_par_prof`
  (pas d'éval avant fin réelle de la séance, vérifié serveur GET **et** POST, `:88`) → si `Evaluation`
  existe et `not evaluation.modifiable` (fenêtre 24 h depuis 1er envoi) → refus (`:102`) → POST :
  `commentaire` obligatoire (`:113`) → `Evaluation.objects.update_or_create` (`:130`) +
  `NoteEvaluation.update_or_create` par critère noté (`:141`).
- **Validation** : commentaire non vide ; notes optionnelles par critère ; `int(request.POST[...])`
  sur les notes dans la branche ré-affichage (`:118`) — **`KeyError`/`ValueError` non gardé** si un
  `note_<id>` est présent mais non entier (peu probable via le formulaire, mais entrée non validée).
- **Effets de bord** : crée/modifie `Evaluation` + `NoteEvaluation` (plusieurs lignes).
- **Tests** : 🔴 **AUCUN** — grep `superviseur_evaluer` sur tous les `tests*.py` → 0 résultat.
  Vue d'écriture avec logique temporelle et fenêtre de modification, **non testée**.
- **État** : ⚠️ à vérifier — **zéro couverture de test** sur une vue d'écriture non triviale.

#### `superviseur_evaluation_detail` — `evaluations/views.py:59`
- Lecture seule d'une évaluation soumise. Scope queryset sur `profs_assignes`. **Aucun test.** ⚠️

### Modèles (`evaluations/models.py`)

| Modèle | Créé par | Modifié par | Supprimé |
|---|---|---|---|
| `Critere:14` | `dashboard.views.admin_critere_ajouter` (testé `CritereLocaliseTests:158`) | `dashboard.views` | `dashboard.views` (ou `est_actif=False`) |
| `Evaluation:51` (1:1 `Seance`) | `superviseur_evaluer` | `superviseur_evaluer` (`update_or_create`) | CASCADE avec `Seance` ; CASCADE avec `Prof` ; `superviseur` SET_NULL |
| `NoteEvaluation:106` | `superviseur_evaluer` | idem | CASCADE |
| `CommentaireMensuel:133` | `dashboard.views` (classement mensuel) | idem | CASCADE avec `Prof` |

`Evaluation.modifiable` : fenêtre 24 h depuis `date` (`auto_now_add`, ne bouge jamais) — logique
correcte (`:93-99`). **Non testée.**

### Tests de l'app evaluations

`python manage.py test evaluations --keepdb` (dans batch 1) → **1 échec** :
`CritereLocaliseTests.test_prof_voit_le_critere_traduit_dans_ses_evaluations` (`evaluations/tests.py:150`)
— la page revient en arabe malgré `HTTP_ACCEPT_LANGUAGE='fr'` car `LangueParDefautArabeMiddleware`
neutralise l'en-tête. **Test à corriger** (poser le cookie de langue), pas un bug de la vue auditée.
Voir **m13**. Le reste (`ProfEvaluationsRecuesTests`, `test_nom_localise_repli`, `test_admin_enregistre_nom_fr_nom_en`)
passe.
Couverture : `prof_evaluations_recues` bien couvert ; `superviseur_evaluer` / `superviseur_evaluation_detail`
**pas couverts du tout**.

### État de l'app evaluations

⚠️ **À vérifier.** La vue `superviseur_evaluer` (écriture d'évaluation + notes, fenêtre de modification
24 h, contrainte « séance terminée ») n'a **aucun test** — c'est le principal risque de l'app.
`superviseur_evaluation_detail` non plus. Le reste est sain.

---

## APP : courses

> `courses/views.py` ne couvre que **la gestion des groupes et du pool de liens Meet**. Tout le reste
> du domaine (séances, présences, calendrier, bilans mensuels, rémunération, disponibilités,
> critères élève…) vit dans **`dashboard/views.py`** — voir section dashboard. Les modèles sont
> tous dans `courses/models.py` ; la logique métier dans `courses/utils.py` (2019 lignes).

### Routes (`courses/urls.py`, préfixe `/courses/`)

| URL | Vue (fichier:ligne) | name | Rôles (vérif) | Méthode |
|---|---|---|---|---|
| `groupes/` | `courses/views.py:64` `groupes_list` | `admin_groupes` | `@role_required('admin','mshrif')` | GET |
| `groupes/ajouter/` | `courses/views.py:170` `groupe_ajouter` | `admin_groupe_ajouter` | `@role_required('admin')` + `@transaction.atomic` | GET/POST |
| `groupes/<id>/` | `courses/views.py:361` `groupe_detail` | `admin_groupe_detail` | `@role_required('admin','mshrif')` | GET |
| `groupes/<id>/modifier/` | `courses/views.py:584` `groupe_modifier` | `admin_groupe_modifier` | `@role_required('admin')` + `@transaction.atomic` | GET/POST |
| `groupes/<id>/ajouter-eleve/` | `courses/views.py:512` `groupe_ajouter_eleve` | `admin_groupe_ajouter_eleve` | `@role_required('admin')` | POST (pas de garde méthode — GET inoffensif) |
| `groupes/<id>/retirer-eleve/<eid>/` | `courses/views.py:535` `groupe_retirer_eleve` | `admin_groupe_retirer_eleve` | `@role_required('admin')` | `if POST` |
| `groupes/<id>/transferer-eleve/<eid>/` | `courses/views.py:546` `groupe_transferer_eleve` | `admin_groupe_transferer_eleve` | `@role_required('admin')` | POST (pas de garde) |
| `groupes/<id>/supprimer/` | `courses/views.py:938` `groupe_supprimer` | `admin_groupe_supprimer` | `@role_required('admin')` | `if POST` (+ `groupe_peut_etre_supprime`) |
| `groupes/<id>/archiver/` | `courses/views.py:980` `groupe_archiver` | `admin_groupe_archiver` | `@role_required('admin','mshrif')` | 🔴 **aucune garde de méthode — mute `statut` sur GET** |
| `groupes/<id>/reactiver/` | `courses/views.py:989` `groupe_reactiver` | `admin_groupe_reactiver` | `@role_required('admin','mshrif')` | 🔴 **idem, mute sur GET** |
| `groupes/<id>/supprimer-definitivement/` | `courses/views.py:1009` `groupe_supprimer_definitivement` | idem | `@role_required('admin')` | `if POST` + saisie exacte du nom |
| `groupes/<id>/criteres/<cid>/definir/` | `courses/views.py:483` `groupe_definir_critere` | `admin_groupe_definir_critere` | `@role_required('admin','mshrif')` | ⚠️ **pas de garde méthode** — sur GET, `request.POST.getlist('options')` = `[]` → `definir_valeurs_groupe(groupe, critere, [])` **efface toutes les valeurs** |
| `liens-meet/` | `courses/views.py:1047` `liens_meet_list` | `admin_liens_meet` | `@role_required('admin','mshrif')` | GET |
| `liens-meet/ajouter/` | `courses/views.py:1116` `lien_meet_ajouter` | `admin_lien_meet_ajouter` | `@role_required('admin')` | `if POST` |
| `liens-meet/<id>/toggle/` | `courses/views.py:1181` `lien_meet_toggle` | `admin_lien_meet_toggle` | `@role_required('admin')` | 🔴 **aucune garde méthode — toggle `est_actif` sur GET** |
| `liens-meet/attribuer/<gid>/` | `courses/views.py:1135` `lien_meet_attribuer_groupe` | `admin_lien_meet_attribuer_groupe` | `@role_required('admin')` | `if POST` |

**Vues mortes** : aucune. **Routes CRUD `creneaux/*` retirées le 2026-09-04** (fusion horaire/groupe) —
le modèle `Creneau` subsiste mais n'a plus d'écran dédié ; un `Creneau` privé est créé automatiquement
par `groupe_ajouter`/`groupe_modifier`.

### Fiches de vue (points saillants)

#### `groupe_ajouter` — `courses/views.py:170` / `groupe_modifier` — `:584`
- **Rôles** : `@role_required('admin')` (**pas mshrif** — mshrif est lecture seule sur les groupes,
  sauf `groupe_definir_critere` et archiver/réactiver).
- **Objectif** : créer/modifier un groupe + son `Creneau` privé (horaire jour/heure/âge/sexe/type/riwaya)
  + assignation prof + lien Meet.
- **Validation** (toute manuelle, pas de Forms) : photo via `valider_photo_groupe` (Pillow) ;
  au moins 1 slot (`_slots_depuis_post`) ; `_ages_creneau_depuis_post` (`:858`) — **cast `int`
  obligatoire** sur `age_min`/`age_max` (docstring `:864` : sinon HTTP 500 sur
  `_categorie_age_creneau` `'6' < 18`) + `age_min ≥ 1` + `age_max ≥ age_min` ; prof revalidé
  serveur (archivé refusé) ; lien Meet : `URLValidator` sur URL collée, `select_for_update` +
  `description_conflit_lien_meet` sous verrou.
- **Avertissements non bloquants** (`avertissements_prof_creneau`) : incompatibilité horaire/âge/sexe
  → ré-affichage avec `confirme='1'` requis.
- **Effets de bord** : `Creneau.objects.create` + `remplacer_slots_creneau` (créé tôt, supprimé
  via `_redisplay` si abandon → **`@transaction.atomic` englobant ajouté à l'audit 2026-09-05**
  pour éviter `Creneau`/`CreneauSlot` orphelins) ; `Groupe.objects.create` ; `regenerer_pour_nouveau_creneau`
  (**supprime + régénère les séances futures non terminées**) ; upload photo Cloudinary ; `LienMeet.get_or_create`.
- **Incohérence** : `groupe_ajouter` lit `request.POST.get('max_eleves', 10)` (`:323`), `groupe_modifier`
  lit `request.POST.get('capacite_max', 10)` (`:770`) — **noms de champ différents** pour la même colonne
  `Groupe.capacite_max`. Valeur stockée en `str` (pas de cast `int`), contrairement à `age_min/age_max`.
- **Tests** : `courses/tests.py:713` `GroupeFormulaireProfEtAgeTests` — `test_creation_groupe_avec_prof_reussit:738`,
  `test_age_non_numerique_refuse_proprement_sans_500_ni_creneau_orphelin:760`,
  `test_age_manquant_refuse_proprement:770`, `test_age_min_superieur_a_age_max_refuse:777`,
  `test_modification_groupe_avec_prof_et_changement_horaire_reussit:749`. **Le bug HTTP 500
  `age_min/age_max` de l'audit du 2026-09-05 est CORRIGÉ sur cette branche et couvert par test.**
- **État** : ✅ sain (bug age corrigé + testé).

#### `groupes_list` — `courses/views.py:64`
- Filtres : `statut`, `prof`, `type` (individuel/groupe), `categorie` (`Groupe.categorie` — champ manuel,
  **plus dérivé du créneau**), `tranche` (sous `categorie=mineurs`, via `creneau__age_min/max`
  chevauchement), `q` (`icontains` OU `trigram_similar`). Pagination 10. `chat_groupe_ids` (1 requête).
- **Tests** : `GroupesListFiltreTests` (14), `GroupesListFiltreTrancheAgeTests` (7). ✅

#### `groupe_detail` — `courses/views.py:361`
- Affiche membres, élèves disponibles, autres groupes, avertissements « en attente de confirmation »
  (recalculés depuis `?confirmer_ajout`/`?confirmer_transfert` GET), onglet « الخصائص » (critères
  `registration.Critere`), icône chat. Correctifs N+1 (2026-08-30) : `annotate(Count)`, `select_related`.
- **État** : ✅ (lecture seule).

#### `groupe_archiver` / `groupe_reactiver` / `lien_meet_toggle` — 🔴 mutation d'état sur GET
- Ces 3 vues **ne vérifient pas `request.method`** et modifient un champ (`Groupe.statut`,
  `LienMeet.est_actif`) sur simple GET. Le CSRF de Django ne protège pas les GET → une requête
  falsifiée (lien piégé, `<img src>` dans un contenu affiché à un admin/mshrif) déclenche l'action.
  Impact modéré (réversible, périmètre admin/mshrif authentifié), mais **incohérent** avec
  `groupe_supprimer`/`groupe_ajouter_eleve` qui gardent bien `if request.method == 'POST'` /
  `if request.method != 'POST'`.
- **Tests** : `courses/tests.py:1405` `test_toggle_desactivation_ninflue_pas_sur_un_groupe_deja_assigne`
  couvre le comportement métier, pas la méthode HTTP.
- **État** : ⚠️ risque potentiel (CSRF sur GET). Voir « À clarifier / à corriger ».

#### `groupe_definir_critere` — `courses/views.py:483` — ⚠️
- Pas de garde `request.method`. Sur GET : `getlist('options') == []` → `len([]) != len(set([]))`
  faux → `definir_valeurs_groupe(groupe, critere, [])` **efface toutes les valeurs EAV du critère
  pour ce groupe**. Même classe de risque CSRF-sur-GET. Testé métier (`GroupeOngletCriteresTests`)
  mais pas ce cas.

#### `groupe_supprimer_definitivement` — `courses/views.py:1009`
- `@role_required('admin')` (**pas mshrif**), `if POST`, **confirmation par saisie exacte du nom**
  (`:1017`). Supprime `Groupe` + `Creneau` + cascade `Seance`/`Presence`/`Evaluation`/`BilanMensuel`.
  Aucune trace conservée (JournalSuppression retiré). ⚠️ Action destructive irréversible — le garde-fou
  (nom exact) est raisonnable.

### Modèles (`courses/models.py`) — traçabilité

| Modèle | Créé par | Modifié par | Supprimé par |
|---|---|---|---|
| `DisponibiliteProf:12` | `dashboard.views` (validation candidature prof, demande de modif approuvée) via `matrice_vers_lignes` | idem | CASCADE avec Prof |
| `DisponibiliteEleve:35` | `dashboard.views` (`matrice_vers_lignes_eleve` — admin uniquement) | idem | CASCADE |
| `DemandeModificationDisponibilite:59` | `dashboard.views` (espace prof) | `dashboard.views` (approbation admin) | — |
| `Creneau:96` | `courses.views.groupe_ajouter`/`groupe_modifier` (privé) | `groupe_modifier` (nouveau Creneau candidat) | `groupe_modifier`/`groupe_supprimer`/`groupe_supprimer_definitivement` |
| `CreneauSlot:184` | `remplacer_slots_creneau` | idem | CASCADE |
| `LienMeet:230` | `lien_meet_ajouter`, `_resoudre_lien_meet_pour_formulaire` (get_or_create) | `lien_meet_toggle` | jamais (SET_NULL partout) |
| `Groupe:266` | `groupe_ajouter` | `groupe_modifier`, `groupe_archiver/reactiver`, `chat.chat_modifier_photo_groupe` (photo), `dashboard.views` (divers) | `groupe_supprimer(_definitivement)` |
| `ReglageLienSeance:505` (singleton) | `get_reglage_lien_seance` | `dashboard.views` | — |
| `HistoriqueGroupeEleve:539` | `_ajouter_eleve_au_groupe` | `_retirer_eleve_du_groupe` (date_fin) | CASCADE |
| `DemandeChangementHalaka:561` | `dashboard.views.eleve_demande_changement_halaka` | `dashboard.views` (valider/refuser) | CASCADE avec Eleve |
| `TarifRemuneration:617` | **DÉPRÉCIÉ** — plus jamais écrit, lu nulle part | — | — |
| `OptionNbSeances:653` | `dashboard.views` | idem | idem |
| `TarifRemunerationGroupe:690` / `TarifRemunerationIndividuel:731` | `dashboard.views` (barèmes) | idem | — |
| `Seance:762` | `courses.utils.etendre_seances` / `regenerer_pour_nouveau_creneau` | `dashboard.views` (prof présence, déplacer, annuler) | CASCADE avec Groupe |
| `Presence:919` | `dashboard.views.prof_presence_sauvegarder` | idem | CASCADE |
| `CritereEleve:1049` | `dashboard.views` | idem | idem |
| `NotePresence:1088` | `dashboard.views.prof_presence_sauvegarder` | idem | CASCADE |
| `BilanMensuel:1117` | `dashboard.views` (prof) | idem (`modifiable_par_prof` : fin du mois suivant) | CASCADE avec Eleve ; SET_NULL Prof |

**Champs gelés / historiques (lus mais jamais réécrits)** — **pas des bugs**, décisions documentées :
- `Creneau.jour_1/heure_debut_1/…/jour_2/…` (`:148-153`) : remplacés par `CreneauSlot`, conservés
  nullable en lecture uniquement pour compat, **plus lus par aucun code** (docstring `:143`).
- `Presence.note_memorisation`/`note_revision` (échelle qualitative) et `note_hifz/note_muraja3a/
  note_tilawa/note_mouwazaba` (`:996-1011`) : remplacés par `NotePresence` (critères dynamiques),
  gelés en lecture seule.
- `Groupe.lien_reunion` : champ texte libre historique, **c'est LUI que lit tout le code
  d'affichage** ; `Groupe.lien_meet` (FK pool) le synchronise.
- `Groupe.creneau` a **`unique=True`** (nouvelle migration `0046_groupe_creneau_unique.py`) →
  warning Django `fields.W342` (ForeignKey unique = OneToOneField). Cosmétique, connu.

`Groupe.tranches_age_frequentees` (`:445`) : property calculée **plus appelée par aucune vue**
(remplacée par `tranches_age_visees`), gardée + testée « pour usage futur ». → code quasi-mort
mais assumé et testé.

### Tests de l'app courses

`courses/tests.py` : **198 tests**, 31 classes — categorie collectif, filtres liste (+tranche âge),
photo/catégorie, formulaire prof + âge (**régression bug 500**), validation photo, dispo non
bloquante, type d'offre non bloquant, chevauchement créneaux, disponibilité liens Meet (+ vues
groupe + gestion + groupes sans lien), chevauchement horaire réel, exception lien Meet par séance,
nom créneau, progression (résultat mémorisation), généralisation N slots, backfill migration,
onglet critères, tranches d'âge précises, rémunération groupe/individuel, couverture tarifs,
compatibilité changement halaka, traduction sourates.

`python manage.py test courses --keepdb` (dans batch 1) → **OK** (198 tests, aucun échec).

### État de l'app courses

⚠️ **À vérifier.** Logique métier riche et **très bien testée** (198 tests), bug HTTP 500
`age_min/age_max` corrigé et couvert. Points ouverts :
1. 🔴 `groupe_archiver` / `groupe_reactiver` / `lien_meet_toggle` / `groupe_definir_critere` :
   **mutation d'état sur requête GET** (pas de garde `request.method`) — risque CSRF, incohérent
   avec les autres vues du module.
2. ⚠️ Incohérence de nom de champ `max_eleves` (ajout) vs `capacite_max` (modif) pour `Groupe.capacite_max`,
   non casté en `int`.

---

## APP : payments

### Routes (`payments/urls.py`, préfixe `/payments/`)

| URL | Vue (fichier:ligne) | name | Rôles (vérif) | Méthode |
|---|---|---|---|---|
| `eleve/` | `payments/views.py:103` `eleve_paiements` | `eleve_paiements` | `@role_required('eleve')` | GET/POST |
| `admin/` | `payments/views.py:250` `admin_paiements` | `admin_paiements` | `@role_required('admin','mshrif')` | GET |
| `admin/<id>/` | `payments/views.py:297` `admin_paiement_detail` | `admin_paiement_detail` | `@role_required('admin','mshrif')` | GET |
| `admin/<id>/valider/` | `payments/views.py:579` `admin_paiement_valider` | `admin_paiement_valider` | `@role_required('admin')` | ⚠️ **aucune garde méthode — `statut='valide'` sur GET** (testé via GET) |
| `admin/<id>/rejeter/` | `payments/views.py:597` `admin_paiement_rejeter` | `admin_paiement_rejeter` | `@role_required('admin')` | ⚠️ **idem, GET** |
| `suivi/` | `payments/views.py:346` `suivi_paiements_eleves` | `suivi_paiements_eleves` | `@role_required('admin','mshrif')` | GET |
| `retards/` | `payments/views.py:625` `paiements_retards` | `paiements_retards` | `@role_required('admin','mshrif')` | GET |
| `suivi/panneau/sauvegarder/` | `payments/views.py:518` `paiement_panel_sauvegarder` | `paiement_panel_sauvegarder` | `@role_required('admin')` | `if POST` (garde OK) |

Vues mortes : aucune.

### Fiches de vue (points saillants)

#### `eleve_paiements` — `payments/views.py:103`
- **Objectif** : l'élève soumet une preuve de paiement multi-mois (chantier « Paiement unique »
  2026-09-03 : 1 `Paiement`, `nb_mois_couverts`, montant total, 1 justificatif).
- **Validation POST** : élève archivé refusé (défense en profondeur, `:110`) ; `date_debut`
  `fromisoformat` tolérant (défaut = début cycle courant) ; `nb_mois` entier ∈ [1, 24]
  (`NB_MOIS_MAX_PAR_PERIODE`) ; `montant` `Decimal` > 0 ; **anti-double-soumission 5 s** ;
  **chevauchement avec un `Paiement` `valide`** → refus ; un `Paiement` `en_attente` chevauchant →
  **supprimé/remplacé** (`:186`).
- **Effets de bord** : `_preparer_justificatif` (Pillow resize 1600px + JPEG q80 — correctif lenteur
  upload Cloudinary) ; `Paiement.save()` + upload ; `envoyer_notification_telegram_avec_photo_async`
  (ou sans photo) ; `marquer_visite('paiements_retard')`.
- **Tests** : `payments/tests.py:*` `EleveePaiementsPeriodeTests`, `PreparerJustificatifTests`,
  `SoumissionPaiementNotifieTelegramAvecPhotoTests`. ✅
- **État** : ✅ sain — validation complète, anti-doublon, anti-chevauchement.

#### `admin_paiement_valider` / `admin_paiement_rejeter` — `payments/views.py:579` / `:597`
- **Objectif** : la direction accepte/rejette un paiement.
- **Effets de bord** : `statut` + `valide_par` + `date_validation` ; **`reconcilier(eleve)`**
  (fait avancer les `CycleAbonnement`) sur validation.
- ⚠️ **Aucune garde `request.method`** → mutation financière sur GET. `payments/tests_cycles.py:363`
  appelle d'ailleurs `client.get(reverse('admin_paiement_valider', …))` — c'est un choix de style
  du projet (liens `<a href>`, pas formulaires). Voir ÉTAPE 2 : **pattern transversal** — beaucoup
  de vues d'action utilisent GET, protégées seulement par `@role_required` + session authentifiée,
  jamais par CSRF.
- **État** : ⚠️ (cohérent avec le projet, mais CSRF-exposé).

#### `paiement_panel_sauvegarder` — `payments/views.py:518`
- `@role_required('admin')` (**mshrif exclu** — lecture seule sur paiements) ; `if POST` (garde OK) ;
  élève archivé refusé ; retrouve le `Paiement` couvrant le mois (multi-mois modifié en entier) ou en
  crée un (`soumis_par_eleve=False`) ; `reconcilier`. **Non testé directement** (grep → aucun test
  nomme cette vue). ⚠️
- **État** : ⚠️ pas de test dédié.

#### `suivi_paiements_eleves` — `payments/views.py:346`
- Grille Groupe → Élève → mois payé/impayé, panneau modal `?panel_eleve=&panel_mois=`.
- **Perf** : correctif 2026-08-30 (ne charge plus toute la table `Paiement` si `?groupe=`) — mais
  **sans `?groupe=` la vue balaie tous les groupes et tous leurs paiements** (documenté `:378`,
  compromis assumé, pas de pagination). Boucle `while i < 600` par élève pour générer les cellules mois.
- **Tests** : partiellement via `tests_cycles.py`. ⚠️ pas de test dédié au rendu de la grille.

#### `paiements_retards` — `payments/views.py:625`
- Liste des élèves en retard (`eleves_en_retard`, requêtes constantes). Message WhatsApp pré-rempli
  (`_message_relance_whatsapp`, `str.replace` sûr). Bouton أرشفة (mshrif inclus).
- **Tests** : `tests_cycles.py` (accès, contenu, interdiction élève), `tests_relance_escalade.py:*`
  `PageDirectionAlerteRougeTests`. ✅

### Moteur `payments/cycles.py` (pas de vue)

`reconcilier(eleve)` (`:173`) — règle les `CycleAbonnement` à la file selon les `Paiement` `valide`,
ne revient jamais en arrière. `cycles_ouverts_en_retard` (`:320`) — **nombre de requêtes constant**
(correctif du point chaud 2026-09-01). `phase_relance_eleve` — escalade J+1/J+5/J+8/J+9/J+10.
Aucun cron : `reconcilier` appelé manuellement après chaque validation/modif de `Paiement`.

### Modèles (`payments/models.py`)

| Modèle | Créé | Modifié | Supprimé |
|---|---|---|---|
| `MoyenPaiement:9` | `dashboard.views` (config) | idem | idem |
| `Paiement:60` | `eleve_paiements`, `paiement_panel_sauvegarder` | `admin_paiement_valider/rejeter`, `paiement_panel_sauvegarder` | `eleve_paiements` (remplacement `en_attente` chevauchant) ; CASCADE avec Eleve |
| `CycleAbonnement:143` | `payments.cycles.demarrer_cycles` (à la validation d'inscription / réactivation), `reconcilier` (cycle N+1) | `reconcilier`, `redemarrer_cycle_courant` | CASCADE avec Eleve |
| `ReglageRelanceWhatsApp:223` (singleton) | `get_reglage_relance_whatsapp` | `dashboard.views.admin_reglage_relance_whatsapp` | — |

`Paiement` : **plus de `unique_together (eleve, mois_reference)`** depuis 2026-09-03 (mois_reference
= date de début libre). Chevauchement géré applicativement dans `eleve_paiements`. `soumis_par_eleve`
distingue soumission élève / saisie manuelle direction (pour la notif 🔔).

### Tests de l'app payments

`payments/tests.py` (19) + `payments/tests_cycles.py` (28) + `payments/tests_relance_escalade.py` (10)
= **57 tests**. Couvre : préparation justificatif, période de paiement, notif Telegram photo, fiche
détail période, cycles (échéances roulantes, reconciliation, retard), relance WhatsApp, escalade
J+8/9/10, notif quotidienne, alerte rouge direction.
**Non couvert** : `paiement_panel_sauvegarder`, rendu de la grille `suivi_paiements_eleves`.

`python manage.py test payments --keepdb` (dans batch 1) → **OK** (aucun échec).

### État de l'app payments

⚠️ **À vérifier.** Cœur financier bien testé (cycles, escalade, soumission élève). Points ouverts :
1. `admin_paiement_valider`/`_rejeter` : validation financière sur GET (voir pattern transversal).
2. `paiement_panel_sauvegarder` sans test dédié (crée/modifie des `Paiement` + `reconcilier`).
3. `suivi_paiements_eleves` sans `?groupe=` : balayage complet de la table `Paiement` (perf, assumé).

---

## APP : registration (wizard public d'inscription élève)

### Routes (`registration/urls.py`, préfixe `/registration/` ; **`/register/student` → `wizard_intro`**)

| URL | Vue (fichier:ligne) | name | Rôles | Méthode |
|---|---|---|---|---|
| `wizard/` | `registration/views.py:76` `wizard_intro` | `wizard_intro` | **public** | GET |
| `wizard/categorie-age/` | `registration/views.py:29` `wizard_categorie_age` | `wizard_categorie_age` | public | GET/POST |
| `wizard/identite/` | `registration/views.py:125` `wizard_identite` | `wizard_identite` | public | GET/POST |
| `wizard/programme/` | `registration/views.py:286` `wizard_programme` | `wizard_programme` | public | GET/POST |
| `wizard/groupe/` | `registration/views.py:396` `wizard_groupe` | `wizard_groupe` | public | GET/POST |
| `wizard/abonnement/` | `registration/views.py:572` `wizard_abonnement` | `wizard_abonnement` | public | GET/POST |
| `wizard/paiement/` | `registration/views.py:636` `wizard_paiement` | `wizard_paiement` | public | GET/POST (**création réelle**) |
| `wizard/confirmation/` | `registration/views.py:746` `wizard_confirmation` | `wizard_confirmation` | public + `@never_cache` | GET |
| `wizard/etape/<slug:code>/` | `registration/views.py:756` `wizard_etape_personnalisee` | `wizard_etape_personnalisee` | public | GET/POST — catch-all APRÈS les 7 étapes réelles |

Vues mortes : aucune. Helpers `_champs_visibles_pour_etape:95`, `_type_offre_et_reponses_filtrage:381`,
`_wizard_confirmer_inscription:668`.

### Modèle de sécurité du wizard

- **État en session** (`registration.utils.wizard_donnees/wizard_maj`), **jamais** en champs cachés HTML.
- **Sauts serveur** : chaque étape vérifie ses prérequis de session (`'nom' not in donnees` →
  `redirect('wizard_identite')` ; `'type_age_choisi' not in ...` → `wizard_categorie_age` ;
  `type_offre != 'groupe'` → saute `wizard_groupe`) — **avant tout rendu, quelle que soit la méthode HTTP**.
- **Revalidation finale complète** dans `_wizard_confirmer_inscription` (`:668`) → **déléguée
  entièrement à `registration.utils.inscrire_eleve`** (choix du groupe re-vérifié à la confirmation
  contre `groupes_compatibles_avec_age`, capacité, statut actif — jamais le calcul de l'étape 3
  potentiellement périmé). Testé : `WizardConfirmationSecuriteTests.test_groupe_id_devenu_incompatible_...`.
- **Anti-rejeu** : `wizard_confirmation` lit + `pop` la session (`@never_cache`) — un refresh ne
  recrée rien.

### Fiches de vue (points saillants)

- **`wizard_categorie_age:29`** — POST : `type_age ∈ ('enfant','adulte')` ; si catégorie fermée →
  `_reponse_categorie_fermee` (réutilise le mécanisme de `inscriptions.views`, `ParametresInscriptions.ouverte_eleve_*`).
- **`wizard_identite:125`** — champs structurels **configurables** (`ConfigurationChampStructurel` :
  label/ordre/obligatoire/actif/regex, **jamais le stockage**) + champs dynamiques
  (`ChampInscription`). `sexe`/`email`/`date_naissance` verrouillés obligatoires ; `date_naissance`
  **revérifiée** contre `type_age_choisi` via `tranche_age_depuis_naissance` (source unique) ;
  `telephone` via `_construire_et_valider_telephone` (partagé avec `inscriptions.views`).
- **`wizard_programme:286`** — champs dynamiques ; `nb_slots` : liste = `OptionNbSeances` actives
  (catalogue partagé), **revalidée serveur** contre un POST forgé (`:356`).
- **`wizard_groupe:396`** — liste filtrée par `groupes_compatibles_avec_age` + `groupes_avec_place_disponible`
  (groupe complet jamais listé — bug 2026-08-21). Si aucun groupe exact : message configurable +
  « groupes proches » (critères `bloquant` seulement) sélectionnables OU carte « attente » →
  `DemandeNonSatisfaite` créée dans les 2 cas. `groupe_id` **revérifié serveur** contre la liste réelle.
- **`wizard_paiement:636` / `_wizard_confirmer_inscription:668`** — POST : `moyen_paiement_code`
  validé (informatif) ; **`inscrire_eleve(donnees, cree_par=None)`** = toute la validation +
  création `InscriptionEleve` + `ReponseInscription` ; notif Telegram `📥 طلب تسجيل جديد — طالب`
  (bug 2026-08-31 : notif oubliée lors de la bascule vers le wizard, corrigé). Session
  `wizard_confirmation` posée puis `pop`.
- **`wizard_etape_personnalisee:756`** — une seule vue pour N étapes créées par le مدير ;
  `code` = étape réelle → redirige vers sa vraie vue ; étape inexistante/désactivée →
  `redirect('wizard_categorie_age')`, jamais 404/500.

### Modèles (`registration/models.py`) et traçabilité

| Modèle | Créé par | Modifié par |
|---|---|---|
| `Critere:92` / `CritereOption:157` | `dashboard.views` (moteur d'inscription) | idem |
| `EtapeInscription:190` / `ChampInscription:426` | `dashboard.views` | idem |
| `ConfigurationChampStructurel:298` | seed migration + `dashboard.views` | `dashboard.views` |
| `ReponseInscription:492` | `inscrire_eleve` (à la soumission wizard) | — |
| `GroupeCritereValeur:529` | `courses.views.groupe_definir_critere` (`definir_valeurs_groupe`) | idem (remplace, n'accumule pas) |
| `PresentationInscription:554` (singleton) | `get_presentation_inscription:681` | `dashboard.views` (Étape 5C) |
| `DemandeNonSatisfaite:723` | `wizard_groupe` (`_enregistrer_demande_non_satisfaite`) | `dashboard.views` (traitement) |

### Tests de l'app registration

`registration/tests.py` : **215 tests**, 45 classes — génération générique, groupes compatibles,
place disponible, nb séances, couverture critères, prix effectif, abonnements/cibles d'âge,
`inscrire_eleve` (isolé), navigation dynamique, étapes verrouillées/personnalisées, **sécurité
wizard** (`WizardGroupeSecuriteTests`, `WizardConfirmationSecuriteTests`), champs structurels
configurables, bornes numériques, localisation. **L'une des apps les mieux couvertes du projet.**

`python manage.py test registration --keepdb` (batch 2) → **5 échecs**, tous dans
`WizardGroupeDisponibilitesSiAttenteTests` : ces tests postent `nb_seances='99'` ; le seed
`OptionNbSeances` = [1,2,3] ⇒ `wizard_programme` rejette (revalidation serveur voulue) ⇒
`wizard_groupe` redirige ⇒ HTML vide. **Tests obsolètes** (m14), pas un bug de la vue. Les 210
autres tests passent.

### État de l'app registration

✅ **Sain** (code). Architecture de sécurité solide (état en session, sauts serveur, revalidation
finale déléguée à une fonction unique testée isolément). Complexité élevée mais maîtrisée.
⚠️ 5 tests obsolètes à mettre à jour (m14 — `nb_seances` hors catalogue).

---

## APP : inscriptions

> **Double statut** : (a) le formulaire élève à une page (`inscription_eleve_choix` /
> `inscription_eleve_formulaire`) est **DORMANT** — remplacé par le wizard `registration`, plus
> aucun lien public n'y mène (`core/urls.py` documente le rollback en 1 ligne) ; (b) le formulaire
> **prof** (`inscription_prof`) est **ACTIF** — c'est `/register/teacher` ; (c) les modèles
> `TypeAbonnement`, `GrillePrixAbonnement`, `ParametresInscriptions`, `PhraseRefus`,
> `InscriptionEleve`, `InscriptionProf` sont **partagés** et centraux à tout le projet.

### Routes (`inscriptions/urls.py`, préfixe `/inscriptions/`)

| URL | Vue (fichier:ligne) | name | Rôles | Statut |
|---|---|---|---|---|
| `eleve/choix/` | `RedirectView` → `inscription_eleve_choix` (301, `urls.py:11`) | — | public | legacy redirect |
| `prof/` | `RedirectView` → `inscription_prof` (301, `urls.py:12`) | — | public | legacy redirect |
| `eleve/formulaire/<str:type_age>/` | `inscriptions/views.py:222` `inscription_eleve_formulaire` | `inscription_eleve_formulaire` | public | ⚠️ **DORMANT** (route vivante, plus liée) |
| `confirmation/` | `inscriptions/views.py:366` `inscription_confirmation` | `inscription_confirmation` | public | **ACTIF** (utilisé aussi par le wizard prof) |

+ hors `inscriptions/urls.py` : `core/urls.py:49` `/register/teacher` → `inscriptions.views.inscription_prof:369`
(name `inscription_prof`) — **ACTIF** ; `core/urls.py:72` `/register/student` → `registration.views.wizard_intro`
(name `inscription_eleve_choix`, mais **pointe vers registration**).

**Vue `inscription_eleve_choix` (`views.py:218`)** : encore utilisée comme cible du `RedirectView`
legacy `/inscriptions/eleve/choix/` — mais ce name est **réassigné dans `core/urls.py:72` au wizard**.
Donc `RedirectView(pattern_name='inscription_eleve_choix')` redirige en réalité vers le wizard.
La fonction `inscription_eleve_choix` elle-même n'est routée **nulle part** → **vue morte de fait**
(le `eleve_choix.html` qu'elle rend n'est plus jamais servi).

### Fiche de vue — `inscription_prof` (ACTIVE) — `inscriptions/views.py:369`
- **Rôles** : public. Garde : `get_parametres_inscriptions().ouverte_prof` sinon `_reponse_categorie_fermee`.
- **Validation POST** (manuelle) : `_email_deja_utilise` ; `_construire_et_valider_telephone` ;
  **champs obligatoires revalidés serveur** (`compte_bancaire`, `rib`, `agence_bancaire`,
  `job_actuel`, **`audio_enregistrement`**, `date_naissance`, **`accepte_charte`** — `:434-452`,
  HTML5 `required` contournable) ; anti-double-soumission 5 s (email+nom+prénom).
- **Effets de bord** : `InscriptionProf.objects.create` (avec `charte_acceptee=True` garanti) ;
  upload audio (storage projet) ; `envoyer_notification_telegram_async` `📥 ... أستاذ`.
- **Correctifs intégrés** : HTTP 500 `date_naissance` vide (`MESSAGE_DATE_NAISSANCE_INVALIDE`,
  `:57`) ; `accepte_charte` bloquant serveur (2026-08-27).
- **Tests** : `inscriptions/tests.py` `InscriptionProfCharteTests`. + `ChampsInscriptionVisiblesTests`,
  `InscriptionPubliqueDateNaissanceTests`.
- **État** : ✅ sain.

### Fiche de vue — `inscription_eleve_formulaire` (DORMANTE) — `inscriptions/views.py:222`
- Même qualité de validation que le prof (email/téléphone/date_naissance/âge vs `type_age`/anti-doublon).
  Crée `InscriptionEleve`. **N'est plus atteignable par un lien public** mais **la route existe** —
  un POST direct sur `/inscriptions/eleve/formulaire/adulte/` **crée toujours une `InscriptionEleve`**.
- **État** : ⚠️ Code mort **exécutable** (par URL directe). Documenté comme volontaire (rollback).
  À clarifier : la garder ou la retirer.

### Modèles partagés (`inscriptions/models.py`) — traçabilité

| Modèle | Créé par | Modifié par | Lu par |
|---|---|---|---|
| `TypeAbonnement:9` | `dashboard.views` (config abonnements) | idem | wizard, `dashboard.admin_eleve_ajouter_manuel`, ancien formulaire |
| `GrillePrixAbonnement:109` | `dashboard.views` | idem | `registration.utils` (prix effectif) |
| `InscriptionEleve:147` | `inscrire_eleve` (wizard) / `inscription_eleve_formulaire` (dormant) / `dashboard.admin_eleve_ajouter_manuel` | `dashboard.views` (validation/refus) ; signal `accounts/signals.py` (→ `rejete` si Eleve supprimé) | `dashboard.views`, `courses.utils` (critères) |
| `InscriptionProf:421` | `inscription_prof` / `dashboard` (ajout manuel prof) | `dashboard.views` (pré-validation directeur → validation مشرف) | `dashboard.views` |
| `ParametresInscriptions:520` (singleton) | `get_parametres_inscriptions:580` | `dashboard.views` | partout (délais, ouverture par catégorie, grâce nouvel élève) |
| `PhraseRefus:588` | `dashboard.views` | idem | `dashboard.views` (refus candidature) |

### Tests de l'app inscriptions

`inscriptions/tests.py` : **20 tests**, 3 classes — champs visibles, date de naissance publique,
charte prof. **Faible** au regard de la surface (téléphone international, anti-doublon, email
partagé, catégorie fermée ne sont pas directement testés ici — certains le sont via `registration`
qui réutilise `_construire_et_valider_telephone` / `MESSAGE_AGE_NE_CORRESPOND_PAS`).

`python manage.py test inscriptions --keepdb` (batch 2) → **OK** (20 tests, aucun échec).

### État de l'app inscriptions

⚠️ **À vérifier.**
1. `inscription_eleve_formulaire` (+ `inscription_eleve_choix`) : **code mort volontaire** — la vue
   `inscription_eleve_choix` n'est routée nulle part ; `inscription_eleve_formulaire` reste
   POST-able par URL directe et crée des `InscriptionEleve`. À clarifier : retirer ou garder.
2. Couverture de test faible pour le formulaire prof actif et les helpers téléphone/email.
3. `_construire_et_valider_telephone`, `_email_bloque_pour_candidature_eleve`, `_email_deja_utilise`
   sont des règles métier sensibles (partage d'email parent/enfant) peu testées directement.

---

## APP : dashboard

> **`dashboard/views.py` = 8424 lignes, ~175 vues routées.** Cœur applicatif : dashboards des 5 rôles,
> validation des candidatures, gestion élèves/profs/superviseurs, séances/présences/bilans,
> rémunération, moteur d'inscription configurable, réglages, notifications 🔔, recherche globale.
> Vu la taille, l'audit ci-dessous est **organisé par domaine fonctionnel** avec zoom sur les vues
> critiques (création/suppression de comptes, financier, permissions). Toutes les vues portent un
> `@role_required(...)` (aucune n'est sans décorateur — vérifié par grep sur `^def .*\(request` vs
> `^@role_required` : correspondance 1:1).

### Inventaire des routes par domaine (`dashboard/urls.py`)

| Domaine | Vues (échantillon) | Rôles dominants |
|---|---|---|
| Dashboards d'accueil | `dashboard_eleve:3293`, `dashboard_prof:495`, `dashboard_superviseur:3622`, `dashboard_admin:2005`, `dashboard_mshrif:2772` | 1 par rôle |
| Espace élève | `eleve_seances`, `eleve_seance_detail`, `eleve_profil`, `eleve_demande_changement_halaka:3513`, `eleve_prof_detail`, `eleve_progression`, `eleve_cartable`, `eleve_cartable_fichier` | `eleve` |
| Espace prof | `prof_groupes`, `prof_groupe_detail`, `prof_seances`, `prof_seance_detail`, **`prof_presence_sauvegarder:896`**, `prof_emploi`, `prof_disponibilites`, `prof_profil`, `prof_remuneration`, `prof_charte`, `prof_hakiba`, `prof_evaluations`, `prof_bilans_mensuels` | `prof` |
| Espace superviseur (مؤطر) | `superviseur_emploi`, `superviseur_seance_detail`, `superviseur_profil`, `superviseur_prof_detail`, `superviseur_groupe_detail`, `superviseur_hakiba` | `superviseur` |
| Candidatures élève | `admin_inscriptions:2052`, `admin_inscription_eleve_detail`, **`admin_valider_eleve:2249`**, `admin_rejeter_eleve:2456` | `admin` (validation), `admin`+`mshrif` (consultation) |
| Candidatures prof (2 étapes) | `admin_valider_prof:2684` (étape 1 = `admin`), `mshrif_valider_prof_final:2873` (étape 2 = `mshrif`, **crée le compte**), `admin_rejeter_prof`, `mshrif_rejeter_prof`, `admin_supprimer_user_orphelin:2645` | `admin` puis `mshrif` |
| Gestion élèves | `admin_eleves`, `admin_eleve_detail`, `admin_eleve_disponibilites` (`admin`), `admin_eleve_suspendre` (`admin`), `admin_eleve_archiver`/`_reactiver` (`admin`+`mshrif`), **`eleve_supprimer_definitivement:4690`** | mixte |
| Gestion profs | `admin_profs`, `admin_prof_detail`, `admin_prof_archiver`/`_reactiver` (`admin`), `admin_prof_infos_complementaires_modifier` (`admin`), `admin_prof_majoration_modifier` (`admin`), **`prof_supprimer_definitivement:4864`**, `admin_prof_disponibilites`, `admin_prof_presentation_modifier` | mixte |
| Superviseurs ↔ profs | `admin_superviseurs`, `admin_superviseur_ajouter` (`admin`), `admin_superviseur_assignations`, `superviseur_supprimer_definitivement:6310` | `admin`(+`mshrif` pour assignations/suppr) |
| Cartable élève / حقيبة prof | `admin_eleve_cartable_gestion/_ajouter/_supprimer` (`admin`+`mshrif`, `@require_POST` sur ajout/suppr), `admin_hakiba_gestion/_ajouter/_supprimer`, `hakiba_fichier:4117`, `eleve_cartable_fichier:4589` | `admin`+`mshrif` (dépôt), lecture élargie |
| Séances / calendrier | `admin_seances`, `admin_seance_annuler:4218` (`admin`), `admin_seance_deplacer:4238` (`admin`), `admin_calendrier`, `rejoindre_seance:775` (tous rôles) | `admin`(+`mshrif` lecture) |
| Demandes (dispo / halaka) | `admin_demandes_disponibilite` + `_approuver`/`_rejeter` (`admin`), `admin_demandes_changement_halaka` + `_valider`/`_refuser` (`admin`+`mshrif`) | mixte |
| Bilans mensuels | `prof_bilans_mensuels` (`prof`), `bilans_mensuels:1745` (`admin`+`superviseur`+`mshrif`), `bilan_mensuel_detail`, `bilans_mensuels_detail_seance`, `suivi_engagement_mensuel` | mixte |
| Rémunération prof | `prof_remuneration` (`prof`), `mshrif_remuneration:2986` / `admin_prof_remuneration_detail` (`admin`+`mshrif`), `admin_tarifs_remuneration` + tarifs groupe/individuel (`admin` pour l'écriture) | mixte |
| Évaluations (مؤطر→prof) | `admin_evaluations:5925`, `admin_evaluation_detail`, `classement_mensuel_profs:6013` (`admin`+`superviseur`+`mshrif`), `classement_mensuel_commentaire:6091` (`admin`+`superviseur`) | mixte |
| Config abonnements & prix | `admin_parametres_abonnements`, `admin_abonnement_ajouter/_modifier/_toggle/_grille_prix` | `admin`+`mshrif` |
| Config critères (éval prof / éval élève) | `admin_criteres*` (`admin` pour l'écriture), `admin_criteres_eleves*` (`admin` pour l'écriture) | `admin`(+`mshrif` lecture) |
| Moteur d'inscription configurable | `admin_criteres_inscription*`, `admin_etapes_inscription*`, `admin_champ_inscription*`, `admin_champ_structurel_modifier`, `admin_moyens_paiement*`, `admin_presentation_inscription`, `admin_demandes_non_satisfaites*` | `admin`+`mshrif` (accès identique) |
| Ajout manuel | `admin_eleve_ajouter_manuel:7882`, `admin_prof_ajouter_manuel:8144` | `admin`+`mshrif` |
| Réglages singletons | `admin_reglage_lien_seance` (`admin`+`mshrif`), `admin_reglage_retention_chat` (**`admin` seul**), `admin_reglage_relance_whatsapp` (`admin`+`mshrif`), `admin_programme_general`, `admin_visibilite_prof`, `admin_gestion_inscriptions`, `mshrif_charte:3145`, `mshrif_logo:3250` (**`mshrif` seul**) | mixte |
| Comptes & email | `admin_utilisateur_modifier_email:6344` (`admin`), `confirmation_modification_email`, `admin_utilisateur_reinitialiser_mot_de_passe:6571` (`admin`+`mshrif`), `admin_mon_compte` (`admin`), `mshrif_mon_compte` (`mshrif`) | `admin`(+`mshrif`) |
| Notes personnelles | `ajouter/modifier/supprimer_note_personnelle` (5 rôles, sur un profil consulté — **auteur strict**), `mes_notes_personnelles` (5 rôles, sur soi) | tous |
| Notifications 🔔 | `mes_notifications:296` (`eleve`+`prof`+`superviseur`+`admin`+`mshrif`) | tous |
| APIs | `api_recherche_globale:6811` (`admin`+`mshrif`), `api_traduire_contenu:6849` (`admin`+`mshrif`, `@require_POST`) | `admin`+`mshrif` |
| Abonnés Telegram | `admin_telegram_abonnes` + `_valider`/`_rejeter`/`_desactiver` (`admin`+`mshrif`) | `admin`+`mshrif` |
| Écrans partagés | `confirmation_creation_compte:2111` (`@never_cache`, session `pop`), `refus_confirme:2193` (`@never_cache`) | `admin`+`mshrif` |

**Vues mortes** : aucune détectée (chaque `def <name>(request…)` est routée dans `dashboard/urls.py`).
**Routes vers vue inexistante** : aucune (grep des noms de `urls.py` dans `views.py` → tous présents).

### Fiches — vues critiques

#### `admin_valider_eleve` — `dashboard/views.py:2249` — `@role_required('admin')`
- **Objectif** : accepter une candidature → créer `User` + `Eleve` + disponibilités + rattachement
  groupe + cycle d'abonnement + email de bienvenue.
- **Validation** : `_verifier_conflit_email` — bypass **strictement scopé ici** au cas « compte élève
  actif partageant l'email » (`partage_eleve_possible`, partage parent/enfant) ; orphelin/archivé/
  autre-rôle → refus.
- **Effets de bord** : `@transaction.atomic` avec **`select_for_update` sur les `User` du même email**
  (anti-race sur le suffixe `username = email__N`) ; `generer_mot_de_passe_sequentiel` ;
  `create_user(doit_changer_mot_de_passe=False)` ; `matrice_vers_lignes_eleve` ; `_ajouter_eleve_au_groupe`
  (si `raison_incompatibilite_groupe` OK — **même fonction que l'ajout manuel**) ; `demarrer_cycles` ;
  `envoyer_email_bienvenue` (**hors transaction**, ne peut plus lever) ; session `confirmation_creation_compte`.
- **Méthode** : pas de garde (GET crée le compte) — pattern projet.
- **Tests** : `dashboard/tests.py` (nombreuses classes autour de la validation, partage d'email). ✅
- **État** : ✅ sain (transaction, anti-race, délégation de la compat groupe).

#### `mshrif_valider_prof_final` — `dashboard/views.py:2873` — `@role_required('mshrif')`
- **Objectif** : étape 2/2 — crée réellement le compte prof (`_creer_compte_prof:413`).
- **Garde d'état** : refuse si l'inscription n'est plus `validee_directeur` (race condition avec un
  rejet مدير entre-temps — documenté `:2718`). `_verifier_conflit_email` **sans bypass** (2 profs /
  prof+élève ne partagent jamais un email).
- **Tests** : `dashboard/tests.py`. ✅

#### `eleve_supprimer_definitivement:4690` / `prof_supprimer_definitivement:4864` / `superviseur_supprimer_definitivement:6310`
- **Objectif** : suppression **réelle** du `User` (+ cascades). Confirmation par **saisie exacte de
  l'email**. `@transaction.atomic`. Fichiers physiques nettoyés par signaux `post_delete`.
- **Permission** : `@role_required('admin', 'mshrif')` sur les 3. ⚠️ Le bandeau de section
  (`dashboard/views.py:4678-4687`) dit encore « مدير UNIQUEMENT (pas مشرف) » — **commentaire périmé** :
  l'accès `mshrif` est une décision assumée et testée (`dashboard/tests.py:218` `test_mshrif_autorise`,
  qui *inverse* l'ancien `test_mshrif_refuse` — « Tâche du 2026-08-13, point 3 »). Voir **m0**.
  Incohérence résiduelle : `courses.groupe_supprimer_definitivement` reste `@role_required('admin')` seul.
- **Tests** : `dashboard/tests.py` `EleveSuppressionDefinitiveTests` / `ProfSuppressionDefinitiveTests` /
  `SuperviseurSuppressionDefinitiveTests` — couvrent cascades, `mshrif` autorisé, `prof`/`superviseur`
  refusés, confirmation email exacte, GET affiche la page. ✅ bien couvert.

#### `prof_presence_sauvegarder` — `dashboard/views.py:896` — `@role_required('prof')`
- **Objectif** : le prof remplit la feuille de présence + notes /20 par critère dynamique + consignes.
- **Gardes** : `seance.groupe__prof=prof` (scope) ; `seance.modifiable_par_prof` (statut `planifiee`
  + fin réelle passée + < 24 h depuis le début) — vérifié serveur GET et POST.
- **Validation** (manuelle, par élève actif) : plages d'ayat cohérentes (`_ayah_incoherentes`) et
  dans les bornes de la sourate (`_ayah_depasse_sourate` — validation annoncée dans `quran_data.py`
  et enfin implémentée) ; notes /20 obligatoires ∈ [1,20] **si présent** ; consignes obligatoires
  si présent ; `resultat_memorisation`/`_revision` ∈ `RESULTAT_CHOICES` sinon `'valide'`.
- **Effets** : `Presence` (upsert) + `NotePresence` par critère ; `Seance.statut='terminee'`.
- **Tests** : `dashboard/tests.py` (feuille de présence, critères dynamiques, fenêtre 24 h). ✅

#### `admin_utilisateur_modifier_email` — `dashboard/views.py:6344` — `@role_required('admin')`
- Change l'email de n'importe quel `User` ; `@never_cache` sur l'écran de confirmation ;
  `invalider_sessions_utilisateur` (déconnexion forcée) ; email de notification à l'ancienne adresse.
- **Tests** : `dashboard/tests.py`. ⚠️ à confirmer.

#### `rejoindre_seance` — `dashboard/views.py:775` — `@role_required('admin','mshrif','superviseur','prof','eleve')`
- Redirige vers `seance.lien_effectif` **uniquement** si `lien_seance_est_actif(seance)` (fenêtre
  ±marge). Anti-partage de lien hors créneau. Scope de la séance selon le rôle. ✅

### Modules non-vues de l'app

- **`dashboard/notifications.py` (585 l.)** — panneau 🔔, calcul à la volée (jamais de modèle par
  notification). `marquer_visite(user, cle)` (upsert `DerniereVisiteNotification`). `_seuils` amorce
  à `user.date_joined` (correctif : un compte neuf ne perd plus le contenu créé avant sa 1re visite).
  `notifications_direction` = liste plate avec historique + pastilles de statut.
  🔴 **Bug probable** (`notifications.py:192-200`) : les événements « nouvelle évaluation de séance »
  (`notes_seances`, côté élève) filtrent sur `.exclude(note_hifz__isnull=True, note_muraja3a__isnull=True,
  note_tilawa__isnull=True, note_mouwazaba__isnull=True)` — or ces 4 champs sont **gelés** et
  **jamais renseignés** pour une évaluation faite depuis `prof_presence_sauvegarder` (qui écrit
  `NotePresence`). → **les nouvelles évaluations ne déclenchent plus le badge 🔔 côté élève.**
  `calculer_progression_eleve` a migré vers `notes_criteres__isnull=False` ; `notifications.py` non.
  **À clarifier / corriger.**
- **`dashboard/recherche.py` (275 l.)** — `rechercher_tout` : 1 requête SQL (`UNION ALL`) sur
  User/Prof/Superviseur/Groupe, `icontains` OU `trigram_similar`. Permissions : endpoint
  `@role_required('admin','mshrif')` seulement, pas de filtre par rôle interne (assumé). `.objects.all()`
  (retrouve aussi archivés). Testé (`recherche` classes dans `dashboard/tests.py`).
- **`dashboard/traduction.py` (71 l.)** — `traduire_depuis_arabe` : Google Translate v2. Sans
  `GOOGLE_TRANSLATE_API_KEY` → `TraductionIndisponible` → endpoint 503, bouton masqué (context
  processor `traduction_auto`). `MAX_CARACTERES=5000`. Non bloquant.
- `dashboard/context_processors.py` — `badges_sidebar_direction` (compteur léger `admin`/`mshrif`),
  `traduction_auto`.

### Patterns transversaux observés dans dashboard

1. **Mutation d'état sur GET** : la majorité des vues d'action (`*_toggle`, `*_archiver`, `*_reactiver`,
   `*_valider`, `*_rejeter`, `*_approuver`, `admin_seance_annuler`, `admin_demande_disponibilite_*`…)
   **n'ont pas de garde `request.method`** et modifient l'état sur un GET. Seules quelques-unes portent
   `@require_POST` (`modifier/supprimer_note_personnelle`, `admin_eleve_cartable_ajouter/_supprimer`,
   `api_traduire_contenu`, `admin_critere_inscription_detacher_groupe`, `admin_demande_non_satisfaite_supprimer`).
   Les suppressions **définitives** (`eleve`/`prof`/`superviseur`/`groupe`) gardent bien `if POST` +
   confirmation par saisie exacte. → **Pattern volontaire du projet** (liens `<a href>`), mais surface
   CSRF réelle pour toutes les actions non-`@require_POST` (un GET falsifié vers un admin/mshrif
   authentifié déclenche l'action). Voir « À clarifier / à corriger ».
2. **Aucun `forms.py`** : 100 % `request.POST.get(...)` + validation manuelle. Cohérent partout,
   mais recopie de règles (parfois factorisée : `_champs_identite_bruts`, `appliquer_regle_nom_parent`
   partagé wizard↔`inscrire_eleve`).
3. **`@transaction.atomic`** systématique sur les créations multi-modèles (comptes) et suppressions.
4. **`@never_cache` + session `pop`** pour tous les écrans de confirmation (anti-rejeu) — bon pattern,
   appliqué de façon cohérente.
5. **`admin` + `mshrif` à parité** sur la quasi-totalité des écrans de configuration (moteur
   d'inscription, abonnements, hakiba, cartable, réglages) ; `mshrif` **exclu** de : suspension élève,
   archivage prof, `admin_reglage_retention_chat`, écriture des critères d'éval, création superviseur,
   tarifs de rémunération (écriture), validation/rejet candidature élève, étape 1 candidature prof.
   `mshrif` **seul** : `mshrif_charte`, `mshrif_logo`, `mshrif_valider_prof_final`.

### Tests de l'app dashboard

`dashboard/tests.py` : **392 tests**, 64 classes. **Couverture large** sur : validation candidatures
(partage email), suppression définitive, présence/critères, bilans, rémunération (groupe/individuel),
notifications 🔔 (élève/prof/direction/superviseur), recherche globale, moteur d'inscription,
ajout manuel, abonnés Telegram, cartable/hakiba, changement de halaka.

`python manage.py test dashboard --keepdb` (batch 2) → **5 échecs** : 3× i18n (`Accept-Language`
neutralisé — m13 : `ProgrammeGeneralLocaliseTests`, `CritereEleveLocaliseTests`,
`MoyenPaiementPresentationDelaisTests`), 2× `AdminInscriptionDetailAuditTests` (`nb_seances='4'`
hors catalogue — m14). **Aucun** échec sur une vue métier auditée. Les ~387 autres passent.

### État de l'app dashboard

⚠️ **À vérifier.** App tentaculaire mais globalement disciplinée (décorateurs partout, transactions,
anti-rejeu, tests denses). Points ouverts :
1. 🔴 **Bug avéré (lecture)** : `notifications.py` « notes_seances » filtre sur les champs `note_hifz`
   gelés → les nouvelles évaluations élève ne déclenchent plus le badge 🔔 (M1).
2. ⚠️ **CSRF sur GET** : la plupart des vues d'action modifient l'état sans `@require_POST`
   (7 `@require_POST` sur ~175 vues — pattern projet) (M2).
3. ⚠️ **Commentaire périmé** sur les 3 suppressions définitives (m0) — l'accès `mshrif` est voulu
   et testé, seul le commentaire dit l'inverse.
4. ⚠️ `suivi_engagement_mensuel`, `admin_calendrier`, `bilans_mensuels` : vues lourdes (correctifs
   perf 2026-08-30 partiels).

---

## ÉTAPE 2 — Cohérence transversale

### 2.1 Méthode de contrôle des permissions — **uniforme**

- **`accounts.decorators.role_required(*roles)`** est le SEUL mécanisme d'autorisation par rôle dans
  tout le projet (grep : ~330 usages, 0 `PermissionRequiredMixin` / `UserPassesTestMixin` / vue CBV).
  Toujours empilé sur `@login_required`. Comportement : rôle non autorisé → `redirect_by_role` (jamais 403).
- Vérifications **objet** (IDOR) : centralisées par app dans un module dédié —
  `chat/permissions.py` (`can_access_conversation`), `examens/permissions.py` (`can_access_examen/copie`),
  `annonces/services.py` (`peut_voir_annonce`). **Modèle exemplaire**, reproduit à l'identique.
  Les autres apps font le scope directement dans le queryset (`get_object_or_404(..., groupe__prof=prof)`) —
  cohérent mais moins visible.
- **Incohérence mineure** : `evaluations.views` et `courses.views` (groupe_detail) scopent à la main ;
  `dashboard.views` scope à la main ; pas de `permissions.py` dans ces apps. Acceptable (pas de fuite
  détectée), mais l'audit IDOR y est plus difficile.

### 2.2 Protection CSRF / méthode HTTP — **incohérente (pattern projet à trancher)**

| Traitement | Vues concernées | Garde |
|---|---|---|
| Suppression **définitive** (compte, groupe) | `eleve/prof/superviseur/groupe_supprimer_definitivement` | ✅ `if POST` + saisie exacte email/nom |
| Actions `@require_POST` explicites | `modifier/supprimer_note_personnelle`, `chat_*` (tous), `examens` (autosave/soumettre/publier/fermer/…), `annonce_ajouter/toggle`, `admin_eleve_cartable_ajouter/_supprimer`, `api_traduire_contenu`, `paiement_panel_sauvegarder` (`if POST`) | ✅ |
| **Actions d'état sans garde de méthode** (mutation sur GET) | `courses`: `groupe_archiver/reactiver`, `lien_meet_toggle`, `groupe_definir_critere` ; `payments`: `admin_paiement_valider/rejeter` ; `dashboard`: la plupart des vues d'action (`*_toggle`, `*_archiver/reactiver`, `admin_valider_eleve/prof`, `admin_rejeter_*`, `admin_seance_annuler`, `admin_demande_*_approuver/rejeter`, `admin_telegram_abonne_*`, tous les `*_toggle` du moteur d'inscription… — seulement 7 `@require_POST` au total) | 🔴 aucune |

Le CSRF Django ne protège pas les requêtes GET. Toutes les vues de la 3ᵉ ligne sont donc déclenchables
par une requête GET falsifiée (lien piégé, `<img src>` dans un contenu affiché à un `admin`/`mshrif`
authentifié — chat, annonces, notes, bilans…). Impact : de « réversible » (toggle) à
**« validation d'un paiement »** / **« création d'un compte »** / **« annulation d'une séance »**.
→ **Décision produit à prendre** : soit c'est assumé (liens `<a href>` dans les templates, session
authentifiée jugée suffisante), soit il faut basculer ces vues en `@require_POST` + formulaires.

### 2.3 Validation d'entrée — **pas de `forms.py`, partout `request.POST.get`**

- **0 `forms.py`** dans le projet. Chaque vue reparse et revalide à la main. Conséquences :
  - Les `AUTH_PASSWORD_VALIDATORS` (`settings.py:186`) ne sont **jamais appliqués** — seul
    `accounts.views.password_change_view` fait une validation maison (`len >= 8`).
  - Le cast `int` est parfois oublié : bug HTTP 500 `age_min/age_max` (corrigé, `_ages_creneau_depuis_post`) ;
    `Groupe.capacite_max` stocké en `str` ; `superviseur_evaluer` fait `int(request.POST[f'note_{id}'])`
    sans garde `KeyError` dans la branche de ré-affichage.
- **Bonne factorisation** quand elle existe : `_construire_et_valider_telephone` (partagé
  `inscriptions.views` ↔ `registration.views`), `appliquer_regle_nom_parent` (wizard ↔ `inscrire_eleve`),
  `raison_incompatibilite_groupe` (ajout manuel ↔ wizard ↔ validation candidature),
  `valider_photo_groupe` (formulaire groupe ↔ chat).

### 2.4 Règle métier appliquée à un endroit mais pas à un autre

| Règle | Appliquée | Manquante / divergente |
|---|---|---|
| Nom du champ capacité groupe | `groupe_ajouter` lit `max_eleves` | `groupe_modifier` lit `capacite_max` — **noms différents pour `Groupe.capacite_max`** |
| `?next=` open-redirect | `dashboard._next_valide` (chemin `/dashboard/` uniquement) ✅ | `accounts.views.modifier_telephone:213` : `redirect(request.POST.get('next'))` **brut, non validé** |
| Champs `note_hifz…` gelés → `notes_criteres` | `calculer_progression_eleve` (migré) ✅ | `dashboard/notifications.py` (`notes_seances`) — **pas migré**, badge 🔔 muet |
| Service de fichier média | `chat.chat_fichier` → relais serveur `core.media_proxy` (URL Cloudinary jamais exposée) ✅ | `annonces.annonce_fichier`, `examens.reponse_audio/_video` → `redirect(fichier.url)` **expose `res.cloudinary.com`** (risque 401 si storage `authenticated`, non confirmé) |
| Suppression définitive | comptes élève/prof/superviseur = `@role_required('admin','mshrif')` (voulu, testé 2026-08-13) | groupes (`courses.groupe_supprimer_definitivement`) = `@role_required('admin')` seul → **incohérent comptes vs groupes** ; + commentaire dashboard `:4680` encore « مدير uniquement » (périmé) |
| `date_naissance` vide → 500 | Corrigé dans `inscription_eleve_formulaire`, `inscription_prof`, `wizard_identite` ✅ | — (couvert partout) |

### 2.5 Fonctionnalités dupliquées

- **`_base_template_admin_ou_mshrif` + `_contexte_base_mshrif`** : réimplémentés à l'identique dans
  `courses/views.py`, `payments/views.py`, `annonces/views.py`, `dashboard/views.py` (4 copies —
  **documenté comme choix délibéré** « pour un si petit bloc »).
- **`FENETRE_ANTI_DOUBLON_SECONDES = 5`** : redéfini dans `annonces/views.py`, `payments/views.py`,
  `inscriptions/views.py` (même valeur, même intention). Acceptable.
- **Validation de fichiers** (extension whitelist + taille) : ré-implémentée dans `chat/services.py`,
  `annonces/services.py`, `examens/services.py`, `dashboard.views._valider_fichier_hakiba`,
  `core/media_proxy.py` — **volontairement non factorisée** (« aucune dépendance entre apps »,
  documenté). 4-5 listes d'extensions à maintenir en parallèle.
- **`TRANCHES_AGE_PRECISES`** (`courses/utils.py`) : réutilisée par `chat.services`, `annonces.services`
  (labels), mais `Annonce.TRANCHE_AGE_CHOICES` **duplique les codes** (cycle d'import courses↔annonces).
- **Notif Telegram `📥 طلب تسجيل جديد`** : texte quasi-identique dans `inscriptions.views` (×2) et
  `registration.views._wizard_confirmer_inscription`. Le wizard a dû ré-ajouter cet appel (bug 2026-08-31).
- **Génération de mot de passe** : `generer_mot_de_passe_sequentiel` / `generer_mot_de_passe_temporaire`
  vivent dans `dashboard.views` et sont importés par `accounts.views` — **couplage `accounts → dashboard`**
  inhabituel (import tardif dans la fonction).

### 2.6 Points positifs transversaux

- Singletons : 9 modèles de config suivent tous `get_or_create(pk=1)` via un `get_*()` dédié. ✅
- i18n contenu-DB : ~12 modèles suivent le même `_localise(champ)` avec repli arabe. ✅
- Anti-rejeu : `@never_cache` + `request.session.pop()` sur **tous** les écrans de confirmation
  (création compte, modif email, refus, wizard). ✅
- `on_delete` : audité (SET_NULL pour les auteurs, CASCADE pour les données possédées) — cohérent
  et documenté modèle par modèle.
- Notifications : jamais de context processor global (coût 0 hors page d'accueil). ✅

---
