# Audit de stabilité — « pages blanches » côté profs

Date : 2026-09-09
Portée : lecture seule, aucun code modifié. Déclencheur : des professeurs
signalent que le site **ne se charge pas** (page **entièrement blanche**, sans
message d'erreur). Question posée : est-ce leur téléphone ?

**Réponse courte : non, c'est l'hébergement.** Une page totalement vide (pas
une page « Server Error 500 » qui, elle, contient du texte) veut dire que la
requête n'a jamais abouti — le serveur n'a rien renvoyé. Le code applicatif
n'est pas en cause dans l'immense majorité des cas.

---

## 0. Contexte infra confirmé

| Élément | Valeur |
|---|---|
| Hébergement web | Render, **plan gratuit** (512 Mo RAM, 0,1 CPU, mise en veille après 15 min sans trafic) |
| Base de données | Supabase, **plan gratuit** (pooler PgBouncer port 6543, latence réseau depuis Render) |
| Serveur | `gunicorn --workers 2 --worker-class gthread --threads 4 --timeout 30` → **8 requêtes simultanées max**, **coupure à 30 s** |
| Ping keep-alive | **UptimeRobot**, toutes les 5 min, sur `https://quranschool.onrender.com` (une simple redirection 302, ne touche pas la base) |
| Uptime mesuré | **99,9 % sur 7 j et 30 j** — 2 incidents / ~20 min de coupure totale en 30 j |
| Observation | Au moment de l'audit : « up for 0h 25m » → le serveur avait **redémarré 25 min plus tôt** |

---

## 1. Ce que UptimeRobot ne voit pas (= ce que les profs subissent)

UptimeRobot affiche 99,9 % mais **ne teste que la page d'accueil**, qui est une
redirection triviale ne faisant aucune requête SQL, vérifiée **toutes les 5
minutes**. Deux phénomènes passent donc totalement sous son radar :

### 1.1 — Redémarrages courts du serveur (CAUSE PRINCIPALE PROBABLE)
Render relance le processus web en ~30–60 s (cold start, ou après un
dépassement mémoire). Entre deux vérifications UptimeRobot espacées de 5 min,
un redémarrage de 40 s est **invisible** — mais un prof qui charge une page
pendant ces 40 s reçoit une **page blanche**. Le compteur « up for 25m »
observé pendant l'audit indique que ces redémarrages arrivent (à vérifier :
recharger le dashboard UptimeRobot plus tard — si le compteur est encore bas,
c'est fréquent).

**Origine du redémarrage** :
- **Mémoire (512 Mo).** Django + 2 workers gthread + `Pillow` (redimensionnement
  des photos de paiement) + relais de fichiers Cloudinary (voir §2.2) peuvent
  dépasser 512 Mo → Render tue et relance l'instance (`Out of memory`).
- **Absence de recyclage des workers.** Le `Procfile` n'a pas de
  `--max-requests` : un worker vit indéfiniment et toute fuite mémoire
  (connexions, objets Python) s'accumule jusqu'au redémarrage forcé.
- **Cold start** après une fenêtre où UptimeRobot lui-même aurait échoué
  (rare : uptime 99,9 %).

### 1.2 — Requêtes légitimes coupées à 30 s
`--timeout 30` tue le worker si une requête n'a pas répondu en 30 s. Sur base
Supabase gratuite **froide** (première requête après une pause, handshake
pooler), une page lourde (dashboard مؤطر, `suivi_paiements_eleves` sans filtre,
grille de disponibilité) peut dépasser 30 s → **worker tué → page blanche**,
sans aucune trace côté UptimeRobot puisque lui ne charge que la redirection.

---

## 2. Points applicatifs (secondaires, mais réels)

### 2.1 — `payments/views.py:suivi_paiements_eleves` — table Paiement chargée en entier au chargement par défaut
**Fichier** : `payments/views.py:417-446`

Le correctif du 2026-08-30 a ajouté un filtre **quand `?groupe=<id>` est
présent**. Mais au **chargement par défaut de la page** (sans filtre),
`Paiement.objects.all()` (ligne 423) est **itéré deux fois** :
- ligne 438 : `for p in paiements_scope:` → instancie **tout l'historique des
  paiements** en objets Python ;
- ligne 443 : `.filter(statut='valide').values_list(...)` → 2ᵉ parcours complet.

`Paiement` grandit d'une ligne par élève et par mois payé — indéfiniment.
C'est le **candidat n°1 pour un pic mémoire** (donc un redémarrage §1.1) sur
une page réservée à l'administration mais consultée quotidiennement.

**Correctif possible sans changer l'UX** : ajouter `.only('eleve_id',
'mois_reference', 'nb_mois_couverts', 'id', 'montant', 'statut')` sur la 1ʳᵉ
boucle, et surtout **borner la période** (ex. 24 derniers mois) puisque
l'écran ne montre de toute façon que 12 mois de colonnes par défaut. La
pagination des lignes (groupes) reste « à discuter » (change l'affichage).

### 2.2 — Relais de fichiers Cloudinary — fichier entier en mémoire
**Fichier** : `core/media_proxy.py:127`, appelé par le cartable, la حقيبة et le chat

`FileResponse(fieldfile.open('rb'), …)` : avec `RawMediaCloudinaryStorage`, le
`.open()` télécharge **tout le fichier en mémoire** avant que `FileResponse` ne
le renvoie par morceaux. Un fichier de 15–20 Mo × plusieurs téléchargements
simultanés sur 512 Mo → pression mémoire. Trafic fichier faible aujourd'hui,
mais à connaître (non couvert par l'audit du 2026-08-30, module créé après).

**Piste** : vérifier si `cloudinary_storage` expose un accès en flux ; sinon,
rediriger vers une URL Cloudinary signée à durée courte pour les gros fichiers
(perd le « tout servi par le site », à arbitrer).

### 2.3 — `LocMemCache` non partagé entre workers
**Fichier** : `core/settings.py` (aucune section `CACHES`)

Chaque worker a son cache mémoire isolé. Sans incidence grave (TTL courts : 15 s
à 5 min), mais le cache logo (5 min) est « à moitié efficace » (MISS ~50 %
selon le worker). Pas de correctif simple sans Redis externe (absent du plan
gratuit) — **à accepter tel quel**.

### 2.4 — Micro N+1 résiduels (impact faible, ne causent PAS de page blanche)
- `dashboard/views.py:566` (`dashboard_prof`) : `sum(g.eleves.exclude(...).count() for g in groupes)` → 1 `COUNT` par groupe du prof (3–8 requêtes).
- `dashboard/views.py:609` (`prof_groupe_detail`) : `groupe.eleves.all()` sans `select_related('user')` → 1 requête par élève affiché.
- Chacun ajoute ~100–300 ms sur base froide, jamais 30 s. À corriger par
  hygiène, pas en urgence.

---

## 3. Ce qui est SAIN (vérifié)

- Audit performance du 2026-08-30 **appliqué à ~90 %** :
  - `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS` + `DISABLE_SERVER_SIDE_CURSORS` ✅ (`core/settings.py:177-190`)
  - `groupe_detail` : `select_related('prof__user','creneau')`, `eleves` en `select_related('user')`, `count()` dédupliqué ✅ (`courses/views.py:414-434`)
  - `groupes_list` : `annotate(Count('eleves', distinct=True))` ✅
  - Cache logo (`get_logo_config`, 5 min) ✅ (`accounts/models.py:695`)
  - Notifications Telegram en **thread daemon détaché** (ne bloque plus la réponse HTTP) ✅ (`core/utils.py:226-262`, `_diffuser_telegram_paiement_valide` utilise bien les variantes `_async`)
- `cycles_ouverts_en_retard()` (calculé à chaque dashboard direction) : **nombre de requêtes constant**, aucune boucle par élève ✅
- `dashboard_admin` : compteurs + slices `[:3]`, pas de N+1 ✅
- Pas de framework JS lourd ; WhiteNoise + manifest storage OK ; `build.sh` fait `collectstatic` + `migrate` avant le boot ✅
- CSRF : `CSRF_TRUSTED_ORIGINS`, `CSRF_FAILURE_VIEW` custom, `SECURE_PROXY_SSL_HEADER` ✅
- `TESTING` neutralise les envois Telegram réels ✅

---

## 4. Recommandations, par ordre de rapport bénéfice/risque

### A — Gratuit, sans risque (`Procfile`) — ✅ APPLIQUÉ le 2026-09-09
```
web: gunicorn core.wsgi --workers 2 --worker-class gthread --threads 4 \
     --timeout 60 --graceful-timeout 30 \
     --max-requests 500 --max-requests-jitter 100 --preload \
     --worker-tmp-dir /dev/shm --log-file -
```
- `--timeout 60` (au lieu de 30) : une page ne finit plus tuée avant d'aboutir
  quand la base est froide. **Ne ralentit AUCUNE requête rapide** (c'est un
  chien de garde « worker figé », pas un quota de durée).
- `--max-requests 500 --max-requests-jitter 100` : chaque worker se recycle
  proprement (un à la fois) après ~500 requêtes → la mémoire est relâchée
  régulièrement → moins de redémarrages Render subis par les profs.
- `--preload` : app chargée une fois dans le master puis forkée → mémoire
  immuable partagée entre les 2 workers (copy-on-write). Vérifié sans effet de
  bord : les 3 `AppConfig.ready()` n'importent que des modules de signaux,
  aucune requête DB / handle fichier à l'import.

### B — Gratuit, sans changement d'UX visible (code) — ✅ PARTIELLEMENT APPLIQUÉ
1. ✅ `suivi_paiements_eleves` (`payments/views.py`) : suppression de
   `paiement_par_cellule` qui instanciait **toute la table Paiement** en objets
   à chaque affichage. La grille ne lit plus que `mois_payes_par_eleve`
   (values_list, 3 colonnes, statut='valide' seulement). Le panneau détail
   charge le Paiement complet d'**un seul** élève (~10 lignes), au clic. 68
   tests payments verts. **Le plus gros pic mémoire connu est éliminé.**
2. ⏳ `annotate` / `select_related('user')` sur les 2 N+1 de §2.4 — pas encore
   fait (impact faible, ne cause pas de page blanche).

### C — Diagnostic à faire côté Render (5 min, ne nécessite pas de code)
- **Render → Logs** : chercher `Out of memory`, `Ran out of memory`,
  `WORKER TIMEOUT`, `SIGKILL`. Confirme lequel de §1.1 / §1.2 domine.
- **Render → Metrics** : courbe mémoire — si elle colle au plafond 512 Mo,
  c'est tranché.
- **Render → Settings → Health Check Path** : si un chemin est configuré et
  qu'il répond lentement/en erreur, Render redéploie en boucle. Vérifier.
- Recharger le dashboard **UptimeRobot** plus tard : si « up for » reste bas
  (< 1 h), les redémarrages sont fréquents.

### D — Payant, la vraie solution de fond (~7 $/mois)
Render **Starter** : plus de mise en veille, plus de RAM. Élimine §1.1 (cold
start + marge mémoire) d'un coup. À considérer si A + B ne suffisent pas, ou
directement si le budget le permet — c'est un site scolaire en production.

### E — À NE PAS faire
- Monter `--workers` : chaque worker coûte ~80–120 Mo sur 512 Mo → aggrave §1.1.
- Toucher UptimeRobot pour « pinguer plus souvent » : le problème n'est pas la
  fréquence du ping (5 min < 15 min de veille), c'est ce qu'il teste.

---

## 4bis — Addendum du 2026-09-10 : log Render capturé + N+1 confirmé

Un log Render du 2026-09-10 11:44 confirme §1.2 **et** révèle un N+1 non listé
en §2.4 :

```
[gunicorn] Worker (pid:92) was sent SIGKILL! Perhaps out of memory?
  File ".../courses/utils.py", line 999, in lien_seance_est_actif
    fin = seance.fin_datetime or debut
  File ".../courses/models.py", line 868, in fin_datetime
    creneau = self.groupe.creneau        <-- requête SQL tuée en plein vol
```

Le worker a été tué (timeout/OOM) **pendant** une requête déclenchée par
`seance.fin_datetime`. Or `dashboard/_meet_icon.html` appelle
`{{ seance|lien_seance_actif }}` **pour chaque séance affichée** sur les agendas
prof / élève / مؤطر, et `lien_seance_est_actif` faisait, par séance :
1. `seance.groupe.creneau` (créneau non `select_related`) — 1 requête ;
2. `creneau.slots.all()` (non `prefetch`) — 1 requête ;
3. `ReglageLienSeance.objects.get_or_create(pk=1)` — 1 requête (+ parfois écriture).

Soit **~3 requêtes SQL par séance** sur une page qui en liste des dizaines →
sur base Supabase froide, dépasse `--timeout 60` → page blanche.

### Correctif appliqué le 2026-09-10 (sans changement d'UX)
- `courses.models.get_reglage_lien_seance` : **mis en cache 60 s** (même patron
  que `get_logo_config`) + `invalider_cache_reglage_lien_seance` appelée par
  `admin_reglage_lien_seance`. `lien_seance_est_actif` l'utilise au lieu de
  `get_or_create` direct → 1 requête par page au lieu de 1 par séance.
- `dashboard/views.py` : `select_related('groupe__creneau')` +
  `prefetch_related('groupe__creneau__slots')` sur les querysets de séances de
  `dashboard_prof`, `prof_seances`, `dashboard_eleve`, `eleve_seances`,
  `dashboard_superviseur` (`toutes_seances` + `candidates_proches`). Le créneau
  et ses slots sont désormais chargés en 1 (+1) requête partagée, quel que soit
  le nombre de séances.
- Tests : `dashboard.tests.AgendaDashboardSansN1CreneauTests` — verrouille
  l'absence de N+1 (le nombre de requêtes ne croît pas avec le nombre de séances).

Reste ouverts : §2.4 (micro N+1 `dashboard_prof:566` / `prof_groupe_detail`),
§2.2 (relais Cloudinary), §D (plan Render payant).

---

## 5. Limites de cet audit

- Pas d'accès aux **logs / métriques Render** ni au **dashboard Supabase**
  (limites de connexions réelles) — §1 est déduit du comportement observé
  (page blanche + 99,9 % UptimeRobot + « up for 25m »), à confirmer par §4.C.
- `dashboard/views.py` (~8000 lignes) couvert par recherche de motifs à risque
  (`for … in …objects`, `.all()`, N+1) + lecture ciblée des vues d'accueil par
  rôle, pas ligne à ligne.
- Aucun `EXPLAIN ANALYZE` ni profileur exécuté contre la base de production.
- Les fichiers en cours de modification au moment de l'audit
  (`courses/views.py`, `dashboard/views.py`, `templates/courses/admin_groupe_detail.html`,
  `courses/tests.py` — chantier « le مشرف peut supprimer un groupe ») sont sans
  rapport avec la stabilité et n'ont pas été inclus.
