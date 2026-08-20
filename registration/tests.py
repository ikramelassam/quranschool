import datetime

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import User
from courses.models import Creneau, Groupe
from courses.utils import remplacer_slots_creneau
from inscriptions.models import InscriptionEleve, TypeAbonnement
from .models import ChampInscription, Critere, CritereOption, EtapeInscription, GroupeCritereValeur, RegleCondition
from .utils import (
    couverture_critere, groupes_compatibles, groupes_compatibles_avec_age,
    inscrire_eleve, nb_seances_disponibles, champ_est_masque,
)

MOT_DE_PASSE = 'xX!test12345'


# Même précaution que inscriptions.tests/dashboard.tests (STORAGES) : toute
# page qui charge le logo (header ou wizard, via accounts.context_processors.
# logo_context) lève une ValueError sans cet override en environnement de test.
_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _creer_admin(email='admin_registration@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مدير', last_name='تجريبي', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif(email='mshrif_registration@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مشرف', last_name='تجريبي', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_creneau(nb_slots=2, age_min=6, age_max=60, sexe_cible='mixte'):
    creneau = Creneau.objects.create(
        sexe_cible=sexe_cible, type_seance='hifz', riwaya='hafs', age_min=age_min, age_max=age_max,
    )
    jours = ['lun', 'mar', 'mer', 'jeu', 'ven']
    remplacer_slots_creneau(creneau, [
        {'jour': jours[i], 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}
        for i in range(nb_slots)
    ])
    return creneau


def _creer_critere(code, label='', backend='eav', filtrable=True, bloquant=False,
                    type_champ='choix_unique', champ_modele_groupe='', options=()):
    critere = Critere.objects.create(
        code=code, label=label or code, backend=backend, filtrable=filtrable, bloquant=bloquant,
        type_champ=type_champ, champ_modele_groupe=champ_modele_groupe,
    )
    for i, (code_opt, label_opt) in enumerate(options):
        CritereOption.objects.create(critere=critere, code=code_opt, label=label_opt, ordre=i)
    return critere


class GroupesCompatiblesBackendsTests(TestCase):
    """groupes_compatibles() — les 3 backends fermés (eav/champ_groupe/nb_slots),
    zéro branche par nom de critère métier."""

    def setUp(self):
        # Codes test_ : la base de test contient déjà 'riwaya'/'type_offre'/
        # 'nb_seances_hebdo' seedés par registration/migrations/0002_seed_
        # wizard_config.py (Étape 6A) — mêmes codes distincts qu'ailleurs.
        self.riwaya = _creer_critere('test_riwaya', options=[('hafs', 'حفص'), ('warsh', 'ورش')])
        self.type_offre = _creer_critere(
            'test_type_offre', backend='champ_groupe', champ_modele_groupe='type_capacite',
            options=[('groupe', 'جماعي'), ('individuel', 'فردي')],
        )
        self.nb_seances = _creer_critere('test_nb_seances_hebdo', backend='nb_slots')

        self.creneau_2slots = _creer_creneau(nb_slots=2)
        self.creneau_3slots = _creer_creneau(nb_slots=3)

        self.groupe_hafs_groupe = Groupe.objects.create(
            nom='مجموعة حفص جماعية', creneau=self.creneau_2slots, statut='actif', type_capacite='groupe',
        )
        GroupeCritereValeur.objects.create(
            groupe=self.groupe_hafs_groupe, critere=self.riwaya,
            option=self.riwaya.options.get(code='hafs'),
        )

        self.groupe_warsh_individuel = Groupe.objects.create(
            nom='مجموعة ورش فردية', creneau=self.creneau_3slots, statut='actif', type_capacite='individuel',
        )
        GroupeCritereValeur.objects.create(
            groupe=self.groupe_warsh_individuel, critere=self.riwaya,
            option=self.riwaya.options.get(code='warsh'),
        )

    def test_backend_eav_filtre_par_option(self):
        resultat = groupes_compatibles({self.riwaya: self.riwaya.options.get(code='hafs')})
        self.assertEqual(list(resultat), [self.groupe_hafs_groupe])

    def test_backend_champ_groupe_filtre_directement_sur_le_champ_reel(self):
        """type_capacite='individuel' seul matcherait aussi les groupes
        individuels RÉELS de la base (Étape 6A) — combiné avec le critère
        riwaya test-spécifique (naturellement isolé, aucun groupe réel n'a
        de GroupeCritereValeur pour CE critère précis) pour rester isolé."""
        resultat = groupes_compatibles({
            self.type_offre: 'individuel',
            self.riwaya: self.riwaya.options.get(code='warsh'),
        })
        self.assertEqual(list(resultat), [self.groupe_warsh_individuel])
        # Aucune GroupeCritereValeur n'est jamais créée pour ce backend.
        self.assertFalse(GroupeCritereValeur.objects.filter(critere=self.type_offre).exists())

    def test_backend_nb_slots_filtre_par_nombre_reel_de_creneauslot(self):
        resultat = groupes_compatibles({self.nb_seances: 3})
        self.assertEqual(list(resultat), [self.groupe_warsh_individuel])
        self.assertFalse(GroupeCritereValeur.objects.filter(critere=self.nb_seances).exists())

    def test_plusieurs_criteres_combines_semantique_et(self):
        resultat = groupes_compatibles({
            self.riwaya: self.riwaya.options.get(code='hafs'),
            self.type_offre: 'groupe',
        })
        self.assertEqual(list(resultat), [self.groupe_hafs_groupe])

        # hafs + individuel -> aucun groupe ne correspond aux 2 à la fois.
        resultat_vide = groupes_compatibles({
            self.riwaya: self.riwaya.options.get(code='hafs'),
            self.type_offre: 'individuel',
        })
        self.assertEqual(list(resultat_vide), [])

    def test_critere_non_filtrable_est_ignore(self):
        """Un critère non filtrable ne restreint rien -> les 2 groupes de ce
        test restent présents dans le résultat (qui contient aussi le fond
        réel de 23 groupes, Étape 6A — d'où assertIn plutôt qu'une égalité
        d'ensemble stricte)."""
        critere_info = _creer_critere('couleur_preferee', filtrable=False, options=[('bleu', 'أزرق')])
        resultat = set(groupes_compatibles({critere_info: critere_info.options.get(code='bleu')}))
        self.assertIn(self.groupe_hafs_groupe, resultat)
        self.assertIn(self.groupe_warsh_individuel, resultat)

    def test_choix_multiple_matche_avec_au_moins_une_option(self):
        langue = _creer_critere(
            'langue', type_champ='choix_multiple',
            options=[('ar', 'العربية'), ('fr', 'الفرنسية'), ('en', 'الإنجليزية')],
        )
        GroupeCritereValeur.objects.create(
            groupe=self.groupe_hafs_groupe, critere=langue, option=langue.options.get(code='fr'),
        )
        resultat = groupes_compatibles({langue: [langue.options.get(code='fr'), langue.options.get(code='en')]})
        self.assertEqual(list(resultat), [self.groupe_hafs_groupe])

    def test_groupes_compatibles_avec_age_applique_la_contrainte_structurelle(self):
        creneau_enfants = _creer_creneau(nb_slots=1, age_min=4, age_max=10)
        groupe_enfants = Groupe.objects.create(nom='مجموعة أطفال', creneau=creneau_enfants, statut='actif')

        naissance_6_ans = datetime.date.today().replace(year=datetime.date.today().year - 6)
        naissance_40_ans = datetime.date.today().replace(year=datetime.date.today().year - 40)

        resultat_enfant = groupes_compatibles_avec_age({}, naissance_6_ans)
        self.assertIn(groupe_enfants, resultat_enfant)  # 6 ans -> dans [4,10]

        resultat_adulte = groupes_compatibles_avec_age({}, naissance_40_ans)
        self.assertNotIn(groupe_enfants, resultat_adulte)  # 40 ans -> hors [4,10]
        self.assertIn(self.groupe_hafs_groupe, resultat_adulte)  # 40 ans -> dans [6,60]


class NbSeancesDisponiblesTests(TestCase):
    """La base de test contient déjà 23 groupes RÉELS (seedés/backfillés par
    registration/migrations/0002_seed_wizard_config.py, Étape 6A) — un
    critère 'test_tag' sert à isoler les groupes propres à chaque test de ce
    fond réel, pour que nb_seances_disponibles({}) sans lui ne soit jamais
    comparé en égalité stricte à une liste qui ignorerait ce fond."""

    def _tag(self):
        return _creer_critere('test_tag_nb_seances', options=[('oui', 'نعم')])

    def _groupe_tague(self, tag, nom, nb_slots):
        groupe = Groupe.objects.create(nom=nom, creneau=_creer_creneau(nb_slots=nb_slots), statut='actif')
        GroupeCritereValeur.objects.create(groupe=groupe, critere=tag, option=tag.options.get(code='oui'))
        return groupe

    def test_ne_propose_que_les_valeurs_reellement_presentes(self):
        tag = self._tag()
        self._groupe_tague(tag, '1 حصة', 1)
        self._groupe_tague(tag, '2 حصص', 2)
        self._groupe_tague(tag, '4 حصص', 4)
        # Aucun groupe à 3 slots créé (parmi les groupes tagués) -> 3 ne
        # doit jamais apparaître, quel que soit le fond réel de la base.
        self.assertEqual(nb_seances_disponibles({tag: tag.options.get(code='oui')}), [1, 2, 4])

    def test_nouveau_groupe_a_5_slots_apparait_sans_aucun_code_supplementaire(self):
        tag = self._tag()
        self._groupe_tague(tag, '5 حصص', 5)
        self.assertEqual(nb_seances_disponibles({tag: tag.options.get(code='oui')}), [5])

    def test_respecte_les_reponses_deja_donnees(self):
        riwaya = _creer_critere('test_riwaya_nb_seances', options=[('hafs', 'حفص'), ('warsh', 'ورش')])
        g1 = Groupe.objects.create(nom='حفص 1 حصة', creneau=_creer_creneau(nb_slots=1), statut='actif')
        GroupeCritereValeur.objects.create(groupe=g1, critere=riwaya, option=riwaya.options.get(code='hafs'))
        g2 = Groupe.objects.create(nom='ورش 2 حصص', creneau=_creer_creneau(nb_slots=2), statut='actif')
        GroupeCritereValeur.objects.create(groupe=g2, critere=riwaya, option=riwaya.options.get(code='warsh'))

        self.assertEqual(nb_seances_disponibles({riwaya: riwaya.options.get(code='hafs')}), [1])
        self.assertEqual(nb_seances_disponibles({riwaya: riwaya.options.get(code='warsh')}), [2])


class CouvertureCritereTests(TestCase):
    def test_none_pour_backend_champ_groupe_et_nb_slots(self):
        type_offre = _creer_critere('test_couverture_type_offre', backend='champ_groupe', champ_modele_groupe='type_capacite')
        nb_seances = _creer_critere('test_couverture_nb_seances', backend='nb_slots')
        self.assertIsNone(couverture_critere(type_offre))
        self.assertIsNone(couverture_critere(nb_seances))

    def test_total_configures_et_groupes_manquants_pour_backend_eav(self):
        """total porte sur TOUS les groupes actifs (comportement voulu, voir
        couverture_critere) — la base de test en contient déjà 23 réels
        (Étape 6A) en plus des 2 créés ici, d'où le total calculé
        dynamiquement plutôt qu'une valeur absolue codée en dur."""
        total_avant = Groupe.actifs.filter(statut='actif').count()
        objectif = _creer_critere('objectif', options=[('memorisation', 'الحفظ')])
        g1 = Groupe.objects.create(nom='مجموعة مهيأة', creneau=_creer_creneau(), statut='actif')
        g2 = Groupe.objects.create(nom='مجموعة غير مهيأة', creneau=_creer_creneau(), statut='actif')
        GroupeCritereValeur.objects.create(groupe=g1, critere=objectif, option=objectif.options.get(code='memorisation'))

        couverture = couverture_critere(objectif)
        self.assertEqual(couverture['total'], total_avant + 2)
        self.assertEqual(couverture['configures'], 1)
        self.assertIn(g2, couverture['groupes_manquants'])
        self.assertNotIn(g1, couverture['groupes_manquants'])

    def test_zero_groupe_configure(self):
        total_avant = Groupe.actifs.filter(statut='actif').count()
        objectif = _creer_critere('objectif', options=[('lecture', 'التلاوة')])
        Groupe.objects.create(nom='مجموعة', creneau=_creer_creneau(), statut='actif')
        couverture = couverture_critere(objectif)
        self.assertEqual(couverture['configures'], 0)
        self.assertEqual(couverture['total'], total_avant + 1)


class RegleConditionMasquageTests(TestCase):
    def test_etape_masquee_si_regle_satisfaite(self):
        etape_groupe = EtapeInscription.objects.create(code='test_choix_groupe', titre='اختيار المجموعة', ordre=3)
        type_offre = _creer_critere(
            'test_type_offre', backend='champ_groupe', champ_modele_groupe='type_capacite',
            options=[('groupe', 'جماعي'), ('individuel', 'فردي')],
        )
        RegleCondition.objects.create(
            cible_content_type=ContentType.objects.get_for_model(etape_groupe),
            cible_object_id=etape_groupe.id,
            critere_condition=type_offre, operateur='different', valeurs=['groupe'],
        )
        champ = ChampInscription.objects.create(etape=etape_groupe, label='اختر مجموعتك', ordre=1)

        # Réponse 'individuel' -> 'different' de 'groupe' -> règle satisfaite -> masqué.
        codes = {type_offre.id: {'individuel'}}
        self.assertTrue(champ_est_masque(champ, codes))

        # Réponse 'groupe' -> pas 'different' -> règle non satisfaite -> visible.
        codes_groupe = {type_offre.id: {'groupe'}}
        self.assertFalse(champ_est_masque(champ, codes_groupe))

        # Aucune réponse encore -> règle non satisfaite (ensemble vide) -> visible par défaut.
        self.assertFalse(champ_est_masque(champ, {}))


def _config_standard():
    """Configuration minimale réaliste (Programme/Riwaya/Groupe-ou-Individuel/
    Nombre de séances) — réutilisée par les tests inscrire_eleve(). Codes
    préfixés test_ : la base de test contient déjà 'identite'/'programme'/
    'riwaya'/'type_offre'/'nb_seances_hebdo' seedés par la migration
    registration/0002_seed_wizard_config.py (Étape 6A) — mêmes codes
    distincts que pour TypeAbonnement plus bas, même raison."""
    from django.contrib.contenttypes.models import ContentType

    etape_identite = EtapeInscription.objects.create(code='test_identite', titre='المعلومات الشخصية', ordre=1)
    etape_programme = EtapeInscription.objects.create(code='test_programme', titre='اختيار البرنامج', ordre=2)
    etape_groupe = EtapeInscription.objects.create(code='test_choix_groupe', titre='اختيار المجموعة', ordre=3)

    riwaya = _creer_critere('test_riwaya', filtrable=True, bloquant=False, options=[('hafs', 'حفص'), ('warsh', 'ورش')])
    type_offre = _creer_critere(
        'test_type_offre', backend='champ_groupe', champ_modele_groupe='type_capacite',
        filtrable=True, bloquant=True, options=[('groupe', 'جماعي'), ('individuel', 'فردي')],
    )
    nb_seances = _creer_critere('test_nb_seances_hebdo', backend='nb_slots', filtrable=True, bloquant=False)

    champ_riwaya = ChampInscription.objects.create(etape=etape_programme, critere=riwaya, label='الرواية', obligatoire=True, ordre=1)
    champ_type_offre = ChampInscription.objects.create(etape=etape_programme, critere=type_offre, label='نوع الحصة', obligatoire=True, ordre=2)
    champ_nb_seances = ChampInscription.objects.create(etape=etape_programme, critere=nb_seances, label='عدد الحصص', obligatoire=False, ordre=3)
    champ_groupe_select = ChampInscription.objects.create(etape=etape_groupe, label='اختر مجموعتك', ordre=1)

    RegleCondition.objects.create(
        cible_content_type=ContentType.objects.get_for_model(etape_groupe),
        cible_object_id=etape_groupe.id,
        critere_condition=type_offre, operateur='different', valeurs=['groupe'],
    )

    # Codes préfixés test_ : la base de test contient déjà les TypeAbonnement
    # réels seedés par inscriptions/migrations/0004_seed_types_abonnement.py
    # (groupe_1mois, individuel_1mois...) — codes distincts pour ne jamais entrer
    # en collision avec cette donnée de départ.
    TypeAbonnement.objects.create(code='test_abo_groupe', label='شهري جماعي', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1)
    TypeAbonnement.objects.create(code='test_abo_individuel', label='شهري فردي', prix=400, type_offre='individuel', cible_age='les_deux', ordre=2)

    return {
        'riwaya': riwaya, 'type_offre': type_offre, 'nb_seances': nb_seances,
        'champ_riwaya': champ_riwaya, 'champ_type_offre': champ_type_offre,
        'champ_nb_seances': champ_nb_seances, 'champ_groupe_select': champ_groupe_select,
    }


class InscrireEleveTests(TestCase):
    def setUp(self):
        # Isole ce scénario de la config RÉELLE seedée par registration/
        # migrations/0002_seed_wizard_config.py (Étape 6A, existe aussi dans
        # cette base de test) — inscrire_eleve() valide À JUSTE TITRE TOUS
        # les ChampInscription actifs, seedés compris ; désactivés ici pour
        # que ces tests restent des scénarios autonomes avec leur propre
        # config test_* (_config_standard), sans avoir à répondre en plus
        # aux 4 champs réels du wizard.
        from .models import ChampInscription
        ChampInscription.objects.update(est_actif=False)

        self.config = _config_standard()
        self.creneau = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        self.groupe = Groupe.objects.create(
            nom='مجموعة حفص جماعية', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(
            groupe=self.groupe, critere=self.config['riwaya'],
            option=self.config['riwaya'].options.get(code='hafs'),
        )

    def _reponses_de_base(self, **overrides):
        base = {
            'nom': 'أحمد الطالب', 'sexe': 'homme', 'telephone': '+212600000000',
            'date_naissance': '2000-01-01', 'email': 'ahmed.test@zidni.test',
            f"champ_{self.config['champ_riwaya'].id}": 'hafs',
            f"champ_{self.config['champ_type_offre'].id}": 'groupe',
            f"champ_{self.config['champ_nb_seances'].id}": '2',
            'groupe_id': str(self.groupe.id),
            'abonnement_code': 'test_abo_groupe',
            'accepte_conditions': 'oui',
        }
        base.update(overrides)
        return base

    def test_creation_reussie_parcours_groupe(self):
        inscription, erreurs = inscrire_eleve(self._reponses_de_base())
        self.assertEqual(erreurs, [])
        self.assertIsNotNone(inscription)
        self.assertEqual(inscription.groupe_choisi, self.groupe)
        self.assertEqual(inscription.abonnement, 'test_abo_groupe')
        # Les réponses dynamiques sont bien créées (riwaya, type_offre, nb_seances).
        self.assertEqual(inscription.reponses.count(), 3)
        reponse_riwaya = inscription.reponses.get(champ=self.config['champ_riwaya'])
        self.assertEqual(reponse_riwaya.option.code, 'hafs')

    def test_creation_reussie_parcours_individuel_saute_le_groupe(self):
        reponses = self._reponses_de_base(**{
            f"champ_{self.config['champ_type_offre'].id}": 'individuel',
            'abonnement_code': 'test_abo_individuel',
        })
        del reponses['groupe_id']
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertEqual(erreurs, [])
        self.assertIsNone(inscription.groupe_choisi)

    def test_groupe_id_poste_en_individuel_est_ignore_silencieusement(self):
        """Sécurité serveur (Partie 3/26) : un groupe_id manipulé dans le POST
        alors que le choix est Individuel ne doit JAMAIS être utilisé, sans être
        pour autant une erreur bloquante pour l'élève."""
        reponses = self._reponses_de_base(**{
            f"champ_{self.config['champ_type_offre'].id}": 'individuel',
            'abonnement_code': 'test_abo_individuel',
            'groupe_id': str(self.groupe.id),  # tentative de contournement
        })
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertEqual(erreurs, [])
        self.assertIsNone(inscription.groupe_choisi)

    def test_email_deja_pris_par_un_compte_est_bloque(self):
        User.objects.create_user(
            username='deja@zidni.test', email='deja@zidni.test', password=MOT_DE_PASSE, role='eleve',
        )
        inscription, erreurs = inscrire_eleve(self._reponses_de_base(email='deja@zidni.test'))
        self.assertIsNone(inscription)
        self.assertTrue(any('البريد' in e for e in erreurs))
        self.assertEqual(InscriptionEleve.objects.count(), 0)

    def test_champ_obligatoire_manquant_bloque(self):
        reponses = self._reponses_de_base()
        del reponses[f"champ_{self.config['champ_riwaya'].id}"]
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertIsNone(inscription)
        self.assertTrue(any('الرواية' in e for e in erreurs))

    def test_groupe_incompatible_refuse_pour_le_public(self):
        creneau_warsh = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        groupe_warsh = Groupe.objects.create(nom='ورش', creneau=creneau_warsh, statut='actif', capacite_max=10)
        GroupeCritereValeur.objects.create(
            groupe=groupe_warsh, critere=self.config['riwaya'],
            option=self.config['riwaya'].options.get(code='warsh'),
        )
        reponses = self._reponses_de_base(groupe_id=str(groupe_warsh.id))  # a répondu hafs mais choisit un groupe warsh
        inscription, erreurs = inscrire_eleve(reponses, cree_par=None, confirme_override=False)
        self.assertIsNone(inscription)
        self.assertTrue(any('لم تعد متاحة' in e for e in erreurs))

    def test_override_ignore_si_cree_par_none_meme_si_flag_true(self):
        """Défense en profondeur : confirme_override=True est sans effet si
        cree_par est None, même si un appelant malveillant/buggé le forçait."""
        creneau_warsh = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        groupe_warsh = Groupe.objects.create(nom='ورش', creneau=creneau_warsh, statut='actif', capacite_max=10)
        GroupeCritereValeur.objects.create(
            groupe=groupe_warsh, critere=self.config['riwaya'],
            option=self.config['riwaya'].options.get(code='warsh'),
        )
        reponses = self._reponses_de_base(groupe_id=str(groupe_warsh.id))
        inscription, erreurs = inscrire_eleve(reponses, cree_par=None, confirme_override=True)
        self.assertIsNone(inscription)

    def test_override_directeur_passe_outre_critere_non_bloquant(self):
        admin = _creer_admin()
        creneau_warsh = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        groupe_warsh = Groupe.objects.create(nom='ورش', creneau=creneau_warsh, statut='actif', capacite_max=10)
        GroupeCritereValeur.objects.create(
            groupe=groupe_warsh, critere=self.config['riwaya'],
            option=self.config['riwaya'].options.get(code='warsh'),
        )
        reponses = self._reponses_de_base(groupe_id=str(groupe_warsh.id))
        inscription, erreurs = inscrire_eleve(reponses, cree_par=admin, confirme_override=True)
        self.assertEqual(erreurs, [])
        self.assertEqual(inscription.groupe_choisi, groupe_warsh)

    def test_override_ne_passe_jamais_outre_lage_structurel(self):
        """L'âge reste bloquant même avec confirme_override=True (Partie 20)."""
        admin = _creer_admin()
        creneau_adultes = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=25, age_max=60)
        remplacer_slots_creneau(creneau_adultes, [{'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}])
        groupe_adultes = Groupe.objects.create(nom='بالغون', creneau=creneau_adultes, statut='actif', capacite_max=10)
        GroupeCritereValeur.objects.create(
            groupe=groupe_adultes, critere=self.config['riwaya'],
            option=self.config['riwaya'].options.get(code='hafs'),
        )
        # Enfant de 8 ans -> hors bornes 25-60 même avec override.
        reponses = self._reponses_de_base(date_naissance='2018-01-01', groupe_id=str(groupe_adultes.id))
        inscription, erreurs = inscrire_eleve(reponses, cree_par=admin, confirme_override=True)
        self.assertIsNone(inscription)

    def test_capacite_pleine_bloque(self):
        self.groupe.capacite_max = 0
        self.groupe.save()
        inscription, erreurs = inscrire_eleve(self._reponses_de_base())
        self.assertIsNone(inscription)
        self.assertTrue(any('مكتملة' in e for e in erreurs))

    def test_mshrif_a_les_memes_capacites_que_directeur(self):
        mshrif = _creer_mshrif()
        creneau_warsh = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        groupe_warsh = Groupe.objects.create(nom='ورش', creneau=creneau_warsh, statut='actif', capacite_max=10)
        GroupeCritereValeur.objects.create(
            groupe=groupe_warsh, critere=self.config['riwaya'],
            option=self.config['riwaya'].options.get(code='warsh'),
        )
        reponses = self._reponses_de_base(groupe_id=str(groupe_warsh.id))
        inscription, erreurs = inscrire_eleve(reponses, cree_par=mshrif, confirme_override=True)
        self.assertEqual(erreurs, [])


# ============================================================================
# TEST DE GÉNÉRICITÉ — Partie 24 : un critère jamais imaginé aujourd'hui doit
# fonctionner de bout en bout (créé -> options -> étape -> obligatoire ->
# filtrable -> valeurs de groupes -> filtrage) sans une seule ligne de code
# spécifique à son nom. Répété avec un 2e critère totalement différent pour
# prouver que ce n'est pas un cas particulier.
# ============================================================================
class RegistrationGenericiteTests(TestCase):
    def _scenario_critere_jamais_prevu(self, code, label, options_codes_labels):
        """Simule EXACTEMENT ce qu'un Directeur/مشرف ferait depuis le dashboard
        (Étape 5, pas encore codée) — ici via l'ORM directement, ce qui est
        strictement équivalent : le dashboard ne fera jamais rien de plus que
        ces mêmes appels Critere.objects.create()/CritereOption.objects.create()."""
        etape = EtapeInscription.objects.create(code=f'etape_{code}', titre=label, ordre=1)
        critere = Critere.objects.create(code=code, label=label, backend='eav', filtrable=True, bloquant=False)
        options = {
            oc: CritereOption.objects.create(critere=critere, code=oc, label=ol, ordre=i)
            for i, (oc, ol) in enumerate(options_codes_labels)
        }
        champ = ChampInscription.objects.create(etape=etape, critere=critere, label=label, obligatoire=True, ordre=1)

        creneau_a = _creer_creneau(nb_slots=2)
        creneau_b = _creer_creneau(nb_slots=2)
        groupe_a = Groupe.objects.create(nom=f'مجموعة أ - {code}', creneau=creneau_a, statut='actif')
        groupe_b = Groupe.objects.create(nom=f'مجموعة ب - {code}', creneau=creneau_b, statut='actif')

        premiere_option = list(options.values())[0]
        deuxieme_option = list(options.values())[1]
        GroupeCritereValeur.objects.create(groupe=groupe_a, critere=critere, option=premiere_option)
        GroupeCritereValeur.objects.create(groupe=groupe_b, critere=critere, option=deuxieme_option)

        return critere, champ, options, groupe_a, groupe_b

    def test_critere_mode_apprentissage_jamais_prevu_filtre_correctement(self):
        critere, champ, options, groupe_a, groupe_b = self._scenario_critere_jamais_prevu(
            'learning_mode', 'طريقة التعلم المفضلة',
            [('visuel', 'بصري'), ('audio', 'سمعي'), ('interactif', 'تفاعلي')],
        )
        resultat = groupes_compatibles({critere: options['visuel']})
        self.assertEqual(list(resultat), [groupe_a])

        # Warning de couverture : 2 groupes actifs au total (voir setUp global,
        # aucun autre groupe créé dans cette méthode), tous les 2 configurés ici.
        couverture = couverture_critere(critere)
        self.assertEqual(couverture['configures'], 2)

    def test_critere_langue_preferee_jamais_prevu_prouve_que_ce_nest_pas_un_cas_special(self):
        """Même scénario, critère totalement différent — AUCUN code de
        groupes_compatibles/couverture_critere/inscrire_eleve ne mentionne
        'learning_mode' NI 'langue' : la généricité tient sur les 3 backends
        fixes de Critere, jamais sur un nom de critère métier."""
        critere, champ, options, groupe_a, groupe_b = self._scenario_critere_jamais_prevu(
            'langue_preferee', 'اللغة المفضلة',
            [('ar', 'العربية'), ('fr', 'الفرنسية'), ('en', 'الإنجليزية')],
        )
        resultat = groupes_compatibles({critere: options['fr']})
        self.assertEqual(list(resultat), [groupe_b])

    def test_critere_jamais_prevu_integre_dans_inscrire_eleve_de_bout_en_bout(self):
        """Bout en bout complet : le nouveau critère est répondu via
        inscrire_eleve() (comme le ferait le futur wizard), pas seulement testé
        au niveau de groupes_compatibles()."""
        # Isole ce scénario de la config RÉELLE seedée par la migration 0002
        # (Étape 6A) — voir la même précaution dans InscrireEleveTests.setUp.
        ChampInscription.objects.update(est_actif=False)

        # Codes test_ : la base de test contient déjà 'identite'/'programme'/
        # 'type_offre' seedés par registration/migrations/0002_seed_wizard_
        # config.py (Étape 6A) — mêmes codes distincts qu'ailleurs dans ce fichier.
        etape_identite = EtapeInscription.objects.create(code='test_identite', titre='المعلومات الشخصية', ordre=1)
        etape_programme = EtapeInscription.objects.create(code='test_programme', titre='اختيار البرنامج', ordre=2)

        critere = Critere.objects.create(code='objectif', label='الهدف التربوي', backend='eav', filtrable=True, bloquant=False)
        opt_memo = CritereOption.objects.create(critere=critere, code='memorisation', label='الحفظ', ordre=1)
        CritereOption.objects.create(critere=critere, code='revision', label='المراجعة', ordre=2)
        champ_objectif = ChampInscription.objects.create(etape=etape_programme, critere=critere, label='الهدف', obligatoire=True, ordre=1)

        type_offre = _creer_critere(
            'test_type_offre', backend='champ_groupe', champ_modele_groupe='type_capacite',
            filtrable=True, bloquant=True, options=[('groupe', 'جماعي'), ('individuel', 'فردي')],
        )
        champ_type_offre = ChampInscription.objects.create(etape=etape_programme, critere=type_offre, label='نوع الحصة', obligatoire=True, ordre=2)

        creneau = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        groupe = Groupe.objects.create(nom='مجموعة الحفظ', creneau=creneau, statut='actif', type_capacite='groupe', capacite_max=10)
        GroupeCritereValeur.objects.create(groupe=groupe, critere=critere, option=opt_memo)

        TypeAbonnement.objects.create(code='test_abo_groupe', label='شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1)

        reponses = {
            'nom': 'فاطمة الطالبة', 'sexe': 'femme', 'telephone': '+212600000001',
            'date_naissance': '2000-01-01', 'email': 'fatima.test@zidni.test',
            f'champ_{champ_objectif.id}': 'memorisation',
            f'champ_{champ_type_offre.id}': 'groupe',
            'groupe_id': str(groupe.id),
            'abonnement_code': 'test_abo_groupe',
            'accepte_conditions': 'oui',
        }
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertEqual(erreurs, [])
        self.assertEqual(inscription.groupe_choisi, groupe)
        reponse_objectif = inscription.reponses.get(champ=champ_objectif)
        self.assertEqual(reponse_objectif.option.code, 'memorisation')


# ============================================================================
# Étape 6A du chantier — fondations du wizard public : introduction (Étape 0)
# + helpers de session serveur.
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardIntroTests(TestCase):
    def test_intro_affiche_le_contenu_de_presentationinscription(self):
        from .models import get_presentation_inscription

        presentation = get_presentation_inscription()
        presentation.titre = 'أهلاً بك في زدني علماً'
        presentation.intro = 'نص الميثاق التجريبي'
        presentation.bouton_texte = 'هيا بنا'
        presentation.save()

        client = Client()
        reponse = client.get(reverse('wizard_intro'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('أهلاً بك في زدني علماً', html)
        self.assertIn('نص الميثاق التجريبي', html)
        self.assertIn('هيا بنا', html)

    def test_intro_accessible_sans_authentification(self):
        """Page publique — aucun compte requis, contrairement au dashboard."""
        client = Client()
        reponse = client.get(reverse('wizard_intro'))
        self.assertEqual(reponse.status_code, 200)


class WizardSessionHelpersTests(TestCase):
    """registration.utils.wizard_donnees/wizard_maj/wizard_reinitialiser —
    testés directement avec un HttpRequest muni d'une vraie session, sans
    passer par une vue (ce sont des briques réutilisées par TOUTES les vues
    du wizard, Étape 6B et suivantes)."""

    def _requete_avec_session(self):
        from django.test import RequestFactory
        from django.contrib.sessions.middleware import SessionMiddleware

        request = RequestFactory().get('/')
        SessionMiddleware(lambda r: None).process_request(request)
        request.session.save()
        return request

    def test_wizard_donnees_vide_par_defaut(self):
        from .utils import wizard_donnees

        request = self._requete_avec_session()
        self.assertEqual(wizard_donnees(request), {})

    def test_wizard_maj_fusionne_sans_ecraser_les_anciennes_cles(self):
        from .utils import wizard_donnees, wizard_maj

        request = self._requete_avec_session()
        wizard_maj(request, {'nom': 'أحمد', 'sexe': 'homme'})
        wizard_maj(request, {'email': 'ahmed@zidni.test'})

        donnees = wizard_donnees(request)
        self.assertEqual(donnees['nom'], 'أحمد')
        self.assertEqual(donnees['sexe'], 'homme')
        self.assertEqual(donnees['email'], 'ahmed@zidni.test')

    def test_wizard_maj_ecrase_uniquement_les_cles_reecrites(self):
        from .utils import wizard_donnees, wizard_maj

        request = self._requete_avec_session()
        wizard_maj(request, {'sexe': 'homme'})
        wizard_maj(request, {'sexe': 'femme'})
        self.assertEqual(wizard_donnees(request)['sexe'], 'femme')

    def test_wizard_reinitialiser_vide_completement(self):
        from .utils import wizard_donnees, wizard_maj, wizard_reinitialiser

        request = self._requete_avec_session()
        wizard_maj(request, {'nom': 'أحمد'})
        wizard_reinitialiser(request)
        self.assertEqual(wizard_donnees(request), {})


# ============================================================================
# Étape 6A (suite) — wizard_identite (Étape 1 du parcours public).
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardIdentiteTests(TestCase):
    def _reponses_valides(self, **overrides):
        base = {
            'nom': 'سارة بنعلي', 'sexe': 'femme', 'email': 'sara.wizard@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600112233', 'telephone_confirmation': '0600112233',
        }
        base.update(overrides)
        return base

    def test_get_affiche_le_formulaire(self):
        reponse = Client().get(reverse('wizard_identite'))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('المعلومات الشخصية', reponse.content.decode('utf-8'))

    def test_post_valide_enregistre_en_session_et_avance(self):
        client = Client()
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides())
        # fetch_redirect_response=False : wizard_programme est encore un stub
        # (TODO Étape 6B) qui redirige lui-même — seul le SAUT vers cette URL
        # nous intéresse ici, pas ce que la page cible fait pour l'instant.
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)

        from .utils import wizard_donnees
        # Simule une requête suivante avec la même session pour lire l'état.
        session = client.session
        self.assertEqual(session['wizard_inscription']['nom'], 'سارة بنعلي')
        self.assertEqual(session['wizard_inscription']['email'], 'sara.wizard@zidni.test')
        self.assertTrue(session['wizard_inscription']['telephone'])  # assemblé par _construire_et_valider_telephone

    def test_post_incomplet_reaffiche_le_formulaire_avec_erreur(self):
        client = Client()
        reponses = self._reponses_valides()
        del reponses['nom']
        reponse = client.post(reverse('wizard_identite'), reponses)
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('الاسم الكامل إلزامي', reponse.content.decode('utf-8'))
        self.assertNotIn('wizard_inscription', client.session)

    def test_champ_informatif_obligatoire_est_valide(self):
        from .models import ChampInscription, EtapeInscription

        etape = EtapeInscription.objects.get(code='identite')
        champ_pays = ChampInscription.objects.create(
            etape=etape, critere=None, type_champ='texte', label='البلد', obligatoire=True, ordre=10,
        )
        client = Client()

        # Sans le champ "البلد" -> refusé (guillemets échappés en HTML : &quot;).
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides())
        html = reponse.content.decode('utf-8')
        self.assertIn('البلد', html)
        self.assertIn('إلزامي', html)

        # Avec -> accepté et transmis en session.
        reponse2 = client.post(reverse('wizard_identite'), self._reponses_valides(**{
            f'champ_{champ_pays.id}': 'المغرب',
        }))
        self.assertRedirects(reponse2, reverse('wizard_programme'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription'][f'champ_{champ_pays.id}'], 'المغرب')

    def test_telephones_non_correspondants_refuses(self):
        client = Client()
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides(telephone_confirmation='0600999999'))
        self.assertIn('غير متطابقين', reponse.content.decode('utf-8'))  # inscriptions.views.MESSAGE_TELEPHONE_MISMATCH
        self.assertNotIn('wizard_inscription', client.session)


# ============================================================================
# Étape 6B — wizard_programme (Étape 2). Point critique explicitement testé :
# le nombre de séances proposé n'est JAMAIS codé en dur, toujours dérivé des
# groupes réels (registration.views._donnees_filtrage_json_pour_wizard).
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardProgrammeTests(TestCase):
    def setUp(self):
        # Critères seedés par la migration 0002_seed_wizard_config.
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

    def _avancer_a_etape_2(self, client):
        client.post(reverse('wizard_identite'), {
            'nom': 'يوسف العلوي', 'sexe': 'homme', 'email': 'youssef.wizard@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600112233', 'telephone_confirmation': '0600112233',
        })

    def test_get_affiche_les_4_criteres_seedes(self):
        client = Client()
        self._avancer_a_etape_2(client)
        reponse = client.get(reverse('wizard_programme'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        for label in ['البرنامج', 'الرواية', 'نوع الحصة', 'عدد الحصص الأسبوعية']:
            self.assertIn(label, html)

    def test_redirige_vers_identite_si_etape_1_pas_encore_faite(self):
        """Accès direct à /wizard/programme/ sans être passé par l'étape 1 —
        pas de session encore peuplée."""
        reponse = Client().get(reverse('wizard_programme'))
        self.assertRedirects(reponse, reverse('wizard_identite'))

    def test_nouveau_groupe_a_nombre_de_seances_inedit_apparait_sans_code(self):
        """LE test explicitement demandé : un groupe à un nombre de séances
        JAMAIS VU ailleurs dans cette suite (5) doit apparaître dans les
        données de filtrage consommées par le JS de l'étape 2, sans la
        moindre modification de code — la fonction ne connaît aucune valeur
        1/2/3/4 codée en dur, elle ne fait que lire creneau.slots.count()."""
        from registration.views import _donnees_filtrage_json_pour_wizard

        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(creneau, [
            {'jour': j, 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}
            for j in ['lun', 'mar', 'mer', 'jeu', 'ven']
        ])
        Groupe.objects.create(nom='مجموعة 5 حصص أسبوعياً', creneau=creneau, statut='actif')

        donnees = _donnees_filtrage_json_pour_wizard()
        nb_slots_presents = {d['nb_slots'] for d in donnees}
        self.assertIn(5, nb_slots_presents)

        # Bout en bout : la page réellement rendue embarque bien cette valeur
        # dans le JSON consommé par le JS (pas seulement la fonction isolée).
        client = Client()
        self._avancer_a_etape_2(client)
        html = client.get(reverse('wizard_programme')).content.decode('utf-8')
        self.assertIn('"nb_slots": 5', html)

    def test_nb_seances_ne_propose_jamais_une_valeur_absente_des_groupes_reels(self):
        """Symétrique du test précédent : si aucun groupe n'a 7 séances/semaine,
        7 ne doit jamais apparaître dans les données de filtrage."""
        from registration.views import _donnees_filtrage_json_pour_wizard

        donnees = _donnees_filtrage_json_pour_wizard()
        nb_slots_presents = {d['nb_slots'] for d in donnees}
        self.assertNotIn(7, nb_slots_presents)

    def test_soumission_valide_avance_a_letape_groupe(self):
        client = Client()
        self._avancer_a_etape_2(client)
        reponse = client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        self.assertRedirects(reponse, reverse('wizard_groupe'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription'][f'champ_{self.champ_riwaya.id}'], 'hafs')

    def test_champ_obligatoire_manquant_refuse(self):
        client = Client()
        self._avancer_a_etape_2(client)
        reponse = client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            # riwaya manquant
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('إلزامي', reponse.content.decode('utf-8'))

    def test_option_dun_autre_critere_est_rejetee(self):
        """Sécurité (réutilise _reponses_a_creer_pour_champ, Étape 4) : un
        code d'option valide mais appartenant à un AUTRE critère (ex: 'hafs'
        soumis pour le champ 'نوع الحصة') doit être refusé."""
        client = Client()
        self._avancer_a_etape_2(client)
        reponse = client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'hafs',  # code d'un AUTRE critère
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('خيار غير صالح', reponse.content.decode('utf-8'))

    def test_regle_conditionnelle_masque_un_champ(self):
        """Un champ masqué par une RegleCondition satisfaite ne doit ni
        s'afficher, ni être exigé comme obligatoire."""
        from django.contrib.contenttypes.models import ContentType

        champ_special = ChampInscription.objects.create(
            etape=self.champ_riwaya.etape, critere=None, type_champ='texte',
            label='حقل خاص بحفص فقط', obligatoire=True, ordre=99,
        )
        RegleCondition.objects.create(
            cible_content_type=ContentType.objects.get_for_model(ChampInscription),
            cible_object_id=champ_special.id,
            critere_condition=self.critere_riwaya, operateur='different', valeurs=['hafs'],
        )

        client = Client()
        self._avancer_a_etape_2(client)
        # riwaya pas encore répondu -> aucune réponse ne satisfait la règle
        # ('different' exige une réponse NON-vide qui diffère de 'hafs') ->
        # le champ spécial reste visible par défaut (comportement déjà
        # couvert par RegleConditionMasquageTests.test_etape_masquee_si_
        # regle_satisfaite, "aucune réponse -> visible").
        html_avant = client.get(reverse('wizard_programme')).content.decode('utf-8')
        self.assertIn('حقل خاص بحفص فقط', html_avant)

        # Répond riwaya=hafs -> 'different' de 'hafs' est FAUX -> règle NON
        # satisfaite -> champ spécial toujours VISIBLE et obligatoire ->
        # soumettre sans lui doit échouer.
        reponse_hafs = client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        self.assertEqual(reponse_hafs.status_code, 200)
        self.assertIn('حقل خاص بحفص فقط', reponse_hafs.content.decode('utf-8'))

        # Répond riwaya=warsh -> 'different' de 'hafs' est VRAI -> règle
        # satisfaite -> champ spécial MASQUÉ -> soumettre sans lui doit réussir.
        reponse_warsh = client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'warsh',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        self.assertRedirects(reponse_warsh, reverse('wizard_groupe'), fetch_redirect_response=False)


# ============================================================================
# Étape 6C — wizard_groupe (Étape 3). Point critique explicitement testé :
# SAUT SERVEUR obligatoire si Individuel, même en forçant l'URL directement.
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardGroupeTests(TestCase):
    def setUp(self):
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe = Groupe.objects.create(
            nom='مجموعة حفص جماعية للاختبار', creneau=self.creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(
            groupe=self.groupe, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'),
        )
        GroupeCritereValeur.objects.create(
            groupe=self.groupe, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'),
        )

    def _avancer_a_etape_3(self, client, type_offre='groupe'):
        client.post(reverse('wizard_identite'), {
            'nom': 'كريم الفاسي', 'sexe': 'homme', 'email': 'karim.wizard@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600445566', 'telephone_confirmation': '0600445566',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': type_offre,
            f'champ_{self.champ_nb_seances.id}': '2',
        })

    def test_get_affiche_les_groupes_compatibles(self):
        client = Client()
        self._avancer_a_etape_3(client, type_offre='groupe')
        reponse = client.get(reverse('wizard_groupe'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('مجموعة حفص جماعية للاختبار', html)
        self.assertIn('حفص', html)  # badge critère riwaya affiché génériquement

    def test_saut_serveur_si_individuel_meme_en_forcant_lurl(self):
        """LE test explicitement demandé : session avec type_offre='individuel'
        en cours -> un accès DIRECT à l'URL de l'étape 3 (GET comme POST) est
        TOUJOURS redirigé serveur vers l'abonnement, jamais un simple masquage
        visuel côté client. La page groupe n'est même pas rendue (aucun
        groupes_compatibles() inutilement exécuté avec un rendu HTML)."""
        client = Client()
        self._avancer_a_etape_3(client, type_offre='individuel')

        reponse_get = client.get(reverse('wizard_groupe'))
        self.assertRedirects(reponse_get, reverse('wizard_abonnement'), fetch_redirect_response=False)

        # Même verdict en POST (tentative de forcer une soumission malgré tout).
        reponse_post = client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self.assertRedirects(reponse_post, reverse('wizard_abonnement'), fetch_redirect_response=False)
        # Le groupe_id posté malgré l'interdiction n'est JAMAIS retenu en session.
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))

    def test_soumission_valide_avance_a_labonnement(self):
        client = Client()
        self._avancer_a_etape_3(client, type_offre='groupe')
        reponse = client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self.assertRedirects(reponse, reverse('wizard_abonnement'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription']['groupe_id'], str(self.groupe.id))

    def test_groupe_id_incompatible_est_refuse(self):
        """Un groupe qui existe réellement mais ne correspond PAS aux critères
        choisis (ici : riwaya warsh alors que l'élève a choisi hafs) est
        refusé — jamais fait confiance à un ID juste parce qu'il est valide
        en base (Partie 22)."""
        creneau_warsh = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='warsh', age_min=6, age_max=60)
        remplacer_slots_creneau(creneau_warsh, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe_warsh = Groupe.objects.create(
            nom='مجموعة ورش', creneau=creneau_warsh, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(
            groupe=groupe_warsh, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='warsh'),
        )

        client = Client()
        self._avancer_a_etape_3(client, type_offre='groupe')
        reponse = client.post(reverse('wizard_groupe'), {'groupe_id': str(groupe_warsh.id)})
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))

    def test_groupe_complet_est_refuse(self):
        self.groupe.capacite_max = 0
        self.groupe.save()
        client = Client()
        self._avancer_a_etape_3(client, type_offre='groupe')
        reponse = client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))

    def test_acces_direct_sans_session_redirige_a_identite(self):
        reponse = Client().get(reverse('wizard_groupe'))
        self.assertRedirects(reponse, reverse('wizard_identite'))


# ============================================================================
# Étape 6D — wizard_abonnement (Étape 4) + wizard_paiement (Étape 5, affichage
# uniquement — la soumission finale/inscrire_eleve() arrive à l'Étape 6E).
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardAbonnementPaiementTests(TestCase):
    def setUp(self):
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe = Groupe.objects.create(
            nom='مجموعة اختبار الاشتراك', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_wizard_abo_groupe', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )
        self.abo_individuel = TypeAbonnement.objects.create(
            code='test_wizard_abo_individuel', label='فردي شهري', prix=400, type_offre='individuel', cible_age='les_deux', ordre=2,
        )

        from payments.models import MoyenPaiement
        self.moyen = MoyenPaiement.objects.create(code='test_wizard_cih', label='CIH بنك', coordonnees='RIB: 000111222', est_actif=True)

    def _avancer_a_etape_4(self, client, type_offre='groupe', choisir_groupe=True):
        client.post(reverse('wizard_identite'), {
            'nom': 'ليلى بنسعيد', 'sexe': 'femme', 'email': 'laila.wizard@zidni.test',
            'date_naissance': '1995-01-01',
            'indicatif_pays': '212', 'telephone': '0600778899', 'telephone_confirmation': '0600778899',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': type_offre,
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        if type_offre == 'groupe' and choisir_groupe:
            client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})

    def test_abonnement_filtre_par_type_offre_groupe(self):
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        reponse = client.get(reverse('wizard_abonnement'))
        html = reponse.content.decode('utf-8')
        self.assertIn('جماعي شهري', html)
        self.assertNotIn('فردي شهري', html)

    def test_abonnement_filtre_par_type_offre_individuel(self):
        client = Client()
        self._avancer_a_etape_4(client, type_offre='individuel')
        reponse = client.get(reverse('wizard_abonnement'))
        html = reponse.content.decode('utf-8')
        self.assertIn('فردي شهري', html)
        self.assertNotIn('جماعي شهري', html)

    def test_acces_abonnement_avec_groupe_pas_encore_choisi_redirige_a_groupe(self):
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe', choisir_groupe=False)
        reponse = client.get(reverse('wizard_abonnement'))
        self.assertRedirects(reponse, reverse('wizard_groupe'))

    def test_post_abonnement_valide_avance_au_paiement(self):
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        reponse = client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_groupe.code})
        self.assertRedirects(reponse, reverse('wizard_paiement'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription']['abonnement_code'], self.abo_groupe.code)

    def test_post_abonnement_invalide_refuse(self):
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        reponse = client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_individuel.code})
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('abonnement_code', client.session.get('wizard_inscription', {}))

    def test_paiement_affiche_moyens_et_date_limite_configurable(self):
        from inscriptions.models import get_parametres_inscriptions
        from django.utils import timezone

        parametres = get_parametres_inscriptions()
        parametres.delai_paiement_jours = 7
        parametres.save()

        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_groupe.code})
        reponse = client.get(reverse('wizard_paiement'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('CIH بنك', html)
        date_limite_attendue = timezone.localdate() + datetime.timedelta(days=7)
        self.assertIn(date_limite_attendue.strftime('%d-%m-%Y'), html)

    def test_acces_paiement_sans_abonnement_redirige(self):
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        reponse = client.get(reverse('wizard_paiement'))
        self.assertRedirects(reponse, reverse('wizard_abonnement'))


# ============================================================================
# Étape 6E (dernière du wizard) — confirmation finale : revalidation complète
# + inscrire_eleve() + message de bienvenue. Point critique explicitement
# demandé : tentative de contournement (groupe_id incompatible injecté
# directement dans la session, contournant la validation normale de l'étape 3)
# rejetée proprement à LA CONFIRMATION, sans planter, sans rien créer.
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardConfirmationTests(TestCase):
    def setUp(self):
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe = Groupe.objects.create(
            nom='مجموعة اختبار التأكيد', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_confirm_abo_groupe', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )
        self.abo_individuel = TypeAbonnement.objects.create(
            code='test_confirm_abo_individuel', label='فردي شهري', prix=400, type_offre='individuel', cible_age='les_deux', ordre=2,
        )
        from payments.models import MoyenPaiement
        self.moyen = MoyenPaiement.objects.create(code='test_confirm_cih', label='CIH بنك', coordonnees='RIB', est_actif=True)

        from registration.models import get_presentation_inscription
        presentation = get_presentation_inscription()
        presentation.message_bienvenue = 'مرحباً بك معنا!'
        presentation.save()

        from inscriptions.models import get_parametres_inscriptions
        parametres = get_parametres_inscriptions()
        parametres.delai_contact_heures = 24
        parametres.save()

    def _avancer_jusquau_paiement(self, client, email, type_offre='groupe', abonnement_code=None):
        client.post(reverse('wizard_identite'), {
            'nom': 'نور الدين حمزة', 'sexe': 'homme', 'email': email,
            'date_naissance': '1998-01-01',
            'indicatif_pays': '212', 'telephone': '0611223344', 'telephone_confirmation': '0611223344',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': type_offre,
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        if type_offre == 'groupe':
            client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        code = abonnement_code or (self.abo_groupe.code if type_offre == 'groupe' else self.abo_individuel.code)
        client.post(reverse('wizard_abonnement'), {'abonnement_code': code})

    def test_parcours_complet_groupe_cree_linscription_et_affiche_la_confirmation(self):
        client = Client()
        self._avancer_jusquau_paiement(client, 'nourdine.wizard@zidni.test', type_offre='groupe')

        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})
        self.assertRedirects(reponse, reverse('wizard_confirmation'), fetch_redirect_response=False)

        inscription = InscriptionEleve.objects.get(email='nourdine.wizard@zidni.test')
        self.assertEqual(inscription.groupe_choisi, self.groupe)
        self.assertEqual(inscription.abonnement, self.abo_groupe.code)
        self.assertTrue(inscription.reponses.exists())  # ReponseInscription bien créées

        reponse_confirmation = client.get(reverse('wizard_confirmation'))
        self.assertEqual(reponse_confirmation.status_code, 200)
        html = reponse_confirmation.content.decode('utf-8')
        self.assertIn('نور الدين حمزة', html)
        self.assertIn('مرحباً بك معنا!', html)
        self.assertIn('24', html)  # délai de contact configurable, jamais codé en dur

        # Session vidée -> rafraîchir la page de confirmation ne réaffiche rien.
        self.assertNotIn('wizard_inscription', client.session)
        reponse_rafraichie = client.get(reverse('wizard_confirmation'))
        self.assertRedirects(reponse_rafraichie, reverse('wizard_intro'))

    def test_parcours_complet_individuel_saute_le_groupe_jusquau_bout(self):
        client = Client()
        self._avancer_jusquau_paiement(client, 'individuel.wizard@zidni.test', type_offre='individuel')
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})
        self.assertRedirects(reponse, reverse('wizard_confirmation'), fetch_redirect_response=False)

        inscription = InscriptionEleve.objects.get(email='individuel.wizard@zidni.test')
        self.assertIsNone(inscription.groupe_choisi)
        self.assertEqual(inscription.abonnement, self.abo_individuel.code)

    def test_moyen_paiement_invalide_refuse_sans_rien_creer(self):
        client = Client()
        self._avancer_jusquau_paiement(client, 'moyen_invalide@zidni.test', type_offre='groupe')
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': 'code_inexistant'})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email='moyen_invalide@zidni.test').exists())

    def test_groupe_id_devenu_incompatible_entre_etape_3_et_confirmation_est_rejete_a_la_confirmation(self):
        """LE test explicitement demandé : simule une tentative de
        contournement — un groupe_id INCOMPATIBLE (autre riwaya) est injecté
        directement dans la session, EN COURT-CIRCUITANT wizard_groupe (donc
        sans jamais passer par sa propre validation) — pour prouver que la
        REVALIDATION à la confirmation finale (inscrire_eleve, via
        groupes_compatibles_avec_age) est indépendante et suffisante à elle
        seule : aucun plantage, aucune InscriptionEleve créée."""
        creneau_warsh = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='warsh', age_min=6, age_max=60)
        remplacer_slots_creneau(creneau_warsh, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe_incompatible = Groupe.objects.create(
            nom='مجموعة غير متوافقة (تجربة اختراق)', creneau=creneau_warsh, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(
            groupe=groupe_incompatible, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='warsh'),
        )

        client = Client()
        # Avance légitimement jusqu'à l'étape 3 (choisit hafs) SANS jamais
        # poster wizard_groupe -> pas de groupe_id en session pour l'instant.
        client.post(reverse('wizard_identite'), {
            'nom': 'محاولة اختراق', 'sexe': 'homme', 'email': 'tentative.contournement@zidni.test',
            'date_naissance': '1998-01-01',
            'indicatif_pays': '212', 'telephone': '0611998877', 'telephone_confirmation': '0611998877',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',  # a choisi hafs
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })

        # Injection directe en session du groupe INCOMPATIBLE (riwaya warsh),
        # sans jamais passer par la validation normale de wizard_groupe —
        # simule un contournement (session altérée, ou plus réalistement un
        # groupe qui devient incompatible après coup — le mécanisme de
        # protection est rigoureusement le même dans les deux cas).
        session = client.session
        donnees = session.get('wizard_inscription', {})
        donnees['groupe_id'] = str(groupe_incompatible.id)
        session['wizard_inscription'] = donnees
        session.save()

        client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_groupe.code})
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})

        # Refusé proprement : pas de redirection vers la confirmation, pas de
        # plantage (200, pas 500), aucune InscriptionEleve créée.
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email='tentative.contournement@zidni.test').exists())
        self.assertIn('لم تعد متاحة', reponse.content.decode('utf-8'))

    def test_groupe_id_dun_groupe_inexistant_est_rejete_sans_planter(self):
        """Variante : un groupe_id qui ne correspond à AUCUN Groupe réel
        (ex: ID au hasard) — jamais un crash (DoesNotExist non rattrapé)."""
        client = Client()
        self._avancer_jusquau_paiement(client, 'groupe_inexistant@zidni.test', type_offre='groupe')

        session = client.session
        donnees = session.get('wizard_inscription', {})
        donnees['groupe_id'] = '999999999'
        session['wizard_inscription'] = donnees
        session.save()

        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email='groupe_inexistant@zidni.test').exists())

    def test_confirmation_sans_session_prealable_redirige_a_lintro(self):
        reponse = Client().get(reverse('wizard_confirmation'))
        self.assertRedirects(reponse, reverse('wizard_intro'))
