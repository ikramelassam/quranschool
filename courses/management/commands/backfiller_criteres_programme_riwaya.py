"""Rattrapage pour les groupes créés AVANT le chantier du 2026-09-15
(« pré-remplissage الخصائص à la création ») — signalement client : plusieurs
groupes déjà existants affichaient encore 'البرنامج'/'الرواية' à
« غير محدد » dans le panneau « الخصائص », alors que l'info est déjà connue
via leur Creneau (type_seance/riwaya).

Ne touche JAMAIS un groupe qui a déjà une GroupeCritereValeur pour l'un de
ces 2 critères (même partielle) — aucune valeur choisie à la main n'est
jamais écrasée. Voir registration.utils.backfiller_criteres_programme_riwaya
pour la logique complète.

    python manage.py backfiller_criteres_programme_riwaya              # DRY-RUN
    python manage.py backfiller_criteres_programme_riwaya --appliquer  # écrit réellement
"""
from django.core.management.base import BaseCommand
from django.db import transaction


class Command(BaseCommand):
    help = "Pré-remplit البرنامج/الرواية pour les groupes existants qui n'en ont pas encore (dry-run par défaut)."

    def add_arguments(self, parser):
        parser.add_argument(
            '--appliquer', action='store_true',
            help="Écrit réellement les valeurs (par défaut : compte seulement, sans rien modifier).",
        )

    def handle(self, *args, **options):
        from courses.models import Groupe
        from registration.models import Critere, GroupeCritereValeur
        from registration.utils import backfiller_criteres_programme_riwaya

        if not options['appliquer']:
            criteres = {
                c.code: c
                for c in Critere.objects.filter(code__in=('programme', 'riwaya'), backend='eav', est_actif=True)
            }
            a_remplir = 0
            for groupe in Groupe.objects.filter(creneau__isnull=False).select_related('creneau'):
                correspondance = {'programme': groupe.creneau.type_seance, 'riwaya': groupe.creneau.riwaya}
                for code, valeur_code in correspondance.items():
                    critere = criteres.get(code)
                    if critere is None:
                        continue
                    if GroupeCritereValeur.objects.filter(groupe=groupe, critere=critere).exists():
                        continue
                    if not critere.options.filter(code=valeur_code, est_actif=True).exists():
                        continue
                    a_remplir += 1
                    self.stdout.write(f"  {groupe.id} « {groupe.nom} » — {critere.code} : {valeur_code}")
            self.stdout.write(self.style.WARNING(
                f"\nDRY-RUN : {a_remplir} valeur(s) seraient remplies. "
                f"Relancer avec --appliquer pour écrire réellement."
            ))
            return

        with transaction.atomic():
            nb_remplis = backfiller_criteres_programme_riwaya()
        self.stdout.write(self.style.SUCCESS(f"{nb_remplis} valeur(s) remplies."))
