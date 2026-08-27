# Generated manually — Besoin 2 (2026-08-27) : grille tarifaire élève (seed du tableau fourni)

from django.db import migrations

# (cible_age, duree_code, duree_label_ar) — 4 durées, 2 tranches d'âge pour
# le جماعي. Les 2 TypeAbonnement historiques (groupe_1mois, groupe_3mois,
# seed 0004) ne distinguaient PAS l'âge — désactivés ici (jamais supprimés,
# voir REMPLACEMENTS ci-dessous), remplacés par 8 nouvelles lignes
# age × durée, seules capables de porter les 2 prix DIFFÉRENTS du tableau
# Besoin 2 (Adultes vs Enfants) pour une même durée. Mêmes codes que
# inscriptions.models.TypeAbonnement.DUREE_CHOICES (jamais importé ici —
# convention des migrations de données de ce projet : constantes recopiées,
# jamais une dépendance vers le modèle réel qui peut évoluer après coup).

# {(cible_age, duree_code): {nb_slots: prix}} — tableau EXACT du Besoin 2.
PRIX_GROUPE = {
    ('adulte', '1mois'): {1: 70, 2: 100, 3: 130},
    ('adulte', '3mois'): {1: 200, 2: 250, 3: 370},
    ('adulte', '6mois'): {1: 390, 2: 450, 3: 720},
    ('adulte', '1an'): {1: 750, 2: 850, 3: 1420},
    ('enfant', '1mois'): {1: 80, 2: 120, 3: 150},
    ('enfant', '3mois'): {1: 220, 2: 340, 3: 430},
    ('enfant', '6mois'): {1: 420, 2: 660, 3: 850},
    ('enfant', '1an'): {1: 820, 2: 1300, 3: 1600},
}

# فردي — pas de distinction d'âge (voir TypeAbonnement.cible_age='les_deux').
# individuel_1mois/individuel_3mois existent déjà (seed 0004) : réutilisés
# tels quels (code inchangé), seules leur duree/prix par défaut sont mis à
# jour + leur grille complétée. individuel_6mois/individuel_1an sont NOUVEAUX.
PRIX_INDIVIDUEL = {
    '1mois': {1: 200, 2: 350, 3: 500},
    '3mois': {1: 500, 2: 1000, 3: 1400},
    '6mois': {1: 900, 2: 1900, 3: 2700},
    '1an': {1: 1700, 2: 3700, 3: 5300},
}

# Codes/prix des 2 lignes جماعي historiques, désactivées par cette migration
# (remplacées par les 8 lignes age × durée ci-dessus — voir leur docstring).
ANCIENS_CODES_GROUPE_A_DESACTIVER = ['groupe_1mois', 'groupe_3mois']


def seed(apps, schema_editor):
    TypeAbonnement = apps.get_model('inscriptions', 'TypeAbonnement')
    GrillePrixAbonnement = apps.get_model('inscriptions', 'GrillePrixAbonnement')

    TypeAbonnement.objects.filter(code__in=ANCIENS_CODES_GROUPE_A_DESACTIVER).update(est_actif=False)

    ordre = 10
    for (cible_age, duree_code), prix_par_slots in PRIX_GROUPE.items():
        code = f'groupe_{cible_age}_{duree_code}'
        abonnement, _ = TypeAbonnement.objects.get_or_create(
            code=code,
            defaults={
                'label': 'الاشتراك الجماعي', 'duree': duree_code, 'type_offre': 'groupe',
                'cible_age': cible_age, 'prix': prix_par_slots[1], 'ordre': ordre, 'est_actif': True,
            },
        )
        ordre += 1
        for nb_slots, prix in prix_par_slots.items():
            GrillePrixAbonnement.objects.get_or_create(
                type_abonnement=abonnement, nb_slots=nb_slots, defaults={'prix': prix},
            )

    for duree_code, prix_par_slots in PRIX_INDIVIDUEL.items():
        code = f'individuel_{duree_code}'
        abonnement, _ = TypeAbonnement.objects.get_or_create(
            code=code,
            defaults={
                'label': 'الاشتراك الفردي', 'duree': duree_code, 'type_offre': 'individuel',
                'cible_age': 'les_deux', 'prix': prix_par_slots[1], 'ordre': ordre, 'est_actif': True,
            },
        )
        # Ligne déjà existante (individuel_1mois/individuel_3mois, seed 0004) :
        # duree/prix mis à jour vers les valeurs Besoin 2 (nb_slots=1) SANS
        # écraser un label déjà personnalisé par le مدير depuis (get_or_create
        # ci-dessus ne touche `defaults` que sur CRÉATION — pour une ligne
        # déjà existante, duree/prix sont donc mis à jour explicitement ici,
        # séparément, jamais le label qui reste au choix du مدير).
        if not _:
            abonnement.duree = duree_code
            abonnement.prix = prix_par_slots[1]
            abonnement.save(update_fields=['duree', 'prix'])
        ordre += 1
        for nb_slots, prix in prix_par_slots.items():
            GrillePrixAbonnement.objects.get_or_create(
                type_abonnement=abonnement, nb_slots=nb_slots, defaults={'prix': prix},
            )


def reverse_seed(apps, schema_editor):
    TypeAbonnement = apps.get_model('inscriptions', 'TypeAbonnement')

    TypeAbonnement.objects.filter(code__in=ANCIENS_CODES_GROUPE_A_DESACTIVER).update(est_actif=True)
    codes_groupe = [f'groupe_{c}_{d}' for c, d in PRIX_GROUPE]
    TypeAbonnement.objects.filter(code__in=codes_groupe).delete()
    # individuel_1mois/individuel_3mois PRÉ-EXISTAIENT à cette migration — ne
    # jamais les supprimer au retour arrière, seulement les 2 vraiment créées ici.
    TypeAbonnement.objects.filter(code__in=['individuel_6mois', 'individuel_1an']).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('inscriptions', '0029_convertir_duree_texte_libre_vers_codes'),
        ('courses', '0040_seed_nb_seances_et_tarifs_remuneration'),
    ]

    operations = [
        migrations.RunPython(seed, reverse_seed),
    ]
