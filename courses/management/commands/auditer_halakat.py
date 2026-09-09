"""Audit 100 % LECTURE SEULE des حلقات (Groupe + Creneau) — aucun .save(),
.delete(), .update() ni migration : la commande ne fait que des SELECT et
imprime un rapport. La lancer ne peut RIEN casser.

But : comprendre pourquoi le wizard public d'inscription affiche « لا توجد
حلقة مناسبة » (écran registration.views.wizard_groupe) alors qu'on s'attend à
voir au moins des « حلقات قريبة ». Reproduit EXACTEMENT la chaîne de filtres
de registration.utils.groupes_compatibles_avec_age + groupes_avec_place_
disponible et dit, حلقة par حلقة, quel filtre la fait sortir.

    python manage.py auditer_halakat                 # état général de toutes les حلقات
    python manage.py auditer_halakat --age 7 --sexe fille
    python manage.py auditer_halakat --age 9 --sexe garcon

--sexe accepte : fille / garcon / f / g / femme / homme (insensible à la casse).
Sans --age, seule la partie « santé des données » s'affiche.
"""
from django.core.management.base import BaseCommand, CommandError
from django.db.models import Count, F


# Valeurs cibles = celles réellement stockées par le wizard (input hidden
# name="sexe" de wizard_identite.html) ET par Creneau.sexe_cible : 'homme' /
# 'femme' / 'mixte'. Le filtre du wizard compare les deux directement
# (registration.utils.groupes_compatibles_avec_age).
SEXE_ALIASES = {
    'fille': 'femme', 'f': 'femme', 'femme': 'femme', 'feminin': 'femme', 'fém': 'femme',
    'garcon': 'homme', 'garçon': 'homme', 'g': 'homme', 'homme': 'homme',
    'masculin': 'homme', 'h': 'homme',
}


class Command(BaseCommand):
    help = "Audit lecture seule des حلقات : santé des données + simulation du wizard public."

    def add_arguments(self, parser):
        parser.add_argument('--age', type=int, default=None,
                            help="Âge du candidat pour simuler le filtrage du wizard.")
        parser.add_argument('--sexe', type=str, default=None,
                            help="Sexe du candidat : fille / garcon (aussi f/g, femme/homme).")

    def handle(self, *args, **options):
        # Console Windows (cp1252) : forcer l'UTF-8 sinon les noms de حلقات en
        # arabe font planter l'écriture. Sans effet ailleurs.
        import sys
        for flux in (sys.stdout, sys.stderr):
            try:
                flux.reconfigure(encoding='utf-8')
            except Exception:
                pass

        from courses.models import Groupe, Creneau

        self.stdout.write(self.style.MIGRATE_HEADING(
            "\n=== 1. SANTÉ DES DONNÉES — toutes les حلقات (actives + archivées) ===\n"))

        groupes = (
            Groupe.objects.select_related('creneau', 'prof__user')
            .annotate(_nb_eleves=Count('eleves', distinct=True),
                      _nb_slots=Count('creneau__slots', distinct=True))
            .order_by('statut', 'nom')
        )
        total = groupes.count()
        if not total:
            self.stdout.write(self.style.ERROR(
                "  AUCUN Groupe en base. Le wizard ne pourra jamais rien proposer."))
            return

        problemes_globaux = 0
        for g in groupes:
            lignes = []
            drapeaux = []

            if g.statut != 'actif':
                drapeaux.append(f"statut={g.statut} (exclu du wizard)")

            if getattr(g, 'cache_du_wizard_public', False):
                drapeaux.append("cache_du_wizard_public=True (masquée manuellement)")

            c = g.creneau
            if c is None:
                drapeaux.append("PAS DE حلقة/horaire rattachée (creneau=NULL) -> INVISIBLE partout")
            else:
                if c.age_min is None or c.age_max is None:
                    drapeaux.append(f"age_min/age_max NULL sur le créneau (min={c.age_min}, max={c.age_max})")
                elif c.age_min > c.age_max:
                    drapeaux.append(f"age_min ({c.age_min}) > age_max ({c.age_max}) — bande d'âge vide")
                if c.age_min is not None and c.age_max is not None and (c.age_min < 3 or c.age_max > 99):
                    drapeaux.append(f"bande d'âge suspecte : {c.age_min}–{c.age_max}")
                if g._nb_slots == 0:
                    drapeaux.append("créneau SANS aucun slot (aucun horaire réel) ")
                lignes.append(
                    f"horaire: âge {c.age_min}–{c.age_max} | sexe_cible={c.sexe_cible} "
                    f"| {g._nb_slots} slot(s) | riwaya={c.riwaya}")

            if g.capacite_max is not None and g._nb_eleves >= g.capacite_max:
                drapeaux.append(f"COMPLÈTE ({g._nb_eleves}/{g.capacite_max})")

            lignes.append(f"élèves: {g._nb_eleves}/{g.capacite_max}")
            prof = g.prof.user.get_full_name() if g.prof and g.prof.user else "—"
            lignes.append(f"prof: {prof}")

            titre = f"• [{g.id}] {g.nom}"
            if drapeaux:
                problemes_globaux += 1
                self.stdout.write(self.style.WARNING(titre))
                for d in drapeaux:
                    self.stdout.write(self.style.ERROR(f"    ⚠ {d}"))
            else:
                self.stdout.write(self.style.SUCCESS(titre))
            for l in lignes:
                self.stdout.write(f"    {l}")

        self.stdout.write("")
        self.stdout.write(f"  {total} حلقة au total, {problemes_globaux} avec au moins un point d'attention.\n")

        self._auditer_criteres()

        age = options['age']
        sexe_brut = options['sexe']
        if age is None:
            self.stdout.write(self.style.MIGRATE_HEADING(
                "\n(pas de --age fourni : simulation du wizard non exécutée)\n"))
            return

        if sexe_brut is None:
            raise CommandError("--sexe est requis dès que --age est fourni.")
        sexe = SEXE_ALIASES.get(sexe_brut.strip().lower())
        if sexe is None:
            raise CommandError(
                f"--sexe={sexe_brut!r} non reconnu. Utilise fille / garcon (ou f/g, femme/homme).")

        self._simuler_wizard(age, sexe, sexe_brut)

    def _auditer_criteres(self):
        from registration.models import Critere, GroupeCritereValeur

        self.stdout.write(self.style.MIGRATE_HEADING(
            "=== 2. CRITÈRES D'INSCRIPTION filtrables ===\n"))
        criteres = Critere.objects.filter(est_actif=True, filtrable=True).order_by('ordre')
        if not criteres:
            self.stdout.write("  Aucun critère filtrable actif.\n")
            return
        for cr in criteres:
            bl = "  ← BLOQUANT (jamais relâché, même pour les « proches »)" if cr.bloquant else ""
            if cr.backend == 'eav':
                couverture = GroupeCritereValeur.objects.filter(critere=cr).count()
                self.stdout.write(
                    f"  • {cr.label} (code={cr.code}, backend=eav) — "
                    f"{couverture} valeur(s) posée(s) sur des حلقات{bl}")
                if couverture == 0:
                    self.stdout.write(self.style.WARNING(
                        "      (aucune حلقة taguée → ce critère est ignoré au filtrage, OK)"))
                elif cr.bloquant:
                    self.stdout.write(self.style.WARNING(
                        "      note : BLOQUANT — une حلقة sans la bonne valeur est écartée "
                        "même des « proches »."))
            elif cr.backend == 'champ_groupe':
                # La valeur vient d'un VRAI champ de Groupe (cr.champ_modele_groupe),
                # jamais d'une GroupeCritereValeur — donc pas de « couverture » à compter.
                champ = cr.champ_modele_groupe
                repartition = ''
                try:
                    from courses.models import Groupe
                    vals = (Groupe.objects.filter(statut='actif')
                            .values_list(champ, flat=True))
                    from collections import Counter
                    repartition = ', '.join(f"{k}={v}" for k, v in Counter(vals).items())
                except Exception:
                    repartition = '(champ illisible)'
                self.stdout.write(
                    f"  • {cr.label} (code={cr.code}, backend=champ_groupe → "
                    f"Groupe.{champ}) — حلقات actives : {repartition}{bl}")
            else:  # nb_slots
                self.stdout.write(
                    f"  • {cr.label} (code={cr.code}, backend=nb_slots → nb de slots "
                    f"réels du créneau) — match EXACT{bl}")
        self.stdout.write("")

    def _simuler_wizard(self, age, sexe, sexe_label):
        from courses.models import Groupe

        self.stdout.write(self.style.MIGRATE_HEADING(
            f"\n=== 3. SIMULATION WIZARD — candidat {age} ans, {sexe_label} ({sexe}) ===\n"))
        self.stdout.write(
            "  (on ne teste ici que les filtres DURS : âge, sexe, capacité, horaire présent.\n"
            "   البرنامج / الرواية / عدد الحصص ne sont PAS testés — ils ne bloquent que le\n"
            "   match exact, jamais les « حلقات قريبة ».)\n")

        actifs = Groupe.objects.filter(statut='actif').select_related('creneau')
        if hasattr(Groupe, 'cache_du_wizard_public'):
            actifs = actifs.exclude(cache_du_wizard_public=True)
        actifs = actifs.annotate(
            _nb_eleves=Count('eleves', distinct=True)).order_by('nom')

        passent = []
        for g in actifs:
            c = g.creneau
            raisons = []
            if c is None:
                raisons.append("pas de حلقة/horaire (creneau=NULL)")
            else:
                if c.age_min is None or c.age_max is None:
                    raisons.append(f"âge du créneau incomplet ({c.age_min}–{c.age_max})")
                elif not (c.age_min <= age <= c.age_max):
                    raisons.append(f"âge {age} hors bande {c.age_min}–{c.age_max}")
                if c.sexe_cible not in ('mixte', sexe):
                    raisons.append(f"sexe_cible={c.sexe_cible} ≠ mixte/{sexe}")
            if g.capacite_max is not None and g._nb_eleves >= g.capacite_max:
                raisons.append(f"complète ({g._nb_eleves}/{g.capacite_max})")

            if raisons:
                self.stdout.write(self.style.ERROR(f"  ✗ [{g.id}] {g.nom}"))
                for r in raisons:
                    self.stdout.write(f"        - {r}")
            else:
                passent.append(g)
                self.stdout.write(self.style.SUCCESS(
                    f"  ✓ [{g.id}] {g.nom}  (âge {c.age_min}–{c.age_max}, "
                    f"sexe_cible={c.sexe_cible}, {g._nb_eleves}/{g.capacite_max})"))

        self.stdout.write("")
        if passent:
            self.stdout.write(self.style.SUCCESS(
                f"  → {len(passent)} حلقة devrai(en)t apparaître (au moins en « قريبة ») "
                f"pour ce candidat.\n"
                f"    Si le client ne les voit pas : vérifier la date de naissance qu'il a\n"
                f"    saisie (âge réellement calculé) et le sexe choisi dans le wizard.\n"))
        else:
            self.stdout.write(self.style.ERROR(
                "  → AUCUNE حلقة ne passe les filtres durs : c'est NORMAL que le client\n"
                "    voie « لا توجد حلقة » sans aucune « قريبة ». Corriger les points ⚠\n"
                "    de la section 1 (bande d'âge, sexe_cible, horaire manquant, capacité).\n"))
