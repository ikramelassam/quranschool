from django.db import migrations

# Mêmes codes/libellés que courses.models.Creneau.TYPE_SEANCE_CHOICES/
# RIWAYA_CHOICES et courses.models.Groupe.TYPE_CAPACITE_CHOICES — pas
# réinventés, réutilisés tels quels pour rester cohérents avec les 20
# Creneau/31 Groupe déjà réels en base (voir le backfill plus bas).
OPTIONS_PROGRAMME = [
    ('hifz', 'الحفظ والمراجعة وتعلم أحكام التجويد'),
    ('tathbit', 'التثبيت وتعلم أحكام التجويد'),
]
OPTIONS_RIWAYA = [
    ('hafs', 'حفص'),
    ('warsh', 'ورش'),
]
OPTIONS_TYPE_OFFRE = [
    ('groupe', 'جماعي'),
    ('individuel', 'فردي'),
]


def seed_configuration_wizard(apps, schema_editor):
    """Étape 6 du chantier du moteur d'inscription configurable — sans cette
    configuration de départ, le nouveau parcours public serait techniquement
    fonctionnel mais VIDE (aucune étape 'اختيار البرنامج', aucun critère,
    donc groupes_compatibles() ne retournerait jamais rien). Ce que le مدير
    ferait lui-même depuis le dashboard (Étape 5A-5B) au premier lancement —
    fait ici une fois pour que le wizard soit utilisable immédiatement avec
    les données réelles déjà en base.

    IMPORTANT : rien n'empêche le مدير de modifier/réordonner/désactiver
    n'importe lequel de ces éléments après coup depuis le dashboard, exactement
    comme s'il les avait créés lui-même — cette migration ne fait que poser un
    point de départ raisonnable, pas une configuration figée."""
    Critere = apps.get_model('registration', 'Critere')
    CritereOption = apps.get_model('registration', 'CritereOption')
    EtapeInscription = apps.get_model('registration', 'EtapeInscription')
    ChampInscription = apps.get_model('registration', 'ChampInscription')
    GroupeCritereValeur = apps.get_model('registration', 'GroupeCritereValeur')
    Groupe = apps.get_model('courses', 'Groupe')

    etape_identite, _ = EtapeInscription.objects.get_or_create(
        code='identite', defaults={'titre': 'المعلومات الشخصية', 'ordre': 1},
    )
    etape_programme, _ = EtapeInscription.objects.get_or_create(
        code='programme', defaults={'titre': 'اختيار البرنامج', 'ordre': 2},
    )

    critere_programme, _ = Critere.objects.get_or_create(
        code='programme',
        defaults={
            'label': 'البرنامج', 'type_champ': 'choix_unique', 'backend': 'eav',
            'filtrable': True, 'bloquant': False, 'ordre': 1,
        },
    )
    critere_riwaya, _ = Critere.objects.get_or_create(
        code='riwaya',
        defaults={
            'label': 'الرواية', 'type_champ': 'choix_unique', 'backend': 'eav',
            'filtrable': True, 'bloquant': False, 'ordre': 2,
        },
    )
    critere_type_offre, _ = Critere.objects.get_or_create(
        code='type_offre',
        defaults={
            'label': 'نوع الحصة', 'type_champ': 'choix_unique', 'backend': 'champ_groupe',
            'champ_modele_groupe': 'type_capacite', 'filtrable': True, 'bloquant': True, 'ordre': 3,
        },
    )
    critere_nb_seances, _ = Critere.objects.get_or_create(
        code='nb_seances_hebdo',
        defaults={
            'label': 'عدد الحصص الأسبوعية', 'type_champ': 'choix_unique', 'backend': 'nb_slots',
            'filtrable': True, 'bloquant': False, 'ordre': 4,
        },
    )

    options_par_code_programme = {}
    for i, (code, label) in enumerate(OPTIONS_PROGRAMME):
        opt, _ = CritereOption.objects.get_or_create(
            critere=critere_programme, code=code, defaults={'label': label, 'ordre': i},
        )
        options_par_code_programme[code] = opt

    options_par_code_riwaya = {}
    for i, (code, label) in enumerate(OPTIONS_RIWAYA):
        opt, _ = CritereOption.objects.get_or_create(
            critere=critere_riwaya, code=code, defaults={'label': label, 'ordre': i},
        )
        options_par_code_riwaya[code] = opt

    for i, (code, label) in enumerate(OPTIONS_TYPE_OFFRE):
        CritereOption.objects.get_or_create(
            critere=critere_type_offre, code=code, defaults={'label': label, 'ordre': i},
        )

    ChampInscription.objects.get_or_create(
        etape=etape_programme, critere=critere_programme,
        defaults={'label': 'البرنامج', 'obligatoire': True, 'ordre': 1},
    )
    ChampInscription.objects.get_or_create(
        etape=etape_programme, critere=critere_riwaya,
        defaults={'label': 'الرواية', 'obligatoire': True, 'ordre': 2},
    )
    ChampInscription.objects.get_or_create(
        etape=etape_programme, critere=critere_type_offre,
        defaults={'label': 'نوع الحصة', 'obligatoire': True, 'ordre': 3},
    )
    ChampInscription.objects.get_or_create(
        etape=etape_programme, critere=critere_nb_seances,
        defaults={'label': 'عدد الحصص الأسبوعية', 'obligatoire': True, 'ordre': 4},
    )

    # Backfill : sans ceci, AUCUN des 31 groupes réels n'aurait de valeur pour
    # 'programme'/'riwaya' -> groupes_compatibles() ne retournerait jamais rien
    # pour un élève réel. Dérivé du creneau (déjà la source de vérité pour ces
    # 2 informations avant ce chantier) — jamais deviné, jamais écrasé si déjà
    # renseigné (get_or_create). type_offre/nb_seances n'ont PAS besoin de
    # backfill : ce sont les backends 'champ_groupe'/'nb_slots', dérivés à la
    # volée, jamais stockés en GroupeCritereValeur (voir registration.models).
    for groupe in Groupe.objects.filter(creneau__isnull=False).select_related('creneau'):
        option_programme = options_par_code_programme.get(groupe.creneau.type_seance)
        if option_programme:
            GroupeCritereValeur.objects.get_or_create(
                groupe=groupe, critere=critere_programme, option=option_programme,
            )
        option_riwaya = options_par_code_riwaya.get(groupe.creneau.riwaya)
        if option_riwaya:
            GroupeCritereValeur.objects.get_or_create(
                groupe=groupe, critere=critere_riwaya, option=option_riwaya,
            )


def ne_rien_faire_au_retour_arriere(apps, schema_editor):
    """Reverse volontairement no-op — même principe que le reste de ce projet
    (0034_backfill_groupe_categorie_depuis_creneau...) : reculer ne peut pas
    distinguer de façon fiable une GroupeCritereValeur posée par CE backfill
    de la même valeur posée manuellement depuis par le مدير entretemps."""
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('registration', '0001_initial'),
        ('courses', '0037_alter_creneau_heure_debut_1_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_configuration_wizard, ne_rien_faire_au_retour_arriere),
    ]
