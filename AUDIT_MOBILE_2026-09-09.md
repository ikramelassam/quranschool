# Audit mobile — application Zidni Ilman

**Date :** 2026-09-09
**Méthode :** audit statique du code (228 templates, 12 layouts de base, ~263 vues).
**Limite importante :** aucun test sur appareil réel n'a été fait (l'automatisation
navigateur est désactivée pour ce projet). Les constats marqués 🟠 *à vérifier sur
appareil* sont des risques identifiés dans le code, pas des bugs confirmés visuellement.

---

## Résumé

| Zone | État mobile |
|---|---|
| Coquille authentifiée (5 sidebars élève/prof/مشرف/مدير/superviseur) | ✅ Bonne — menu hamburger + overlay + breakpoint 768px + cibles tactiles 44px partout |
| Parcours d'inscription public (wizard 6 étapes + anciens formulaires) | ✅ Bon après les correctifs de cette session |
| Authentification (login, mot de passe oublié) | ✅ Bon |
| Espace élève (tableau de bord, paiements, progression, carnet, examens) | ✅ Bon dans l'ensemble |
| Chat / messagerie | 🟡 Correct — layout mobile dédié, mais `alert()` pour les erreurs |
| Espace prof — saisie des évaluations (`prof_seance_detail`) | 🟡 Dense, champs `-sm` (zoom iOS), pensé pour ordinateur |
| Espace prof/مشرف — emplois du temps, rémunération | 🟡 Tableaux larges, scroll horizontal (fonctionnel) |
| Administration (مدير) — ~90 écrans de configuration | 🟡 Utilisable via la coquille responsive, non optimisé, `confirm()` natif |
| Django admin (`/admin/`, 28 gabarits) | ⚪ Hors périmètre réel — responsive Django par défaut, usage bureau |

**Aucun** anti-pattern bloquant généralisé : pas de `user-scalable=no`, pas de
`maximum-scale`, grilles CSS en `auto-fit/minmax` (responsives), tous les grands
tableaux ont un conteneur `overflow-x:auto`.

---

## P0 — cassait l'usage mobile (CORRIGÉ cette session)

### 1. Champ e-mail refusé sur mobile RTL — « أدخل عنوان بريد إلكتروني »
**Fichiers :** `templates/inscriptions/wizard_identite.html`, `_wizard_base.html`,
`eleve_formulaire.html`, `prof_formulaire.html`, `_champs_dynamiques.html`,
`inscriptions/views.py`, `registration/views.py`
**Symptôme :** le clavier arabe / l'autocomplétion collent une espace finale ou une
marque directionnelle invisible (U+200F, U+200E, U+FEFF…) à l'adresse. Le champ
`type="email"` devient invalide côté navigateur → envoi bloqué avec un message qui
dit « saisis une adresse » alors qu'elle est là. `str.strip()` côté serveur
n'enlève pas ces caractères → compte créé avec un e-mail inutilisable.
**Correctif appliqué :**
- attributs `dir="ltr" inputmode="email" autocapitalize="none" autocorrect="off" spellcheck="false"` sur tous les champs e-mail du parcours ;
- nettoyage JS à chaque frappe (`_wizard_base.html` + les 2 anciens formulaires) ;
- helper serveur `nettoyer_email_saisi()` (miroir) dans les 3 vues qui lisent l'e-mail ;
- test de non-régression `test_email_avec_marques_invisibles_mobile_est_nettoye`.

### 2. Page de confirmation d'inscription sans `viewport`
**Fichier :** `templates/inscriptions/confirmation.html`
**Symptôme :** dernière page du parcours (« تم إرسال طلبك بنجاح »), aucune balise
`<meta name="viewport">` ni `<title>` → rendue à ~980px puis dézoomée par le
navigateur mobile, texte minuscule. Mauvaise dernière impression.
**Correctif appliqué :** ajout `viewport` + `<title>` + `body{padding:20px}` +
`.card{width:100%}`.

---

## P1 — gêne réelle sur mobile (recommandé, NON corrigé)

### 3. Grille de disponibilités — cases à cocher minuscules
**Fichier :** `templates/courses/_grille_disponibilites.html`
**Écrans concernés :** wizard groupe, wizard individuel, `eleve_formulaire`,
`prof_formulaire`, + 12 écrans admin.
**Constat :** le tableau (7 jours × N heures, `min-width:600px`) scrolle
horizontalement (conteneur `overflow-x:auto` présent, OK). Mais les `<input
type="checkbox">` sont à la taille par défaut (~13-16px) : cible tactile très
en-dessous des 44px recommandés, dans un tableau qu'il faut déjà faire défiler.
Choisir ses créneaux au doigt est pénible.
**Piste :** `transform:scale(1.6)` + `padding` sur les `<td>` en dessous de 768px,
ou passer à une liste de "puces jour/heure" empilée sur mobile.

### 4. `prof_seance_detail` — saisie des notes, champs `form-*-sm`
**Fichier :** `templates/dashboard/prof_seance_detail.html` (lignes 216-301)
**Constat :** `form-select-sm` / `form-control-sm` = `font-size:0.875rem` (14px) →
**iOS Safari zoome automatiquement** à chaque focus. Plusieurs champs par élève sur
une même ligne → mise en page très large. Le prof note toute une séance ; sur
téléphone c'est laborieux.
**Piste :** forcer `font-size:16px` sur ces `input`/`select` en dessous de 768px
(supprime le zoom iOS sans changer le desktop), et empiler les champs par élève en
colonne sur mobile.

### 5. `chat.html` — erreurs via `alert()` natif
**Fichier :** `templates/chat/chat.html` (lignes 926, 1183, 1185) + suppression de
message ligne 914 (`confirm()`).
**Constat :** écran utilisé par élèves et profs, souvent sur mobile. Un `alert()`
bloque tout le fil JS et, d'après la note projet, casse aussi les outils
d'automatisation. Échec d'envoi / échec de suppression = pop-up système.
**Piste :** toast in-page (le composant `_messages.html` existe déjà) + modale de
confirmation maison pour la suppression.

---

## P2 — non optimisé, fonctionne (pour information)

### 6. Champ e-mail dynamique généré (`champ_<id>`)
`_champs_dynamiques.html` — corrigé cette session (mêmes attributs que le champ
e-mail structurel). À garder en tête si d'autres types de champs sont ajoutés.

### 7. Tableaux larges de l'espace prof/مشرف
`prof_emploi.html`, `superviseur_emploi.html`, `mshrif_remuneration.html` :
`min-width` 520-600px, tous **avec** conteneur `overflow-x:auto`. Le scroll
horizontal fonctionne mais n'est pas évident (pas d'ombre de bord ni d'indice
visuel). Piste : ombre de défilement CSS (`background-attachment:local`).

### 8. `confirm()` natif sur ~35 écrans d'administration
Boutons supprimer / accepter / archiver (`admin_*`, `mshrif_*`, `courses/admin_*`).
Fonctionne nativement sur mobile mais pop-up système peu élégante et non
traduisible finement. Priorité basse : écrans مدير, surtout utilisés sur ordinateur.

### 9. Grille stats `suivi_engagement_mensuel`
`grid-template-columns:repeat(4,1fr)` → `repeat(2,1fr)` seulement en dessous de
1100px. Sur un téléphone de 360px, 2 colonnes de statistiques restent serrées.
Piste : `repeat(1,1fr)` ou `auto-fit minmax(140px,1fr)` en dessous de 480px.

### 10. `_header_raccourcis.html` — panneau `width:min(360px, calc(100vw - 24px))`
Correct (déjà borné au viewport). Aucune action.

---

## P3 — vérifications à faire sur appareil réel 🟠

| # | Écran | Point à vérifier |
|---|---|---|
| 11 | Toutes les pages authentifiées en **français/anglais** (LTR) | La sidebar reste `right:0` même en LTR (note assumée dans `base_eleve.html`). Le bouton hamburger est `top:14px; left:14px` → en LTR il peut chevaucher le `page-title`. |
| 12 | `_verification_whatsapp.html` (téléphone + confirmation) | `type="tel"` sans `inputmode` ni `autocomplete="tel-national"`. Le clavier numérique s'affiche en général, à confirmer sur Android/iOS. `wa_ouvrirVerification()` fait un `alert()` si numéro vide. |
| 13 | `eleve_paiements.html` / `suivi_paiements_eleves.html` | Upload `screenshot` `accept="image/*"` : choix appareil photo / galerie à tester (iOS + Android + WebView Facebook). Compression Cloudinary déjà en place (voir mémoire). |
| 14 | `prof_formulaire.html` — enregistreur audio `MediaRecorder` | Repli si `MediaRecorder` absent : à tester sur Safari iOS (support partiel) et navigateurs in-app. |
| 15 | `annonces/canal_detail.html` | Envoi de fichiers (image/vidéo/audio/PDF via un seul `<input type=file>` partagé) — flux à dérouler sur mobile. |
| 16 | `examens/passage.html` | En-tête + chrono en `position:sticky` : vérifier qu'il ne masque pas la 1re question sur petits écrans, et le comportement au scroll pendant la saisie des réponses. |
| 17 | `chat/_panel.html` | `<input type=file>` photo/audio cachés déclenchés par bouton — capture caméra sur mobile. |
| 18 | Modales plein écran (`_media_viewer.html`, `suivi_paiements_eleves` panel, chat) | `position:fixed; inset:0` : défilement interne du contenu quand il dépasse la hauteur d'écran + fermeture au bouton (pas seulement au clic sur l'overlay). |
| 19 | `_select_cherchable.html` (select cherchable maison) | Ouverture/fermeture du menu déroulant au tactile, clavier virtuel qui pousse la liste (déjà 2 correctifs dans l'historique — voir mémoire). |
| 20 | Tous les `<input type="date">` | Rendu du sélecteur natif iOS/Android + valeur pré-remplie `value="{{ ... }}"` bien reprise. |

---

## Ce qui est déjà bien fait (à ne pas casser)

- Les 5 layouts de tableau de bord : hamburger `.sidebar-toggle` 44×44, overlay
  sombre, `transform:translateX` animé, `@media (max-width:768px)`, menu scrollable
  (`-webkit-overflow-scrolling:touch`).
- `base_eleve.html` : breakpoint fin supplémentaire `@media (max-width:480px)` pour
  l'anneau de progression et les rangées de stats.
- `examens/passage.html` : `prefers-reduced-motion` respecté, `sticky` choisi
  volontairement à la place de `fixed` (commentaire explicite dans le code).
- Bootstrap 5.3 en base → `.form-control` à 16px par défaut (pas de zoom iOS), sauf
  les `-sm` explicites (constat #4).
- Grand tableau = conteneur `overflow-x:auto` systématique.
- `tokens.css` : contrastes AA vérifiés et documentés.

---

## Plan d'action proposé (par ordre de valeur)

1. **P1 #3** — cases à cocher de la grille de disponibilités agrandies sur mobile
   (impacte directement le parcours d'inscription).
2. **P1 #4** — `font-size:16px` forcé + empilage vertical sur `prof_seance_detail`
   en dessous de 768px.
3. **P1 #5** — remplacer les `alert()`/`confirm()` de `chat.html` par des toasts /
   modale maison.
4. **P3** — session de test sur 2-3 appareils réels (un Android, un iPhone, un
   navigateur in-app Facebook/Instagram) en déroulant les points #11 à #20.
5. **P2 #7-#9** — finitions (indice de scroll horizontal, grille stats 1 colonne).
