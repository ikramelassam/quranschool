import datetime

from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User, Eleve, Prof
from inscriptions.models import InscriptionEleve
from .models import Creneau, Groupe, DisponibiliteEleve, DisponibiliteProf
from .utils import (
    raison_incompatibilite_groupe, avertissements_groupe, avertissements_prof_creneau,
)

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


def _creer_prof(email='prof_courses@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    return Prof.objects.create(user=u, ville='الرباط', niveau_memorisation='كامل')


def _creer_inscription_eleve(**overrides):
    """Candidature liée à l'élève de test — les critères d'âge/programme/
    riwaya du couple (eleve, groupe) sont lus depuis Eleve.inscription (voir
    raison_incompatibilite_groupe/avertissements_groupe), donc indispensable
    pour tester ces fonctions sur un Eleve déjà validé."""
    valeurs = dict(
        nom='طالب تجريبي', date_naissance=datetime.date(2015, 1, 1), sexe='homme',
        telephone='0600000000', email='inscription_courses@zidni.test',
        programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois',
    )
    valeurs.update(overrides)
    return InscriptionEleve.objects.create(**valeurs)


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


class DisponibiliteEleveNonBloquanteTests(TestCase):
    """Chantier du 2026-08-16 : la disponibilité horaire de l'élève ne doit
    plus bloquer l'ajout à un groupe — même comportement que côté prof
    (avertissements_prof_creneau, Tâche du 2026-08-09), simple avertissement
    non bloquant. Couvre à la fois les fonctions utilitaires (courses.utils)
    et la vue d'ajout (admin_groupe_ajouter_eleve) de bout en bout."""

    def setUp(self):
        self.admin = _creer_admin('admin_dispo_courses@zidni.test')
        # Créneau lun/mer 16h-17h — voir _creer_creneau. age 6-12, mixte,
        # hifz/hafs : neutralisé pour n'isoler QUE le critère disponibilité
        # (programme/riwaya/sexe de l'inscription alignés dessus ci-dessous).
        self.creneau = _creer_creneau()
        self.groupe = Groupe.objects.create(nom='مجموعة اختبار التفرغ', creneau=self.creneau)

    def _creer_eleve_avec_inscription(self, email):
        eleve = _creer_eleve(email)
        eleve.inscription = _creer_inscription_eleve(email=f'ins_{email}')
        eleve.save()
        return eleve

    def test_dispo_incompatible_nest_plus_bloquante(self):
        """Élève avec une disponibilité déclarée qui ne couvre PAS le créneau :
        raison_incompatibilite_groupe doit rester None (avant ce chantier,
        retournait un message bloquant)."""
        eleve = self._creer_eleve_avec_inscription('eleve_dispo_incompatible@zidni.test')
        DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='jeu', heure_debut='10:00')
        self.assertIsNone(raison_incompatibilite_groupe(eleve, self.groupe))

    def test_dispo_incompatible_produit_un_avertissement(self):
        eleve = self._creer_eleve_avec_inscription('eleve_dispo_avert@zidni.test')
        DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='jeu', heure_debut='10:00')
        avertissements = avertissements_groupe(eleve, self.groupe)
        self.assertTrue(any('جدول تفرغ' in a for a in avertissements))

    def test_dispo_vide_reste_silencieuse(self):
        """Aucune disponibilité déclarée du tout (matrice vide) : même logique
        que le prof, l'absence de déclaration n'est pas une preuve
        d'incompatibilité — pas d'avertissement affiché."""
        eleve = self._creer_eleve_avec_inscription('eleve_dispo_vide@zidni.test')
        self.assertIsNone(raison_incompatibilite_groupe(eleve, self.groupe))
        avertissements = avertissements_groupe(eleve, self.groupe)
        self.assertFalse(any('جدول تفرغ' in a for a in avertissements))

    def test_dispo_complete_aucun_avertissement(self):
        eleve = self._creer_eleve_avec_inscription('eleve_dispo_complete@zidni.test')
        DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='lun', heure_debut='16:00')
        DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='mer', heure_debut='16:00')
        self.assertIsNone(raison_incompatibilite_groupe(eleve, self.groupe))
        avertissements = avertissements_groupe(eleve, self.groupe)
        self.assertFalse(any('جدول تفرغ' in a for a in avertissements))

    def test_autres_criteres_bloquants_restent_actifs(self):
        """Régression : seule la disponibilité devient non bloquante — l'âge
        (et les autres critères de raison_incompatibilite_groupe) doivent
        continuer à bloquer normalement."""
        eleve = self._creer_eleve_avec_inscription('eleve_age_hors_plage@zidni.test')
        eleve.inscription.date_naissance = datetime.date(1990, 1, 1)  # trop âgé pour le créneau 6-12 ans
        eleve.inscription.save()
        raison = raison_incompatibilite_groupe(eleve, self.groupe)
        self.assertIsNotNone(raison)
        self.assertIn('عمر', raison)

    def test_vue_ajout_sans_confirmation_demande_confirmation_pas_de_rejet(self):
        """Contrairement à un rejet bloquant (message d'erreur, élève non
        ajouté, aucune option de poursuivre), l'incompatibilité de dispo doit
        déclencher le même mécanisme de confirmation que les autres
        avertissements non bloquants (programme/riwaya/sexe)."""
        eleve = self._creer_eleve_avec_inscription('eleve_vue_sans_confirme@zidni.test')
        DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='jeu', heure_debut='10:00')

        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        reponse = client.post(
            reverse('admin_groupe_ajouter_eleve', args=[self.groupe.id]),
            {'eleve_id': str(eleve.id)},
        )
        self.assertRedirects(
            reponse,
            reverse('admin_groupe_detail', args=[self.groupe.id]) + f'?confirmer_ajout={eleve.id}',
        )
        self.assertFalse(self.groupe.eleves.filter(id=eleve.id).exists())

        # La page de confirmation affiche bien l'avertissement de dispo.
        reponse_detail = client.get(reponse.url)
        self.assertContains(reponse_detail, 'جدول تفرغ')

    def test_vue_ajout_avec_confirmation_ajoute_malgre_dispo_incompatible(self):
        eleve = self._creer_eleve_avec_inscription('eleve_vue_confirme@zidni.test')
        DisponibiliteEleve.objects.create(eleve=eleve, jour_semaine='jeu', heure_debut='10:00')

        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        reponse = client.post(
            reverse('admin_groupe_ajouter_eleve', args=[self.groupe.id]),
            {'eleve_id': str(eleve.id), 'confirme': '1'},
            follow=True,
        )
        self.assertRedirects(reponse, reverse('admin_groupe_detail', args=[self.groupe.id]))
        self.assertTrue(self.groupe.eleves.filter(id=eleve.id).exists())
        self.assertContains(reponse, 'جدول تفرغ')  # avertissement affiché (messages.warning)

    def test_comportement_prof_inchange(self):
        """Non-régression : le prof suit toujours exactement le même mécanisme
        qu'avant ce chantier (avertissement non bloquant sur la dispo), non
        touché par ce correctif côté élève."""
        prof = _creer_prof('prof_dispo_inchange@zidni.test')
        DisponibiliteProf.objects.create(prof=prof, jour_semaine='jeu', heure_debut='10:00')
        avertissements = avertissements_prof_creneau(prof, self.creneau)
        self.assertTrue(any('جدول تفرغ' in a for a in avertissements))
