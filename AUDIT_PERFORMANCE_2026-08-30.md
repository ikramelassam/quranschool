# Audit de performance — Zidni Ilman (v2, refait entièrement)

Date : 2026-08-30
Portée : lecture seule (aucun code métier modifié). Remplace la version
précédente de ce fichier (même date) : celle-ci était partielle (uniquement
`courses/views.py` + config) et un peu périmée entre-temps — voir « Ce qui a
déjà été corrigé depuis » ci-dessous. Cette version relit l'intégralité des
apps backend (11 apps, tous les `views.py`/`models.py`/`services.py`), les
templates concernés, la config (`settings.py`, `Procfile`, `build.sh`,
`requirements.txt`) et le frontend (bases `templates/dashboard/base_*.html`).
Contexte confirmé par Ikram : **Render (plan free) + Supabase (plan free)**
— ça change la priorisation, voir section 0.

Méthode réelle (transparence, pas de survol) : `core/settings.py`,
`Procfile`, `build.sh`, `requirements.txt`, tous les context processors,
middlewares, décorateurs lus intégralement. `courses/views.py` (1155 lignes),
`payments/views.py` (421), `chat/views.py` (467), `accounts/services.py`
(154) lus intégralement. `dashboard/views.py` (7998 lignes, le plus gros
fichier du projet) n'a pas été relu ligne 1 à 7998 dans l'ordre — repéré
d'abord par recherche systématique de tous les motifs à risque (boucles
`for` sur un queryset, `.objects.all()` sans borne, `select_related`/
`prefetch_related` absents), puis chaque zone repérée a été lue en entier
avec son contexte et vérifiée contre son template. C'est une méthode fiable
pour ce genre de bug (motif syntaxique reconnaissable), mais je le signale
explicitement : je n'affirme pas avoir lu les ~359 vues de ce fichier une
par une.

---

## 0. Ce qui compte le plus vu le contexte (plans FREE Render + Supabase)

Avant les micro-optimisations de requêtes : sur un plan **Render free**, le
service web s'éteint après ~15 minutes sans trafic et met **30 à 60 secondes**
à redémarrer à la requête suivante ("cold start" — chargement de Python/
Django, connexion à Supabase, etc.). Pour une petite école avec du trafic
intermittent (quelques visites espacées dans la journée), c'est très
probablement **la plus grosse cause de lenteur perçue** ("le site est lent"),
plus que n'importe quel N+1 ci-dessous — un N+1 ajoute des secondes, un cold
start en ajoute des dizaines, et frappe le premier visiteur après une pause.

Ça n'est pas un bug de code, donc pas de "correctif" ligne par ligne ici,
mais ça doit être la 1ère chose vérifiée si le symptôme rapporté est "lent au
1er chargement de la journée / après une pause" plutôt que "lent à chaque
page" :
- Confirmer le symptôme : la lenteur constatée est-elle systématique, ou
  seulement après une période d'inactivité ?
- Si c'est bien un cold start : soit accepter ce compromis du plan free,
  soit passer à un plan payant (élimine le problème), soit — solution
  fréquemment utilisée mais qui contourne l'esprit du plan gratuit, à
  valider avec toi plutôt que mise en place sans discussion — un ping
  externe périodique (ex. UptimeRobot toutes les 10 min) qui garde le
  service éveillé.
- Supabase free : le projet se met en pause après 7 jours **sans aucune
  requête** — peu probable avec un site actif, mais si le site est resté
  inutilisé une semaine, la 1ère requête qui suit peut échouer/traîner le
  temps que Supabase réveille le projet (plusieurs secondes à ~1 minute).

Ceci dit, tout ce qui suit reste valable et cumulable : moins un cold start
dure, mieux c'est, et une fois le service chaud, les points 1 à 5 ci-dessous
sont ce qui détermine la vitesse ressentie à chaque page.

---

## 1. Ce qui a déjà été corrigé depuis la version précédente de cet audit

Bonne surprise en relisant `courses/views.py` : quelqu'un (toi ou une autre
session, commentaires "Correctif du 2026-08-30") a déjà réglé deux points que
la 1ère version de cet audit avait signalés :
- `groupe_ajouter`/`groupe_modifier` : `Prof.actifs.select_related('user')`
  ajouté (c'était 15-30 requêtes en trop par page, une par prof).
- `_liens_meet_contexte`/`liens_meet_list` : la grille disponibilité liens
  Meet × créneaux, qui faisait ~800 requêtes et ~88 secondes mesurées en
  conditions réelles (21 créneaux × 16 liens), a été remplacée par
  `courses.utils.matrice_disponibilite_liens_meet` — 4 requêtes fixes au
  lieu de 2 par couple (lien, créneau). C'était la cause des erreurs 500
  "Internal Server Error" sur `/courses/groupes/<id>/modifier/` (timeout
  gunicorn de 30s dépassé).

Ces deux points ne sont **plus** dans le plan d'action ci-dessous.

---

## 2. N+1 / requêtes en boucle — encore ouverts

### 2.1 — CRITIQUE — `courses/views.py:groupe_detail` (fiche halaka)
**Fichiers** : `courses/views.py:332-432`, `templates/courses/admin_groupe_detail.html`

Toujours présent (vérifié dans le code actuel, pas une supposition) :
- `groupe = get_object_or_404(Groupe, id=groupe_id)` (ligne 335) sans
  `select_related('prof__user', 'creneau')` — le template accède à
  `groupe.prof.statut`, `groupe.prof.user.get_full_name/.email/.telephone`
  (lignes 69-88) et `groupe.creneau.get_riwaya_display` (ligne 102) : 2-3
  requêtes en plus à chaque ouverture de fiche.
- `eleves_disponibles = Eleve.actifs.exclude(groupes=groupe)` (ligne 336)
  sans `.select_related('user')` — le template (`{% for eleve in
  eleves_disponibles %}` ligne 233) affiche `eleve.user.get_full_name`
  (ligne 234) : **1 requête par élève actif non membre de ce groupe**, donc
  potentiellement toute la population active moins la taille du groupe.
- `{% for eleve in groupe.eleves.all %}` (ligne 190) → `eleve.user.
  get_full_name/.email/.telephone` (lignes 194-201) — `groupe.eleves` n'est
  select_related nulle part dans la vue → 1 requête par élève déjà membre.
- `{{ groupe.eleves.count }}` appelé 2 fois dans le template (lignes 119 et
  156) → 2 requêtes `COUNT` identiques.

**Impact** : école à 80-150 élèves actifs → 60 à 150+ requêtes rien que pour
cette page, à chaque ouverture.

**Correctif** :
```python
# courses/views.py, groupe_detail
groupe = get_object_or_404(
    Groupe.objects.select_related('prof__user', 'creneau'), id=groupe_id
)
eleves_disponibles = Eleve.actifs.exclude(groupes=groupe).select_related('user')
eleves_du_groupe = groupe.eleves.select_related('user').all()
nb_eleves = groupe.eleves.count()  # calculé une fois

context = {
    'groupe': groupe,
    'eleves_disponibles': eleves_disponibles,
    'eleves_du_groupe': eleves_du_groupe,   # nouvelle clé, remplace groupe.eleves.all au template
    'nb_eleves': nb_eleves,                  # remplace groupe.eleves.count aux 2 endroits
    ...
}
```
Et dans `admin_groupe_detail.html` : remplacer `groupe.eleves.all` par
`eleves_du_groupe`, et `groupe.eleves.count` (x2) par `nb_eleves`.

**Priorité : à faire immédiatement** (page probablement la plus visitée par
l'admin, aucun changement de comportement).

### 2.2 — UTILE — `courses/views.py:groupes_list` (liste des halakat)
**Fichiers** : `courses/views.py:74-168`, `templates/courses/admin_groupes.html:152`

Déjà `select_related('prof__user', 'creneau')` + paginée (10/page) — bien
fait. Reste : `{{ groupe.eleves.count }}` dans la boucle du template (ligne
152) → 1 `COUNT` par ligne affichée (borné à 10 par la pagination, mais
évitable).

**Correctif** :
```python
groupes = Groupe.objects.select_related('prof__user', 'creneau').annotate(
    nb_eleves=Count('eleves')
).order_by('id')
```
puis `{{ groupe.nb_eleves }}` dans le template. **Priorité : à planifier**
(gain faible, la pagination borne déjà le dégât).

### 2.3 — CRITIQUE (nouveau, pas vu dans la 1ère version) — `payments/views.py:suivi_paiements_eleves`
**Fichier** : `payments/views.py:232-349`

C'est la page maître-détail "متابعة المدفوعات" (tableau Groupe → Élève →
mois). Deux problèmes cumulés, plus graves que les N+1 ci-dessus car ils
grossissent avec le temps (pas juste avec le nombre d'élèves) :

1. **Ligne 258** : `for p in Paiement.objects.all():` — charge **TOUTE la
   table Paiement** en mémoire Python, à CHAQUE ouverture de cette page,
   sans aucun filtre, même quand `?groupe=<id>` est passé en paramètre
   (le filtre `groupe_id` ne s'applique qu'à `groupes_qs`, jamais à cette
   requête). Un `Paiement` est créé par élève par mois payé : avec 100
   élèves × 12 mois/an × plusieurs années, cette table ne fait que grandir
   — c'est exactement le genre de requête non bornée qui peut finir par
   provoquer un OOM sur un service à mémoire limitée (Render free = 512 Mo),
   ce que la 1ère version de cet audit cherchait sans le trouver (elle
   n'avait pas ouvert ce fichier).
2. **Ligne 263** : `Paiement.objects.filter(statut='valide').values_list(...)`
   — même défaut (aucun filtre par groupe/période), même si `.values_list`
   est déjà plus léger (pas d'instanciation de modèle).
3. **Aucune pagination** sur le tableau final (`donnees`, ligne 272-317) :
   contrairement à `admin_paiements`/`groupes_list`/`admin_eleves` (qui
   utilisent tous `paginer(...)`), cette page affiche TOUS les groupes et
   TOUS leurs élèves d'un coup (le cap "12 mois" ne limite que les colonnes
   par ligne, pas le nombre de lignes).

**Correctif proposé** :
```python
# Filtrer par le même scope que groupes_qs, calculé une fois
eleves_scope_ids = None
if groupe_id:
    eleves_scope_ids = list(
        Groupe.objects.filter(id=groupe_id).values_list('eleves__id', flat=True)
    )

paiements_qs = Paiement.objects.all()
if eleves_scope_ids is not None:
    paiements_qs = paiements_qs.filter(eleve_id__in=eleves_scope_ids)

paiement_par_cellule = {}
for p in paiements_qs.only('eleve_id', 'mois_reference', 'id', 'montant', 'statut'):
    cle = (p.eleve_id, p.mois_reference.year, p.mois_reference.month)
    paiement_par_cellule[cle] = p
```
et pareil pour la requête `statut='valide'` du dessous. Pour la pagination,
paginer `groupes_qs` (comme `groupes_list`) plutôt que d'itérer tous les
groupes retournés — **à valider avec toi** car ça change la présentation
(un admin qui scrollait tout d'un coup devra changer de page), donc pas un
correctif "invisible" comme les autres.

**Priorité : à faire rapidement** pour les points 1-2 (aucun changement de
comportement, juste moins de données chargées) ; **à planifier/discuter**
pour la pagination (point 3, change l'UX).

### 2.4 — IMPORTANT (nouveau) — `dashboard/views.py:bilans_mensuels`
**Fichier** : `dashboard/views.py:1667-1770` (env.), `templates/dashboard/bilans_mensuels.html`

La requête `groupes` (ligne 1694) est déjà bien faite : `select_related(
'prof__user').prefetch_related('eleves__user')` — donc `groupe.eleves.all()`
(appelé 2 fois, lignes 1725 et 1727) ne recompte PAS 2 requêtes grâce au
cache de prefetch (je le précise pour ne pas le signaler à tort). Le vrai
problème est plus loin, **dans** la boucle `for eleve in groupe.eleves.all()`
(ligne 1727) :
```python
moyennes_qs = NotePresence.objects.filter(presence__eleve=eleve, ...)
...
bilan = BilanMensuel.objects.filter(eleve=eleve, prof=groupe.prof)...first()
```
**2 requêtes par élève affiché**, non batchées. Pour un admin/مشرف qui
affiche tous les groupes sans filtre (comportement par défaut de la page),
c'est 2 × (nombre total d'élèves actifs de l'école) requêtes en plus des
requêtes de base — sur 100-150 élèves, 200-300 requêtes sur une seule page.

**Correctif proposé** (regrouper les 2 requêtes par élève en 2 requêtes
totales, avant la boucle) :
```python
eleve_ids = [e.id for g in groupes for e in g.eleves.all()]

moyennes_par_eleve = {}
qs_moy = NotePresence.objects.filter(presence__eleve_id__in=eleve_ids, critere__est_actif=True)
if annee:
    qs_moy = qs_moy.filter(presence__seance__date__year=annee, presence__seance__date__month=mois_num)
for ligne in qs_moy.values('presence__eleve_id', 'critere__nom_ar', 'critere__ordre').annotate(moyenne=Avg('note')):
    moyennes_par_eleve.setdefault(ligne['presence__eleve_id'], []).append(ligne)

bilans_par_eleve = {}
qs_bilan = BilanMensuel.objects.filter(eleve_id__in=eleve_ids)
if annee:
    qs_bilan = qs_bilan.filter(mois_reference__year=annee, mois_reference__month=mois_num)
for b in qs_bilan.order_by('eleve_id', '-mois_reference'):
    bilans_par_eleve.setdefault(b.eleve_id, b)  # garde le premier = le plus récent par eleve_id
```
puis lire dans les deux dicts au lieu de requêter dans la boucle. Détail
d'implémentation à valider en test (l'ordre `order_by('eleve_id',
'-mois_reference')` + `setdefault` reproduit `.first()` par élève sans boucle
de requêtes — un test unitaire dessus est recommandé avant de merger, cette
partie est plus délicate que les select_related simples ci-dessus).

**Priorité : à planifier** (page de bilan mensuel, pas la plus visitée au
quotidien, mais le calcul grossit avec le nombre d'élèves).

### 2.5 — MOYEN (nouveau) — `dashboard/views.py:_tranches_enseignees_par` (programme général)
**Fichier** : `dashboard/views.py:1243-1250`

```python
def _tranches_enseignees_par(profs_qs):
    tranches = set()
    for prof in profs_qs:
        for groupe in prof.groupes.filter(statut='actif'):
            for eleve in groupe.eleves.filter(statut='actif').select_related('inscription'):
                ...
```
Triple boucle, aucun `prefetch_related` sur `profs_qs` en entrée : 1 requête
par prof pour ses groupes, puis 1 requête par groupe pour ses élèves. Pour un
مؤطر avec plusieurs profs assignés (`superviseur.profs_assignes.all()`,
l'appelant le plus exposé), ça peut faire une dizaine de requêtes — modeste
en volume absolu, mais facile à corriger :
```python
def _tranches_enseignees_par(profs_qs):
    from accounts.models import Eleve
    tranches = set()
    dates_naissance = Eleve.objects.filter(
        statut='actif', groupes__statut='actif', groupes__prof__in=profs_qs
    ).select_related('inscription').values_list('inscription__date_naissance', flat=True).distinct()
    for date_naissance in dates_naissance:
        if date_naissance:
            tranches.add(tranche_age_depuis_naissance(date_naissance))
    return tranches
```
(1 requête au lieu de 1 + N + M). **Priorité : optionnel** — page peu
visitée (programme général), volume de requêtes déjà modeste.

---

## 3. Cache

### 3.1 — IMPORTANT — Logo non caché (déjà signalé, toujours vrai)
**Fichier** : `accounts/context_processors.py`, `accounts/models.py:495-518`

`logo_context`, enregistré globalement dans `TEMPLATES[0].OPTIONS.
context_processors`, s'exécute sur **chaque page** (dashboard ET pages
publiques : login, inscription) et appelle `get_logo_config()` →
`LogoConfig.objects.get_or_create(pk=1)` sans cache. Comparer à
`chat_badge_context` (caché 15s, voir 3.2).

**Correctif** :
```python
# accounts/models.py
from django.core.cache import cache

def get_logo_config():
    config = cache.get('logo_config')
    if config is None:
        config, _ = LogoConfig.objects.get_or_create(pk=1)
        cache.set('logo_config', config, 300)  # 5 min
    return config

def invalider_cache_logo():
    cache.delete('logo_config')
```
et appeler `invalider_cache_logo()` dans la vue `mshrif_logo` après
sauvegarde (même patron que `chat.services.invalider_cache_non_lus`).
**Priorité : à faire rapidement** (impact sur absolument toutes les pages,
correctif trivial, aucun changement de comportement visible).

### 3.2 — Déjà bien fait — badge chat
`chat.services.total_messages_non_lus` : caché 15s par utilisateur
(`cache.set(cle_cache, total, 15)`), invalidation explicite ailleurs — bon
patron, à répliquer pour le logo (3.1) et les annonces (3.3).

### 3.3 — UTILE (nouveau) — Badge annonces non caché, contrairement au chat
**Fichier** : `annonces/context_processors.py`, `annonces/services.py:171-174`

`annonces_badge_context` (exécuté sur chaque page pour tout utilisateur
`role='eleve'`) fait 2 requêtes non cachées à chaque page : `Eleve.objects.
select_related('inscription').get(user=user)` (context processor) puis
`annonces_visibles_pour_eleve(eleve).exclude(lectures__user=user).count()`
(service). Chacune reste une requête simple et indexée (pas un N+1), mais
c'est incohérent avec le badge chat (même fréquence d'affichage, lui caché
15s) et s'ajoute au coût par page de chaque élève connecté.

**Correctif** : même patron que `total_messages_non_lus` — `cache.get_or_set(
f'annonces_non_lues_{user.id}', lambda: annonces_non_lues_pour_eleve(eleve, user), 15)`,
invalidé (ou simplement laissé expirer, vu le TTL court) dans
`marquer_annonces_lues`. **Priorité : optionnel** (2 requêtes légères, pas un
N+1, mais gain gratuit vu le patron déjà existant à copier).

### 3.4 — Config cache — pas de `CACHES` dans `settings.py`
Aucune section `CACHES` définie → Django retombe sur `LocMemCache` par
défaut. Ça fonctionne, mais deux limites à connaître (pas forcément un "bug"
à corriger, plutôt un point à surveiller) :
- Avec `gunicorn --workers 2`, chaque worker a **son propre cache en
  mémoire, non partagé** — un `cache.set()` fait par le worker A n'est pas
  vu par le worker B. En pratique pour les badges 15s ci-dessus, l'effet est
  juste un taux de cache-hit plus faible (~50% au lieu de ~100%), jamais une
  incohérence grave vu le TTL très court — pas critique, mais si un futur
  cache à TTL long est ajouté (ex. logo à 5 min ci-dessus), la moitié des
  requêtes STARTA quand même MISS selon le worker qui répond. Sans service
  Redis/Memcached externe (aucun sur le plan free Render/Supabase), il n'y a
  pas de correctif simple à ce point précis — à accepter tel quel vu
  l'échelle du projet.
- Le cache est vidé à chaque redéploiement (redémarrage des workers) — sans
  incidence pratique ici (TTL de 15s à 5 min).

**Priorité : aucune action requise**, juste un point de contexte pour ne pas
être surpris si un futur cache à TTL plus long semble "à moitié efficace".

---

## 4. Connexions DB / infra

### 4.1 — CRITIQUE (déjà signalé, toujours vrai) — `CONN_MAX_AGE` non défini
**Fichier** : `core/settings.py:137-139`

```python
DATABASES = {'default': env.db('DATABASE_URL')}
```
Pas de `CONN_MAX_AGE` → défaut Django = 0 → une connexion Postgres neuve
(TCP+TLS+auth) est ouverte puis fermée à CHAQUE requête HTTP, pour chaque
thread gunicorn. `DATABASE_URL` pointe déjà vers le pooler Supabase (port
`6543`, mode transaction) donc PgBouncer est en place côté Supabase, mais
`CONN_MAX_AGE=0` repaie quand même le handshake client ↔ PgBouncer à chaque
requête.

**Correctif** :
```python
DATABASES = {'default': env.db('DATABASE_URL')}
DATABASES['default']['CONN_MAX_AGE'] = 60
DATABASES['default']['CONN_HEALTH_CHECKS'] = True  # Django >= 4.1
```
Sur un pooler en mode transaction (PgBouncer), garder la connexion cliente
ouverte côté Django ne pose pas de souci de compatibilité (PgBouncer gère le
multiplexage des connexions réelles vers Postgres indépendamment de la durée
de vie de la connexion cliente) — juste à vérifier que la limite de
connexions clientes du plan free Supabase n'est pas plus basse que
`workers × threads` (2 × 4 = 8 ici, largement sous les limites free tier
habituelles). **Priorité : à faire immédiatement** (1-2 lignes, gain sur
absolument chaque requête).

### 4.2 — Procfile / mémoire
```
web: gunicorn core.wsgi --workers 2 --worker-class gthread --threads 4 --timeout 30 --worker-tmp-dir /dev/shm --log-file -
```
8 requêtes concurrentes max au total. Le point 2.3 (page paiements qui charge
toute la table) est le candidat le plus probable pour un pic mémoire sur un
service à 512 Mo (plan free) — pas trouvé dans la version précédente de
l'audit faute d'avoir ouvert `payments/views.py`. Une fois 2.3 corrigé, revoir
si des symptômes de saturation persistent avant de toucher au Procfile (pas
de valeur workers/threads chiffrée fiable sans les métriques Render — même
réserve que la version précédente).

### 4.3 — Chat : polling HTTP répété côté navigateur
**Fichier** : `templates/chat/chat.html` — `setInterval(rafraichirListe, 10000)`
et `setInterval(poll, 8000)`. Chaque onglet chat ouvert = ~1 requête/8s +
1/10s en continu, chacune payant le coût d'une connexion DB neuve tant que
4.1 n'est pas corrigé, et occupant un des 8 slots gunicorn le temps de la
requête. **Priorité : à discuter avec toi** (réduire la fréquence, ou la
couper via `document.visibilityState` quand l'onglet est en arrière-plan) —
change un comportement visible (fraîcheur du chat), pas un correctif neutre.

---

## 5. Entrées/sorties bloquantes (nouveau, absent de la 1ère version)

### 5.1 — IMPORTANT — Notifications Telegram synchrones dans le cycle requête/réponse
**Fichier** : `core/utils.py:73-121` (`envoyer_notification_telegram`), appelée
notamment depuis `payments/views.py:157` (nouveau paiement soumis par un
élève) et d'autres points similaires (nouvelle inscription, mot de passe
oublié — mêmes patrons ailleurs dans `dashboard/views.py`/`inscriptions/`).

```python
for abonne in abonnes:
    try:
        if envoyer_message_telegram_direct(abonne.chat_id, message):
            ...
```
`envoyer_message_telegram_direct` fait un `requests.post(..., timeout=5)`
**synchrone**, un appel réseau externe par abonné Telegram actif, exécuté
DANS le traitement de la requête HTTP de l'utilisateur (élève qui soumet un
paiement, candidat qui s'inscrit...) — donc avant que la réponse ne lui soit
renvoyée. Si l'API Telegram est lente ou indisponible, ou s'il y a plusieurs
abonnés (plusieurs مدير/مشرف abonnés aux notifications), l'utilisateur attend
potentiellement plusieurs secondes (jusqu'à `5s × nb_abonnés` dans le pire
cas) juste pour voir "paiement envoyé avec succès" — un souci Telegram
retarde une action qui n'a pourtant rien à voir avec Telegram.

**Correctif proposé** (sans ajouter Celery/Redis, hors de portée pour ce
projet/cette hébergeur) : lancer l'envoi Telegram dans un thread daemon
détaché plutôt que d'attendre son résultat avant de répondre :
```python
import threading

def envoyer_notification_telegram_async(message):
    threading.Thread(
        target=envoyer_notification_telegram, args=(message,), daemon=True
    ).start()
```
et remplacer les appels `envoyer_notification_telegram(...)` par
`envoyer_notification_telegram_async(...)` aux points d'appel identifiés
(paiement, inscription, mot de passe oublié). **Limite à connaître** : un
thread daemon est tué net si le worker gunicorn redémarre avant sa fin —
acceptable ici (notification "best effort", déjà tolérante aux échecs
individuels par design, voir le docstring de la fonction) mais à dire
explicitement puisque ça change une garantie implicite (avant : la requête
HTTP ne se termine que si Telegram a fini de répondre à tous ; après : la
requête répond tout de suite, l'envoi Telegram peut échouer silencieusement
en cas de redémarrage exactement pendant cette fenêtre — rarissime en
pratique). **Priorité : à planifier** (pas literally cassé, mais un vrai
gain de réactivité perçue sur les actions qui déclenchent une notification).

---

## 6. Frontend

### 6.1 — UTILE (nouveau) — CSS entièrement inline dans chaque base, jamais mis en cache navigateur
**Fichiers** : `templates/dashboard/base_admin.html` (454 lignes, dont un
`<style>` de ~400 lignes), pareil pour `base_prof.html`/`base_eleve.html`/
`base_superviseur.html`/`base_mshrif.html` (déjà noté comme dette technique
dans `CLAUDE.md`, mais avec un vrai coût perf à préciser) : ce CSS étant
inline dans le HTML de CHAQUE page (pas dans un fichier `.css` séparé), il
est retéléchargé intégralement à chaque navigation complète — un fichier
statique séparé serait mis en cache par le navigateur (WhiteNoise sert déjà
`static/` avec des headers de cache longue durée via
`CompressedManifestStaticFilesStorage`) et ne serait téléchargé qu'une fois
par session. Avec Bootstrap/Tajawal déjà en CDN (mis en cache par le
navigateur indépendamment de ce site), ce CSS inline propre au projet est la
seule partie qui repaie son poids à chaque clic.

**Correctif** (structurel, pas un "quick win" vu le volume de templates à
adapter) : extraire le contenu de chaque `<style>` de base dans
`static/css/base_<role>.css` (ou un seul `static/css/dashboard.css` commun +
overrides courts par rôle), chargé via `<link rel="stylesheet" href="{%
static ... %}">`. **Priorité : optionnel/structurel** — gain réel mais pas
urgent, à faire quand une refonte CSS est de toute façon prévue (cf. dette
technique déjà notée dans `CLAUDE.md` §14).

### 6.2 — Optionnel — Police Tajawal chargée même en français/anglais
**Fichier** : `templates/dashboard/base_*.html` — `<link href="https://
fonts.googleapis.com/css2?family=Tajawal...">` chargé inconditionnellement,
puis `* { font-family: 'Tajawal', sans-serif; }` appliqué globalement même
quand `LANGUAGE_BIDI` est faux (utilisateur en français/anglais). Un
visiteur FR/EN paie donc une requête de police (+ un flash de texte le temps
du téléchargement) pour une police pensée pour l'arabe, sans bénéfice
visuel. **Correctif** : conditionner le `<link>` Google Fonts et la règle
`font-family` à `{% if LANGUAGE_BIDI %}`, avec un empilement de polices
système (`-apple-system, Segoe UI, Roboto, sans-serif`) en repli pour FR/EN.
**Priorité : optionnel** (gain faible mais gratuit une fois vu).

### 6.3 — Mineur — Images du logo non optimisées
**Fichier** : `static/images/logo_nouveau.jpeg` (96 Ko), `logo.jpeg` (48 Ko).
Pas énorme, mais un logo utilisé sur CHAQUE page (favicon + header sidebar)
gagnerait à être compressé/redimensionné à sa taille d'affichage réelle
(WebP ou JPEG optimisé réduirait probablement ce poids de moitié). WhiteNoise
compresse déjà en gzip via `CompressedManifestStaticFilesStorage`, mais gzip
n'apporte presque rien sur un JPEG déjà compressé — il faut réduire l'image
elle-même, pas sa compression de transport. **Priorité : optionnel**.

### 6.4 — Vérifié, pas de souci
Pas de framework JS lourd (contrainte du projet respectée : vanilla JS,
Bootstrap 5 CDN, pas de bundle à charger). Chat en polling plutôt que
WebSocket — choix d'architecture documenté, pas un oubli (voir 4.3).

---

## 7. Index base de données

Peu de manque : `Groupe.nom` a un index GIN trigram (`courses/models.py:473`,
recherche globale), les FK sont indexées automatiquement par Django/Postgres.
Pas de colonne filtrée/triée fréquemment identifiée sans index dans les
modèles inspectés (`courses`, `chat`, `accounts`, `payments`). À l'échelle
d'une école (centaines à quelques milliers de lignes par table), Postgres
scanne ces tables sans qu'un index supplémentaire change quoi que ce soit de
perceptible — **non prioritaire**, à revisiter seulement si `EXPLAIN
ANALYZE` en production montre un `Seq Scan` coûteux sur une requête précise.

---

## 8. Plan d'action

| # | Priorité | Fix | Fichiers |
|---|----------|-----|----------|
| 1 | CRITIQUE | `CONN_MAX_AGE=60` + `CONN_HEALTH_CHECKS=True` | `core/settings.py` |
| 2 | CRITIQUE | `select_related`/dédup `count()` sur `groupe_detail` (prof, creneau, eleves, eleves_disponibles) | `courses/views.py`, `templates/courses/admin_groupe_detail.html` |
| 3 | CRITIQUE | `suivi_paiements_eleves` : filtrer les 2 requêtes `Paiement` par le scope groupe/élèves affiché au lieu de charger toute la table | `payments/views.py` |
| 4 | IMPORTANT | Cacher `get_logo_config()` (patron déjà existant pour le badge chat) | `accounts/models.py`/`context_processors.py` |
| 5 | IMPORTANT | Notifications Telegram en thread daemon (ne pas bloquer la réponse HTTP) | `core/utils.py`, points d'appel (paiement, inscription, mdp oublié) |
| 6 | À PLANIFIER | Batch des requêtes par élève dans `bilans_mensuels` (2 requêtes/élève → 2 requêtes totales) | `dashboard/views.py` |
| 7 | UTILE | `annotate(Count('eleves'))` sur `groupes_list` | `courses/views.py`, `admin_groupes.html` |
| 8 | UTILE | Cacher le badge annonces 15s (même patron que le chat) | `annonces/services.py`/`context_processors.py` |
| 9 | À DISCUTER | Pagination de `suivi_paiements_eleves` (change l'UX) | `payments/views.py` |
| 10 | À DISCUTER | Polling chat conditionné à la visibilité de l'onglet / intervalle allongé | `templates/chat/chat.html` |
| 11 | À VÉRIFIER (infra, pas du code) | Confirmer si la lenteur rapportée est un cold start Render free plutôt qu'un souci de code — voir section 0 | Render dashboard |
| 12 | Optionnel | `_tranches_enseignees_par` en 1 requête au lieu de boucle imbriquée | `dashboard/views.py` |
| 13 | Optionnel/structurel | Extraire le CSS inline des `base_*.html` vers des fichiers statiques cachés | `templates/dashboard/base_*.html` |
| 14 | Optionnel | Police Tajawal seulement si `LANGUAGE_BIDI` | `templates/dashboard/base_*.html` |
| 15 | Optionnel | Compresser/redimensionner les JPEG du logo | `static/images/*.jpeg` |

### Quick wins (gain élevé, effort faible, aucun changement de comportement visible)
1, 2, 3 (partie requêtes, pas la pagination), 4, 7.

### Actions structurelles (plus lourdes ou nécessitant une décision produit)
5 (limite de garantie à accepter explicitement), 6 (logique de batch plus
délicate, mérite un test avant merge), 9 et 10 (changent l'UX, à discuter
avec toi avant d'implémenter), 13 (refonte CSS).

---

## Limites de cet audit

- Aucun outil de comptage runtime (`django-debug-toolbar`/`django-silk`) ni
  `EXPLAIN ANALYZE` exécuté contre la base réelle — tous les chiffres de
  requêtes ci-dessus sont des estimations à partir de la lecture du code
  (comptage des accès relationnels non `select_related`/`prefetch_related`
  visibles dans le template correspondant à chaque vue), pas des mesures.
- `dashboard/views.py` (7998 lignes, ~359 vues) a été couvert par recherche
  systématique de motifs à risque plutôt que relu ligne par ligne dans
  l'ordre — voir le paragraphe de méthode en tête de document. Les zones
  listées en section 2 ont, elles, été lues et vérifiées en entier contre
  leur template.
- Pas d'accès aux métriques Render (CPU/mémoire/latence par page) ni aux
  tableaux de bord Supabase (limites de connexions réelles du plan free) —
  la section 0 et le point 4.1 en tiennent compte par des marges de
  prudence plutôt que des chiffres exacts.
