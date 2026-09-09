"""Déduplication des حلقات créées en double par une double soumission du
formulaire « إنشاء المجموعة » (bug signalé par le client le 2026-09-09 :
« علي بن ابي طالب » créé une fois, présent deux fois — groupes 471/472,
byte-pour-byte identiques, IDs consécutifs). La cause (absence de garde
anti-double-soumission) est corrigée dans courses.views.groupe_ajouter +
le template ; cette commande nettoie les doublons DÉJÀ en base.

Deux groupes sont considérés comme doublons quand ils ont EXACTEMENT :
  - le même nom (nom arabe, comparaison stricte)
  - le même enseignant (prof_id, y compris « aucun »)
  - le même horaire : même ensemble de créneaux (jour, heure_debut, heure_fin)

Parmi un lot de doublons, on GARDE le plus ancien (id le plus petit) et on
propose de supprimer les autres — mais UNIQUEMENT ceux qui ne portent aucune
donnée vivante : 0 élève, 0 présence, 0 évaluation, 0 examen, 0 demande de
changement de حلقة. Un doublon qui aurait déjà servi n'est jamais touché
(message explicite, à traiter à la main).

    python manage.py dedupliquer_groupes              # DRY-RUN : liste seulement
    python manage.py dedupliquer_groupes --supprimer  # supprime réellement

La suppression réutilise le cascade ORM de Django (séances/conversation de
chat/slots du créneau privé partent avec le groupe) dans une transaction.
"""
from django.core.management.base import BaseCommand
from django.db import transaction

from courses.models import Groupe


def _signature(groupe):
    """(nom, prof_id, frozenset des slots) — deux groupes de même signature
    sont des doublons stricts."""
    creneau = groupe.creneau
    slots = frozenset(
        (s.jour, s.heure_debut, s.heure_fin)
        for s in (creneau.slots.all() if creneau else [])
    )
    return (groupe.nom, groupe.prof_id, slots)


def _obstacles_suppression(groupe):
    """Liste des raisons qui interdisent de supprimer ce groupe
    automatiquement (données vivantes rattachées). Vide => suppression sûre."""
    obstacles = []
    nb_eleves = groupe.eleves.count()
    if nb_eleves:
        obstacles.append(f'{nb_eleves} élève(s)')
    nb_presences = sum(s.presences.count() for s in groupe.seances.all())
    if nb_presences:
        obstacles.append(f'{nb_presences} présence(s)')
    nb_evals = sum(1 for s in groupe.seances.all() if hasattr(s, 'evaluation'))
    if nb_evals:
        obstacles.append(f'{nb_evals} évaluation(s)')
    if groupe.examens.exists():
        obstacles.append(f'{groupe.examens.count()} examen(s)')
    demandes = groupe.demandes_changement_halaka_visant_ce_groupe.count()
    if demandes:
        obstacles.append(f'{demandes} demande(s) de changement de حلقة')
    return obstacles


class Command(BaseCommand):
    help = "Détecte et (avec --supprimer) nettoie les حلقات créées en double."

    def add_arguments(self, parser):
        parser.add_argument(
            '--supprimer', action='store_true',
            help="Supprime réellement les doublons sûrs (sinon : dry-run).",
        )

    def handle(self, *args, **options):
        supprimer = options['supprimer']

        lots = {}
        for groupe in Groupe.objects.select_related('creneau', 'prof').prefetch_related(
            'creneau__slots', 'eleves', 'seances__presences'
        ).order_by('id'):
            lots.setdefault(_signature(groupe), []).append(groupe)

        doublons = {sig: gs for sig, gs in lots.items() if len(gs) > 1}
        if not doublons:
            self.stdout.write(self.style.SUCCESS('Aucun doublon de حلقة détecté.'))
            return

        a_supprimer = []
        for sig, groupes in doublons.items():
            garde = groupes[0]
            self.stdout.write('')
            self.stdout.write(self.style.WARNING(
                f'Doublon : « {garde.nom} » (prof {garde.prof_id}) — {len(groupes)} exemplaires'
            ))
            self.stdout.write(f'  GARDÉ    : groupe #{garde.id}')
            for extra in groupes[1:]:
                obstacles = _obstacles_suppression(extra)
                if obstacles:
                    self.stdout.write(self.style.NOTICE(
                        f'  CONSERVÉ : groupe #{extra.id} — porte des données : {", ".join(obstacles)} (à traiter à la main)'
                    ))
                else:
                    self.stdout.write(f'  À SUPPRIMER : groupe #{extra.id} (vide)')
                    a_supprimer.append(extra)

        self.stdout.write('')
        if not a_supprimer:
            self.stdout.write('Rien à supprimer automatiquement.')
            return

        if not supprimer:
            self.stdout.write(self.style.WARNING(
                f'DRY-RUN : {len(a_supprimer)} groupe(s) seraient supprimés. '
                'Relancer avec --supprimer pour agir.'
            ))
            return

        with transaction.atomic():
            for groupe in a_supprimer:
                creneau = groupe.creneau
                gid = groupe.id
                groupe.delete()
                if creneau:
                    creneau.delete()
                self.stdout.write(self.style.SUCCESS(f'  groupe #{gid} supprimé (+ créneau privé)'))

        self.stdout.write('')
        self.stdout.write(self.style.SUCCESS(f'{len(a_supprimer)} doublon(s) supprimé(s).'))
