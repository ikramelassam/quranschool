# زدني علماً — Quran School Management Platform

> 🚧 **Ce projet est actuellement en cours de développement.**

<br>

## 📖 À propos

**زدني علماً** est une plateforme web complète de gestion d'une école coranique à distance, développée pour un **client réel**.

Elle digitalise l'ensemble du processus : inscription des élèves et enseignants, gestion des groupes et des séances, suivi des présences, des notes et des évaluations — le tout avec des tableaux de bord dédiés à chaque rôle.

> Projet réalisé en autonomie dans le cadre d'un apprentissage du Software Engineering appliqué — **EMINES UM6P**, Ben Guerir, Maroc.

<br>

## ✨ Fonctionnalités principales

### ✅ Implémentées

**Authentification & Gestion des rôles**
- Authentification par email (backend personnalisé)
- Redirection automatique selon le rôle : admin / professeur / élève / superviseur

**Espace Administrateur**
- Validation/rejet des inscriptions avec création automatique des comptes
- Gestion des créneaux horaires (ajouter, modifier, activer/désactiver)
- Gestion des groupes (créer, modifier, assigner élèves et professeurs)
- Création et annulation des séances
- Vue d'ensemble : statistiques, inscriptions récentes

**Inscription Élève**
- Formulaire dynamique : créneaux filtrés en temps réel selon l'âge et le sexe
- Choix du programme (حفظ / مراجعة), de la riwaya, de l'outil de connexion et de l'abonnement

**Inscription Professeur**
- Formulaire complet en 7 sections : infos personnelles, qualifications, préférences pédagogiques, disponibilités, outils, parcours, informations bancaires + enregistrement audio

**Espace Professeur**
- Vue des groupes et élèves assignés
- Feuille de présence par séance : statut, quantité mémorisée/révisée, notes, remarques
- Emploi du temps hebdomadaire

**Espace Élève**
- Historique des séances avec notes et remarques du professeur
- Profil personnel et groupes

**Espace Superviseur**
- Consultation des séances terminées et des évaluations des élèves

### 🔜 En cours / Planifiées
- Suivi des paiements
- Évaluation des professeurs par le superviseur
- Envoi automatique des identifiants par email
- Sécurisation des vues par rôle
- Pages de paramètres

<br>

## 🛠️ Stack Technique

| Technologie | Détail |
|-------------|--------|
| **Backend** | Python 3.12 · Django 6.0.2 |
| **Base de données** | PostgreSQL |
| **Frontend** | Bootstrap 5 RTL · JavaScript Vanilla |
| **Police** | Tajawal (Google Fonts) |
| **Auth** | Backend personnalisé (authentification par email) |

<br>

## 🏗️ Architecture — 6 Applications Django

```
accounts/       → Utilisateurs, Eleve, Prof, Superviseur (modèle User personnalisé)
inscriptions/   → Formulaires d'inscription élèves et professeurs
courses/        → Créneaux, Groupes, Séances, Présences
payments/       → Suivi des paiements (en cours)
evaluations/    → Évaluations superviseur (en cours)
dashboard/      → Vues des tableaux de bord par rôle (pas de modèles)
```

<br>

## 👥 Rôles & Flux

```
Élève          →  Inscription →  Admin valide  →  Compte créé  →  Assigné à un groupe
Professeur     →  Inscription →  Admin valide  →  Compte créé  →  Assigné à un groupe
Admin          →  Gère tout : créneaux, groupes, séances, inscriptions
Superviseur    →  Consulte les séances terminées et les évaluations
```

<br>

## 🗄️ Modèle de données (simplifié)

```
User (AbstractUser)
 ├── role: eleve / prof / superviseur / admin
 ├── Eleve (OneToOne)
 │    └── groupes (ManyToMany → Groupe)
 └── Prof (OneToOne)
      └── groupes (ForeignKey → Groupe)

Creneau ──────────────────────── Groupe
(horaire: jour1+jour2, heures)    (nom, prof, creneau, eleves, capacite_max)
                                       │
                                    Seance (date, heure, type, statut)
                                       │
                                    Presence (eleve, statut, notes, remarques)

InscriptionEleve / InscriptionProf → validées par admin → créent User+Eleve/Prof
```

<br>

## 🚀 Installation locale

```bash
# 1. Cloner le projet
git clone <repo_url>
cd quran-school-management

# 2. Environnement virtuel
python -m venv venv
venv\Scripts\activate        # Windows
source venv/bin/activate     # Mac/Linux

# 3. Dépendances
pip install django psycopg2-binary

# 4. Base de données
# Créer une DB PostgreSQL nommée "quran_school_db"
# Configurer core/settings.py

# 5. Migrations
python manage.py migrate

# 6. Superutilisateur
python manage.py createsuperuser

# 7. Lancer
python manage.py runserver
```

**Configuration minimale `settings.py` :**
```python
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.postgresql',
        'NAME': 'quran_school_db',
        'USER': 'postgres',
        'PASSWORD': 'votre_mot_de_passe',
        'HOST': 'localhost',
        'PORT': '5432',
    }
}
AUTHENTICATION_BACKENDS = ['accounts.backends.EmailBackend']
LOGIN_URL = '/accounts/login/'
```

<br>

## 📄 Licence

© 2026 Ikram El Assam — Tous droits réservés.
Ce projet est partagé à titre de démonstration. Toute réutilisation du code sans autorisation explicite est interdite.
