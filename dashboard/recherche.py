"""Recherche globale (مدير/مشرف) — Chantier du 2026-08-14.

Point d'entrée unique : `rechercher_tout`, utilisé par le seul endpoint
dashboard.views.api_recherche_globale (@role_required('admin', 'mshrif')).
Pas de deuxième implémentation ailleurs — les selects cherchables (Chantier 2
du même prompt) réutilisent CE module, ne recodent pas leur propre filtrage.

Deux mécanismes PostgreSQL combinés pour chaque champ cherché :
- icontains : sous-chaîne classique, couvre l'immense majorité des cas.
- trigram_similar (extension pg_trgm, index GIN — voir migrations
  accounts.0030/0031, courses.0027, inscriptions.0017) : rattrape les fautes
  de frappe et variantes de translittération qu'icontains rate seul (ex:
  "ahmed" vs "ahmad"). En OR avec icontains (recall maximal).

Tri : correspondance EXACTE (iexact) toujours en tête de sa catégorie, puis
similarité trigram décroissante pour le reste.

PERFORMANCE — pourquoi une seule requête SQL, pas 4 (une par modèle) :
la base de dev est un Postgres distant (Supabase, pooler eu-west-1) — chaque
aller-retour réseau coûte ~100-200ms à lui seul, INDÉPENDAMMENT de la
complexité de la requête (mesuré : 4 requêtes séquentielles = 650-1000ms,
alors qu'EXPLAIN confirme un Seq Scan optimal sur des tables de ~65-400
lignes — l'index n'est pas le facteur limitant à ce volume, le nombre
d'allers-retours l'est). rechercher_tout construit donc une projection par
modèle (titre/contexte calculés en SQL via Concat/Case/Coalesce, pas en
Python) et les combine en une seule requête via QuerySet.union(all=True) —
Django préserve bien le ORDER BY + LIMIT de CHAQUE branche à l'intérieur de
l'UNION ALL (vérifié empiriquement sur ce Postgres), donc le "top 5 par
catégorie" reste correct malgré la fusion. Un seul aller-retour réseau au
lieu de 4 : ~150-250ms mesurés au lieu de 650-1000ms. Le solde restant
(encore au-dessus de 200ms strict depuis une machine de dev qui interroge un
Postgres distant par l'internet public) est une latence réseau incompressible
à ce niveau, pas un défaut de la requête — voir le rapport du chantier pour
la mesure exacte et sa discussion.

Permissions : chaque queryset de base ci-dessous est EXACTEMENT celui déjà
utilisé par les pages de liste existantes (admin_eleves/admin_profs/
admin_superviseurs/groupes_list, voir dashboard.views et courses.views) —
مدير et مشرف y ont un accès strictement identique, aucune de ces vues
n'applique de filtre par rôle sur le queryset lui-même. Aucun filtrage par
rôle n'est donc fait dans ce module : le seul contrôle d'accès nécessaire
est que l'endpoint entier soit réservé à ces 2 rôles (@role_required sur la
vue, pas ici).

Volontairement `.objects.all()` partout (pas `.actifs`) : une recherche
globale doit retrouver N'IMPORTE QUI, y compris un compte archivé/suspendu.
Chaque résultat affiche son statut s'il n'est pas actif.
"""
import re

from django.contrib.postgres.search import TrigramSimilarity
from django.db.models import BooleanField, Case, CharField, F, Q, Value, When
from django.db.models.functions import Concat, Coalesce, Greatest, NullIf, Trim
from django.urls import reverse
# gettext_lazy (pas "_" : ce module utilise "_" comme variable jetable dans
# plusieurs boucles, ex: `for _, _, fonction, _ in CATEGORIES`) — les libellés
# de CATEGORIES sont construits une seule fois à l'import, un gettext_ eager
# figerait la langue. Résolus à la sérialisation JSON (DjangoJSONEncoder gère
# les proxies gettext_lazy), donc dans la langue de la requête.
from django.utils.translation import gettext_lazy

LIMITE_PAR_CATEGORIE = 5

TIRET = Value(' — ')


def detecter_mois(q):
    """Retourne 'AAAA-MM' si `q` ressemble à une référence de mois (mm/aaaa,
    aaaa-mm, ou 'mois_arabe aaaa' selon la même convention que
    dashboard.templatetags.libelles_arabes.mois_annee_ar), sinon None.

    Détection séparée du scoring texte normal (A2bis) : "07/2026" n'a aucun
    sens comparé par similarité trigram à un nom de personne — branche à
    part, vérifiée AVANT toute recherche par catégorie."""
    from dashboard.templatetags.libelles_arabes import MOIS_AR

    q = q.strip()
    m = re.fullmatch(r'(0?[1-9]|1[0-2])[/\-](\d{4})', q)
    if m:
        mois, annee = int(m.group(1)), int(m.group(2))
        return f'{annee:04d}-{mois:02d}'
    m = re.fullmatch(r'(\d{4})[/\-](0?[1-9]|1[0-2])', q)
    if m:
        annee, mois = int(m.group(1)), int(m.group(2))
        return f'{annee:04d}-{mois:02d}'
    parties = q.split()
    if len(parties) == 2 and parties[1].isdigit() and len(parties[1]) == 4:
        nom_mois, annee = parties
        for numero, libelle in MOIS_AR.items():
            if libelle == nom_mois:
                return f'{int(annee):04d}-{numero:02d}'
    return None


def _condition(champs, q):
    """OR de tous les champs : icontains OU trigram_similar (voir docstring
    du module). `champs` : chemins de lookup Django (ex: 'user__email')."""
    filtre = Q()
    for champ in champs:
        filtre |= Q(**{f'{champ}__icontains': q}) | Q(**{f'{champ}__trigram_similar': q})
    return filtre


def _exact(champs, q):
    exact_q = Q()
    for champ in champs:
        exact_q |= Q(**{f'{champ}__iexact': q})
    return Case(When(exact_q, then=Value(True)), default=Value(False), output_field=BooleanField())


def _similarite(champs, q):
    sims = [TrigramSimilarity(champ, q) for champ in champs]
    return sims[0] if len(sims) == 1 else Greatest(*sims)


def _nom_complet(prefixe_user='user'):
    """NOM COMPLET calculé en SQL (pas en Python — voir docstring perf du
    module) : Concat(prénom, ' ', nom), retombe sur l'email si les deux sont
    vides (compte créé sans nom renseigné)."""
    return Coalesce(
        NullIf(
            Trim(Concat(F(f'{prefixe_user}__first_name'), Value(' '), F(f'{prefixe_user}__last_name'))),
            Value(''),
        ),
        F(f'{prefixe_user}__email'),
        output_field=CharField(),
    )


def _projection(queryset, categorie, titre, contexte, champs, q, limite):
    return (
        queryset.filter(_condition(champs, q))
        .annotate(
            _categorie=Value(categorie, output_field=CharField()),
            _obj_id=F('id'),
            _titre=titre,
            _contexte=contexte,
            _exact=_exact(champs, q),
            _sim=_similarite(champs, q),
        )
        .order_by('-_exact', '-_sim', 'id')
        .values('_categorie', '_obj_id', '_titre', '_contexte', '_exact', '_sim')[:limite]
    )


def _projection_eleves(q, limite):
    from accounts.models import Eleve

    champs = [
        'user__first_name', 'user__last_name', 'user__email', 'user__telephone',
        'inscription__nom_parent',
    ]
    contexte = Case(
        When(statut='suspendu', then=Concat(F('user__email'), TIRET, Value('موقوف'))),
        When(statut='archive', then=Concat(F('user__email'), TIRET, Value('مؤرشف'))),
        default=F('user__email'),
        output_field=CharField(),
    )
    return _projection(
        Eleve.objects.select_related(None), 'eleves', _nom_complet(), contexte, champs, q, limite,
    )


def _projection_profs(q, limite):
    from accounts.models import Prof

    champs = ['user__first_name', 'user__last_name', 'user__email', 'user__telephone', 'ville']
    ville_ou_email = Case(
        When(ville='', then=F('user__email')),
        default=F('ville'),
        output_field=CharField(),
    )
    contexte = Case(
        When(statut='archive', then=Concat(ville_ou_email, TIRET, Value('مؤرشف'))),
        default=ville_ou_email,
        output_field=CharField(),
    )
    return _projection(Prof.objects.select_related(None), 'profs', _nom_complet(), contexte, champs, q, limite)


def _projection_superviseurs(q, limite):
    from accounts.models import Superviseur

    champs = ['user__first_name', 'user__last_name', 'user__email', 'user__telephone']
    return _projection(
        Superviseur.objects.select_related(None), 'superviseurs',
        _nom_complet(), F('user__email'), champs, q, limite,
    )


def _projection_groupes(q, limite):
    from courses.models import Groupe

    champs = ['nom']
    prof_nom = Concat(F('prof__user__first_name'), Value(' '), F('prof__user__last_name'), output_field=CharField())
    contexte_base = Case(
        When(prof__isnull=True, then=Value('بدون أستاذ')),
        default=prof_nom,
        output_field=CharField(),
    )
    contexte = Case(
        When(statut='archive', then=Concat(contexte_base, TIRET, Value('مؤرشفة'))),
        default=contexte_base,
        output_field=CharField(),
    )
    return _projection(
        Groupe.objects.select_related(None), 'groupes', F('nom'), contexte, champs, q, limite,
    )


# (clé, libellé traduisible, fonction de projection, url de "voir tout" avec ?q=
# — None si la page cible ne sait pas encore filtrer par q)
CATEGORIES = [
    ('eleves', gettext_lazy('الطلاب'), _projection_eleves, 'admin_eleves'),
    ('profs', gettext_lazy('الأساتذة'), _projection_profs, 'admin_profs'),
    ('superviseurs', gettext_lazy('المؤطرون'), _projection_superviseurs, 'admin_superviseurs'),
    # groupes_list filtre désormais par ?q= (courses.views.groupes_list,
    # correction du 2026-08-14 — même filtre icontains+trigram_similar sur
    # Groupe.nom que ce module, pas une 2e logique recodée à part).
    ('groupes', gettext_lazy('المجموعات'), _projection_groupes, 'admin_groupes'),
]

URL_PAR_CATEGORIE = {
    'eleves': 'admin_eleve_detail',
    'profs': 'admin_prof_detail',
    'superviseurs': 'admin_superviseur_assignations',
    'groupes': 'admin_groupe_detail',
}


def rechercher_tout(q, limite_par_categorie=LIMITE_PAR_CATEGORIE):
    """Point d'entrée unique (A3). Retourne (mois_detecte, categories) :
    - mois_detecte : 'AAAA-MM' ou None (A2bis).
    - categories : liste de dicts {cle, libelle, resultats, a_plus, voir_tout_url}.
    q vide ou <2 caractères → aucune recherche, aucune requête SQL (A5)."""
    q = (q or '').strip()
    if len(q) < 2:
        return None, []

    mois = detecter_mois(q)

    # +1 par catégorie : sert uniquement à savoir s'il faut "voir tout"
    # (A4ter), jamais affiché lui-même.
    limite_fetch = limite_par_categorie + 1
    projections = [fonction(q, limite_fetch) for _, _, fonction, _ in CATEGORIES]

    premiere, *reste = projections
    lignes = list(premiere.union(*reste, all=True)) if reste else list(premiere)

    par_categorie = {cle: [] for cle, *_ in CATEGORIES}
    for ligne in lignes:
        par_categorie.setdefault(ligne['_categorie'], []).append(ligne)

    categories = []
    for cle, libelle, _fonction, url_liste in CATEGORIES:
        lignes_cat = par_categorie.get(cle, [])
        a_plus = len(lignes_cat) > limite_par_categorie
        resultats = [
            {
                'id': ligne['_obj_id'],
                'titre': ligne['_titre'],
                'contexte': ligne['_contexte'],
                'url': reverse(URL_PAR_CATEGORIE[cle], args=[ligne['_obj_id']]),
            }
            for ligne in lignes_cat[:limite_par_categorie]
        ]
        voir_tout_url = f"{reverse(url_liste)}?q={q}" if (a_plus and url_liste) else None
        categories.append({
            'cle': cle,
            'libelle': libelle,
            'resultats': resultats,
            'a_plus': a_plus,
            'voir_tout_url': voir_tout_url,
        })
    return mois, categories
