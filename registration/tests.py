import datetime

from django.conf import settings
from django.contrib.contenttypes.models import ContentType
from django.test import TestCase, Client, override_settings
from django.urls import reverse

from accounts.models import Eleve, User
from courses.models import Creneau, Groupe
from courses.utils import remplacer_slots_creneau
from inscriptions.models import GrillePrixAbonnement, InscriptionEleve, TypeAbonnement
from .models import (
    ChampInscription, ConfigurationChampStructurel, Critere, CritereOption, EtapeInscription,
    GroupeCritereValeur, RegleCondition,
)
from .utils import (
    abonnements_disponibles, champs_structurels_actifs, couverture_critere, couverture_grille_prix,
    groupes_avec_place_disponible, groupes_compatibles, groupes_compatibles_avec_age, inscrire_eleve,
    nb_seances_disponibles, nb_slots_reels_systeme, nb_slots_repondu, prix_effectif,
    valider_champ_structurel_libre, champ_est_masque,
)

MOT_DE_PASSE = 'xX!test12345'


# Même précaution que inscriptions.tests/dashboard.tests (STORAGES) : toute
# page qui charge le logo (header ou wizard, via accounts.context_processors.
# logo_context) lève une ValueError sans cet override en environnement de test.
_STORAGES_TEST = {
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
}


def _choisir_categorie_age(client, type_age='adulte'):
    """Étape -1 restaurée le 2026-08-22 (بالغ/طفل) — TOUS les tests qui
    avancent le wizard public depuis wizard_identite doivent d'abord passer
    par cette étape (SAUT SERVEUR sinon, voir wizard_identite). Toutes les
    dates de naissance utilisées dans ce fichier correspondent à 'adulte'
    (défaut ici) — passer type_age='enfant' explicitement pour un scénario
    mineur."""
    return client.post(reverse('wizard_categorie_age'), {'type_age': type_age})


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

        resultat_enfant = groupes_compatibles_avec_age({}, naissance_6_ans, 'homme')
        self.assertIn(groupe_enfants, resultat_enfant)  # 6 ans -> dans [4,10]

        resultat_adulte = groupes_compatibles_avec_age({}, naissance_40_ans, 'homme')
        self.assertNotIn(groupe_enfants, resultat_adulte)  # 40 ans -> hors [4,10]
        self.assertIn(self.groupe_hafs_groupe, resultat_adulte)  # 40 ans -> dans [6,60]


def _remplir_groupe(groupe, nb_eleves, prefixe):
    """Inscrit nb_eleves Eleve réels dans groupe.eleves (M2M) — pour simuler
    un groupe qui a atteint sa capacite_max, sans jamais deviner un raccourci
    (ex: bidouiller directement capacite_max=0, comme le faisait déjà
    test_groupe_complet_est_refuse plus bas pour un autre besoin) : ici on
    veut le cas RÉEL demandé — capacite_max=X avec VRAIMENT X élèves déjà
    inscrits."""
    for i in range(nb_eleves):
        email = f'{prefixe}_{i}@zidni.test'
        user = User.objects.create_user(username=email, email=email, password=MOT_DE_PASSE, role='eleve')
        eleve = Eleve.objects.create(user=user, sexe='homme')
        groupe.eleves.add(eleve)


class GroupesAvecPlaceDisponibleTests(TestCase):
    """Bug signalé le 2026-08-21 : groupes_compatibles()/groupes_compatibles_
    avec_age() ne filtraient QUE sur les critères et l'âge, jamais sur la
    capacité — un groupe déjà plein (capacite_max atteinte) apparaissait donc
    dans la liste affichée à l'étape 3 du wizard, alors même que le POST/la
    confirmation finale le refusaient déjà après coup (voir WizardGroupeTests.
    test_groupe_complet_est_refuse et WizardConfirmationTests plus bas). Tests
    du correctif : groupes_avec_place_disponible()."""

    def setUp(self):
        self.creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(self.creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe_plein = Groupe.objects.create(
            nom='مجموعة ممتلئة تماماً', creneau=self.creneau, statut='actif', capacite_max=3,
        )
        _remplir_groupe(self.groupe_plein, 3, 'plein')  # capacite_max=3, 3 élèves déjà inscrits -> plein

        self.groupe_presque_plein = Groupe.objects.create(
            nom='مجموعة شبه ممتلئة', creneau=self.creneau, statut='actif', capacite_max=3,
        )
        _remplir_groupe(self.groupe_presque_plein, 2, 'presque')  # 2/3 -> encore 1 place

    def test_groupe_plein_exclu_groupe_avec_place_inclus(self):
        resultat = groupes_avec_place_disponible(Groupe.objects.filter(id__in=[self.groupe_plein.id, self.groupe_presque_plein.id]))
        self.assertNotIn(self.groupe_plein, resultat)
        self.assertIn(self.groupe_presque_plein, resultat)

    def test_compose_correctement_avec_groupes_compatibles(self):
        """Le vrai chemin utilisé par les vues (wizard_groupe, ajout manuel) :
        groupes_avec_place_disponible(groupes_compatibles_avec_age(...))."""
        resultat = groupes_avec_place_disponible(
            groupes_compatibles_avec_age({}, datetime.date(2000, 1, 1), 'homme')
        )
        self.assertNotIn(self.groupe_plein, resultat)
        self.assertIn(self.groupe_presque_plein, resultat)

    def test_groupe_devient_plein_apres_1_inscription_de_plus(self):
        """Le dernier siège pris fait bien disparaître le groupe de la liste
        — pas seulement les groupes déjà pleins au moment du fixture."""
        _remplir_groupe(self.groupe_presque_plein, 1, 'dernier')  # 3/3 maintenant
        resultat = groupes_avec_place_disponible(Groupe.objects.filter(id=self.groupe_presque_plein.id))
        self.assertNotIn(self.groupe_presque_plein, resultat)


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

    def test_individuel_sans_groupe_individuel_reel_reste_selectionnable(self):
        """LE bug signalé le 2026-08-21 : en parcours Individuel, le nombre de
        séances est PUREMENT INDICATIF (décision déjà actée — voir
        ReponseInscription.valeur_texte dans registration/models.py) — il ne
        doit JAMAIS être filtré/bloqué par l'absence d'un groupe individuel
        réel déjà configuré pour la combinaison exacte de critères choisie.

        Ici : riwaya=warsh + type_offre=individuel, mais AUCUN groupe
        individuel n'existe pour warsh (seul un groupe GROUPE existe pour
        warsh, à 3 séances) — l'ancien comportement (filtrage strict) aurait
        renvoyé [] et bloqué l'inscription. Le nouveau comportement doit
        renvoyer une liste non vide, dérivée de TOUS les groupes du système."""
        riwaya = _creer_critere('test_riwaya_individuel', options=[('hafs', 'حفص'), ('warsh', 'ورش')])
        type_offre = _creer_critere(
            'test_type_offre_individuel', backend='champ_groupe', champ_modele_groupe='type_capacite',
            options=[('groupe', 'جماعي'), ('individuel', 'فردي')],
        )
        # Seul groupe existant pour warsh : un groupe GROUPE (pas individuel), à 3 séances.
        groupe_warsh = Groupe.objects.create(
            nom='مجموعة ورش جماعية', creneau=_creer_creneau(nb_slots=3), statut='actif', type_capacite='groupe',
        )
        GroupeCritereValeur.objects.create(groupe=groupe_warsh, critere=riwaya, option=riwaya.options.get(code='warsh'))

        # Ancien comportement (filtrage strict, bugué) : liste VIDE — aucun
        # groupe individuel+warsh n'existe. Vérifié explicitement ici pour
        # documenter le contraste avec le comportement corrigé ci-dessous.
        candidats_strict = groupes_compatibles({
            riwaya: riwaya.options.get(code='warsh'),
            type_offre: 'individuel',
        })
        self.assertEqual(list(candidats_strict), [])

        # Comportement corrigé : le nombre de séances reste sélectionnable,
        # dérivé de TOUS les groupes du système (ici, le seul groupe existant
        # à 3 séances, même s'il est de type "groupe" et pas "individuel").
        resultat = nb_seances_disponibles({
            riwaya: riwaya.options.get(code='warsh'),
            type_offre: 'individuel',
        })
        self.assertEqual(resultat, [3])
        self.assertNotEqual(resultat, [])

    def test_groupe_reste_filtre_strictement_meme_apres_le_correctif_individuel(self):
        """Non-régression explicite : le comportement 'groupe' (filtrage
        strict) ne doit PAS être affecté par le correctif Individuel
        ci-dessus — un groupe à 3 séances existe pour warsh, mais si
        type_offre='groupe' est choisi, seul 3 doit apparaître, jamais une
        union globale du système."""
        riwaya = _creer_critere('test_riwaya_groupe_strict', options=[('hafs', 'حفص'), ('warsh', 'ورش')])
        type_offre = _creer_critere(
            'test_type_offre_groupe_strict', backend='champ_groupe', champ_modele_groupe='type_capacite',
            options=[('groupe', 'جماعي'), ('individuel', 'فردي')],
        )
        groupe_warsh = Groupe.objects.create(
            nom='مجموعة ورش جماعية 2', creneau=_creer_creneau(nb_slots=3), statut='actif', type_capacite='groupe',
        )
        GroupeCritereValeur.objects.create(groupe=groupe_warsh, critere=riwaya, option=riwaya.options.get(code='warsh'))
        # Un 2e groupe, hafs, à 4 séances -> ne doit JAMAIS apparaître pour
        # une réponse riwaya=warsh + type_offre=groupe (filtrage strict).
        groupe_hafs = Groupe.objects.create(
            nom='مجموعة حفص جماعية', creneau=_creer_creneau(nb_slots=4), statut='actif', type_capacite='groupe',
        )
        GroupeCritereValeur.objects.create(groupe=groupe_hafs, critere=riwaya, option=riwaya.options.get(code='hafs'))

        resultat = nb_seances_disponibles({
            riwaya: riwaya.options.get(code='warsh'),
            type_offre: 'groupe',
        })
        self.assertEqual(resultat, [3])
        self.assertNotIn(4, resultat)


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


# ============================================================================
# Étape 9 — GrillePrixAbonnement (prix par nb_slots, décidé le 2026-08-21) :
# nb_slots_reels_systeme (factorisation), nb_slots_repondu, prix_effectif
# (repli sur TypeAbonnement.prix) et couverture_grille_prix (warning non
# bloquant, même esprit que CouvertureCritereTests ci-dessus).
# ============================================================================

class NbSlotsReelsSystemeTests(TestCase):
    def test_factorisation_identique_a_la_branche_individuel_de_nb_seances_disponibles(self):
        """Non-régression du refactor (Étape 9) : nb_slots_reels_systeme()
        doit renvoyer EXACTEMENT ce que renvoyait déjà la branche 'individuel'
        de nb_seances_disponibles avant l'extraction — jamais 2 calculs qui
        pourraient diverger."""
        tag = _creer_critere('test_tag_nb_slots_reels', options=[('oui', 'نعم')])
        groupe = Groupe.objects.create(nom='مجموعة نظام', creneau=_creer_creneau(nb_slots=5), statut='actif')
        GroupeCritereValeur.objects.create(groupe=groupe, critere=tag, option=tag.options.get(code='oui'))
        type_offre = _creer_critere(
            'test_type_offre_nb_slots_reels', backend='champ_groupe', champ_modele_groupe='type_capacite',
        )
        self.assertIn(5, nb_slots_reels_systeme())
        self.assertEqual(nb_slots_reels_systeme(), nb_seances_disponibles({type_offre: 'individuel'}))


class NbSlotsReponduTests(TestCase):
    def setUp(self):
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

    def test_none_si_rien_repondu(self):
        self.assertIsNone(nb_slots_repondu({}))

    def test_valeur_entiere_si_deja_repondu(self):
        self.assertEqual(nb_slots_repondu({f'champ_{self.champ_nb_seances.id}': '3'}), 3)

    def test_none_si_valeur_non_entiere(self):
        self.assertIsNone(nb_slots_repondu({f'champ_{self.champ_nb_seances.id}': 'abc'}))


class PrixEffectifTests(TestCase):
    """Le repli sur TypeAbonnement.prix (jamais de blocage silencieux du
    wizard tant qu'une combinaison précise n'a pas de ligne de grille) —
    décision actée explicitement le 2026-08-21."""

    def setUp(self):
        self.abonnement = TypeAbonnement.objects.create(
            code='test_prix_effectif_mensuel', label='شهري تجريبي', prix=80, type_offre='groupe',
        )

    def test_repli_sur_prix_type_abonnement_si_aucune_ligne_de_grille(self):
        self.assertEqual(prix_effectif(self.abonnement, 2), self.abonnement.prix)

    def test_repli_sur_prix_type_abonnement_si_nb_slots_none(self):
        GrillePrixAbonnement.objects.create(type_abonnement=self.abonnement, nb_slots=2, prix=150)
        self.assertEqual(prix_effectif(self.abonnement, None), self.abonnement.prix)

    def test_utilise_le_prix_de_la_grille_si_combinaison_exacte_configuree(self):
        GrillePrixAbonnement.objects.create(type_abonnement=self.abonnement, nb_slots=4, prix=180)
        self.assertEqual(prix_effectif(self.abonnement, 4), 180)
        # nb_slots=2 n'a aucune ligne -> repli, jamais le prix de la ligne nb_slots=4.
        self.assertEqual(prix_effectif(self.abonnement, 2), self.abonnement.prix)

    def test_ligne_desactivee_ignoree_repli_sur_type_abonnement(self):
        GrillePrixAbonnement.objects.create(type_abonnement=self.abonnement, nb_slots=3, prix=999, est_actif=False)
        self.assertEqual(prix_effectif(self.abonnement, 3), self.abonnement.prix)


class AbonnementsDisponiblesCibleAgeTests(TestCase):
    """Correction 7 (2026-08-22, suite au test local) : signalé "un seul
    abonnement apparaît pour Individuel + une tranche d'âge donnée" —
    reproduit ici pour vérifier s'il s'agit d'un vrai bug de filtrage ou de
    données de test incomplètes (cible_age non 'les_deux' sur certaines
    lignes). Conclusion : PAS un bug — abonnements_disponibles() filtre
    volontairement sur cible_age (voir sa docstring), donc 2 TypeAbonnement
    Individuel de durées différentes mais de cible_age DIFFÉRENTE
    ('adulte' vs 'enfant', au lieu de 'les_deux') ne peuvent normalement
    JAMAIS apparaître tous les deux pour une même tranche d'âge — c'est
    exactement le comportement voulu (restreindre une offre à une tranche),
    pas une régression. Ce test protège ce comportement intentionnel."""

    def test_cible_age_specifique_exclut_lautre_tranche(self):
        # assertIn/assertNotIn plutôt qu'une égalité de liste stricte : les 4
        # TypeAbonnement seedés (0004_seed_types_abonnement, cible_age=
        # 'les_deux' par défaut) sont aussi présents en base de test et
        # apparaîtraient légitimement dans les 2 résultats — pas pertinent
        # pour ce que ce test vérifie (l'EXCLUSION mutuelle des 2 lignes
        # ci-dessous, chacune restreinte à une seule tranche d'âge).
        abo_adulte = TypeAbonnement.objects.create(
            code='test_cible_adulte', label='شهر', prix=400, type_offre='individuel', cible_age='adulte',
        )
        abo_enfant = TypeAbonnement.objects.create(
            code='test_cible_enfant', label='3 أشهر', prix=500, type_offre='individuel', cible_age='enfant',
        )
        resultat_adulte = abonnements_disponibles('individuel', 'adulte')
        resultat_enfant = abonnements_disponibles('individuel', 'enfant')
        self.assertIn(abo_adulte, resultat_adulte)
        self.assertNotIn(abo_adulte, resultat_enfant)
        self.assertIn(abo_enfant, resultat_enfant)
        self.assertNotIn(abo_enfant, resultat_adulte)

    def test_les_deux_apparait_pour_nimporte_quelle_tranche(self):
        abo = TypeAbonnement.objects.create(
            code='test_cible_les_deux', label='شهر', prix=400, type_offre='individuel', cible_age='les_deux',
        )
        self.assertIn(abo, abonnements_disponibles('individuel', 'adulte'))
        self.assertIn(abo, abonnements_disponibles('individuel', 'enfant'))


class TypeAbonnementDureeAfficheeTests(TestCase):
    """Correction 5 (2026-08-22, chantier grille de prix) : `duree` est un
    champ à part de `label`, jamais dérivé par découpage de texte en code —
    duree_affichee() retombe simplement sur `label` en entier si `duree`
    n'est pas renseignée."""

    def test_duree_renseignee_est_utilisee(self):
        abo = TypeAbonnement.objects.create(code='test_duree_1', label='جماعي - شهر', duree='شهر', prix=80)
        self.assertEqual(abo.duree_affichee, 'شهر')

    def test_duree_vide_retombe_sur_le_label_complet(self):
        abo = TypeAbonnement.objects.create(code='test_duree_2', label='جماعي - شهر', prix=80)
        self.assertEqual(abo.duree_affichee, 'جماعي - شهر')


class TypeAbonnementLabelNettoyeTests(TestCase):
    """Correction 4 (2026-08-22, suite au test local de la page مدير) :
    `label` ne doit plus répéter le type d'offre (جماعي/فردي) — c'est la
    DONNÉE elle-même qui devait être nettoyée (migration 0025), pas
    seulement l'affichage (déjà réglé par `duree`, correction 5 du cycle
    précédent). Vérifié sur les 4 codes seedés réellement en base, pas sur
    un objet recréé dans le test (la migration ne s'exécute pas à chaque
    test, seulement une fois pour de vrai — ce test vérifie donc l'état
    réel après migration, sur toutes les bases où elle tourne, y compris
    en production)."""

    def test_labels_seedes_ne_contiennent_plus_le_prefixe_type_offre(self):
        for code in ('groupe_1mois', 'groupe_3mois', 'individuel_1mois', 'individuel_3mois'):
            abo = TypeAbonnement.objects.get(code=code)
            self.assertFalse(abo.label.startswith('جماعي - '), f'{code}: {abo.label!r}')
            self.assertFalse(abo.label.startswith('فردي - '), f'{code}: {abo.label!r}')

    def test_str_conserve_le_type_offre_malgre_le_label_nettoye(self):
        """__str__ (utilisé notamment par l'admin Django natif,
        inscriptions.admin) doit continuer à distinguer جماعي/فردي même si
        `label` seul ne le porte plus."""
        abo = TypeAbonnement.objects.get(code='groupe_1mois')
        self.assertIn('جماعي', str(abo))
        abo_individuel = TypeAbonnement.objects.get(code='individuel_1mois')
        self.assertIn('فردي', str(abo_individuel))


class CouvertureGrillePrixTests(TestCase):
    """Base de calcul changée le 2026-08-22 : plage_nb_slots_grille_prix()
    (fixe, 1..10) au lieu de nb_slots_reels_systeme() (groupes réels) —
    AUCUN vrai groupe créé dans ces tests, volontairement, preuve que la
    couverture ne dépend plus d'aucun groupe existant."""

    def test_total_configures_et_manquants(self):
        abonnement = TypeAbonnement.objects.create(
            code='test_couverture_grille', label='اختبار تغطية', prix=100, type_offre='groupe',
        )
        # Configure seulement nb_slots=5, parmi la plage fixe 1..10.
        GrillePrixAbonnement.objects.create(type_abonnement=abonnement, nb_slots=5, prix=250)

        couverture = couverture_grille_prix(abonnement)
        self.assertEqual(couverture['total'], 10)
        self.assertEqual(couverture['configures'], 1)
        self.assertNotIn(5, couverture['nb_slots_manquants'])
        for v in range(1, 11):
            if v != 5:
                self.assertIn(v, couverture['nb_slots_manquants'])

    def test_zero_ligne_configuree(self):
        abonnement = TypeAbonnement.objects.create(
            code='test_couverture_grille_vide', label='اختبار فارغ', prix=100, type_offre='groupe',
        )
        couverture = couverture_grille_prix(abonnement)
        self.assertEqual(couverture['configures'], 0)
        self.assertEqual(couverture['nb_slots_manquants'], list(range(1, 11)))

    def test_ligne_desactivee_compte_comme_non_configuree(self):
        abonnement = TypeAbonnement.objects.create(
            code='test_couverture_grille_off', label='اختبار معطل', prix=100, type_offre='groupe',
        )
        GrillePrixAbonnement.objects.create(type_abonnement=abonnement, nb_slots=4, prix=300, est_actif=False)
        couverture = couverture_grille_prix(abonnement)
        self.assertEqual(couverture['configures'], 0)
        self.assertIn(4, couverture['nb_slots_manquants'])


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

    def test_sans_groupe_accepte_seulement_si_aucun_groupe_ne_correspond_vraiment(self):
        """Défense en profondeur PROPRE à inscrire_eleve (chantier du
        2026-08-22, indépendante du garde-fou déjà côté vue wizard_groupe) :
        un 'demande_non_satisfaite_id' posté ne suffit JAMAIS à lui seul —
        revérifié ici qu'aucun groupe ne correspond réellement à la
        combinaison exacte avant d'accepter groupe_choisi=None."""
        reponses = self._reponses_de_base(demande_non_satisfaite_id='999')
        del reponses['groupe_id']
        # self.groupe correspond réellement (setUp) -> refusé malgré le flag.
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertIsNone(inscription)
        self.assertTrue(any('يرجى اختيار مجموعة' in e for e in erreurs))

    def test_sans_groupe_accepte_si_vraiment_aucun_groupe_ne_correspond(self):
        reponses = self._reponses_de_base(
            demande_non_satisfaite_id='999',
            **{f"champ_{self.config['champ_nb_seances'].id}": '77'},  # jamais réel
        )
        del reponses['groupe_id']
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertEqual(erreurs, [])
        self.assertIsNone(inscription.groupe_choisi)


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
# Chantier du 2026-08-23 (Partie 3A, "extension du moteur générique à l'étape
# Identité") — un ChampInscription AVEC critère attaché à l'étape RÉELLE
# 'identite' (pas seulement critere=NULL comme avant cette correction) doit
# fonctionner EXACTEMENT comme un champ attaché à 'programme' : affiché au
# vrai wizard public, réponse enregistrée, groupes filtrés en conséquence —
# à la fois côté public ET côté admin_eleve_ajouter_manuel. "لغة التواصل
# المفضلة" (préférence de langue de communication) : critère JAMAIS
# rencontré ailleurs dans ce fichier, choisi pour prouver que ce n'est pas
# un cas particulier câblé en dur (même esprit que RegistrationGenericiteTests
# ci-dessus, appliqué cette fois à l'étape Identité plutôt que Programme).
# ============================================================================
class ChampAvecCritereSurEtapeIdentiteTests(TestCase):
    def setUp(self):
        self.etape_identite = EtapeInscription.objects.get(code='identite')
        self.critere_langue = Critere.objects.create(
            code='langue_tawasul', label='لغة التواصل المفضلة', backend='eav',
            filtrable=True, bloquant=False, ordre=99,
        )
        self.opt_ar = CritereOption.objects.create(critere=self.critere_langue, code='ar', label='العربية', ordre=1)
        self.opt_fr = CritereOption.objects.create(critere=self.critere_langue, code='fr', label='الفرنسية', ordre=2)
        # Attaché à l'étape IDENTITÉ (pas 'programme') — c'est précisément
        # ce que le trou identifié par l'audit du 2026-08-23 rendait
        # jusqu'ici invisible au wizard public, malgré une création admin
        # sans erreur. Équivalent strict de ce que ferait le مدير depuis
        # /dashboard/admin/etapes-inscription/<id>/champs/ajouter/ (voir
        # RegistrationGenericiteTests._scenario_critere_jamais_prevu pour
        # la même convention ORM-direct-équivaut-au-dashboard).
        self.champ_langue = ChampInscription.objects.create(
            etape=self.etape_identite, critere=self.critere_langue,
            label='لغة التواصل المفضلة', obligatoire=True, ordre=99,
        )

        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.creneau = _creer_creneau(nb_slots=2, age_min=6, age_max=60)
        self.groupe_arabophone = Groupe.objects.create(
            nom='مجموعة تواصل بالعربية', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        self.groupe_francophone = Groupe.objects.create(
            nom='مجموعة تواصل بالفرنسية', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        for groupe, option in [(self.groupe_arabophone, self.opt_ar), (self.groupe_francophone, self.opt_fr)]:
            GroupeCritereValeur.objects.create(groupe=groupe, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
            GroupeCritereValeur.objects.create(groupe=groupe, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))
            GroupeCritereValeur.objects.create(groupe=groupe, critere=self.critere_langue, option=option)

        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_langue_abo', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )

    # ---- Côté wizard public ----

    def test_apparait_sur_la_vraie_page_publique_wizard_identite(self):
        client = Client()
        _choisir_categorie_age(client)
        reponse = client.get(reverse('wizard_identite'))
        html = reponse.content.decode('utf-8')
        self.assertIn('لغة التواصل المفضلة', html)
        self.assertIn('الفرنسية', html)

    def test_obligatoire_bloque_la_progression_si_non_repondu(self):
        client = Client()
        _choisir_categorie_age(client)
        reponse = client.post(reverse('wizard_identite'), {
            'nom': 'يوسف بلقاسم', 'sexe': 'homme', 'email': 'test_langue_manquante@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0611334455', 'telephone_confirmation': '0611334455',
            # champ_<id> de langue_tawasul volontairement absent.
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('لغة التواصل المفضلة', reponse.content.decode('utf-8'))
        self.assertIn('إلزامي', reponse.content.decode('utf-8'))

    def test_filtre_les_groupes_bout_en_bout_wizard_public(self):
        """LE test de généricité demandé : répond 'fr' à un critère attaché à
        l'étape IDENTITÉ (jamais 'programme') et prouve qu'il filtre bien les
        groupes à l'étape suivante — exactement comme Riwaya/Programme."""
        client = Client()
        _choisir_categorie_age(client)
        reponse_identite = client.post(reverse('wizard_identite'), {
            'nom': 'سارة الحسني', 'sexe': 'femme', 'email': 'test_langue_fr@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0611778899', 'telephone_confirmation': '0611778899',
            f'champ_{self.champ_langue.id}': 'fr',
        })
        self.assertRedirects(reponse_identite, reverse('wizard_programme'), fetch_redirect_response=False)
        # La réponse est bien accumulée en session (comme n'importe quel
        # champ_<id> répondu à 'programme' — même mécanisme, pas un 2e format).
        self.assertEqual(client.session['wizard_inscription'][f'champ_{self.champ_langue.id}'], 'fr')

        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        reponse_groupe = client.get(reverse('wizard_groupe'))
        ids_proposes = set(reponse_groupe.context['groupes'].values_list('id', flat=True))
        self.assertEqual(ids_proposes, {self.groupe_francophone.id})
        self.assertNotIn(self.groupe_arabophone.id, ids_proposes)

    # ---- Côté ajout manuel admin ----

    def test_fonctionne_aussi_cote_admin_ajouter_manuel(self):
        """MÊME critère, MÊME étape, MÊME filtrage — via admin_eleve_ajouter_
        manuel (déjà générique par étape avant cette correction, voir l'audit
        du 2026-08-23 : evaluer_champs_actifs() ne filtre jamais par étape).
        Vérifie qu'aucune divergence n'existe entre les 2 portes d'entrée."""
        admin = User.objects.create_user(
            username='admin_test_langue_identite@zidni.test', email='admin_test_langue_identite@zidni.test',
            password='xX!test12345', role='admin', doit_changer_mot_de_passe=False,
        )
        client = Client()
        client.force_login(admin)

        reponse_round1 = client.post(reverse('admin_eleve_ajouter_manuel'), {
            'round_form': 'identite',
            'nom': 'كريم التازي', 'sexe': 'homme', 'email': 'test_langue_admin@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0611998877', 'telephone_confirmation': '0611998877',
            f'champ_{self.champ_langue.id}': 'fr',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        self.assertEqual(reponse_round1.status_code, 200)
        self.assertEqual(reponse_round1.context['round_form'], 'confirmation')
        ids_proposes = set(reponse_round1.context['groupes'].values_list('id', flat=True))
        self.assertEqual(ids_proposes, {self.groupe_francophone.id})

        reponse_finale = client.post(reverse('admin_eleve_ajouter_manuel'), {
            'round_form': 'confirmation',
            'nom': 'كريم التازي', 'sexe': 'homme', 'email': 'test_langue_admin@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0611998877', 'telephone_confirmation': '0611998877',
            f'champ_{self.champ_langue.id}': 'fr',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
            'groupe_id': str(self.groupe_francophone.id),
            'abonnement_code': self.abo_groupe.code,
        })
        inscription = InscriptionEleve.objects.get(email='test_langue_admin@zidni.test')
        self.assertRedirects(reponse_finale, reverse('admin_inscription_eleve_detail', args=[inscription.id]))
        self.assertEqual(inscription.groupe_choisi_id, self.groupe_francophone.id)
        reponse_langue = inscription.reponses.get(champ=self.champ_langue)
        self.assertEqual(reponse_langue.option.code, 'fr')


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
        _choisir_categorie_age(client)  # Étape -1 (2026-08-22) : sinon SAUT SERVEUR vers wizard_categorie_age
        reponse = client.get(reverse('wizard_intro'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('أهلاً بك في زدني علماً', html)
        self.assertIn('نص الميثاق التجريبي', html)
        self.assertIn('هيا بنا', html)

    def test_intro_accessible_sans_authentification(self):
        """Page publique — aucun compte requis, contrairement au dashboard."""
        client = Client()
        _choisir_categorie_age(client)  # Étape -1 (2026-08-22) : sinon SAUT SERVEUR vers wizard_categorie_age
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
# Chantier du 2026-08-22 — Étape -1 restaurée : choix بالغ/طفل EN TOUT DÉBUT
# de parcours (comme dans l'ancien système, inscriptions.views.
# inscription_eleve_choix). Réutilise TEL QUEL les mécanismes déjà existants
# (ParametresInscriptions.ouverte_eleve_*, _reponse_categorie_fermee,
# MESSAGE_AGE_NE_CORRESPOND_PAS) — jamais une 2e source de vérité sur l'âge.
# ============================================================================
@override_settings(STORAGES=_STORAGES_TEST)
class WizardCategorieAgeTests(TestCase):
    def test_get_affiche_le_formulaire(self):
        reponse = Client().get(reverse('wizard_categorie_age'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        self.assertIn('طفل', html)
        self.assertIn('بالغ', html)

    def test_choix_valide_avance_vers_intro(self):
        client = Client()
        reponse = client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        self.assertRedirects(reponse, reverse('wizard_intro'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription']['type_age_choisi'], 'adulte')

    def test_choix_invalide_refuse_sans_rien_enregistrer(self):
        client = Client()
        reponse = client.post(reverse('wizard_categorie_age'), {'type_age': 'autre_chose'})
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('wizard_inscription', client.session)

    def test_categorie_fermee_bloque_immediatement_meme_reutilisation_du_mecanisme_existant(self):
        from inscriptions.models import get_parametres_inscriptions

        parametres = get_parametres_inscriptions()
        parametres.ouverte_eleve_adulte = False
        parametres.save()

        client = Client()
        reponse = client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('wizard_inscription', client.session)
        # Même écran que l'ancien système (inscriptions/inscription_fermee.html).
        self.assertIn('التسجيل مغلق حالياً لفئة الطلاب البالغون', reponse.content.decode('utf-8'))

    def test_wizard_intro_saute_vers_categorie_age_si_pas_encore_choisi(self):
        reponse = Client().get(reverse('wizard_intro'))
        self.assertRedirects(reponse, reverse('wizard_categorie_age'))

    def test_wizard_identite_saute_vers_categorie_age_si_pas_encore_choisi(self):
        reponse = Client().get(reverse('wizard_identite'))
        self.assertRedirects(reponse, reverse('wizard_categorie_age'))

    def test_date_naissance_incoherente_avec_le_choix_precoce_est_rejetee(self):
        """LE test explicitement demandé : le choix précoce بالغ/طفل est
        REVÉRIFIÉ contre la VRAIE date de naissance à l'étape 1 — jamais fait
        confiance seul, même principe que l'ancien inscription_eleve_
        formulaire (categorie_reelle != type_age -> erreur)."""
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        reponse = client.post(reverse('wizard_identite'), {
            'nom': 'اختبار التناقض', 'sexe': 'homme', 'email': 'incoherence.age@zidni.test',
            'date_naissance': '2015-01-01',  # ~11 ans en 2026 -> enfant, pas adulte
            'indicatif_pays': '212', 'telephone': '0600112244', 'telephone_confirmation': '0600112244',
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('يبدو أنك طفل', reponse.content.decode('utf-8'))
        # type_age_choisi reste seul en session (posé par wizard_categorie_age
        # juste avant) — nom/sexe/... de CETTE soumission rejetée, eux, jamais.
        self.assertNotIn('nom', client.session.get('wizard_inscription', {}))

    def test_date_naissance_coherente_avec_le_choix_precoce_reussit(self):
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'enfant'})
        reponse = client.post(reverse('wizard_identite'), {
            'nom': 'اختبار التطابق', 'nom_parent': 'ولي أمر الاختبار',
            'sexe': 'homme', 'email': 'coherence.age@zidni.test',
            'date_naissance': '2015-01-01',
            'indicatif_pays': '212', 'telephone': '0600112255', 'telephone_confirmation': '0600112255',
        })
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)

    def test_nom_parent_absent_si_adulte_choisi(self):
        """Demande du 2026-08-22 : le champ dépend du choix déjà fait à
        l'étape -1, jamais une mention conditionnelle vague."""
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        html = client.get(reverse('wizard_identite')).content.decode('utf-8')
        self.assertNotIn('name="nom_parent"', html)
        # 'ولي الأمر' seul apparaît AUSSI dans le label du champ job_actuel
        # ("العمل الحالي (أو عمل ولي الأمر إن كان المسجَّل قاصراً)"), sans
        # rapport avec nom_parent -> on vérifie le label PROPRE à nom_parent,
        # jamais la sous-chaîne générique.
        self.assertNotIn('اسم ولي الأمر', html)

    def test_nom_parent_obligatoire_sans_mention_si_enfant_choisi(self):
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'enfant'})
        html = client.get(reverse('wizard_identite')).content.decode('utf-8')
        self.assertIn('name="nom_parent"', html)
        self.assertIn('اسم ولي الأمر', html)
        # L'ancien label vague ("اسم ولي الأمر (إن كان المسجَّل قاصراً)",
        # seedé en 0004) ne doit plus apparaître pour nom_parent — on vérifie
        # la chaîne EXACTE de cet ancien label, pas la sous-chaîne générique
        # "إن كان المسجَّل قاصراً" qui appartient aussi (légitimement) au
        # label du champ job_actuel, non concerné par cette demande.
        self.assertNotIn('اسم ولي الأمر (إن كان المسجَّل قاصراً)', html)

    def test_nom_parent_obligatoire_bloque_si_enfant_et_vide(self):
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'enfant'})
        reponse = client.post(reverse('wizard_identite'), {
            'nom': 'اختبار ولي الأمر', 'sexe': 'homme', 'email': 'wali.amr.manquant@zidni.test',
            'date_naissance': '2015-01-01', 'nom_parent': '',
            'indicatif_pays': '212', 'telephone': '0600112266', 'telephone_confirmation': '0600112266',
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('إلزامي', reponse.content.decode('utf-8'))
        self.assertNotIn('nom', client.session.get('wizard_inscription', {}))  # rien enregistré, validation refusée

    def test_nom_parent_ignore_meme_si_poste_pour_un_adulte(self):
        """Sécurité serveur : même si nom_parent est posté malicieusement
        pour un adulte, il n'est jamais lu ni stocké."""
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        reponse = client.post(reverse('wizard_identite'), {
            'nom': 'اختبار تجاهل', 'sexe': 'homme', 'email': 'ignore.wali@zidni.test',
            'date_naissance': '2000-01-01', 'nom_parent': 'محاولة تمرير',
            'indicatif_pays': '212', 'telephone': '0600112277', 'telephone_confirmation': '0600112277',
        })
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)
        self.assertNotIn('nom_parent', client.session['wizard_inscription'])

    def test_job_actuel_cible_eleve_si_adulte_choisi(self):
        """Même incohérence que nom_parent (demande du 2026-08-22) : le label
        seedé ("العمل الحالي (أو عمل ولي الأمر إن كان المسجَّل قاصراً)") est
        remplacé par un label ciblé selon le choix بالغ/طفل déjà fait."""
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'adulte'})
        html = client.get(reverse('wizard_identite')).content.decode('utf-8')
        self.assertIn('العمل الحالي', html)
        self.assertNotIn('عمل ولي الأمر', html)
        self.assertNotIn('العمل الحالي (أو عمل ولي الأمر إن كان المسجَّل قاصراً)', html)

    def test_job_actuel_cible_wali_al_amr_si_enfant_choisi(self):
        client = Client()
        client.post(reverse('wizard_categorie_age'), {'type_age': 'enfant'})
        html = client.get(reverse('wizard_identite')).content.decode('utf-8')
        self.assertIn('عمل ولي الأمر', html)
        self.assertNotIn('العمل الحالي (أو عمل ولي الأمر إن كان المسجَّل قاصراً)', html)


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

    def test_get_sans_categorie_age_choisie_redirige(self):
        """SAUT SERVEUR (chantier du 2026-08-22, Étape -1 restaurée) : accès
        direct sans être passé par wizard_categorie_age."""
        reponse = Client().get(reverse('wizard_identite'))
        self.assertRedirects(reponse, reverse('wizard_categorie_age'))

    def test_get_affiche_le_formulaire(self):
        client = Client()
        _choisir_categorie_age(client)
        reponse = client.get(reverse('wizard_identite'))
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('المعلومات الشخصية', reponse.content.decode('utf-8'))

    def test_post_valide_enregistre_en_session_et_avance(self):
        client = Client()
        _choisir_categorie_age(client)
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
        _choisir_categorie_age(client)
        reponses = self._reponses_valides()
        del reponses['nom']
        reponse = client.post(reverse('wizard_identite'), reponses)
        self.assertEqual(reponse.status_code, 200)
        # Message générique depuis le 2026-08-22 (ConfigurationChampStructurel,
        # valider_champ_structurel_libre) : "&quot;{label}&quot; إلزامي."
        # remplace l'ancien message codé en dur spécifique à 'nom' — même
        # format que TOUS les champs structurels génériques désormais.
        html = reponse.content.decode('utf-8')
        self.assertIn('الاسم الكامل', html)
        self.assertIn('إلزامي', html)
        self.assertNotIn('nom', client.session.get('wizard_inscription', {}))

    def test_champ_informatif_obligatoire_est_valide(self):
        from .models import ChampInscription, EtapeInscription

        etape = EtapeInscription.objects.get(code='identite')
        champ_pays = ChampInscription.objects.create(
            etape=etape, critere=None, type_champ='texte', label='البلد', obligatoire=True, ordre=10,
        )
        client = Client()
        _choisir_categorie_age(client)

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
        _choisir_categorie_age(client)
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides(telephone_confirmation='0600999999'))
        self.assertIn('غير متطابقين', reponse.content.decode('utf-8'))  # inscriptions.views.MESSAGE_TELEPHONE_MISMATCH
        self.assertNotIn('nom', client.session.get('wizard_inscription', {}))


# ============================================================================
# Étape 6B — wizard_programme (Étape 2). Point critique explicitement testé :
# le nombre de séances proposé n'est JAMAIS codé en dur, toujours dérivé des
# groupes réels (registration.utils.donnees_filtrage_json_pour_wizard).
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
        _choisir_categorie_age(client)
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

    def test_html_expose_les_attributs_js_necessaires_au_correctif_individuel(self):
        """La logique du correctif (bugs A+B du 2026-08-21) vit côté JS —
        aucun moteur JS dans les tests Django (pas de Selenium/Playwright dans
        ce projet, jamais eu jusqu'ici) — donc on vérifie ce que le serveur
        peut garantir : les data-* dont le JS a besoin sont bien présents dans
        le HTML rendu, et le champ nombre de séances démarre caché (Bug B)."""
        client = Client()
        self._avancer_a_etape_2(client)
        html = client.get(reverse('wizard_programme')).content.decode('utf-8')
        self.assertIn('data-backend="champ_groupe"', html)  # identifie type_offre génériquement
        self.assertIn('id="nb_seances_wrapper" style="display:none;"', html)  # Bug B : caché par défaut
        self.assertIn('data-obligatoire="1"', html)

    def test_redirige_vers_identite_si_etape_1_pas_encore_faite(self):
        """Accès direct à /wizard/programme/ sans être passé par l'étape 1 —
        pas de session encore peuplée. fetch_redirect_response=False : sans
        catégorie d'âge choisie non plus (chantier du 2026-08-22), la cible
        elle-même redirige encore vers wizard_categorie_age — seul le
        PREMIER saut nous intéresse ici."""
        reponse = Client().get(reverse('wizard_programme'))
        self.assertRedirects(reponse, reverse('wizard_identite'), fetch_redirect_response=False)

    def test_nombre_de_seances_libre_meme_sans_aucun_groupe_reel_a_ce_nombre(self):
        """Chantier du 2026-08-22 ("liberté totale du nombre de séances") :
        99 séances/semaine n'existe RÉELLEMENT nulle part dans le système —
        avant ce chantier, seules les valeurs calculées depuis les groupes
        réels étaient acceptées. Doit désormais être accepté sans erreur,
        pour Groupe comme pour Individuel (plus de distinction)."""
        client = Client()
        self._avancer_a_etape_2(client)
        reponse = client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '99',
        })
        self.assertRedirects(reponse, reverse('wizard_groupe'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription'][f'champ_{self.champ_nb_seances.id}'], '99')

    def test_nombre_de_seances_zero_ou_non_numerique_refuse(self):
        """Liberté totale ne veut pas dire aucune validation : un input libre
        côté client nécessite une vraie validation serveur (avant, seules des
        valeurs déjà calculées/valides pouvaient être postées)."""
        client = Client()
        self._avancer_a_etape_2(client)
        for valeur_invalide in ('0', '-1', 'abc'):
            reponse = client.post(reverse('wizard_programme'), {
                f'champ_{self.champ_programme.id}': 'hifz',
                f'champ_{self.champ_riwaya.id}': 'hafs',
                f'champ_{self.champ_type_offre.id}': 'groupe',
                f'champ_{self.champ_nb_seances.id}': valeur_invalide,
            })
            # Jamais redirigé vers l'étape suivante -> valeur bien rejetée.
            self.assertEqual(reponse.status_code, 200, valeur_invalide)
            self.assertNotIn(
                f'champ_{self.champ_nb_seances.id}', client.session.get('wizard_inscription', {}), valeur_invalide
            )

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
        _choisir_categorie_age(client)
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

    def test_groupe_plein_napparait_pas_du_tout_dans_la_liste_affichee(self):
        """LE bug signalé le 2026-08-21 : contrairement à test_groupe_complet_
        est_refuse ci-dessus (qui vérifie seulement que le POST est refusé),
        ce test vérifie que le groupe COMPLET (capacite_max réellement atteinte
        par de vrais élèves inscrits, pas capacite_max=0) n'apparaît même pas
        dans le HTML de la liste — un visiteur ne doit jamais avoir la
        possibilité de le voir/cliquer dessus en premier lieu."""
        _remplir_groupe(self.groupe, self.groupe.capacite_max, 'wizard_plein')

        client = Client()
        self._avancer_a_etape_3(client, type_offre='groupe')
        reponse = client.get(reverse('wizard_groupe'))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        # Assertion volontairement limitée à CE groupe (pas "la liste est
        # vide") : la base de test contient aussi 23 groupes réels seedés
        # (migration 0002) qui peuvent, selon leur propre configuration,
        # apparaître ou non pour ces mêmes critères — pas l'objet de ce test.
        self.assertNotIn(self.groupe.nom, html)

    def test_acces_direct_sans_session_redirige_a_identite(self):
        reponse = Client().get(reverse('wizard_groupe'))
        self.assertRedirects(reponse, reverse('wizard_identite'), fetch_redirect_response=False)

    def test_continuer_sans_groupe_ignore_si_un_groupe_correspond_vraiment(self):
        """Sécurité serveur (Partie 22, chantier du 2026-08-22) : POSTer
        continuer_sans_groupe=1 alors qu'un groupe correspond RÉELLEMENT à la
        combinaison exacte (self.groupe, ici) doit être ignoré — jamais une
        confiance aveugle dans ce flag posté côté client. aucun_groupe_exact
        est calculé SERVEUR, pas lu depuis le POST."""
        from registration.models import DemandeNonSatisfaite

        client = Client()
        self._avancer_a_etape_3(client, type_offre='groupe')  # self.groupe correspond exactement
        reponse = client.post(reverse('wizard_groupe'), {'continuer_sans_groupe': '1'})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('يرجى اختيار مجموعة', reponse.content.decode('utf-8'))
        self.assertEqual(DemandeNonSatisfaite.objects.count(), 0)
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))


# ============================================================================
# Chantier du 2026-08-23 — "exclusion manuelle d'un groupe" : Groupe.
# cache_du_wizard_public=True exclut un groupe UNIQUEMENT du formulaire
# public (registration.utils.groupes_compatibles/groupes_compatibles_
# avec_age), jamais de l'ajout manuel Directeur/مشرف (voir dashboard.tests.
# GroupeCacheDuWizardPublicCoteAdminTests pour le pendant admin) ni du reste
# du projet (le groupe reste statut='actif' partout ailleurs).
# ============================================================================
class GroupeCacheDuWizardPublicTests(TestCase):
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
        # Groupe CACHÉ — matche PARFAITEMENT tous les critères (programme,
        # riwaya, âge, sexe, nb_seances) : seul cache_du_wizard_public=True
        # doit expliquer son absence des résultats publics.
        self.groupe_cache = Groupe.objects.create(
            nom='مجموعة مخفية يدوياً عن الاستمارة', creneau=self.creneau, statut='actif',
            type_capacite='groupe', capacite_max=10, cache_du_wizard_public=True,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe_cache, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe_cache, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        # Groupe NON caché (cache_du_wizard_public=False, la valeur par
        # défaut) — même créneau/critères, sert de témoin de non-régression.
        self.groupe_visible = Groupe.objects.create(
            nom='مجموعة عادية غير مخفية', creneau=self.creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe_visible, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe_visible, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        from inscriptions.models import TypeAbonnement
        from payments.models import MoyenPaiement
        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_cache_wizard_abo', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )
        self.moyen = MoyenPaiement.objects.create(code='test_cache_wizard_cih', label='CIH بنك', coordonnees='RIB', est_actif=True)

    def _reponses_pour_filtrage(self):
        return {
            self.critere_programme: self.critere_programme.options.get(code='hifz'),
            self.critere_riwaya: self.critere_riwaya.options.get(code='hafs'),
            self.critere_type_offre: 'groupe',
        }

    # ---- Niveau unitaire (appel direct des fonctions) ----

    def test_groupe_cache_jamais_dans_groupes_compatibles(self):
        resultat = groupes_compatibles(self._reponses_pour_filtrage())
        self.assertNotIn(self.groupe_cache, resultat)
        self.assertIn(self.groupe_visible, resultat)

    def test_groupe_cache_jamais_dans_groupes_compatibles_avec_age(self):
        resultat = groupes_compatibles_avec_age(self._reponses_pour_filtrage(), datetime.date(2000, 1, 1), 'homme')
        self.assertNotIn(self.groupe_cache, resultat)
        self.assertIn(self.groupe_visible, resultat)

    def test_non_regression_groupe_non_cache_se_comporte_comme_avant(self):
        """cache_du_wizard_public=False (valeur par défaut) : le comportement
        de groupes_compatibles()/groupes_compatibles_avec_age() est
        RIGOUREUSEMENT identique à avant cette modification — même résultat
        que si le paramètre exclure_caches_wizard_public n'existait pas."""
        self.assertQuerySetEqual(
            groupes_compatibles(self._reponses_pour_filtrage()),
            groupes_compatibles(self._reponses_pour_filtrage(), exclure_caches_wizard_public=False).exclude(id=self.groupe_cache.id),
            ordered=False,
        )
        resultat_age = groupes_compatibles_avec_age(self._reponses_pour_filtrage(), datetime.date(2000, 1, 1), 'homme')
        self.assertEqual(list(resultat_age), [self.groupe_visible])

    # ---- Niveau intégration (vraie vue publique) ----

    def _avancer_a_etape_3(self, client):
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'زائر اختبار الإخفاء', 'sexe': 'homme', 'email': 'cache_wizard_public@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0611556677', 'telephone_confirmation': '0611556677',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })

    def test_groupe_cache_absent_de_la_vraie_page_publique_meme_sil_matche_tout(self):
        client = Client()
        self._avancer_a_etape_3(client)
        reponse = client.get(reverse('wizard_groupe'))
        html = reponse.content.decode('utf-8')
        ids_proposes = set(reponse.context['groupes'].values_list('id', flat=True))
        self.assertNotIn(self.groupe_cache.id, ids_proposes)
        self.assertIn(self.groupe_visible.id, ids_proposes)
        self.assertNotIn('مجموعة مخفية يدوياً عن الاستمارة', html)
        self.assertIn('مجموعة عادية غير مخفية', html)

    # ---- Sécurité anti-contournement (revalidation finale) ----

    def test_groupe_id_cache_force_via_session_est_rejete_a_la_confirmation(self):
        """Même patron que WizardAbonnementPaiementTests.test_groupe_id_
        devenu_incompatible_entre_etape_3_et_confirmation_est_rejete_a_la_
        confirmation : injecte directement en session le groupe CACHÉ
        (jamais proposé par wizard_groupe, donc jamais choisi normalement),
        en court-circuitant sa validation — la revalidation finale
        (inscrire_eleve, cree_par=None -> exclure_caches_wizard_public=True)
        doit rejeter proprement, jamais planter ni créer l'inscription."""
        client = Client()
        self._avancer_a_etape_3(client)

        session = client.session
        donnees = session.get('wizard_inscription', {})
        donnees['groupe_id'] = str(self.groupe_cache.id)
        session['wizard_inscription'] = donnees
        session.save()

        client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_groupe.code})
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})

        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email='cache_wizard_public@zidni.test').exists())
        self.assertIn('لم تعد متاحة', reponse.content.decode('utf-8'))


# ============================================================================
# Correction 8 (2026-08-22) — navigation dynamique : EtapeInscription.ordre/
# est_actif pilote RÉELLEMENT la page suivante visitée par l'élève, plus une
# simple valeur cosmétique. Avant cette correction, seules 2 étapes sur 7
# (identite/programme) existaient en base — les 5 autres (catégorie d'âge,
# groupe, abonnement, paiement, confirmation) étaient de pures vues Python
# 100% codées en dur (bug signalé le 2026-08-22 : la page مدير des étapes
# n'en listait que 2).
# ============================================================================
class EtapeInscriptionVerrouilleeTests(TestCase):
    """5 des 7 étapes ne peuvent jamais être désactivées (EtapeInscription.
    CODES_VERROUILLES) — chacune est un vrai prérequis dur ailleurs dans le
    code, voir EtapeInscription.__doc__ pour le détail par étape."""

    def test_tentative_de_desactivation_est_ignoree_pour_les_etapes_verrouillees(self):
        from registration.models import EtapeInscription

        for code in EtapeInscription.CODES_VERROUILLES:
            etape = EtapeInscription.objects.get(code=code)
            etape.est_actif = False
            etape.save()
            etape.refresh_from_db()
            self.assertTrue(etape.est_actif, f'{code} aurait dû rester active')

    def test_programme_et_groupe_restent_desactivables(self):
        """Les 2 SEULES étapes librement activables/désactivables — preuve
        négative que CODES_VERROUILLES ne verrouille pas tout par excès de
        prudence."""
        from registration.models import EtapeInscription

        for code in ('programme', 'groupe'):
            etape = EtapeInscription.objects.get(code=code)
            etape.est_actif = False
            etape.save()
            etape.refresh_from_db()
            self.assertFalse(etape.est_actif, f'{code} aurait dû pouvoir être désactivée')
            etape.est_actif = True  # remis en état pour ne pas polluer les autres tests
            etape.save()


class EtapeSuivanteResolverTests(TestCase):
    """registration.utils.etape_suivante/etape_est_active/url_etape_suivante
    en isolation — la séquence par défaut (seed) doit correspondre EXACTEMENT
    à l'ancien enchaînement figé, avant toute reconfiguration par le مدير."""

    def test_sequence_par_defaut_identique_a_lancien_enchainement_fige(self):
        from registration.utils import etape_suivante

        self.assertEqual(etape_suivante('categorie_age'), 'identite')
        self.assertEqual(etape_suivante('identite'), 'programme')
        self.assertEqual(etape_suivante('programme'), 'groupe')
        self.assertEqual(etape_suivante('groupe'), 'abonnement')
        self.assertEqual(etape_suivante('abonnement'), 'paiement')
        self.assertEqual(etape_suivante('paiement'), 'confirmation')
        self.assertIsNone(etape_suivante('confirmation'))

    def test_etape_desactivee_est_sautee(self):
        from registration.models import EtapeInscription
        from registration.utils import etape_suivante

        EtapeInscription.objects.filter(code='groupe').update(est_actif=False)
        self.assertEqual(etape_suivante('programme'), 'abonnement')
        self.assertEqual(etape_suivante('groupe'), 'abonnement')

    def test_reordonnancement_change_reellement_la_sequence(self):
        from registration.models import EtapeInscription
        from registration.utils import etape_suivante

        EtapeInscription.objects.filter(code='groupe').update(ordre=10)  # après paiement/confirmation
        self.assertEqual(etape_suivante('programme'), 'abonnement')
        self.assertEqual(etape_suivante('abonnement'), 'paiement')

    def test_etape_custom_du_madir_est_desormais_servie_pas_sautee(self):
        """Chantier du 2026-08-23 (Partie 3B, "étapes repositionnables/
        insérables n'importe où") : une étape créée librement par le مدير
        (code hors des 7 réels, admin_etape_inscription_ajouter) a désormais
        SA PROPRE page (wizard_etape_personnalisee) — comportement CHANGÉ
        délibérément par rapport à l'ancien (transparente/sautée, voir
        historique de ce test) : avant cette correction, `ordre` la
        positionnait bien dans la liste admin mais elle ne s'affichait
        JAMAIS au candidat, trou identifié par l'audit du 2026-08-23."""
        from django.urls import reverse
        from registration.models import EtapeInscription
        from registration.utils import url_etape_suivante

        # 'groupe' repoussé à ordre=10 (même idiome que WizardNavigationDynamique
        # Tests.test_reordonnancement_change_le_parcours_reellement_visite) pour
        # insérer 'test_etape_custom' SANS ambiguïté juste après 'programme'(2) —
        # ordre étant un IntegerField, 2 et 3 n'ont pas de valeur intermédiaire.
        EtapeInscription.objects.filter(code='groupe').update(ordre=10)
        EtapeInscription.objects.create(code='test_etape_custom', titre='مرحلة مخصصة', ordre=3, est_actif=True)
        self.assertEqual(url_etape_suivante('programme'), reverse('wizard_etape_personnalisee', args=['test_etape_custom']))
        self.assertEqual(url_etape_suivante('test_etape_custom'), reverse('wizard_abonnement'))


class WizardNavigationDynamiqueTests(TestCase):
    """Bout en bout (vraies requêtes HTTP, pas juste la fonction resolver en
    isolation) : désactiver/réordonner une étape depuis le dashboard change
    RÉELLEMENT le parcours vécu par l'élève."""

    def setUp(self):
        from registration.models import EtapeInscription

        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)
        self.etape_groupe = EtapeInscription.objects.get(code='groupe')
        self.etape_programme = EtapeInscription.objects.get(code='programme')

    def _identite(self, client):
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'اختبار التنقل', 'sexe': 'homme', 'email': 'nav.dynamique@zidni.test',
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600778899', 'telephone_confirmation': '0600778899',
        })

    def _programme(self, client, type_offre='individuel'):
        return client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': type_offre,
            f'champ_{self.champ_nb_seances.id}': '2',
        })

    def test_etape_groupe_desactivee_saute_meme_pour_un_choix_groupe(self):
        """Contrairement au saut Individuel (déjà existant avant cette
        correction) : ici c'est le choix 'groupe' qui est fait, mais l'étape
        elle-même est désactivée par le مدير — le saut doit quand même avoir
        lieu, ET inscrire_eleve() ne doit jamais bloquer faute de groupe_id
        (voir InscrireEleveNavigationDynamiqueTests ci-dessous)."""
        self.etape_groupe.est_actif = False
        self.etape_groupe.save()

        client = Client()
        self._identite(client)
        reponse = self._programme(client, type_offre='groupe')
        self.assertRedirects(reponse, reverse('wizard_abonnement'), fetch_redirect_response=False)
        # GET direct sur l'URL de l'étape groupe, forcée malgré tout : sautée aussi.
        reponse_get = client.get(reverse('wizard_groupe'))
        self.assertRedirects(reponse_get, reverse('wizard_abonnement'), fetch_redirect_response=False)

    def test_etape_programme_desactivee_saute_directement_vers_groupe(self):
        self.etape_programme.est_actif = False
        self.etape_programme.save()

        client = Client()
        self._identite(client)
        reponse_get = client.get(reverse('wizard_programme'))
        self.assertRedirects(reponse_get, reverse('wizard_groupe'), fetch_redirect_response=False)
        # POST direct forcé malgré tout : sauté aussi, aucune donnée retenue.
        reponse_post = client.post(reverse('wizard_programme'), {f'champ_{self.champ_programme.id}': 'hifz'})
        self.assertRedirects(reponse_post, reverse('wizard_groupe'), fetch_redirect_response=False)
        self.assertNotIn(f'champ_{self.champ_programme.id}', client.session.get('wizard_inscription', {}))

    def test_reordonnancement_change_le_parcours_reellement_visite(self):
        """'groupe' déplacé APRÈS 'paiement'/'confirmation' (ordre=10, au lieu
        de 3) — preuve que le réordonnancement affecte RÉELLEMENT la
        séquence : url_etape_suivante('abonnement') pointe désormais vers
        'paiement' (groupe n'est plus juste après), et 'groupe' lui-même,
        devenu la toute dernière étape active, n'a plus rien après lui."""
        from registration.utils import url_etape_suivante

        self.etape_groupe.ordre = 10  # après paiement(5)/confirmation(6)
        self.etape_groupe.save()
        # Chantier du 2026-08-23 (Partie 3B) : url_etape_suivante() renvoie
        # désormais un CHEMIN déjà résolu (reverse()), plus un simple nom de
        # vue — nécessaire pour pouvoir aussi pointer vers une étape
        # personnalisée (wizard_etape_personnalisee, paramétrée par son
        # code) ; comparé ici à reverse('wizard_X'), jamais au nom brut.
        self.assertEqual(url_etape_suivante('abonnement'), reverse('wizard_paiement'))
        self.assertEqual(url_etape_suivante('paiement'), reverse('wizard_confirmation'))
        # 'groupe' devenu la toute dernière étape active dans l'ordre : plus
        # rien après elle -> repli sur 'wizard_confirmation' (comportement
        # documenté, pas une erreur — un مدير qui réordonne ainsi obtient un
        # parcours cohérent uniquement s'il réordonne aussi les étapes
        # voisines en conséquence, responsabilité assumée comme partout
        # ailleurs dans ce chantier).
        self.assertEqual(url_etape_suivante('groupe'), reverse('wizard_confirmation'))


class InscrireEleveNavigationDynamiqueTests(TestCase):
    """inscrire_eleve() ne doit jamais bloquer une inscription 'groupe' faute
    de groupe_id quand l'étape 'groupe' a été désactivée par le مدير — même
    repli que l'Individuel (groupe_id ignoré), pas une erreur."""

    def setUp(self):
        from registration.models import EtapeInscription

        EtapeInscription.objects.filter(code='groupe').update(est_actif=False)
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)
        self.abonnement = TypeAbonnement.objects.create(
            code='test_nav_dyn_abo', label='شهر', prix=80, type_offre='groupe', cible_age='les_deux',
        )

    def test_inscription_groupe_reussit_sans_groupe_id_si_etape_desactivee(self):
        reponses = {
            'nom': 'اختبار بدون مجموعة', 'sexe': 'homme', 'email': 'sans.groupe.etape@zidni.test',
            'date_naissance': '2000-01-01', 'telephone': '0600112233',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
            'abonnement_code': self.abonnement.code,
        }
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertEqual(erreurs, [])
        self.assertIsNotNone(inscription)
        self.assertIsNone(inscription.groupe_choisi)


# ============================================================================
# Chantier du 2026-08-23 (Partie 3B, "étapes repositionnables/insérables
# n'importe où") — une étape personnalisée créée par le مدير, positionnée
# ENTRE 2 étapes réelles verrouillées ('abonnement' et 'paiement' ici), doit
# avoir sa propre page (wizard_etape_personnalisee), bloquer la progression
# si un champ obligatoire n'est pas rempli, et sa réponse doit être
# enregistrée ET visible sur la fiche de la candidature — exactement comme
# n'importe quelle étape réelle. "الشروط والأحكام" (case à cocher
# obligatoire) : exemple concret donné, jamais un cas particulier câblé en
# dur (même principe de preuve que ChampAvecCritereSurEtapeIdentiteTests).
# ============================================================================
class EtapePersonnaliseeInsereeEntreDeuxEtapesReellesTests(TestCase):
    def setUp(self):
        from registration.models import EtapeInscription

        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        # paiement(5)/confirmation(6) repoussées à 6/7 (même idiome que
        # WizardNavigationDynamiqueTests) pour insérer SANS ambiguïté la
        # nouvelle étape à ordre=5, juste après 'abonnement'(4).
        EtapeInscription.objects.filter(code='paiement').update(ordre=6)
        EtapeInscription.objects.filter(code='confirmation').update(ordre=7)
        self.etape_conditions = EtapeInscription.objects.create(
            code='test_conditions', titre='الشروط والأحكام', ordre=5, est_actif=True,
        )
        self.champ_conditions = ChampInscription.objects.create(
            etape=self.etape_conditions, critere=None, type_champ='booleen',
            label='أوافق على شروط وأحكام التسجيل', obligatoire=True, ordre=1,
        )

        self.abonnement = TypeAbonnement.objects.create(
            code='test_conditions_abo', label='فردي شهري', prix=400, type_offre='individuel', cible_age='les_deux', ordre=1,
        )
        from payments.models import MoyenPaiement
        self.moyen = MoyenPaiement.objects.create(code='test_conditions_cih', label='CIH بنك', coordonnees='RIB', est_actif=True)

    def _avancer_jusqua_abonnement(self, client, email):
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'عبد الرحمن الوزاني', 'sexe': 'homme', 'email': email,
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0611223344', 'telephone_confirmation': '0611223344',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'individuel',
            f'champ_{self.champ_nb_seances.id}': '2',
        })
        return client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abonnement.code})

    def test_apparait_au_bon_endroit_entre_abonnement_et_paiement(self):
        client = Client()
        reponse = self._avancer_jusqua_abonnement(client, 'test_conditions_ordre@zidni.test')
        self.assertRedirects(
            reponse, reverse('wizard_etape_personnalisee', args=['test_conditions']), fetch_redirect_response=False,
        )
        reponse_page = client.get(reverse('wizard_etape_personnalisee', args=['test_conditions']))
        self.assertEqual(reponse_page.status_code, 200)
        html = reponse_page.content.decode('utf-8')
        self.assertIn('الشروط والأحكام', html)
        self.assertIn('أوافق على شروط وأحكام التسجيل', html)
        self.assertIn(f'name="champ_{self.champ_conditions.id}"', html)

    def test_bloque_la_progression_si_non_cochee(self):
        client = Client()
        self._avancer_jusqua_abonnement(client, 'test_conditions_bloque@zidni.test')
        # Case NON cochée -> absente du POST (comportement HTML standard
        # d'une checkbox non cochée, jamais envoyée par le navigateur).
        reponse = client.post(reverse('wizard_etape_personnalisee', args=['test_conditions']), {})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('إلزامي', reponse.content.decode('utf-8'))
        # Jamais avancé à 'paiement' -> jamais retenu en session non plus.
        self.assertNotIn(f'champ_{self.champ_conditions.id}', client.session.get('wizard_inscription', {}))

    def test_reponse_enregistree_bout_en_bout_et_visible_sur_fiche_admin(self):
        """LE test bout en bout demandé : coche la case, termine l'inscription
        (paiement), et vérifie que la réponse est bien enregistrée EN BASE
        ET affichée sur /dashboard/admin/inscriptions/eleve/<id>/ (fiche
        détail consultée par le مدير)."""
        email = 'test_conditions_bout_en_bout@zidni.test'
        client = Client()
        self._avancer_jusqua_abonnement(client, email)

        reponse_conditions = client.post(
            reverse('wizard_etape_personnalisee', args=['test_conditions']),
            {f'champ_{self.champ_conditions.id}': '1'},
        )
        self.assertRedirects(reponse_conditions, reverse('wizard_paiement'), fetch_redirect_response=False)

        reponse_paiement = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})
        self.assertRedirects(reponse_paiement, reverse('wizard_confirmation'), fetch_redirect_response=False)

        inscription = InscriptionEleve.objects.get(email=email)
        reponse_bd = inscription.reponses.get(champ=self.champ_conditions)
        self.assertEqual(reponse_bd.valeur_texte, '1')

        admin = User.objects.create_user(
            username='admin_test_conditions@zidni.test', email='admin_test_conditions@zidni.test',
            password='xX!test12345', role='admin', doit_changer_mot_de_passe=False,
        )
        client_admin = Client()
        client_admin.force_login(admin)
        html_fiche = client_admin.get(
            reverse('admin_inscription_eleve_detail', args=[inscription.id])
        ).content.decode('utf-8')
        self.assertIn('أوافق على شروط وأحكام التسجيل', html_fiche)
        self.assertIn('نعم', html_fiche)

    def test_champ_obligatoire_etape_personnalisee_revalide_par_inscrire_eleve(self):
        """Confirme (Partie 3B, point 4) que inscrire_eleve() — utilisé par
        les 2 portes d'entrée — parcourt bien aussi les champs d'une étape
        personnalisée pour l'obligatoire, EXACTEMENT comme n'importe quelle
        autre étape (déjà le cas via evaluer_champs_actifs, qui ne filtre
        jamais par étape — voir son docstring) : sans réponse au champ
        obligatoire de 'test_conditions', la création échoue avec un message
        clair, jamais une InscriptionEleve incomplète créée silencieusement."""
        reponses = {
            'nom': 'اختبار بدون موافقة', 'sexe': 'homme', 'email': 'test_conditions_sans_reponse@zidni.test',
            'date_naissance': '2000-01-01', 'telephone': '0600112233',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'individuel',
            f'champ_{self.champ_nb_seances.id}': '2',
            'abonnement_code': self.abonnement.code,
            # champ_<id> de test_conditions volontairement absent.
        }
        inscription, erreurs = inscrire_eleve(reponses)
        self.assertIsNone(inscription)
        self.assertIn(f'"{self.champ_conditions.label}" إلزامي.', erreurs)
        self.assertFalse(InscriptionEleve.objects.filter(email='test_conditions_sans_reponse@zidni.test').exists())

    def test_etape_reelle_forcee_via_lurl_generique_redirige_vers_sa_vraie_vue(self):
        """Garde-fou : /registration/wizard/etape/programme/ (un des 7 codes
        réels) ne doit JAMAIS être rendu par la vue générique — toujours
        redirigé vers sa vraie vue dédiée, qui seule porte sa logique propre
        (âge/sexe pour 'identite', groupes pour 'groupe'...)."""
        client = Client()
        _choisir_categorie_age(client)
        reponse = client.get(reverse('wizard_etape_personnalisee', args=['programme']))
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)


# ============================================================================
# Chantier du 2026-08-22 — "liberté totale du nombre de séances" : quand
# AUCUN groupe ne correspond à la combinaison EXACTE de critères (généralisé
# à TOUTE combinaison, pas seulement le nombre de séances) : message
# configurable + liste informative de groupes proches (critères non
# négociables seulement) + DemandeNonSatisfaite pour traçabilité.
# ============================================================================
class WizardGroupeAucunMatchExactTests(TestCase):
    def setUp(self):
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        # Groupe "proche" : correspond à l'âge/sexe (non négociables) et au
        # programme/riwaya, mais PAS au nombre de séances demandé (77,
        # jamais réel) -> apparaît dans groupes_proches, jamais dans groupes.
        creneau_proche = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=60)
        remplacer_slots_creneau(creneau_proche, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        self.groupe_proche = Groupe.objects.create(
            nom='مجموعة قريبة اختبار عدم التطابق', creneau=creneau_proche, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe_proche, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe_proche, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

    def _avancer_a_etape_3(self, client, email='aucun.match@zidni.test', nb_seances='77'):
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'اختبار عدم التطابق', 'sexe': 'homme', 'email': email,
            'date_naissance': '2000-01-01',
            'indicatif_pays': '212', 'telephone': '0600112233', 'telephone_confirmation': '0600112233',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': nb_seances,
        })

    def test_affiche_message_configurable_et_groupes_proches(self):
        from registration.models import get_presentation_inscription

        presentation = get_presentation_inscription()
        presentation.message_aucun_groupe_exact = 'رسالة اعتذار اختبار خاصة'
        presentation.save()

        client = Client()
        self._avancer_a_etape_3(client)
        html = client.get(reverse('wizard_groupe')).content.decode('utf-8')
        self.assertIn('رسالة اعتذار اختبار خاصة', html)
        self.assertIn('مجموعة قريبة اختبار عدم التطابق', html)

    def test_continuer_sans_groupe_enregistre_une_demande_non_satisfaite(self):
        from registration.models import DemandeNonSatisfaite

        client = Client()
        self._avancer_a_etape_3(client)
        self.assertEqual(DemandeNonSatisfaite.objects.count(), 0)
        reponse = client.post(reverse('wizard_groupe'), {'continuer_sans_groupe': '1'})
        self.assertRedirects(reponse, reverse('wizard_abonnement'), fetch_redirect_response=False)

        demande = DemandeNonSatisfaite.objects.get()
        self.assertEqual(demande.nb_slots, 77)
        # reponses_pour_filtrage_depuis_resultats stocke TOUJOURS une liste
        # pour un backend 'eav', même en choix_unique (voir groupes_
        # compatibles, qui accepte les deux formes) — snapshot fidèle, pas
        # une chaîne brute.
        self.assertEqual(demande.criteres_json.get(self.critere_riwaya.code), ['hafs'])
        self.assertIsNone(demande.inscription)
        self.assertEqual(client.session['wizard_inscription']['groupe_id'], '')

    def test_inscription_reussit_sans_groupe_et_lie_la_demande(self):
        from inscriptions.models import InscriptionEleve, TypeAbonnement
        from payments.models import MoyenPaiement
        from registration.models import DemandeNonSatisfaite

        abo = TypeAbonnement.objects.create(
            code='test_aucun_match_abo', label='شهري جماعي', prix=80, type_offre='groupe', cible_age='les_deux',
        )
        moyen = MoyenPaiement.objects.create(code='test_aucun_match_cih', label='CIH بنك', coordonnees='RIB', est_actif=True)

        client = Client()
        self._avancer_a_etape_3(client, email='aucun.match.confirme@zidni.test')
        client.post(reverse('wizard_groupe'), {'continuer_sans_groupe': '1'})
        client.post(reverse('wizard_abonnement'), {'abonnement_code': abo.code})
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': moyen.code})
        self.assertRedirects(reponse, reverse('wizard_confirmation'), fetch_redirect_response=False)

        inscription = InscriptionEleve.objects.get(email='aucun.match.confirme@zidni.test')
        self.assertIsNone(inscription.groupe_choisi)
        demande = DemandeNonSatisfaite.objects.get()
        self.assertEqual(demande.inscription_id, inscription.id)

    def test_bouton_suivant_desactive_avant_tout_choix(self):
        """Refonte du 2026-08-22 : aucune progression possible sans un choix
        explicite (groupe proche ou attente)."""
        client = Client()
        self._avancer_a_etape_3(client)
        html = client.get(reverse('wizard_groupe')).content.decode('utf-8')
        self.assertIn('id="btn_suivant_aucun_match" disabled', html)

    def test_groupe_proche_devient_selectionnable_et_enregistre_quand_meme_la_demande(self):
        """Refonte du 2026-08-22 : les groupes proches ne sont plus juste
        informatifs — l'élève peut les choisir. La combinaison EXACTE
        demandée reste tracée même dans ce cas (utile au مدير)."""
        from registration.models import DemandeNonSatisfaite

        client = Client()
        self._avancer_a_etape_3(client)
        reponse = client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe_proche.id)})
        self.assertRedirects(reponse, reverse('wizard_abonnement'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription']['groupe_id'], str(self.groupe_proche.id))

        demande = DemandeNonSatisfaite.objects.get()
        self.assertEqual(demande.nb_slots, 77)

    def test_aucun_choix_soumis_est_refuse(self):
        client = Client()
        self._avancer_a_etape_3(client)
        reponse = client.post(reverse('wizard_groupe'), {})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('يرجى اختيار مجموعة قريبة أو تأكيد الانتظار', reponse.content.decode('utf-8'))
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))

    def test_groupe_id_hors_liste_proche_est_refuse(self):
        """Sécurité serveur (Partie 22) : un groupe_id qui existe réellement
        mais ne fait PAS partie des groupes proches proposés (ne respecte
        même pas les critères non négociables) est refusé, jamais une
        confiance aveugle dans l'ID posté."""
        creneau_hors_sujet = Creneau.objects.create(sexe_cible='femme', type_seance='hifz', riwaya='warsh', age_min=6, age_max=10)
        remplacer_slots_creneau(creneau_hors_sujet, [
            {'jour': 'mer', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe_hors_sujet = Groupe.objects.create(
            nom='مجموعة خارج الاقتراحات', creneau=creneau_hors_sujet, statut='actif', type_capacite='groupe', capacite_max=10,
        )

        client = Client()
        self._avancer_a_etape_3(client)  # homme, 2000-01-01 -> adulte
        reponse = client.post(reverse('wizard_groupe'), {'groupe_id': str(groupe_hors_sujet.id)})
        self.assertEqual(reponse.status_code, 200)
        self.assertIn('يرجى اختيار مجموعة قريبة أو تأكيد الانتظار', reponse.content.decode('utf-8'))
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))

    def test_inscription_reussit_avec_un_groupe_proche_choisi(self):
        """Bout en bout : le groupe proche choisi à l'étape 3 est bien celui
        de l'inscription finale, malgré le mismatch sur le nombre de séances."""
        from inscriptions.models import InscriptionEleve, TypeAbonnement
        from payments.models import MoyenPaiement

        abo = TypeAbonnement.objects.create(
            code='test_groupe_proche_abo', label='شهري جماعي', prix=80, type_offre='groupe', cible_age='les_deux',
        )
        moyen = MoyenPaiement.objects.create(code='test_groupe_proche_cih', label='CIH بنك', coordonnees='RIB', est_actif=True)

        client = Client()
        self._avancer_a_etape_3(client, email='groupe.proche.confirme@zidni.test')
        client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe_proche.id)})
        client.post(reverse('wizard_abonnement'), {'abonnement_code': abo.code})
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': moyen.code})
        self.assertRedirects(reponse, reverse('wizard_confirmation'), fetch_redirect_response=False)

        inscription = InscriptionEleve.objects.get(email='groupe.proche.confirme@zidni.test')
        self.assertEqual(inscription.groupe_choisi, self.groupe_proche)


# ============================================================================
# RÉGRESSION signalée le 2026-08-22 : le filtre par sexe des halaqat (élève
# femme -> seulement halaqat femmes, élève homme -> seulement halaqat hommes)
# ne fonctionnait plus. Investigation (git log --all -p sur registration/
# utils.py depuis 308f28e, tout premier commit du moteur) : groupes_
# compatibles_avec_age() n'a JAMAIS filtré sur Creneau.sexe_cible, à AUCUN
# moment de l'historique de ce moteur — ce n'est donc PAS une régression
# introduite par un des 3 commits récents (fix capacité groupes_avec_place_
# disponible, bugs A/B/C wizard_programme, GrillePrixAbonnement — vérifiés
# un par un, aucun ne touche à groupes_compatibles_avec_age ni à sexe) mais
# un angle mort présent depuis l'origine de ce moteur, jamais couvert par un
# test avant celui-ci. Corrigé le même jour (voir groupes_compatibles_avec_
# age, désormais un paramètre sexe obligatoire, traité EXACTEMENT comme
# l'âge : structurel, jamais contournable par confirme_override) —
# volontairement distinct de courses.utils.raison_incompatibilite_groupe/
# avertissements_groupe, où sexe reste informatif seulement depuis la Tâche
# 14 (décision explicite du client, mais pour l'ADMIN réassignant un Eleve
# DÉJÀ EXISTANT à un groupe — un contexte différent de l'inscription
# initiale d'un nouvel élève, traitée ici).
# ============================================================================
class RegressionSexeGroupesTests(TestCase):
    def setUp(self):
        self.critere_programme = Critere.objects.get(code='programme')
        self.critere_riwaya = Critere.objects.get(code='riwaya')
        self.critere_type_offre = Critere.objects.get(code='type_offre')
        self.critere_nb_seances = Critere.objects.get(code='nb_seances_hebdo')
        self.champ_programme = ChampInscription.objects.get(etape__code='programme', critere=self.critere_programme)
        self.champ_riwaya = ChampInscription.objects.get(etape__code='programme', critere=self.critere_riwaya)
        self.champ_type_offre = ChampInscription.objects.get(etape__code='programme', critere=self.critere_type_offre)
        self.champ_nb_seances = ChampInscription.objects.get(etape__code='programme', critere=self.critere_nb_seances)

        self.groupe_hommes = self._creer_groupe('مجموعة رجال — اختبار الانحدار', sexe_cible='homme')
        self.groupe_femmes = self._creer_groupe('مجموعة نساء — اختبار الانحدار', sexe_cible='femme')
        self.groupe_mixte = self._creer_groupe('مجموعة مختلطة — اختبار الانحدار', sexe_cible='mixte')

    def _creer_groupe(self, nom, sexe_cible):
        creneau = Creneau.objects.create(
            sexe_cible=sexe_cible, type_seance='hifz', riwaya='hafs', age_min=18, age_max=90,
        )
        remplacer_slots_creneau(creneau, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe = Groupe.objects.create(nom=nom, creneau=creneau, statut='actif', type_capacite='groupe', capacite_max=10)
        GroupeCritereValeur.objects.create(groupe=groupe, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=groupe, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))
        return groupe

    def test_unitaire_femme_exclut_groupe_hommes_inclut_femmes_et_mixte(self):
        resultat = groupes_compatibles_avec_age({}, datetime.date(1995, 1, 1), 'femme')
        self.assertNotIn(self.groupe_hommes, resultat)
        self.assertIn(self.groupe_femmes, resultat)
        self.assertIn(self.groupe_mixte, resultat)

    def test_unitaire_homme_exclut_groupe_femmes_inclut_hommes_et_mixte(self):
        resultat = groupes_compatibles_avec_age({}, datetime.date(1995, 1, 1), 'homme')
        self.assertNotIn(self.groupe_femmes, resultat)
        self.assertIn(self.groupe_hommes, resultat)
        self.assertIn(self.groupe_mixte, resultat)

    def _avancer_a_etape_3(self, client, sexe):
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'اختبار الانحدار', 'sexe': sexe, 'email': f'regression.sexe.{sexe}@zidni.test',
            'date_naissance': '1995-01-01',
            'indicatif_pays': '212', 'telephone': '0600334455', 'telephone_confirmation': '0600334455',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '1',
        })

    def test_bout_en_bout_wizard_public_femme_ne_voit_jamais_un_groupe_hommes(self):
        client = Client()
        self._avancer_a_etape_3(client, sexe='femme')
        html = client.get(reverse('wizard_groupe')).content.decode('utf-8')
        self.assertIn(self.groupe_femmes.nom, html)
        self.assertIn(self.groupe_mixte.nom, html)
        self.assertNotIn(self.groupe_hommes.nom, html)

    def test_bout_en_bout_wizard_public_homme_ne_voit_jamais_un_groupe_femmes(self):
        client = Client()
        self._avancer_a_etape_3(client, sexe='homme')
        html = client.get(reverse('wizard_groupe')).content.decode('utf-8')
        self.assertIn(self.groupe_hommes.nom, html)
        self.assertIn(self.groupe_mixte.nom, html)
        self.assertNotIn(self.groupe_femmes.nom, html)

    def test_post_groupe_hommes_refuse_pour_une_femme_meme_en_forcant_lid(self):
        """Sécurité serveur (Partie 22) : même en POSTant directement l'ID du
        groupe hommes (visible ou non côté client), la soumission doit être
        refusée pour une élève femme — jamais une confiance aveugle en un ID
        valide en base."""
        client = Client()
        self._avancer_a_etape_3(client, sexe='femme')
        reponse = client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe_hommes.id)})
        self.assertEqual(reponse.status_code, 200)
        self.assertNotIn('groupe_id', client.session.get('wizard_inscription', {}))


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

    def _avancer_a_etape_4(self, client, type_offre='groupe', choisir_groupe=True, nb_seances='2'):
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'ليلى بنسعيد', 'sexe': 'femme', 'email': 'laila.wizard@zidni.test',
            'date_naissance': '1995-01-01',
            'indicatif_pays': '212', 'telephone': '0600778899', 'telephone_confirmation': '0600778899',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': type_offre,
            f'champ_{self.champ_nb_seances.id}': nb_seances,
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

    def test_affichage_montre_uniquement_la_duree_sans_repeter_le_type_offre(self):
        """Correction 5 (2026-08-22) : type d'offre déjà choisi 2 étapes plus
        tôt (Programme) — la ligne de prix à l'étape Abonnement ne doit plus
        répéter "جماعي"/"فردي", seule la durée (TypeAbonnement.duree) doit
        apparaître."""
        self.abo_groupe.duree = 'شهر'
        self.abo_groupe.save()
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        html = client.get(reverse('wizard_abonnement')).content.decode('utf-8')
        self.assertIn('شهر', html)
        self.assertNotIn('جماعي شهري', html)

    def test_affichage_retombe_sur_le_label_complet_si_duree_non_renseignee(self):
        """duree vide (compte non encore mis à jour par le مدير) -> repli sur
        label en entier, jamais un texte manquant."""
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        html = client.get(reverse('wizard_abonnement')).content.decode('utf-8')
        self.assertIn('جماعي شهري', html)

    def test_prix_affiche_repli_sur_type_abonnement_sans_ligne_de_grille(self):
        """Étape 9 (GrillePrixAbonnement, 2026-08-21) : sans aucune ligne de
        grille configurée, le prix affiché reste TypeAbonnement.prix — jamais
        de blocage/prix vide."""
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        reponse = client.get(reverse('wizard_abonnement'))
        abonnements = {a.code: a for a in reponse.context['abonnements']}
        self.assertEqual(abonnements[self.abo_groupe.code].prix_affiche, self.abo_groupe.prix)

    def test_prix_affiche_utilise_la_grille_si_combinaison_configuree(self):
        """nb_seances_hebdo=2 déjà répondu (via _avancer_a_etape_4) doit
        matcher exactement la ligne de grille nb_slots=2 ci-dessous."""
        GrillePrixAbonnement.objects.create(type_abonnement=self.abo_groupe, nb_slots=2, prix=999)
        client = Client()
        self._avancer_a_etape_4(client, type_offre='groupe')
        reponse = client.get(reverse('wizard_abonnement'))
        abonnements = {a.code: a for a in reponse.context['abonnements']}
        self.assertEqual(abonnements[self.abo_groupe.code].prix_affiche, 999)

    def test_prix_affiche_individuel_utilise_le_nb_slots_reellement_choisi(self):
        """Correction du 2026-08-22 (grille de prix incohérente/incomplète) :
        reproduit le scénario signalé (Individuel + 4 séances/semaine
        affichait le prix de 2) — une fois qu'une ligne de grille EXISTE
        pour nb_slots=4 (désormais possible pour n'importe quel nombre,
        chantier grille de prix), le wizard affiche bien ce prix, jamais
        celui d'une autre combinaison."""
        GrillePrixAbonnement.objects.create(type_abonnement=self.abo_individuel, nb_slots=4, prix=777)
        client = Client()
        self._avancer_a_etape_4(client, type_offre='individuel', nb_seances='4')
        reponse = client.get(reverse('wizard_abonnement'))
        abonnements = {a.code: a for a in reponse.context['abonnements']}
        self.assertEqual(abonnements[self.abo_individuel.code].prix_affiche, 777)

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
        _choisir_categorie_age(client)
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
        # Bouton retour (demande du 2026-08-22) : vers l'accueil du site
        # public, jamais "تسجيل الدخول" (aucun compte élève actif à ce stade).
        self.assertIn('العودة إلى الصفحة الرئيسية', html)
        self.assertNotIn('تسجيل الدخول', html)

        # Session vidée -> rafraîchir la page de confirmation ne réaffiche rien.
        self.assertNotIn('wizard_inscription', client.session)
        reponse_rafraichie = client.get(reverse('wizard_confirmation'))
        # fetch_redirect_response=False : wizard_reinitialiser() vide TOUTE la
        # session, type_age_choisi compris (chantier du 2026-08-22) — la
        # cible elle-même redirige donc encore une fois vers wizard_
        # categorie_age, seul ce PREMIER saut nous intéresse ici.
        self.assertRedirects(reponse_rafraichie, reverse('wizard_intro'), fetch_redirect_response=False)

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
        _choisir_categorie_age(client)
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

    def test_groupe_devenu_complet_entre_etape_3_et_confirmation_est_rejete_proprement(self):
        """Variante CAPACITÉ du test ci-dessus (bug signalé le 2026-08-21) :
        un groupe COMPATIBLE (bons critères/âge) mais devenu complet — soit
        parce qu'un autre élève s'est inscrit entretemps, soit simulé ici en
        injectant son id directement en session, en court-circuitant
        wizard_groupe (qui l'aurait déjà exclu de sa propre liste depuis le
        correctif groupes_avec_place_disponible). Prouve que inscrire_eleve()
        revalide la capacité en toute indépendance, avec son message dédié
        ("مكتملة العدد", pas le message générique) — jamais un plantage."""
        _remplir_groupe(self.groupe, self.groupe.capacite_max, 'confirm_devient_plein')

        client = Client()
        _choisir_categorie_age(client)
        client.post(reverse('wizard_identite'), {
            'nom': 'محاولة مقعد ممتلئ', 'sexe': 'homme', 'email': 'groupe.devenu.plein@zidni.test',
            'date_naissance': '1998-01-01',
            'indicatif_pays': '212', 'telephone': '0611778899', 'telephone_confirmation': '0611778899',
        })
        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '2',
        })

        session = client.session
        donnees = session.get('wizard_inscription', {})
        donnees['groupe_id'] = str(self.groupe.id)
        session['wizard_inscription'] = donnees
        session.save()

        client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_groupe.code})
        reponse = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})

        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(InscriptionEleve.objects.filter(email='groupe.devenu.plein@zidni.test').exists())
        self.assertIn('مكتملة العدد', reponse.content.decode('utf-8'))

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
        self.assertRedirects(reponse, reverse('wizard_intro'), fetch_redirect_response=False)


# ============================================================================
# BUG signalé le 2026-08-22 : du texte de commentaire technique s'affichait
# littéralement à l'écran, à au moins 2 endroits (page de confirmation
# finale, étape "nombre de séances"). Cause identifiée : {# ... #} est un tag
# Django MONO-LIGNE UNIQUEMENT (documentation officielle, confirmé
# empiriquement lors de l'investigation) — un commentaire étalé sur
# plusieurs lignes n'est PAS reconnu comme un commentaire par le parseur et
# s'affiche tel quel, verbatim, dans le HTML rendu.
#
# Recherche EXHAUSTIVE de tout le dépôt (regex {#(.*?)#} en mode DOTALL sur
# templates/**/*.html) : exactement 3 occurrences trouvées, TOUTES
# introduites au commit précédent (bugs A/B/C, 2026-08-21) — wizard_
# confirmation.html, wizard_programme.html, admin_eleve_ajouter_manuel.html.
# Aucune autre occurrence ailleurs dans le reste (bien plus ancien) du
# dépôt — corrigées en {% comment %}/{% endcomment %}, le seul tag Django
# qui supporte correctement un commentaire multi-lignes (vérifié
# empiriquement lui aussi, y compris avec un {# ... #} littéral À
# L'INTÉRIEUR du bloc comment, pour documenter la cause sans la reproduire).
# ============================================================================
class AucuneFuiteDeCommentaireTechniqueTests(TestCase):
    """Charge CHAQUE page du wizard public (parcours Groupe, jusqu'à la
    confirmation finale) + admin_eleve_ajouter_manuel (Étape 7), et vérifie
    qu'aucune ne contient jamais '{#' ni '#}' littéralement dans le HTML
    rendu — garde-fou GÉNÉRIQUE contre toute régression future de ce type,
    pas seulement les 3 spots déjà connus et déjà corrigés ci-dessus."""

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
        ])
        self.groupe = Groupe.objects.create(
            nom='مجموعة اختبار تسرب التعليقات', creneau=self.creneau, statut='actif', type_capacite='groupe', capacite_max=10,
        )
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=self.critere_programme, option=self.critere_programme.options.get(code='hifz'))
        GroupeCritereValeur.objects.create(groupe=self.groupe, critere=self.critere_riwaya, option=self.critere_riwaya.options.get(code='hafs'))

        self.abo_groupe = TypeAbonnement.objects.create(
            code='test_fuite_abo_groupe', label='جماعي شهري', prix=80, type_offre='groupe', cible_age='les_deux', ordre=1,
        )
        from payments.models import MoyenPaiement
        self.moyen = MoyenPaiement.objects.create(code='test_fuite_cih', label='CIH بنك', coordonnees='RIB', est_actif=True)

    def _assert_pas_de_fuite(self, reponse, contexte):
        html = reponse.content.decode('utf-8')
        self.assertNotIn('{#', html, f"Fuite de commentaire technique détectée sur : {contexte}")
        self.assertNotIn('#}', html, f"Fuite de commentaire technique détectée sur : {contexte}")

    def test_toutes_les_pages_du_wizard_public_sans_fuite_de_commentaire(self):
        client = Client()
        self._assert_pas_de_fuite(client.get(reverse('wizard_categorie_age')), 'wizard_categorie_age')
        _choisir_categorie_age(client)
        self._assert_pas_de_fuite(client.get(reverse('wizard_intro')), 'wizard_intro')
        self._assert_pas_de_fuite(client.get(reverse('wizard_identite')), 'wizard_identite')

        client.post(reverse('wizard_identite'), {
            'nom': 'اختبار تسرب التعليقات', 'sexe': 'homme', 'email': 'fuite.commentaire.wizard@zidni.test',
            'date_naissance': '1998-01-01',
            'indicatif_pays': '212', 'telephone': '0611998877', 'telephone_confirmation': '0611998877',
        })
        self._assert_pas_de_fuite(client.get(reverse('wizard_programme')), 'wizard_programme (avant réponse)')

        client.post(reverse('wizard_programme'), {
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '1',
        })
        self._assert_pas_de_fuite(client.get(reverse('wizard_groupe')), 'wizard_groupe')

        client.post(reverse('wizard_groupe'), {'groupe_id': str(self.groupe.id)})
        self._assert_pas_de_fuite(client.get(reverse('wizard_abonnement')), 'wizard_abonnement')

        client.post(reverse('wizard_abonnement'), {'abonnement_code': self.abo_groupe.code})
        self._assert_pas_de_fuite(client.get(reverse('wizard_paiement')), 'wizard_paiement')

        reponse_paiement = client.post(reverse('wizard_paiement'), {'moyen_paiement_code': self.moyen.code})
        self.assertRedirects(reponse_paiement, reverse('wizard_confirmation'), fetch_redirect_response=False)
        self._assert_pas_de_fuite(client.get(reverse('wizard_confirmation')), 'wizard_confirmation')

    def test_admin_eleve_ajouter_manuel_sans_fuite_de_commentaire(self):
        admin = _creer_admin(email='admin_fuite_commentaire@zidni.test')
        client = Client()
        client.force_login(admin)

        self._assert_pas_de_fuite(client.get(reverse('admin_eleve_ajouter_manuel')), 'admin_eleve_ajouter_manuel (round identité)')

        reponse_round2 = client.post(reverse('admin_eleve_ajouter_manuel'), {
            'round_form': 'identite',
            'nom': 'اختبار تسرب يدوي', 'sexe': 'homme', 'email': 'fuite.commentaire.manuel@zidni.test',
            'date_naissance': '1998-01-01',
            'indicatif_pays': '212', 'telephone': '0611556677', 'telephone_confirmation': '0611556677',
            f'champ_{self.champ_programme.id}': 'hifz',
            f'champ_{self.champ_riwaya.id}': 'hafs',
            f'champ_{self.champ_type_offre.id}': 'groupe',
            f'champ_{self.champ_nb_seances.id}': '1',
        })
        self._assert_pas_de_fuite(reponse_round2, 'admin_eleve_ajouter_manuel (round confirmation)')


# ============================================================================
# CHANTIER du 2026-08-22 — champs structurels 100% configurables (nom/
# nom_parent/sexe/telephone/date_naissance/email/job_actuel/niveau_scolaire),
# SAUF sexe/date_naissance/email (verrouillés : label+ordre seulement) —
# voir registration.models.ConfigurationChampStructurel.__doc__.
# ============================================================================
class ChampsStructurelsConfigurablesTests(TestCase):
    def test_seed_contient_les_8_champs_actifs_par_defaut(self):
        cles = set(ConfigurationChampStructurel.objects.values_list('champ_cle', flat=True))
        self.assertEqual(cles, {
            'nom', 'nom_parent', 'sexe', 'telephone', 'date_naissance', 'email',
            'job_actuel', 'niveau_scolaire',
        })
        self.assertEqual(len(champs_structurels_actifs('identite')), 8)

    def test_champs_verrouilles_toujours_obligatoires_et_actifs_meme_si_on_essaie_le_contraire(self):
        for cle in ConfigurationChampStructurel.CLES_VERROUILLEES:
            config = ConfigurationChampStructurel.objects.get(champ_cle=cle)
            config.obligatoire = False
            config.est_actif = False
            config.save()
            config.refresh_from_db()
            self.assertTrue(config.obligatoire, cle)
            self.assertTrue(config.est_actif, cle)

    def test_champ_verrouille_etape_non_modifiable_meme_si_on_essaie(self):
        autre_etape = EtapeInscription.objects.create(code='test_autre_etape_verrou', titre='مرحلة أخرى', ordre=99)
        config = ConfigurationChampStructurel.objects.get(champ_cle='email')
        etape_originale_id = config.etape_id
        config.etape = autre_etape
        config.save()
        config.refresh_from_db()
        self.assertEqual(config.etape_id, etape_originale_id)

    def test_valider_champ_structurel_libre_obligatoire_vide(self):
        config = ConfigurationChampStructurel.objects.get(champ_cle='job_actuel')
        config.obligatoire = True
        config.save()
        self.assertIsNotNone(valider_champ_structurel_libre(config, ''))
        self.assertIsNone(valider_champ_structurel_libre(config, 'مهندس'))

    def test_valider_champ_structurel_libre_regex_appliquee_seulement_si_rempli(self):
        config = ConfigurationChampStructurel.objects.get(champ_cle='niveau_scolaire')
        config.regex_validation = r'^[0-9]{1,2}$'
        config.message_erreur_regex = 'يجب أن يكون رقماً'
        config.obligatoire = False
        config.save()
        self.assertIsNone(valider_champ_structurel_libre(config, '6'))
        self.assertEqual(valider_champ_structurel_libre(config, 'سادسة'), 'يجب أن يكون رقماً')
        # Non obligatoire + vide -> jamais rejeté par la regex.
        self.assertIsNone(valider_champ_structurel_libre(config, ''))


class WizardIdentiteChampsStructurelsTests(TestCase):
    def _reponses_valides(self, **overrides):
        base = {
            'nom': 'سارة بنعلي', 'sexe': 'femme', 'email': 'sara.structurel@zidni.test',
            'date_naissance': '1998-01-01',
            'indicatif_pays': '212', 'telephone': '0611223344', 'telephone_confirmation': '0611223344',
        }
        base.update(overrides)
        return base

    def test_champ_desactive_disparait_du_formulaire_et_nest_jamais_exige(self):
        ConfigurationChampStructurel.objects.filter(champ_cle='job_actuel').update(est_actif=False)

        client = Client()
        _choisir_categorie_age(client)
        html = client.get(reverse('wizard_identite')).content.decode('utf-8')
        self.assertNotIn('name="job_actuel"', html)

        reponse = client.post(reverse('wizard_identite'), self._reponses_valides(job_actuel='ignoré'))
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)
        self.assertNotIn('job_actuel', client.session['wizard_inscription'])

    def test_champ_generique_rendu_obligatoire_bloque_si_vide(self):
        # niveau_scolaire plutôt que job_actuel : depuis la correction du
        # 2026-08-22 (label ciblé selon بالغ/طفل), job_actuel n'affiche plus
        # jamais son label brut de configuration — voir test_job_actuel_*
        # dans WizardCategorieAgeTests pour ce comportement spécifique.
        config = ConfigurationChampStructurel.objects.get(champ_cle='niveau_scolaire')
        config.obligatoire = True
        config.save()

        client = Client()
        _choisir_categorie_age(client)
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides(niveau_scolaire=''))
        self.assertEqual(reponse.status_code, 200)
        html = reponse.content.decode('utf-8')
        # Django échappe les guillemets ("&quot;") dans {{ erreur }} — on
        # vérifie le label ET "إلزامي" séparément plutôt que la chaîne brute
        # avec guillemets littéraux.
        self.assertIn(config.label, html)
        self.assertIn('إلزامي', html)

    def test_telephone_optionnel_si_configure_ainsi(self):
        ConfigurationChampStructurel.objects.filter(champ_cle='telephone').update(obligatoire=False)

        client = Client()
        _choisir_categorie_age(client)
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides(
            indicatif_pays='', telephone='', telephone_confirmation='',
        ))
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription']['telephone'], '')

    def test_label_personnalise_par_le_madir_saffiche_a_lelevi(self):
        ConfigurationChampStructurel.objects.filter(champ_cle='email').update(label='بريدك الشخصي')

        client = Client()
        _choisir_categorie_age(client)
        html = client.get(reverse('wizard_identite')).content.decode('utf-8')
        self.assertIn('بريدك الشخصي', html)

    def test_niveau_scolaire_optionnel_par_defaut_et_bien_stocke(self):
        client = Client()
        _choisir_categorie_age(client)
        reponse = client.post(reverse('wizard_identite'), self._reponses_valides(niveau_scolaire='الثالثة إعدادي'))
        self.assertRedirects(reponse, reverse('wizard_programme'), fetch_redirect_response=False)
        self.assertEqual(client.session['wizard_inscription']['niveau_scolaire'], 'الثالثة إعدادي')
