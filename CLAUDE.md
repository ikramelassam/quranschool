## **Zidni Ilman — Document de Transmission Complet** 

## Pour Claude Code — Reprise du projet Django 

Projet: `■■■■ ■■■■■` | Client réel | Développeuse: Ikram El Assam — EMINES UM6P 

## **1. OBJECTIF DU PROJET** 

## **But du projet :** 

Plateforme web complète de gestion d'une école coranique à distance ( `■■■■ ■■■■ ■■■■■` ). Digitalise tout le cycle de vie : inscription → validation → affectation aux groupes → suivi des séances → évaluations → paiements. 

## **Utilisateurs :** 

- Admin — gère tout (inscriptions, groupes, créneaux, séances, paiements) 

- Prof (Professeur) — voit ses groupes, marque les présences, évalue les élèves par séance 

- Eleve (Étudiant) — voit ses séances, ses notes et les remarques du professeur 

- Superviseur — surveille les séances terminées, évalue les professeurs 

## **Fonctionnalités principales :** 

- Authentification par email avec rôles multiples 

- Inscription élève avec créneaux dynamiques (filtrés par âge et sexe en JS) 

- Inscription professeur (7 sections dont upload audio) 

- Workflow admin : validation → création automatique de compte User+Eleve/Prof 

- Gestion des créneaux horaires (CRUD + toggle actif/inactif) 

- Gestion des groupes (CRUD + assignation élèves/prof/créneau) 

- Gestion des séances par l'admin 

- Feuille de présence par prof (présence + notes + quantité mémorisée + remarques) 

- Dashboard dédié par rôle avec sidebar propre à chaque rôle 

- Suivi paiements (modèle existant, vues non implémentées) 

- Évaluation superviseur (modèle existant, vues non implémentées) 

## **Contraintes :** 

- Interface entièrement en arabe, direction RTL 

- Bootstrap 5 RTL uniquement (pas de Tailwind, pas de framework JS) 

- Pas de Django Forms — tout en HTML brut + request.POST.get() 

- PostgreSQL obligatoire (pas SQLite) 

- Windows OS, venv local, path: C:\Users\ikram\Desktop\quran-school-management 

- Client réel : code sensible, ne pas exposer publiquement 

- Étudiante débutante — expliquer avant de coder 

## **2. ARCHITECTURE GÉNÉRALE** 

## **Structure des dossiers :** 

```
quran-school-management/
■■■manage.py
■■■core/
■■■■settings.py
■■■■urls.py
```

- `# Config Django principale` 

- `# DB, auth backends, installed apps, templates, static # Root URL dispatcher (include par app)` 

**==> picture [402 x 309] intentionally omitted <==**

**----- Start of picture text -----**<br>
■ ■■■ wsgi.py<br>■■■ accounts/  # Utilisateurs et profils<br>■ ■■■ models.py  # User, Eleve, Prof, Superviseur<br>■ ■■■ views.py  # login_view, logout_view, redirect_by_role<br>■ ■■■ urls.py  # /accounts/login/, /accounts/logout/<br>■ ■■■ backends.py  # EmailBackend (auth par email)<br>■ ■■■ admin.py  # CustomUserAdmin (affiche champ role)<br>■■■ inscriptions/  # Formulaires d'inscription<br>■ ■■■ models.py  # InscriptionEleve, InscriptionProf, DisponibiliteInscription<br>■ ■■■ views.py  # inscription_eleve_choix, inscription_eleve_formulaire,<br>■ ■ # inscription_prof, inscription_confirmation<br>■ ■■■ urls.py<br>■■■ courses/  # Groupes, séances, créneaux, présences<br>■ ■■■ models.py  # Creneau, Groupe, Seance, Presence, Disponibilite<br>■ ■■■ views.py  # CRUD groupes + CRUD créneaux<br>■ ■■■ urls.py<br>■ ■■■ admin.py<br>■■■ payments/  # Paiements (modèle seulement, pas de vues)<br>■ ■■■ models.py<br>■■■ evaluations/  # Évaluations superviseur (modèle seulement)<br>■ ■■■ models.py<br>■■■ dashboard/  # Vues des dashboards (ZÉRO modèle)<br>■ ■■■ views.py  # Toutes les vues dashboard (admin, prof, eleve, superviseur)<br>■ ■■■ urls.py  # Toutes les URLs dashboard<br>■■■ templates/<br>■ ■■■ accounts/login.html<br>■ ■■■ dashboard/  # base_admin/prof/eleve/superviseur + toutes les pages<br>■ ■■■ inscriptions/  # eleve_choix, eleve_formulaire, prof_formulaire, confirmation<br>■ ■■■ courses/  # CRUD groupes et créneaux<br>■■■ static/<br>■■■ images/logo.png<br>**----- End of picture text -----**<br>


## **Rôle de chaque application :** 

|App|Rôle|Contient des modèles ?|
|---|---|---|
||||
|accounts|Utilisateurs + profils par rôle|Oui (User, Eleve, Prof, Superviseur)|
|inscriptions|Formulaires candidature élève/prof|Oui (InscriptionEleve, InscriptionProf)|
||||
|courses|Créneaux, groupes, séances, présences|Oui (Creneau, Groupe, Seance, Presence)|
|payments|Suivi paiements|Oui (Paiement) — PAS de vues|
||||
|evaluations|Évaluations superviseur|Oui (Evaluation) — PAS de vues|
|dashboard|Toutes les vues des dashboards|NON — uniquement views.py + urls.py|
||||



## **3. BASE DE DONNÉES** 

## **App: accounts — Model: User (extends AbstractUser)** 

```
Rôle: Modèle utilisateur central. Tous les rôles partagent ce modèle.
Champs ajoutés (au-delà d'AbstractUser):
telephone = CharField(max_length=20, blank=True)
date_naissance = DateField(null=True, blank=True)
role = CharField(choices=['eleve','prof','superviseur','admin'], default='eleve')
IMPORTANT: username = email à la création (contournement car Django requiert username unique)
AUTH_USER_MODEL = 'accounts.User' dans settings.py
str: str(self.username)
```

## **App: accounts — Model: Eleve** 

```
Rôle: Profil étudiant lié à un User.
user = OneToOneField(User, CASCADE)
sexe = CharField(max_length=10, default='')
statut = CharField(max_length=20, default='actif')
Relation ManyToMany INVERSE: eleve.groupes.all() via courses.Groupe.eleves
str: str(self.user)
```

## **App: accounts — Model: Prof** 

```
Rôle: Profil professeur.
```

```
user = OneToOneField(User, CASCADE)
ville = CharField(max_length=100)
certifications = TextField(blank=True)
niveau_memorisation = CharField(max_length=100)
type_eleve_preference = JSONField(default=list) # ['enfants','adultes','les_deux']
contrainte_genre = JSONField(default=list) # ['homme','femme','mixte']
langues = JSONField(default=list) # ['arabe','francais','anglais']
outils_maitrises = JSONField(default=list) # ['whatsapp','meet','zoom']
parcours_scolaire = TextField()
parcours_enseignant = TextField()
gestion_eleve_faible = TextField(blank=True)
gestion_eleve_absent = TextField(blank=True)
compte_bancaire = CharField(max_length=50)
rib = CharField(max_length=50)
Relation: prof.groupes.all() via courses.Groupe.prof (ForeignKey)
str: str(self.user)
```

## **App: accounts — Model: Superviseur** 

```
Rôle: Profil superviseur (minimal).
user = OneToOneField(User, CASCADE)
```

## **App: inscriptions — Model: InscriptionEleve** 

```
Rôle: Formulaire de candidature étudiant. SÉPARÉ du modèle Eleve.
nom, prenom(blank), nom_parent(blank) = CharField
date_naissance = DateField
sexe = CharField(default='')
telephone, email = CharField/EmailField
creneau_souhaite = ForeignKey('courses.Creneau', null=True, blank=True, SET_NULL)
programme = CharField(choices: hifz/tathbit, default='hifz')
riwaya = CharField(choices: warsh/hafs, default='hafs')
outil = CharField(choices: whatsapp/meet/les_deux, default='whatsapp')
abonnement = CharField(choices: groupe_1mois(80dh)/groupe_3mois(220dh)/
individuel_1mois(400dh)/individuel_3mois(1100dh))
accepte_conditions = BooleanField(default=False)
veut_contribuer = BooleanField(default=False)
remarques = TextField(blank=True)
statut = CharField(choices: en_attente/valide/rejete, default='en_attente')
date_soumission = DateTimeField(auto_now_add=True)
str: "{nom} {prenom}"
```

## **App: inscriptions — Model: InscriptionProf** 

```
Rôle: Formulaire de candidature professeur. SÉPARÉ du modèle Prof.
nom, prenom, date_naissance, ville, statut_familial, job_actuel = CharField/DateField
certifications, niveau_memorisation = TextField/CharField
type_eleve_preference, contrainte_genre, langues, outils_maitrises = JSONField(default=list)
parcours_scolaire, parcours_enseignant = TextField
gestion_eleve_faible, gestion_eleve_absent = TextField
compte_bancaire, rib = CharField
audio_enregistrement = FileField(upload_to='audio_inscriptions/', null=True, blank=True)
email = EmailField
statut = CharField(choices: en_attente/valide/rejete, default='en_attente')
date_soumission = DateTimeField(auto_now_add=True)
```

```
NOTE: MEDIA_ROOT pas encore configuré dans settings.py ! Les uploads audio ne fonctionnent pas.
```

## **App: courses — Model: Creneau** 

```
Rôle: Créneau horaire hebdomadaire (2 jours obligatoires). Géré par l'admin.
sexe_cible = CharField(choices: homme/femme/mixte, default='mixte')
age_min = IntegerField # ex: 4
age_max = IntegerField # ex: 15 (ou 999 pour adultes sans limite)
jour_1 = CharField(choices: lun/mar/mer/jeu/ven/sam/dim)
heure_debut_1, heure_fin_1 = TimeField
jour_2 = CharField(choices: lun/mar/mer/jeu/ven/sam/dim)
heure_debut_2, heure_fin_2 = TimeField
est_actif = BooleanField(default=True)
```

```
# est_actif=False: n'apparaît plus dans le formulaire d'inscription mais les groupes existants ne sont PAS affectés
str: "{jour_1_display} {heure_debut_1} + {jour_2_display} {heure_debut_2}"
```

**App: courses — Model: Groupe** 

```
Rôle: Groupe d'élèves assigné à un prof et un créneau.
nom = CharField(max_length=100)
description= TextField(blank=True)
eleves = ManyToManyField('accounts.Eleve', blank=True, related_name='groupes')
prof = ForeignKey(Prof, null=True, blank=True, SET_NULL, related_name='groupes')
creneau = ForeignKey(Creneau, null=True, blank=True, SET_NULL, related_name='groupes')
capacite_max = IntegerField(default=10)
statut = CharField(choices: actif/archive, default='actif')
IMPORTANT: eleve.groupes.all() fonctionne grâce au related_name='groupes' sur ManyToMany
str: self.nom
```

**App: courses — Model: Seance** 

```
Rôle: Une séance de cours. Créée par l'admin, remplie par le prof.
groupe = ForeignKey(Groupe, CASCADE, related_name='seances')
date = DateField
heure = TimeField
type = CharField(choices: normal/rattrapage/revision)
statut = CharField(choices: planifiee/terminee/annulee, default='planifiee')
superviseur = ForeignKey(Superviseur, null=True, blank=True, SET_NULL)
# statut passe à 'terminee' quand le prof sauvegarde les présences
str: "{groupe} - {date}"
```

**App: courses — Model: Presence** 

```
Rôle: Présence + évaluation d'un élève pour une séance donnée.
seance = ForeignKey(Seance, CASCADE, related_name='presences')
eleve = ForeignKey(Eleve, CASCADE, related_name='presences')
statut = CharField(choices: present/absent_excuse/absent, default='present')
quantite_memorisee = CharField(max_length=200, blank=True) # ex: "■■■■■■1-10"
quantite_revisee = CharField(max_length=200, blank=True)
note_memorisation = CharField(choices: mumtaz/hasan/mutawassit/yuid, blank=True)
note_revision= CharField(choices: mumtaz/hasan/mutawassit/yuid, blank=True)
remarque = TextField(blank=True)
unique_together: (seance, eleve)
# Créé/mis à jour via Presence.objects.update_or_create(seance=, eleve=, defaults={...})
str: "{eleve} - {seance}"
```

**App: payments — Model: Paiement (PAS DE VUES)** 

`eleve = ForeignKey(Eleve) montant = DecimalField date_paiement = DateField mois_concerne = CharField statut = CharField(choices: paye/en_attente/retard) remarque = TextField(blank=True)` **App: evaluations — Model: Evaluation (PAS DE VUES)** `seance = ForeignKey(Seance) superviseur = ForeignKey(Superviseur) note_prof = CharField ou IntegerField commentaire = TextField date = DateTimeField(auto_now_add=True)` 

**App: evaluations — Model: Evaluation (PAS DE VUES)** 

## **4. AUTHENTIFICATION** 

**EmailBackend — accounts/backends.py :** 

```
class EmailBackend(ModelBackend):
def authenticate(self, request, username=None, password=None, **kwargs):
try:
user = User.objects.get(email=username)
```

```
if user.check_password(password):
return user
return None
except User.DoesNotExist:
return None
```

```
# Dans settings.py:
AUTHENTICATION_BACKENDS = ['accounts.backends.EmailBackend']
LOGIN_URL = '/accounts/login/'
```

## **redirect_by_role — accounts/views.py :** 

```
def redirect_by_role(user):
if user.role == 'eleve': return redirect('dashboard_eleve')
elif user.role == 'prof': return redirect('dashboard_prof')
elif user.role == 'superviseur':return redirect('dashboard_superviseur')
elif user.role == 'admin': return redirect('dashboard_admin')
return redirect('login')
```

## **Décorateurs utilisés :** 

Toutes les vues dashboard utilisent @login_required uniquement. Il N'Y A PAS de vérification de rôle dans les vues — LIMITATION CONNUE : n'importe quel utilisateur connecté peut accéder à n'importe quel dashboard s'il connaît l'URL. 

## **Création des comptes (logique admin_valider_eleve / admin_valider_prof) :** 

```
# Lors de la validation d'une inscription par l'admin:
if not User.objects.filter(email=inscription.email).exists():
password_temp = ''.join(random.choices(string.ascii_letters + string.digits, k=8))
user = User.objects.create_user(
username=inscription.email, # username = email (convention du projet)
email=inscription.email,
password=password_temp,
first_name=inscription.nom,
last_name=inscription.prenom, # pour prof seulement
role='eleve' # ou 'prof'
)
Eleve.objects.create(user=user, sexe=inscription.sexe, statut='actif')
# OU Prof.objects.create(user=user, ville=..., ...)
inscription.statut = 'valide'
inscription.save()
# PROBLÈME: password_temp n'est jamais envoyé à l'utilisateur (pas d'email configuré)
```

## **5. FONCTIONNALITÉS RÉALISÉES** 

**Login / Logout** — 100% fonctionnel 

`■` auth par email, redirect par rôle, EmailBackend configuré 

**Inscription Élève** — 100% fonctionnel 

`■` choix enfant/adulte, formulaire dynamique, créneaux filtrés JS par âge+sexe, sauvegarde InscriptionEleve 

**Inscription Prof** — 95% fonctionnel 

`■` 7 sections, toggle buttons JS pour multi-select, upload audio (champ existe) 

`■■` Reste: MEDIA_ROOT non configuré → audio ne s'enregistre pas sur disque 

**Admin — Valider Élève** — 100% fonctionnel 

`■` crée User+Eleve automatiquement, gère doublon email 

`■■` Reste: pas d'envoi email avec mot de passe 

**Admin — Valider Prof** — 100% fonctionnel 

`■` crée User+Prof avec tous les champs copiés depuis InscriptionProf 

`■■` Reste: pas d'envoi email avec mot de passe 

**Admin — Créneaux CRUD** — 100% fonctionnel 

`■` ajouter/modifier/toggle actif, formulaire avec TimeField 

**Admin — Groupes CRUD** — 100% fonctionnel 

`■` ajouter/modifier/assigner élèves+prof+créneau, detail page 

**Admin — Séances** — 100% fonctionnel 

`■` créer séance par groupe, annuler séance 

**Admin — Dashboard home** — 100% fonctionnel 

`■` stats (total élèves/profs/groupes/pending), dernières inscriptions élèves+profs 

**Admin — Liste élèves validés** — 100% fonctionnel 

`■` liste avec statut et nombre de groupes 

**Admin — Liste profs validés** — 100% fonctionnel 

`■` liste avec ville et nombre de groupes 

**Prof — Dashboard home** — 100% fonctionnel 

`■` stats (groupes, élèves, séances récentes) 

**Prof — Mes groupes** — 100% fonctionnel 

`■` liste groupes + détail avec élèves 

**Prof — Mes séances** — 100% fonctionnel 

`■` liste toutes séances avec statut 

**Prof — Feuille présence** — 90% fonctionnel 

`■` formulaire par élève: statut+notes+quantités+remarques, update_or_create 

`■■` Reste: bug potentiel: presences[eleve.id] en template Django 

**Prof — Emploi du temps** — 100% fonctionnel 

`■` affiche créneaux par groupe 

**Élève — Dashboard home** — 100% fonctionnel 

`■` stats + dernières évaluations avec remarques prof 

**Élève — Mes séances** — 100% fonctionnel 

`■` historique complet avec notes et remarques 

**Élève — Profil** — 100% fonctionnel 

`■` infos personnelles + groupes 

**Superviseur — Dashboard** — 100% fonctionnel 

`■` liste séances terminées 

**Superviseur — Détail séance** — 100% fonctionnel 

`■` toutes présences + notes élèves 

## **6. FONCTIONNALITÉS INCOMPLÈTES** 

`■` PAIEMENTS — modèle Paiement existe, ZÉRO vues/templates/URLs. À créer complètement. 

`■` ÉVALUATION SUPERVISEUR — modèle Evaluation existe, ZÉRO vues. Le superviseur ne peut que voir les séances, pas évaluer le prof. 

`■` ENVOI EMAIL — à la création de compte, le mot de passe temporaire est généré mais jamais envoyé à l'utilisateur. 

`■` MEDIA_ROOT — non configuré dans settings.py. Les uploads audio (InscriptionProf) ne sont pas sauvegardés sur disque. 

`■` SÉCURITÉ PAR RÔLE — aucune vérification de rôle dans les vues. Un élève connecté peut accéder à /dashboard/admin/ s'il connaît l'URL. 

`■` PAGES PARAMÈTRES — sidebar contient ' `■■■■■■■■■` ' mais pointe vers '#' pour tous les rôles. 

`■` CALENDRIER SÉANCES — sidebar admin contient ' `■■■■■■ ■■■■■■` ' mais pointe vers '#'. 

`■` MOT DE PASSE — pas de page 'mot de passe oublié' ni de reset. 

`■` PAGINATION — toutes les listes affichent tous les éléments sans pagination. 

`■` PROFIL SUPERVISEUR — le superviseur n'a pas de profil complet dans accounts (Superviseur model très minimal). 

## **7. CHOIX TECHNIQUES** 

**EmailBackend au lieu de username:** Le client voulait la connexion par email. Django utilise username par défaut. Solution: backend personnalisé + username=email à la création. 

**6 applications Django séparées:** Séparation des responsabilités. accounts=qui, inscriptions=candidatures, courses=pédagogie, payments=finances. dashboard n'a PAS de modèles. 

**Creneau dans courses/ pas inscriptions/:** Un créneau est un concept pédagogique (horaire d'un groupe), pas juste une préférence d'inscription. L'élève choisit un créneau, le groupe y est assigné. 

**InscriptionEleve séparé de Eleve:** La candidature n'est pas le compte. L'admin valide → compte créé. Historique des candidatures conservé. 

**Pas de Django Forms:** Formulaires HTML bruts + request.POST.get(). Plus simple pour une débutante, moins de magie. Contrepartie: pas de validation automatique. 

**ManyToMany Groupe.eleves:** Un élève peut être dans plusieurs groupes. Relation via related_name='groupes' accessible via eleve.groupes.all(). 

**JSONField pour langues/outils:** Données multi-valuées variables (langues parlées, outils maîtrisés). JSONField stocke une liste Python directement. Alternative aurait été des BooleanFields multiples. 

**Bootstrap 5 RTL:** Interface arabe, direction RTL requise. Bootstrap RTL gère automatiquement la direction. CDN, pas d'installation. 

**Template inheritance par rôle:** base_admin.html, base_prof.html, base_eleve.html, base_superviseur.html. Sidebar différente par rôle, couleur différente. Toutes les pages héritent du bon base. 

**update_or_create pour Presence:** Le prof peut remplir la feuille plusieurs fois (correction). update_or_create évite les doublons (unique_together seance+eleve). 

## **8. PACKAGES UTILISÉS** 

`django==6.0.2` → `framework web principal psycopg2-binary` → `connecteur PostgreSQL pour Django # Frontend (CDN, pas installés): Bootstrap 5.3 RTL` → `https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css Tajawal (Google Fonts)` → `police arabe` 

```
# À installer pour les emails (futur):
# pip install django-anymail ou configuration SMTP native Django
# Pour les rapports PDF (si besoin futur):
# pip install reportlab
```

## **9. ENDPOINTS COMPLETS** 

`# core/urls.py (root) admin/` → `Django admin natif accounts/` → `include('accounts.urls') dashboard/` → `include('dashboard.urls') inscriptions/` → `include('inscriptions.urls') courses/` → `include('courses.urls') # accounts/urls.py` → `prefix /accounts/ login/` → `login_view (GET: formulaire, POST: authentifie + redirect par rôle) logout/` → `logout_view (déconnecte + redirect login) # inscriptions/urls.py` → `prefix /inscriptions/ eleve/choix/` → `inscription_eleve_choix (page choix enfant/adulte) eleve/formulaire/<str:type_age>/` → `inscription_eleve_formulaire (GET: formulaire, POST: create) prof/` → `inscription_prof (GET: formulaire 7 sections, POST: create) confirmation/` → `inscription_confirmation (page succès) # courses/urls.py` → `prefix /courses/` 

`groupes/` → `groupes_list groupes/ajouter/` → `groupe_ajouter groupes/<int:groupe_id>/` → `groupe_detail groupes/<int:groupe_id>/modifier/` → `groupe_modifier groupes/<int:groupe_id>/ajouter-eleve/` → `groupe_ajouter_eleve (POST only) creneaux/` → `creneaux_list creneaux/ajouter/` → `creneau_ajouter creneaux/<int:creneau_id>/modifier/` → `creneau_modifier creneaux/<int:creneau_id>/toggle/` → `creneau_toggle (GET, inverse est_actif) # dashboard/urls.py` → `prefix /dashboard/ # Dashboards principaux eleve/` → `dashboard_eleve prof/` → `dashboard_prof superviseur/` → `dashboard_superviseur admin/` → `dashboard_admin # Élève eleve/seances/` → `eleve_seances eleve/profil/` → `eleve_profil # Prof prof/groupes/` → `prof_groupes prof/groupes/<int:groupe_id>/` → `prof_groupe_detail prof/seances/` → `prof_seances prof/seances/<int:seance_id>/` → `prof_seance_detail prof/seances/<int:seance_id>/presence/` → `prof_presence_sauvegarder (POST only) prof/emploi/` → `prof_emploi # Superviseur superviseur/seance/<int:seance_id>/` → `superviseur_seance_detail # Admin — inscriptions admin/inscriptions/` → `admin_inscriptions admin/inscriptions/eleve/<int:id>/` → `admin_inscription_eleve_detail admin/inscriptions/eleve/<int:id>/valider/` → `admin_valider_eleve admin/inscriptions/eleve/<int:id>/rejeter/` → `admin_rejeter_eleve admin/inscriptions/profs/` → `admin_inscriptions_profs admin/inscriptions/prof/<int:id>/` → `admin_inscription_prof_detail admin/inscriptions/prof/<int:id>/valider/` → `admin_valider_prof admin/inscriptions/prof/<int:id>/rejeter/` → `admin_rejeter_prof # Admin — gestion admin/eleves/` → `admin_eleves admin/profs/` → `admin_profs admin/seances/` → `admin_seances (GET: liste, POST: créer) admin/seances/<int:seance_id>/annuler/` → `admin_seance_annuler` 

## **10. TEMPLATES** 

`# Héritage: base_admin.html`  `admin.html, admin_inscriptions.html, admin_inscription_detail.html, admin_inscriptions_profs.html, admin_inscription_prof_detail.html, admin_eleves.html, admin_profs.html, admin_seances.html + courses/admin_groupes.html, admin_groupe_ajouter.html, admin_groupe_detail.html, admin_groupe_modifier.html, admin_creneaux.html, admin_creneau_ajouter.html, admin_creneau_modifier.html base_prof.html`  `prof.html, prof_groupes.html, prof_groupe_detail.html, prof_seances.html, prof_seance_detail.html, prof_emploi.html base_eleve.html`  `eleve.html, eleve_seances.html, eleve_profil.html base_superviseur.html`  `superviseur.html, superviseur_seance_detail.html # Standalone (pas d'héritage): accounts/login.html inscriptions/eleve_choix.html inscriptions/eleve_formulaire.html` 

```
inscriptions/prof_formulaire.html
inscriptions/confirmation.html
```

`# Blocs disponibles dans les bases: {% block title %}` → `titre onglet navigateur {% block content %}` → `contenu principal {% block extra_css %}` → `CSS additionnel {% block extra_js %}` → `JS additionnel # Couleurs sidebar: base_admin.html: background: #2d5a1b (vert foncé) base_prof.html: background: #1a3a5c (bleu foncé) base_eleve.html: background: #2d5a1b (vert foncé) base_superviseur.html: background: #6b3a2a (marron)` 

## **11. STATIC** 

`static/ ■■■ images/ ■■■ logo.png`  `logo de la plateforme, utilisé dans toutes les sidebars STATICFILES_DIRS = [BASE_DIR / 'static'] # dans settings.py {% load static %} # en tête de chaque template {% static 'images/logo.png' %} # usage dans template` 

```
# CSS: tout inline dans les templates (pas de fichiers .css séparés)
# JS: tout inline dans les templates (pas de fichiers .js séparés)
```

```
# Bootstrap 5 RTL via CDN:
https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.rtl.min.css
```

```
# Police Tajawal via Google Fonts:
https://fonts.googleapis.com/css2?family=Tajawal:wght@300;400;500;700&display=swap
```

```
# MEDIA (non configuré!):
# MEDIA_ROOT et MEDIA_URL manquent dans settings.py
```

```
# Les uploads audio (inscription prof) ne fonctionnent pas
```

## **12. LOGIQUE MÉTIER IMPORTANTE** 

## **Filtrage dynamique des créneaux (JS dans eleve_formulaire.html) :** 

```
# La view envoie tous les créneaux actifs en JSON:
creneaux_json = json.dumps([{
'id': c.id, 'label': str(c),
'age_min': c.age_min, 'age_max': c.age_max,
'sexe_cible': c.sexe_cible,
} for c in Creneau.objects.filter(est_actif=True)])
# En JS:
const creneaux = {{ creneaux_json|safe }};
```

`function calculerAge()` → `calcule âge depuis date_naissance function selectSexe(sexe, el)` → `enregistre le sexe sélectionné function afficherCreneaux()` → `filtre créneaux par: - age >= creneau.age_min AND age <= creneau.age_max` 

`- creneau.sexe_cible == 'mixte' OR creneau.sexe_cible == sexe` → `affiche boutons cliquables` → `stocke l'ID sélectionné dans <input type="hidden" name="creneau_souhaite">` 

## **Sauvegarde présences (prof_presence_sauvegarder) :** 

```
for eleve in seance.groupe.eleves.all():
Presence.objects.update_or_create(
seance=seance,
eleve=eleve,
```

```
defaults={
```

```
'statut': request.POST.get(f'statut_{eleve.id}', 'absent'),
'quantite_memorisee': request.POST.get(f'memorisee_{eleve.id}', ''),
'note_memorisation': request.POST.get(f'note_memo_{eleve.id}', ''),
'remarque': request.POST.get(f'remarque_{eleve.id}', ''),
...
}
)
seance.statut = 'terminee'
seance.save()
```

## **Toggle buttons multi-select en JS (prof_formulaire.html) :** 

```
# Pour les champs JSONField (langues, outils, type_eleve, contrainte_genre):
const multiSelections = {};
function toggleMulti(el, field, value) {
if (!multiSelections[field]) multiSelections[field] = [];
const idx = multiSelections[field].indexOf(value);
if (idx > -1) { multiSelections[field].splice(idx, 1); el.classList.remove('selected'); }
else { multiSelections[field].push(value); el.classList.add('selected'); }
# Recrée les inputs hidden pour que request.POST.getlist(field) fonctionne
document.querySelectorAll(`input[name="${field}"]`).forEach(i => i.remove());
multiSelections[field].forEach(v => {
const input = document.createElement('input');
input.type = 'hidden'; input.name = field; input.value = v;
document.querySelector('form').appendChild(input);
});
}
```

`# Dans la view: request.POST.getlist('langues')` → `['arabe', 'francais']` 

## **13. BUGS CONNUS** 

1. presences[eleve.id] dans prof_seance_detail.html — Django templates n'acceptent pas les dict lookups par variable entière. Le template utilise presences[eleve.id] qui peut échouer. Fix: créer un filtre custom ou restructurer en liste. 

2. MEDIA_ROOT manquant — uploads audio dans InscriptionProf.audio_enregistrement ne sont pas sauvegardés. Champ FileField pointe vers nulle part. 

3. Pas de vérification de rôle — @login_required seulement. Un élève peut accéder à /dashboard/admin/ s'il connaît l'URL. 

4. Mot de passe jamais communiqué — password_temp généré à la validation mais jamais envoyé à l'utilisateur. L'utilisateur ne peut pas se connecter sans intervention admin. 

5. Si User existe déjà (même email), le bloc Prof.objects.create est ignoré — si admin valide une inscription dont l'email existe déjà en DB, la validation passe mais sans créer le profil Prof/Eleve. 

6. Pas de validation côté serveur des formulaires — les champs required ne sont vérifiés qu'en HTML (client-side). Un POST malformé peut créer des entrées incomplètes en DB. 

7. admin_inscriptions affiche seulement les inscriptions ÉLÈVES — le lien ' `■■■ ■■■■ ■■■■■■■` ' pointe vers admin_inscriptions qui ne montre que les élèves, pas les profs. 

8. sidebar active state dans base_prof.html — certains liens n'ont pas le check {% if request.resolver_match.url_name == '...' %}active{% endif %}. 

## **14. DETTE TECHNIQUE** 

- Pas de Django Forms → validation uniquement HTML. Refactoriser avec ModelForm pour validation serveur et affichage d'erreurs propre. 

- Tout le CSS est inline dans les templates → difficile à maintenir. Créer un fichier style.css dans static/. 

- dashboard/views.py est énorme → split en views_admin.py, views_prof.py, views_eleve.py, views_superviseur.py. 

- Imports dans les vues (from accounts.models import ...) à l'intérieur des fonctions → les mettre en haut du fichier. 

- Pas de tests unitaires → aucun test écrit. 

- Pas de gestion des erreurs → si un champ requis manque, le serveur plante (500) au lieu d'afficher un message d'erreur. 

- Pas de pagination → avec beaucoup d'élèves/séances, les pages seront lentes. 

- Pas de recherche/filtre → admin ne peut pas chercher un élève par nom. 

- Pas de messages Django (django.contrib.messages) → après validation/rejet, pas de feedback visuel (flash messages). 

- settings.py sans variables d'environnement → mot de passe DB en dur dans le code. 

## **15. CE QUE JE REFERAIS AUJOURD'HUI** 

- Utiliser Django Forms dès le début — la validation manuelle avec request.POST.get() est fragile et répétitive. 

- Configurer MEDIA_ROOT avant de créer le FileField — j'aurais évité le bug des uploads audio. 

- Créer un décorateur @role_required dès le début — la sécurité par rôle aurait été intégrée partout. 

- Séparer dashboard/views.py en plusieurs fichiers dès le début — le fichier est devenu trop gros. 

- Utiliser django.contrib.messages pour les feedbacks utilisateur — les redirections silencieuses sont mauvaises UX. 

- Mettre les imports en haut des fichiers views.py — les imports dans les fonctions sont une mauvaise pratique. 

- Créer un fichier static/css/style.css — le CSS inline est non maintenable. 

- Utiliser des variables d'environnement pour les secrets (python-decouple ou django-environ). 

- Écrire des tests dès le début — même simples, ils auraient évité des régressions. 

## **16. PRIORITÉ POUR TERMINER LE PROJET** 

- **1 — CRITIQUE** : Configurer MEDIA_ROOT dans settings.py + core/urls.py pour les uploads audio 

Fichiers: settings.py, core/urls.py 

- **2 — CRITIQUE** : Fixer le bug presences[eleve.id] dans prof_seance_detail.html (filtre custom ou restructuration) 

Fichiers: templates/dashboard/prof_seance_detail.html, dashboard/views.py 

- **3 — CRITIQUE** : Implémenter la sécurité par rôle (@role_required decorator) 

- Fichiers: dashboard/views.py, utils.py à créer 

- **4 — IMPORTANT** : Envoi email avec mot de passe temporaire lors de la validation inscription 

Fichiers: dashboard/views.py, settings.py (EMAIL) 

- **5 — IMPORTANT** : Implémenter les Paiements (vues + templates + URLs) 

Fichiers: payments/views.py, payments/urls.py, templates/dashboard/ 

- **6 — IMPORTANT** : Implémenter l'évaluation superviseur des séances 

Fichiers: evaluations/views.py, templates/dashboard/superviseur_evaluation.html 

- **7 — UTILE** : Ajouter django.contrib.messages pour les feedbacks (validation OK, rejet OK, etc.) 

Fichiers: dashboard/views.py, tous les templates base 

- **8 — UTILE** : Pages paramètres (au minimum: changement mot de passe) 

Fichiers: accounts/views.py, templates/ 

- **9 — UTILE** : Pagination pour les listes longues 

Fichiers: dashboard/views.py 

- **10 — OPTIONNEL** : Calendrier hebdomadaire interactif pour le dashboard admin 

Fichiers: templates/dashboard/admin_calendrier.html 

## **17. CONSEILS POUR LA NOUVELLE IA** 

1. LIRE AVANT DE CODER — Ikram est étudiante débutante. Toujours expliquer le concept AVANT d'écrire le code. Elle veut comprendre, pas juste copier. 

2. MONTRER LE LIEN MODÈLE→VUE→TEMPLATE — toujours rappeler comment un champ du modèle devient une variable dans la vue devient une variable dans le template. 

3. USERNAME = EMAIL — c'est une convention critique du projet. Toujours créer les users avec username=email. 

4. DASHBOARD APP N'A PAS DE MODÈLES — ne jamais mettre de modèles dans dashboard/. Toujours dans l'app métier correspondante. 

5. TOUT EN ARABE RTL — tous les templates sont en arabe, direction RTL. Bootstrap 5 RTL obligatoire. 

6. VÉRIFIER LES MIGRATIONS — après tout changement de modèle: makemigrations puis migrate. 

7. RESET DB SI PROBLÈME — si migrations bloquées: pgAdmin → Drop quran_school_db → Create quran_school_db 

- → migrate → createsuperuser. 

8. EMAIL ADMIN: admin@gmail.com — role='admin' à changer manuellement dans Django admin après createsuperuser. 

9. COLORS: vert=#2d5a1b, or=#C9A84C, fond=#f0ebe3, marron=#6b3a2a — respecter la charte graphique. 

10. WINDOWS OS — les commandes sont PowerShell. Activation venv: .\venv\Scripts\Activate.ps1 

11. LE PROJET EST POUR UN VRAI CLIENT — ne pas exposer de données réelles, respecter la confidentialité. 

Document généré automatiquement — Projet `■■■■ ■■■■■` — Ikram El Assam — EMINES UM6P 2026 

