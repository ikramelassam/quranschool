import datetime

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User, Eleve, Prof
from .models import Creneau, Groupe

MOT_DE_PASSE = 'xX!test12345'


def _creer_admin(email='admin_courses@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مدير', last_name='تجريبي', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif(email='mshrif_courses@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مشرف', last_name='تجريبي', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_eleve(email='eleve_courses@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme', statut='actif')


def _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12):
    return Creneau.objects.create(
        sexe_cible=sexe_cible, type_seance='hifz', riwaya='hafs',
        age_min=age_min, age_max=age_max,
        jour_1='lun', heure_debut_1=datetime.time(16, 0), heure_fin_1=datetime.time(17, 0),
        jour_2='mer', heure_debut_2=datetime.time(16, 0), heure_fin_2=datetime.time(17, 0),
    )


def _connecter(client, user):
    client.force_login(user)


class GroupeCategorieCollectifTests(TestCase):
    """Groupe.categorie_collectif — dérivée du créneau, jamais stockée."""

    def test_individuel_na_jamais_de_categorie_meme_avec_creneau_adulte_homme(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='فردي 1', type_capacite='individuel', creneau=creneau)
        self.assertIsNone(groupe.categorie_collectif)

    def test_collectif_homme_18_plus_categorie_hommes(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='رجال 1', type_capacite='groupe', creneau=creneau)
        self.assertEqual(groupe.categorie_collectif, 'hommes')

    def test_collectif_femme_18_plus_categorie_femmes(self):
        creneau = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='نساء 1', type_capacite='groupe', creneau=creneau)
        self.assertEqual(groupe.categorie_collectif, 'femmes')

    def test_collectif_moins_18_categorie_enfants_meme_sexe_cible_mixte(self):
        creneau = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)
        groupe = Groupe.objects.create(nom='أطفال 1', type_capacite='groupe', creneau=creneau)
        self.assertEqual(groupe.categorie_collectif, 'enfants')

    def test_collectif_exactement_17_ans_max_reste_enfants(self):
        # Borne : age_max=17 est TOUJOURS < 18, donc entièrement mineur.
        creneau = _creer_creneau(sexe_cible='homme', age_min=15, age_max=17)
        groupe = Groupe.objects.create(nom='حد 17', type_capacite='groupe', creneau=creneau)
        self.assertEqual(groupe.categorie_collectif, 'enfants')

    def test_collectif_sans_creneau_categorie_none(self):
        groupe = Groupe.objects.create(nom='بدون حلقة', type_capacite='groupe')
        self.assertIsNone(groupe.categorie_collectif)

    def test_collectif_creneau_mixte_adulte_categorie_none_jamais_devinee(self):
        # Cas volontairement non classifiable : adultes des deux sexes. Ne doit
        # JAMAIS être assigné à 'hommes' ou 'femmes' au hasard.
        creneau = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='مختلط بالغ', type_capacite='groupe', creneau=creneau)
        self.assertIsNone(groupe.categorie_collectif)

    def test_collectif_creneau_a_cheval_enfant_adulte_categorie_none(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=15, age_max=25)
        groupe = Groupe.objects.create(nom='بين الفئتين', type_capacite='groupe', creneau=creneau)
        self.assertIsNone(groupe.categorie_collectif)


class GroupesListFiltreTests(TestCase):
    """Vue admin_groupes (courses.views.groupes_list) : filtres type/categorie."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

        creneau_hommes = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        creneau_femmes = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        creneau_enfants = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)

        self.groupe_individuel = Groupe.objects.create(
            nom='ZZZ_فردي_تجريبي', type_capacite='individuel', creneau=creneau_hommes,
        )
        self.groupe_hommes = Groupe.objects.create(
            nom='ZZZ_رجال_تجريبي', type_capacite='groupe', creneau=creneau_hommes,
        )
        self.groupe_femmes = Groupe.objects.create(
            nom='ZZZ_نساء_تجريبي', type_capacite='groupe', creneau=creneau_femmes,
        )
        self.groupe_enfants = Groupe.objects.create(
            nom='ZZZ_أطفال_تجريبي', type_capacite='groupe', creneau=creneau_enfants,
        )

    def _get(self, user, **params):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, user)
        return client.get(reverse('admin_groupes'), params)

    def _noms_affiches(self, reponse):
        return {g.nom for g in reponse.context['groupes']}

    def test_filtre_tous_affiche_les_4_groupes(self):
        reponse = self._get(self.admin)
        noms = self._noms_affiches(reponse)
        self.assertTrue({
            self.groupe_individuel.nom, self.groupe_hommes.nom,
            self.groupe_femmes.nom, self.groupe_enfants.nom,
        }.issubset(noms))

    def test_filtre_individuel_exclut_les_collectifs(self):
        reponse = self._get(self.admin, type='individuel')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_individuel.nom, noms)
        self.assertNotIn(self.groupe_hommes.nom, noms)
        self.assertNotIn(self.groupe_femmes.nom, noms)
        self.assertNotIn(self.groupe_enfants.nom, noms)

    def test_filtre_groupe_exclut_lindividuel(self):
        reponse = self._get(self.admin, type='groupe')
        noms = self._noms_affiches(reponse)
        self.assertNotIn(self.groupe_individuel.nom, noms)
        self.assertIn(self.groupe_hommes.nom, noms)
        self.assertIn(self.groupe_femmes.nom, noms)
        self.assertIn(self.groupe_enfants.nom, noms)

    def test_filtre_groupe_hommes(self):
        reponse = self._get(self.admin, type='groupe', categorie='hommes')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms & {self.groupe_hommes.nom, self.groupe_femmes.nom, self.groupe_enfants.nom, self.groupe_individuel.nom}, {self.groupe_hommes.nom})

    def test_filtre_groupe_femmes(self):
        reponse = self._get(self.admin, type='groupe', categorie='femmes')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms & {self.groupe_hommes.nom, self.groupe_femmes.nom, self.groupe_enfants.nom, self.groupe_individuel.nom}, {self.groupe_femmes.nom})

    def test_filtre_groupe_enfants(self):
        reponse = self._get(self.admin, type='groupe', categorie='enfants')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms & {self.groupe_hommes.nom, self.groupe_femmes.nom, self.groupe_enfants.nom, self.groupe_individuel.nom}, {self.groupe_enfants.nom})

    def test_groupe_individuel_najamais_dans_une_sous_categorie_collective(self):
        for categorie in ('hommes', 'femmes', 'enfants'):
            reponse = self._get(self.admin, type='groupe', categorie=categorie)
            self.assertNotIn(self.groupe_individuel.nom, self._noms_affiches(reponse))

    def test_combinaison_type_et_categorie_avec_recherche_q(self):
        reponse = self._get(self.admin, type='groupe', categorie='hommes', q='ZZZ_رجال')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_hommes.nom, noms)
        self.assertNotIn(self.groupe_femmes.nom, noms)

    def test_categorie_sans_type_groupe_est_ignoree_sans_erreur(self):
        # Paramètre manipulé (?categorie= sans ?type=groupe) : ne doit jamais
        # planter ni élargir/restreindre incorrectement l'accès.
        reponse = self._get(self.admin, categorie='hommes')
        self.assertEqual(reponse.status_code, 200)

    def test_mshrif_a_acces_en_lecture_avec_les_memes_filtres(self):
        reponse = self._get(self.mshrif, type='groupe', categorie='femmes')
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(self.groupe_femmes.nom, self._noms_affiches(reponse))

    def test_eleve_non_autorise_redirige_hors_de_la_page(self):
        eleve = _creer_eleve()
        reponse = self._get(eleve.user, type='groupe')
        # role_required redirige (jamais 403/404 brut) — voir accounts.decorators.
        self.assertEqual(reponse.status_code, 302)
        self.assertNotEqual(reponse.url, reverse('admin_groupes'))
