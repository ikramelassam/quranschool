# Data migration du chantier 2 niveaux (2026-09-12, v3) — succède à la
# migration STRUCTURELLE 0052 (qui n'a rien touché aux données). Convertit
# les 2 anciennes lignes globales ProfilCriteresSeance(position=1) et
# (position=2) — héritées de la v2 du 2026-09-12, seedées par la migration
# 0051 — vers le nouveau modèle à 2 niveaux (Niveau 1 commun, clé
# (nb_seances_semaine, position)).
#
# ============================================================
# CE QUI A ÉTÉ VÉRIFIÉ AVANT D'ÉCRIRE CETTE MIGRATION (2026-09-12)
# ============================================================
#
# 1. Cadence réelle des groupes existants (requête read-only sur la prod,
#    groupe.creneau.slots.count()) : 37 groupes à 2 séances/semaine, 19 à 1
#    séance/semaine, 0 groupe à 3+ séances. Les seules valeurs de
#    nb_seances_semaine RÉELLEMENT utilisées aujourd'hui sont donc 1 et 2 —
#    aucune autre valeur n'est fabriquée ici.
#
# 2. Contenu ACTUEL des 2 anciennes lignes (vérifié par SQL brut juste avant
#    d'écrire cette migration, sur la table courses_profilcriteresseance
#    encore au format v2) :
#      position=1 -> critères {1, 3, 4}
#      position=2 -> critères {1, 2, 4}
#    Cette migration copie ce contenu EXACT (jamais recalculé depuis
#    CritereEleve.type_lie, même s'il se trouve qu'ils coïncident
#    aujourd'hui — voir ProfilCriteresSeance.__doc__ : la config enregistrée
#    est toujours la seule vérité, jamais un recalcul).
#
# 3. Sous l'ancien modèle (v2), `position` seule était la clé — position=1
#    était donc partagée par TOUS les groupes atteignant leur 1ʳᵉ séance,
#    qu'ils en aient 1 SEULE au total (19 groupes) ou 2 au total (37
#    groupes). Pour préserver EXACTEMENT le comportement actuel, le contenu
#    de l'ancienne position=1 devient donc la config commune de POSITION 1
#    pour LES DEUX buckets (nb_seances_semaine=1 ET nb_seances_semaine=2).
#    L'ancienne position=2 (jamais atteinte que par un groupe à 2 séances)
#    devient la position 2 du bucket nb_seances_semaine=2 uniquement.
#
# 4. Groupes 381-384 (4 groupes sans créneau, donc sans cadence réelle)
#    : EXPLICITEMENT EXCLUS de cette migration, sur demande explicite du
#    client — "les groupes sans créneau ne représentent pas réellement une
#    cadence hebdomadaire de 1 séance". Aucun bucket n'est fabriqué pour
#    eux ici. Si un de ces groupes est un jour réellement évalué (aucun
#    prof ne leur est assigné aujourd'hui, donc impossible en pratique via
#    le parcours normal), Seance.nb_seances_semaine retombera sur 1 par son
#    PROPRE mécanisme de repli déjà existant (identique à celui de
#    numero_dans_la_semaine pour un groupe sans créneau) — ce repli est un
#    comportement RUNTIME préexistant, pas quelque chose que cette migration
#    construit ou décide pour eux. Investigation complète mais NON
#    concluante sur leur origine exacte (nom "verif_finale_20260812_..." +
#    Groupe.date_creation=2026-09-09 MAIS conversation chat associée
#    (chat.Conversation, OneToOneField CASCADE, créée automatiquement à la
#    création du Groupe par un signal — voir chat.signals.
#    creer_conversation_pour_nouveau_groupe) datée du 2026-08-15, donc 3
#    semaines et demie AVANT la date de création qu'affiche le Groupe
#    lui-même — contradiction non résolue) : décision du client de ne PAS
#    les supprimer ni les utiliser pour construire quoi que ce soit ici.
#
# 5. Aucun CritereEleve n'est créé/dupliqué : seule l'association M2M
#    change (profil.criteres.set(...)), toujours vers les MÊMES objets
#    CritereEleve déjà existants.
#
# 6. Aucune NotePresence n'est touchée : ProfilCriteresSeance n'a AUCUNE FK
#    entrante depuis Presence/NotePresence (voir son __doc__) — cette
#    migration ne référence jamais ces tables, l'historique d'évaluation
#    n'est ni recalculé ni réécrit.
#
# Les 2 anciennes lignes (groupe=NULL, nb_seances_semaine=NULL) sont
# supprimées à la fin — entièrement remplacées, plus jamais lues par aucun
# code depuis ce chantier (Seance.criteres_applicables ne cherche plus que
# par (groupe, position) puis (nb_seances_semaine, position) réel), les
# laisser en base ne serait que 2 lignes fantômes source de confusion.

from django.db import migrations


def migrer_vers_deux_niveaux(apps, schema_editor):
    ProfilCriteresSeance = apps.get_model('courses', 'ProfilCriteresSeance')

    ancien_position_1 = ProfilCriteresSeance.objects.filter(
        groupe__isnull=True, nb_seances_semaine__isnull=True, position=1,
    ).first()
    ancien_position_2 = ProfilCriteresSeance.objects.filter(
        groupe__isnull=True, nb_seances_semaine__isnull=True, position=2,
    ).first()

    if ancien_position_1 is not None:
        criteres_pos1 = list(ancien_position_1.criteres.all())
        for nb in (1, 2):
            profil, _ = ProfilCriteresSeance.objects.get_or_create(
                groupe=None, nb_seances_semaine=nb, position=1,
            )
            profil.criteres.set(criteres_pos1)

    if ancien_position_2 is not None:
        criteres_pos2 = list(ancien_position_2.criteres.all())
        profil, _ = ProfilCriteresSeance.objects.get_or_create(
            groupe=None, nb_seances_semaine=2, position=2,
        )
        profil.criteres.set(criteres_pos2)

    if ancien_position_1 is not None:
        ancien_position_1.delete()
    if ancien_position_2 is not None:
        ancien_position_2.delete()


def revert(apps, schema_editor):
    """Reconstruit les 2 anciennes lignes globales à partir des nouveaux
    buckets — SANS PERTE uniquement si aucune personnalisation n'a divergé
    les buckets (1,1)/(2,1) depuis la migration avant (voir la remarque
    ci-dessous). Best-effort, comme toute reverse migration de ce projet."""
    ProfilCriteresSeance = apps.get_model('courses', 'ProfilCriteresSeance')

    profil_1_1 = ProfilCriteresSeance.objects.filter(groupe__isnull=True, nb_seances_semaine=1, position=1).first()
    profil_2_1 = ProfilCriteresSeance.objects.filter(groupe__isnull=True, nb_seances_semaine=2, position=1).first()
    profil_2_2 = ProfilCriteresSeance.objects.filter(groupe__isnull=True, nb_seances_semaine=2, position=2).first()

    ancien_1, _ = ProfilCriteresSeance.objects.get_or_create(
        groupe=None, nb_seances_semaine=None, position=1,
    )
    # Si (1,1) et (2,1) ont divergé après la migration (personnalisation
    # commune de l'un des 2 buckets), impossible de restaurer une seule
    # ligne "position=1" sans perte — on privilégie ici le bucket majoritaire
    # (37 groupes à 2 séances contre 19 à 1 séance, vérifié le 2026-09-12).
    source_1 = profil_2_1 or profil_1_1
    if source_1 is not None:
        ancien_1.criteres.set(list(source_1.criteres.all()))

    ancien_2, _ = ProfilCriteresSeance.objects.get_or_create(
        groupe=None, nb_seances_semaine=None, position=2,
    )
    if profil_2_2 is not None:
        ancien_2.criteres.set(list(profil_2_2.criteres.all()))

    if profil_1_1 is not None:
        profil_1_1.delete()
    if profil_2_1 is not None:
        profil_2_1.delete()
    if profil_2_2 is not None:
        profil_2_2.delete()


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0052_profilcriteresseance_deux_niveaux'),
    ]

    operations = [
        migrations.RunPython(migrer_vers_deux_niveaux, revert),
    ]
