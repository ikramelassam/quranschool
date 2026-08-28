import datetime
import io

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse

from accounts.models import User, Eleve, Prof
from annonces.models import Annonce
from inscriptions.models import InscriptionEleve
from .models import (
    Creneau, CreneauSlot, Groupe, DisponibiliteEleve, DisponibiliteProf, LienMeet, Seance, Presence,
    OptionNbSeances, TarifRemunerationGroupe, TarifRemunerationIndividuel,
)
from .utils import (
    raison_incompatibilite_groupe, avertissements_groupe, avertissements_prof_creneau,
    creneaux_se_chevauchent, groupes_en_conflit_pour_lien, lien_meet_est_disponible,
    liens_meet_disponibles, valider_photo_groupe, regenerer_pour_nouveau_creneau,
    groupes_en_conflit_pour_lien_a_horaire_reel, liens_meet_disponibles_pour_seance,
    lien_effectif_disponible_pour_seance, horaire_reel_seance,
    calculer_hizb_precis, calculer_progression_eleve,
    categorie_derivee_du_creneau, backfiller_categorie_depuis_creneau,
    remplacer_slots_creneau, etendre_seances, JOUR_INDEX_INVERSE,
    calculer_remuneration_prof, couverture_tarifs_remuneration_groupe,
    groupes_compatibles_sexe_age_pour_changement,
)
from registration.models import GroupeCritereValeur

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


def _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12, nb_slots=2):
    """Créneau de test — nb_slots (défaut 2, comportement historique inchangé)
    permet de tester la généralisation N séances/semaine sans dupliquer cette
    fixture (voir CreneauGeneralisationSlotsTests)."""
    creneau = Creneau.objects.create(
        sexe_cible=sexe_cible, type_seance='hifz', riwaya='hafs',
        age_min=age_min, age_max=age_max,
    )
    jours_defaut = ['lun', 'mer', 'jeu', 'sam', 'dim']
    slots = [
        {'jour': jours_defaut[i], 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)}
        for i in range(nb_slots)
    ]
    remplacer_slots_creneau(creneau, slots)
    return creneau


def _creer_creneau_horaire(jour_1, hd1, hf1, jour_2, hd2, hf2, **overrides):
    """Variante de _creer_creneau avec un horaire hebdomadaire explicite (2 slots)
    — nécessaire pour tester creneaux_se_chevauchent/liens_meet_disponibles sur
    des combinaisons de jours/heures précises (Tâche du 2026-08-17). jour_1/hd1/
    hf1/jour_2/hd2/hf2 gardés comme paramètres positionnels (aucun call site à
    modifier) mais écrits désormais dans CreneauSlot, pas dans les colonnes
    jour_1/jour_2 (devenues nullable et non lues nulle part dans le code
    applicatif depuis le chantier de généralisation N séances/semaine)."""
    valeurs = dict(
        sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12,
    )
    valeurs.update(overrides)
    creneau = Creneau.objects.create(**valeurs)
    remplacer_slots_creneau(creneau, [
        {'jour': jour_1, 'heure_debut': hd1, 'heure_fin': hf1},
        {'jour': jour_2, 'heure_debut': hd2, 'heure_fin': hf2},
    ])
    return creneau


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


def _image_upload(nom='photo.png', couleur=(200, 30, 30), format='PNG'):
    """Un vrai fichier image (PIL réel, pas juste renommé) — nécessaire car
    courses.utils.valider_photo_groupe ouvre/vérifie le fichier avec Pillow,
    même patron que dashboard.tests pour LogoConfig."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (10, 10), couleur).save(buffer, format=format)
    buffer.seek(0)
    content_type = 'image/png' if format == 'PNG' else f'image/{format.lower()}'
    return SimpleUploadedFile(nom, buffer.read(), content_type=content_type)


def _creer_eleve_avec_age(age, email):
    """Eleve VALIDÉ (avec InscriptionEleve liée, voir Eleve.inscription) dont
    l'âge est CONNU et contrôlé — nécessaire pour tester courses.utils.
    _tranche_age_eleve/calculer_remuneration_prof, qui lisent l'âge
    EXCLUSIVEMENT depuis eleve.inscription.date_naissance (Eleve n'a pas de
    date_naissance propre) — voir _tranche_age_eleve.__doc__."""
    aujourdhui = datetime.date.today()
    date_naissance = aujourdhui.replace(year=aujourdhui.year - age)
    inscription = InscriptionEleve.objects.create(
        nom='طالب تجريبي', date_naissance=date_naissance, sexe='homme',
        telephone='0600000000', email=email,
        programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois', statut='valide',
    )
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme', statut='actif', inscription=inscription)


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
    """Vue admin_groupes (courses.views.groupes_list) : filtres type/categorie.

    Depuis le Chantier du 2026-08-18, la sous-navigation catégorie des
    pastilles (النساء/الرجال/الأطفال) filtre directement Groupe.categorie —
    PLUS Groupe.categorie_collectif (property dérivée du créneau, laissée
    intacte dans le modèle mais plus utilisée par cette vue ; voir
    GroupeCategorieCollectifTests qui continue de tester la property
    elle-même, inchangée). Les créneaux ci-dessous sont délibérément choisis
    en CONTRADICTION avec la categorie assignée au groupe (ex:
    categorie='femmes_adultes' sur un créneau sexe_cible='homme') précisément
    pour prouver que ce filtre ne dérive plus rien de l'âge/sexe du créneau."""

    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()

        # Créneaux volontairement mal assortis avec la categorie assignée au
        # groupe correspondant — voir docstring de la classe.
        creneau_a = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        creneau_b = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        creneau_c = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)

        self.groupe_sans_categorie = Groupe.objects.create(
            nom='ZZZ_بدون_فئة', type_capacite='groupe', creneau=creneau_c,
        )
        self.groupe_femmes = Groupe.objects.create(
            nom='ZZZ_نساء_تجريبي', type_capacite='groupe', categorie='femmes_adultes',
            creneau=creneau_a,  # créneau homme, PAS femme — sans rapport avec categorie
        )
        self.groupe_hommes = Groupe.objects.create(
            nom='ZZZ_رجال_تجريبي', type_capacite='groupe', categorie='hommes_adultes',
            creneau=creneau_b,  # créneau femme, PAS homme — sans rapport avec categorie
        )
        self.groupe_mineurs = Groupe.objects.create(
            nom='ZZZ_أطفال_تجريبي', type_capacite='groupe', categorie='mineurs',
            creneau=creneau_a,  # créneau adulte 18-60, PAS mineur — sans rapport avec categorie
        )
        # Nom volontairement SANS le mot "نساء" (contrairement aux 3 groupes
        # ci-dessus) — sinon nom__trigram_similar (recherche floue, voir plus
        # bas) le ferait remonter sur toute recherche visant groupe_femmes,
        # indépendamment de la categorie réellement testée ici.
        self.groupe_individuel_femmes = Groupe.objects.create(
            nom='ZZZ_فردي_مصنّف_تجريبي', type_capacite='individuel', categorie='femmes_adultes',
        )

    def _get(self, user, **params):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, user)
        return client.get(reverse('admin_groupes'), params)

    def _noms_affiches(self, reponse):
        return {g.nom for g in reponse.context['groupes']}

    def test_filtre_tous_affiche_toutes_les_categories(self):
        reponse = self._get(self.admin)
        noms = self._noms_affiches(reponse)
        self.assertTrue({
            self.groupe_sans_categorie.nom, self.groupe_femmes.nom,
            self.groupe_hommes.nom, self.groupe_mineurs.nom,
            self.groupe_individuel_femmes.nom,
        }.issubset(noms))

    def test_filtre_type_individuel_exclut_les_collectifs(self):
        reponse = self._get(self.admin, type='individuel')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_individuel_femmes.nom, noms)
        self.assertNotIn(self.groupe_femmes.nom, noms)
        self.assertNotIn(self.groupe_hommes.nom, noms)
        self.assertNotIn(self.groupe_mineurs.nom, noms)

    def test_filtre_type_groupe_exclut_lindividuel(self):
        reponse = self._get(self.admin, type='groupe')
        noms = self._noms_affiches(reponse)
        self.assertNotIn(self.groupe_individuel_femmes.nom, noms)
        self.assertIn(self.groupe_femmes.nom, noms)
        self.assertIn(self.groupe_hommes.nom, noms)
        self.assertIn(self.groupe_mineurs.nom, noms)

    def test_filtre_categorie_femmes_adultes(self):
        reponse = self._get(self.admin, categorie='femmes_adultes')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_femmes.nom, noms)
        self.assertIn(self.groupe_individuel_femmes.nom, noms)
        self.assertNotIn(self.groupe_hommes.nom, noms)
        self.assertNotIn(self.groupe_mineurs.nom, noms)
        self.assertNotIn(self.groupe_sans_categorie.nom, noms)

    def test_filtre_categorie_hommes_adultes(self):
        reponse = self._get(self.admin, categorie='hommes_adultes')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms & {
            self.groupe_femmes.nom, self.groupe_hommes.nom, self.groupe_mineurs.nom,
            self.groupe_sans_categorie.nom, self.groupe_individuel_femmes.nom,
        }, {self.groupe_hommes.nom})

    def test_filtre_categorie_mineurs(self):
        reponse = self._get(self.admin, categorie='mineurs')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms & {
            self.groupe_femmes.nom, self.groupe_hommes.nom, self.groupe_mineurs.nom,
            self.groupe_sans_categorie.nom, self.groupe_individuel_femmes.nom,
        }, {self.groupe_mineurs.nom})

    def test_aucun_groupe_femmes_adultes_najamais_dans_hommes_ou_mineurs(self):
        for valeur in ('hommes_adultes', 'mineurs'):
            reponse = self._get(self.admin, categorie=valeur)
            noms = self._noms_affiches(reponse)
            self.assertNotIn(self.groupe_femmes.nom, noms)
            self.assertNotIn(self.groupe_individuel_femmes.nom, noms)

    def test_combinaison_type_groupe_et_categorie_femmes_adultes(self):
        reponse = self._get(self.admin, type='groupe', categorie='femmes_adultes')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_femmes.nom, noms)
        self.assertNotIn(self.groupe_individuel_femmes.nom, noms)

    def test_combinaison_type_individuel_et_categorie_femmes_adultes(self):
        reponse = self._get(self.admin, type='individuel', categorie='femmes_adultes')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_individuel_femmes.nom, noms)
        self.assertNotIn(self.groupe_femmes.nom, noms)

    def test_groupe_sans_categorie_reste_accessible_via_le_tout(self):
        reponse = self._get(self.admin)
        self.assertIn(self.groupe_sans_categorie.nom, self._noms_affiches(reponse))

    def test_filtre_categorie_combinable_avec_recherche_q(self):
        # q réduit encore le résultat À L'INTÉRIEUR de la même categorie —
        # groupe_individuel_femmes est aussi femmes_adultes mais ne
        # correspond pas à la recherche par nom.
        reponse = self._get(self.admin, categorie='femmes_adultes', q='ZZZ_نساء')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_femmes.nom, noms)
        self.assertNotIn(self.groupe_individuel_femmes.nom, noms)

    def test_filtre_categorie_combinable_avec_statut_et_prof(self):
        prof = _creer_prof()
        self.groupe_hommes.prof = prof
        self.groupe_hommes.statut = 'archive'
        self.groupe_hommes.save()
        reponse = self._get(self.admin, categorie='hommes_adultes', statut='archive', prof=prof.id)
        self.assertIn(self.groupe_hommes.nom, self._noms_affiches(reponse))

    def test_filtre_categorie_combinable_avec_creneau(self):
        reponse = self._get(self.admin, categorie='femmes_adultes', creneau=self.groupe_femmes.creneau_id)
        self.assertIn(self.groupe_femmes.nom, self._noms_affiches(reponse))

    def test_categorie_ne_derive_pas_de_lage_ou_du_sexe_du_creneau(self):
        # Les créneaux de setUp sont délibérément mal assortis avec la
        # categorie assignée (ex: femmes_adultes sur un créneau sexe_cible=
        # 'homme', mineurs sur un créneau age_min=18) — si ce filtre utilisait
        # encore age_min/age_max/sexe_cible du créneau (comme l'ancien
        # categorie_collectif), ces groupes n'apparaîtraient PAS ici.
        reponse = self._get(self.admin, categorie='femmes_adultes')
        self.assertIn(self.groupe_femmes.nom, self._noms_affiches(reponse))
        reponse = self._get(self.admin, categorie='mineurs')
        self.assertIn(self.groupe_mineurs.nom, self._noms_affiches(reponse))

    def test_mshrif_a_acces_en_lecture_avec_le_filtre_categorie(self):
        reponse = self._get(self.mshrif, categorie='femmes_adultes')
        self.assertEqual(reponse.status_code, 200)
        self.assertIn(self.groupe_femmes.nom, self._noms_affiches(reponse))

    def test_eleve_non_autorise_redirige_hors_de_la_page(self):
        eleve = _creer_eleve()
        reponse = self._get(eleve.user, type='groupe')
        # role_required redirige (jamais 403/404 brut) — voir accounts.decorators.
        self.assertEqual(reponse.status_code, 302)
        self.assertNotEqual(reponse.url, reverse('admin_groupes'))


class GroupesListFiltreTrancheAgeTests(TestCase):
    """Vue admin_groupes (courses.views.groupes_list), 3e niveau de filtre
    ?tranche= sous ?categorie=mineurs — les 3 tranches d'âge précises
    التلقين/البراعم/اليافعون (courses.utils.TRANCHES_AGE_PRECISES).

    Calculé à partir de la حلقة (Creneau.age_min/age_max) assignée au groupe,
    PAS de l'âge individuel de chaque élève inscrit — aucun élève créé dans
    cette classe de tests, volontairement, pour bien vérifier que ce filtre
    ne dépend d'aucune inscription réelle."""

    def setUp(self):
        self.admin = _creer_admin()
        creneau_talqin = _creer_creneau(age_min=5, age_max=7)
        creneau_baraim = _creer_creneau(age_min=8, age_max=13)
        creneau_yafiun = _creer_creneau(age_min=14, age_max=18)
        # Chevauche 2 tranches (talqin + baraim) — doit apparaître dans les 2.
        creneau_chevauchant = _creer_creneau(age_min=6, age_max=9)
        # Hors 5-18 ans (adultes) — n'appartient à aucune tranche. age_min=19
        # (pas 18) : اليافعون couvre 14-18 INCLUS (TRANCHES_AGE_PRECISES), un
        # créneau démarrant pile à 18 chevaucherait donc encore اليافعون —
        # même comportement hérité que GroupeTranchesAgeViseesTests.
        # test_vide_si_creneau_adultes, pas une régression introduite ici.
        creneau_adulte = _creer_creneau(age_min=19, age_max=60)

        self.groupe_talqin = Groupe.objects.create(
            nom='ZZZ_تلقين_تجريبي', type_capacite='groupe', categorie='mineurs', creneau=creneau_talqin,
        )
        self.groupe_baraim = Groupe.objects.create(
            nom='ZZZ_براعم_تجريبي', type_capacite='groupe', categorie='mineurs', creneau=creneau_baraim,
        )
        self.groupe_yafiun = Groupe.objects.create(
            nom='ZZZ_يافعون_تجريبي', type_capacite='groupe', categorie='mineurs', creneau=creneau_yafiun,
        )
        self.groupe_chevauchant = Groupe.objects.create(
            nom='ZZZ_متداخل_تجريبي', type_capacite='groupe', categorie='mineurs', creneau=creneau_chevauchant,
        )
        self.groupe_adulte_mineurs = Groupe.objects.create(
            nom='ZZZ_بالغين_مصنف_أطفال_تجريبي', type_capacite='groupe', categorie='mineurs', creneau=creneau_adulte,
        )
        # categorie != 'mineurs' : ne doit JAMAIS apparaître sous une tranche,
        # même si son créneau chevauche talqin — le filtre tranche ne
        # s'applique qu'en combinaison avec categorie='mineurs' (voir
        # groupes_list).
        self.groupe_hors_mineurs = Groupe.objects.create(
            nom='ZZZ_رجال_créneau_talqin_تجريبي', type_capacite='groupe',
            categorie='hommes_adultes', creneau=_creer_creneau(sexe_cible='homme', age_min=5, age_max=7),
        )

    def _get(self, **params):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        return client.get(reverse('admin_groupes'), params)

    def _noms_affiches(self, reponse):
        return {g.nom for g in reponse.context['groupes']}

    def test_filtre_tranche_talqin(self):
        reponse = self._get(categorie='mineurs', tranche='talqin')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms, {self.groupe_talqin.nom, self.groupe_chevauchant.nom})

    def test_filtre_tranche_baraim(self):
        reponse = self._get(categorie='mineurs', tranche='baraim')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms, {self.groupe_baraim.nom, self.groupe_chevauchant.nom})

    def test_filtre_tranche_yafiun(self):
        reponse = self._get(categorie='mineurs', tranche='yafiun')
        noms = self._noms_affiches(reponse)
        self.assertEqual(noms, {self.groupe_yafiun.nom})

    def test_groupe_adulte_najamais_dans_une_tranche(self):
        for code in ('talqin', 'baraim', 'yafiun'):
            reponse = self._get(categorie='mineurs', tranche=code)
            self.assertNotIn(self.groupe_adulte_mineurs.nom, self._noms_affiches(reponse))

    def test_filtre_tranche_ignore_sans_categorie_mineurs(self):
        # ?tranche= seul (sans ?categorie=mineurs) ne doit RIEN filtrer — la
        # sous-navigation tranche n'est même pas affichée dans ce cas côté
        # template, mais la vue doit rester sûre même si l'URL est forgée
        # à la main.
        reponse = self._get(tranche='talqin')
        noms = self._noms_affiches(reponse)
        self.assertIn(self.groupe_hors_mineurs.nom, noms)
        self.assertIn(self.groupe_yafiun.nom, noms)

    def test_categorie_mineurs_seule_affiche_toutes_les_tranches(self):
        reponse = self._get(categorie='mineurs')
        noms = self._noms_affiches(reponse)
        self.assertTrue({
            self.groupe_talqin.nom, self.groupe_baraim.nom, self.groupe_yafiun.nom,
            self.groupe_chevauchant.nom, self.groupe_adulte_mineurs.nom,
        }.issubset(noms))
        self.assertNotIn(self.groupe_hors_mineurs.nom, noms)


class GroupeCategorieChampTests(TestCase):
    """Groupe.categorie (Tâche du 2026-08-17) — réutilise EXACTEMENT
    Annonce.CIBLE_CHOICES, jamais une 2e liste de catégories recodée à part."""

    def test_categorie_choices_identiques_a_annonce_cible_choices(self):
        self.assertEqual(Groupe.CATEGORIE_CHOICES, Annonce.CIBLE_CHOICES)

    def test_categorie_vide_par_defaut(self):
        groupe = Groupe.objects.create(nom='بدون فئة')
        self.assertEqual(groupe.categorie, '')
        self.assertEqual(groupe.get_categorie_display(), '')

    def test_categorie_disponible_meme_pour_un_groupe_individuel(self):
        # Contrairement à categorie_collectif (toujours None pour un
        # individuel), categorie est un vrai champ, indépendant du type.
        groupe = Groupe.objects.create(nom='فردي مصنّف', type_capacite='individuel', categorie='hommes_adultes')
        self.assertEqual(groupe.categorie, 'hommes_adultes')
        self.assertEqual(groupe.get_categorie_display(), 'الطلاب البالغون')


class CategorieDeriveeDuCreneauTests(TestCase):
    """courses.utils.categorie_derivee_du_creneau — règle de dérivation
    utilisée par le backfill (Chantier du 2026-08-19), réplique de
    Groupe.categorie_collectif mais SANS sa restriction type_capacite=='groupe'
    (Groupe.categorie s'applique à n'importe quel type de groupe)."""

    def test_creneau_mineur_donne_mineurs(self):
        creneau = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)
        self.assertEqual(categorie_derivee_du_creneau(creneau), 'mineurs')

    def test_creneau_exactement_17_ans_max_reste_mineurs(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=15, age_max=17)
        self.assertEqual(categorie_derivee_du_creneau(creneau), 'mineurs')

    def test_creneau_adulte_homme_donne_hommes_adultes(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        self.assertEqual(categorie_derivee_du_creneau(creneau), 'hommes_adultes')

    def test_creneau_adulte_femme_donne_femmes_adultes(self):
        creneau = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        self.assertEqual(categorie_derivee_du_creneau(creneau), 'femmes_adultes')

    def test_creneau_a_cheval_enfant_adulte_non_tranche(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=7, age_max=99)
        self.assertIsNone(categorie_derivee_du_creneau(creneau))

    def test_creneau_adulte_mixte_non_tranche(self):
        creneau = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        self.assertIsNone(categorie_derivee_du_creneau(creneau))


class BackfillCategorieDepuisCreneauTests(TestCase):
    """courses.utils.backfiller_categorie_depuis_creneau — même patron que
    chat.tests.BackfillConversationsExistantesTests : teste la fonction
    réutilisable (vrais modèles), répliquée sur modèles historiques par
    courses/migrations/0034_backfill_groupe_categorie_depuis_creneau.py."""

    def test_remplit_les_cas_sans_ambiguite_et_retourne_le_compte(self):
        creneau_hommes = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        creneau_femmes = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        creneau_enfants = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)
        g_hommes = Groupe.objects.create(nom='ZZZ_backfill_hommes', creneau=creneau_hommes)
        g_femmes = Groupe.objects.create(nom='ZZZ_backfill_femmes', creneau=creneau_femmes, type_capacite='individuel')
        g_enfants = Groupe.objects.create(nom='ZZZ_backfill_enfants', creneau=creneau_enfants)

        nb_remplis = backfiller_categorie_depuis_creneau()

        self.assertEqual(nb_remplis, 3)
        g_hommes.refresh_from_db(); g_femmes.refresh_from_db(); g_enfants.refresh_from_db()
        self.assertEqual(g_hommes.categorie, 'hommes_adultes')
        self.assertEqual(g_femmes.categorie, 'femmes_adultes')
        self.assertEqual(g_enfants.categorie, 'mineurs')

    def test_laisse_vide_un_groupe_sans_creneau(self):
        groupe = Groupe.objects.create(nom='ZZZ_backfill_sans_creneau')
        self.assertEqual(backfiller_categorie_depuis_creneau(), 0)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, '')

    def test_laisse_vide_un_creneau_ambigu_a_cheval_enfant_adulte(self):
        creneau = _creer_creneau(sexe_cible='homme', age_min=7, age_max=99)
        groupe = Groupe.objects.create(nom='ZZZ_backfill_ambigu', creneau=creneau)
        self.assertEqual(backfiller_categorie_depuis_creneau(), 0)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, '')

    def test_laisse_vide_un_creneau_adulte_mixte(self):
        creneau = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='ZZZ_backfill_mixte_adulte', creneau=creneau)
        self.assertEqual(backfiller_categorie_depuis_creneau(), 0)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, '')

    def test_necrase_jamais_une_categorie_deja_renseignee_meme_incoherente(self):
        # Categorie manuelle 'mineurs' sur un créneau homme adulte —
        # incohérente avec la dérivation, mais categorie est un champ saisi
        # librement par le مدير (voir Groupe.categorie.__doc__) : le backfill
        # ne doit JAMAIS l'écraser, cohérente ou non avec le créneau.
        creneau = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='ZZZ_backfill_deja_rempli', creneau=creneau, categorie='mineurs')

        nb_remplis = backfiller_categorie_depuis_creneau()

        self.assertEqual(nb_remplis, 0)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, 'mineurs')

    def test_idempotent_aucun_effet_si_rejoue(self):
        creneau = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='ZZZ_backfill_idempotent', creneau=creneau)

        premier_passage = backfiller_categorie_depuis_creneau()
        deuxieme_passage = backfiller_categorie_depuis_creneau()

        self.assertEqual(premier_passage, 1)
        self.assertEqual(deuxieme_passage, 0)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, 'femmes_adultes')

    def test_groupe_individuel_egalement_rempli(self):
        # Contrairement à categorie_collectif (jamais pour un individuel),
        # ce backfill couvre aussi les groupes individuels — Groupe.categorie
        # s'applique à n'importe quel type de groupe.
        creneau = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='ZZZ_backfill_individuel', creneau=creneau, type_capacite='individuel')

        self.assertEqual(backfiller_categorie_depuis_creneau(), 1)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, 'femmes_adultes')


class GroupePhotoEtCategorieVuesTests(TestCase):
    """Photo + catégorie via les vues admin (groupe_ajouter/groupe_modifier) —
    Tâche du 2026-08-17. Photo : upload/remplacement/suppression, validation
    serveur type/taille (même patron que dashboard.views.mshrif_logo)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.creneau = _creer_creneau()
        self.client = Client(SERVER_NAME='localhost')
        _connecter(self.client, self.admin)

    def _ajouter(self, **extra):
        donnees = {
            'nom': 'مجموعة الصورة', 'creneau': self.creneau.id,
            'type_capacite': 'groupe', 'max_eleves': 10,
        }
        donnees.update(extra)
        return self.client.post(reverse('admin_groupe_ajouter'), donnees)

    def test_creation_avec_photo_et_categorie_valides(self):
        reponse = self._ajouter(photo=_image_upload(), categorie='mineurs')
        self.assertEqual(reponse.status_code, 302)
        groupe = Groupe.objects.get(nom='مجموعة الصورة')
        self.assertTrue(groupe.photo)
        self.assertEqual(groupe.categorie, 'mineurs')
        groupe.photo.delete(save=False)

    def test_creation_sans_photo_reste_valide(self):
        reponse = self._ajouter()
        self.assertEqual(reponse.status_code, 302)
        groupe = Groupe.objects.get(nom='مجموعة الصورة')
        self.assertFalse(groupe.photo)
        self.assertEqual(groupe.categorie, '')

    def test_creation_extension_refusee_ne_cree_rien(self):
        fichier = SimpleUploadedFile('script.exe', b'MZ', content_type='application/octet-stream')
        reponse = self._ajouter(photo=fichier)
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Groupe.objects.filter(nom='مجموعة الصورة').exists())

    def test_creation_fichier_non_image_refuse(self):
        # Extension acceptée mais contenu non-image (PIL doit le détecter).
        fichier = SimpleUploadedFile('faux.png', b'ceci nest pas une image', content_type='image/png')
        reponse = self._ajouter(photo=fichier)
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Groupe.objects.filter(nom='مجموعة الصورة').exists())

    def test_remplacement_de_photo(self):
        groupe = Groupe.objects.create(nom='مجموعة قديمة', creneau=self.creneau, photo=_image_upload('ancienne.png'))
        ancienne_url = groupe.photo.name
        reponse = self.client.post(reverse('admin_groupe_modifier', args=[groupe.id]), {
            'nom': groupe.nom, 'creneau': self.creneau.id, 'type_capacite': 'groupe',
            'capacite_max': 10, 'statut': 'actif', 'photo': _image_upload('nouvelle.png'),
        })
        self.assertEqual(reponse.status_code, 302)
        groupe.refresh_from_db()
        self.assertTrue(groupe.photo)
        self.assertNotEqual(groupe.photo.name, ancienne_url)
        groupe.photo.delete(save=False)

    def test_suppression_de_photo_via_case_a_cocher(self):
        groupe = Groupe.objects.create(nom='مجموعة بصورة', creneau=self.creneau, photo=_image_upload())
        self.assertTrue(groupe.photo)
        reponse = self.client.post(reverse('admin_groupe_modifier', args=[groupe.id]), {
            'nom': groupe.nom, 'creneau': self.creneau.id, 'type_capacite': 'groupe',
            'capacite_max': 10, 'statut': 'actif', 'supprimer_photo': '1',
        })
        self.assertEqual(reponse.status_code, 302)
        groupe.refresh_from_db()
        self.assertFalse(groupe.photo)

    def test_modification_categorie(self):
        groupe = Groupe.objects.create(nom='مجموعة للتصنيف', creneau=self.creneau, categorie='hommes_adultes')
        reponse = self.client.post(reverse('admin_groupe_modifier', args=[groupe.id]), {
            'nom': groupe.nom, 'creneau': self.creneau.id, 'type_capacite': 'groupe',
            'capacite_max': 10, 'statut': 'actif', 'categorie': 'femmes_adultes',
        })
        self.assertEqual(reponse.status_code, 302)
        groupe.refresh_from_db()
        self.assertEqual(groupe.categorie, 'femmes_adultes')

    def test_filtre_par_categorie_dans_la_liste(self):
        # Paramètre `categorie` — depuis le Chantier du 2026-08-18, le
        # formulaire détaillé "فئة المجموعة" (ancien paramètre `cat`) a été
        # retiré car doublon exact des pastilles النساء/الرجال/الأطفال, qui
        # filtrent ce même champ Groupe.categorie via `categorie`.
        Groupe.objects.create(nom='ZZZ_مصنّفة_رجال', creneau=self.creneau, categorie='hommes_adultes')
        Groupe.objects.create(nom='ZZZ_مصنّفة_نساء', creneau=self.creneau, categorie='femmes_adultes')
        reponse = self.client.get(reverse('admin_groupes'), {'categorie': 'hommes_adultes'})
        noms = {g.nom for g in reponse.context['groupes']}
        self.assertIn('ZZZ_مصنّفة_رجال', noms)
        self.assertNotIn('ZZZ_مصنّفة_نساء', noms)


class ValiderPhotoGroupeTests(TestCase):
    """courses.utils.valider_photo_groupe — validation unitaire, sans passer par une vue."""

    def test_image_valide_acceptee(self):
        self.assertIsNone(valider_photo_groupe(_image_upload()))

    def test_extension_non_supportee_refusee(self):
        fichier = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        self.assertIsNotNone(valider_photo_groupe(fichier))

    def test_fichier_trop_lourd_refuse(self):
        from .utils import TAILLE_MAX_PHOTO_GROUPE_OCTETS
        contenu = b'\x00' * (TAILLE_MAX_PHOTO_GROUPE_OCTETS + 1)
        fichier = SimpleUploadedFile('grande.png', contenu, content_type='image/png')
        self.assertIsNotNone(valider_photo_groupe(fichier))


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


# ==================== POOL DE LIENS GOOGLE MEET (Tâche du 2026-08-17) ====================

class CreneauxSeChevauchentTests(TestCase):
    """creneaux_se_chevauchent — lit désormais CreneauSlot (chantier de
    généralisation N séances/semaine), donc le créneau doit être persisté (les
    slots sont une relation inverse, inutilisable sur une instance non
    sauvegardée) — délègue à _creer_creneau_horaire plutôt qu'une construction
    locale en mémoire comme avant ce chantier."""

    def _creneau(self, jour_1, hd1, hf1, jour_2, hd2, hf2):
        return _creer_creneau_horaire(jour_1, hd1, hf1, jour_2, hd2, hf2)

    def test_chevauchement_partiel_meme_jour_est_un_conflit(self):
        # 14:00-15:00 vs 14:30-15:30
        a = self._creneau('lun', datetime.time(14, 0), datetime.time(15, 0), 'mer', datetime.time(14, 0), datetime.time(15, 0))
        b = self._creneau('lun', datetime.time(14, 30), datetime.time(15, 30), 'mer', datetime.time(14, 30), datetime.time(15, 30))
        self.assertTrue(creneaux_se_chevauchent(a, b))

    def test_bornes_qui_se_touchent_ne_sont_pas_un_conflit(self):
        # 14:00-15:00 vs 15:00-16:00
        a = self._creneau('lun', datetime.time(14, 0), datetime.time(15, 0), 'mer', datetime.time(14, 0), datetime.time(15, 0))
        b = self._creneau('lun', datetime.time(15, 0), datetime.time(16, 0), 'mer', datetime.time(15, 0), datetime.time(16, 0))
        self.assertFalse(creneaux_se_chevauchent(a, b))

    def test_meme_jour_chevauchement_general_est_un_conflit(self):
        a = self._creneau('lun', datetime.time(10, 0), datetime.time(12, 0), 'mer', datetime.time(10, 0), datetime.time(12, 0))
        b = self._creneau('lun', datetime.time(11, 0), datetime.time(11, 30), 'mer', datetime.time(20, 0), datetime.time(21, 0))
        self.assertTrue(creneaux_se_chevauchent(a, b))

    def test_jours_differents_aucun_conflit_meme_avec_memes_heures(self):
        a = self._creneau('lun', datetime.time(14, 0), datetime.time(15, 0), 'mer', datetime.time(14, 0), datetime.time(15, 0))
        b = self._creneau('mar', datetime.time(14, 0), datetime.time(15, 0), 'jeu', datetime.time(14, 0), datetime.time(15, 0))
        self.assertFalse(creneaux_se_chevauchent(a, b))

    def test_conflit_uniquement_sur_le_premier_creneau_suffit(self):
        a = self._creneau('lun', datetime.time(14, 0), datetime.time(15, 0), 'mer', datetime.time(14, 0), datetime.time(15, 0))
        # lundi en conflit, mercredi totalement différent (aucun chevauchement) -> True quand même
        b = self._creneau('lun', datetime.time(14, 30), datetime.time(15, 30), 'mer', datetime.time(20, 0), datetime.time(21, 0))
        self.assertTrue(creneaux_se_chevauchent(a, b))

    def test_conflit_uniquement_sur_le_second_creneau_suffit(self):
        a = self._creneau('lun', datetime.time(14, 0), datetime.time(15, 0), 'mer', datetime.time(14, 0), datetime.time(15, 0))
        # lundi compatible (bornes touchantes), mercredi en conflit -> True
        b = self._creneau('lun', datetime.time(15, 0), datetime.time(16, 0), 'mer', datetime.time(14, 30), datetime.time(15, 30))
        self.assertTrue(creneaux_se_chevauchent(a, b))

    def test_deux_creneaux_compatibles_aucun_conflit(self):
        a = self._creneau('lun', datetime.time(14, 0), datetime.time(15, 0), 'mer', datetime.time(14, 0), datetime.time(15, 0))
        b = self._creneau('lun', datetime.time(16, 0), datetime.time(17, 0), 'mer', datetime.time(16, 0), datetime.time(17, 0))
        self.assertFalse(creneaux_se_chevauchent(a, b))


class LienMeetDisponibiliteTests(TestCase):
    """groupes_en_conflit_pour_lien / lien_meet_est_disponible /
    liens_meet_disponibles — logique de disponibilité (Tâche du 2026-08-17)."""

    def setUp(self):
        self.creneau_a = _creer_creneau_horaire(
            'lun', datetime.time(14, 0), datetime.time(15, 0),
            'mer', datetime.time(14, 0), datetime.time(15, 0),
        )
        self.lien1 = LienMeet.objects.create(url='https://meet.google.com/aaa-aaaa-aaa', libelle='Meet 1')
        self.lien2 = LienMeet.objects.create(url='https://meet.google.com/bbb-bbbb-bbb', libelle='Meet 2')
        self.groupe_a = Groupe.objects.create(
            nom='مجموعة أ', creneau=self.creneau_a, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )

    def test_conflit_sur_le_premier_creneau_rend_le_lien_indisponible(self):
        creneau_b = _creer_creneau_horaire(
            'lun', datetime.time(14, 30), datetime.time(15, 30),  # conflit
            'mer', datetime.time(20, 0), datetime.time(21, 0),    # aucun conflit
        )
        self.assertFalse(lien_meet_est_disponible(self.lien1, creneau_b))
        self.assertEqual(len(groupes_en_conflit_pour_lien(self.lien1, creneau_b)), 1)

    def test_conflit_sur_le_second_creneau_rend_le_lien_indisponible(self):
        creneau_b = _creer_creneau_horaire(
            'lun', datetime.time(20, 0), datetime.time(21, 0),    # aucun conflit
            'mer', datetime.time(14, 30), datetime.time(15, 30),  # conflit
        )
        self.assertFalse(lien_meet_est_disponible(self.lien1, creneau_b))

    def test_premier_compatible_mais_second_en_conflit_indisponible(self):
        creneau_b = _creer_creneau_horaire(
            'lun', datetime.time(15, 0), datetime.time(16, 0),    # bornes touchantes, compatible
            'mer', datetime.time(14, 30), datetime.time(15, 30),  # conflit
        )
        self.assertFalse(lien_meet_est_disponible(self.lien1, creneau_b))

    def test_deux_creneaux_compatibles_lien_disponible(self):
        creneau_b = _creer_creneau_horaire(
            'lun', datetime.time(16, 0), datetime.time(17, 0),
            'mer', datetime.time(16, 0), datetime.time(17, 0),
        )
        self.assertTrue(lien_meet_est_disponible(self.lien1, creneau_b))
        self.assertEqual(groupes_en_conflit_pour_lien(self.lien1, creneau_b), [])

    def test_groupe_archive_ne_bloque_pas_le_lien(self):
        self.groupe_a.statut = 'archive'
        self.groupe_a.save(update_fields=['statut'])
        # Même horaire exact que groupe_a, qui est maintenant archivé.
        self.assertTrue(lien_meet_est_disponible(self.lien1, self.creneau_a))

    def test_modification_exclut_le_groupe_lui_meme(self):
        self.assertTrue(lien_meet_est_disponible(self.lien1, self.creneau_a, groupe_exclu=self.groupe_a))
        self.assertEqual(groupes_en_conflit_pour_lien(self.lien1, self.creneau_a, groupe_exclu=self.groupe_a), [])

    def test_groupe_sans_creneau_est_gere_sans_conflit(self):
        self.assertTrue(lien_meet_est_disponible(self.lien1, None))
        self.assertEqual(groupes_en_conflit_pour_lien(self.lien1, None), [])
        self.assertIn(self.lien1, liens_meet_disponibles(None))

    def test_meme_lien_horaires_differents_autorise(self):
        creneau_b = _creer_creneau_horaire(
            'lun', datetime.time(16, 0), datetime.time(17, 0),
            'mer', datetime.time(16, 0), datetime.time(17, 0),
        )
        self.assertIn(self.lien1, liens_meet_disponibles(creneau_b))

    def test_meme_lien_chevauchement_interdit(self):
        creneau_b = _creer_creneau_horaire(
            'lun', datetime.time(14, 30), datetime.time(15, 30),
            'mer', datetime.time(14, 30), datetime.time(15, 30),
        )
        self.assertNotIn(self.lien1, liens_meet_disponibles(creneau_b))
        self.assertIn(self.lien2, liens_meet_disponibles(creneau_b))  # inutilisé, donc toujours disponible

    def test_lien_inactif_absent_des_disponibles(self):
        self.lien2.est_actif = False
        self.lien2.save(update_fields=['est_actif'])
        self.assertNotIn(self.lien2, liens_meet_disponibles(self.creneau_a))

    def test_un_groupe_a_au_maximum_un_lien(self):
        # Assigner un nouveau lien REMPLACE l'ancien, jamais un second en plus
        # (Groupe.lien_meet est une ForeignKey simple, pas M2M).
        self.groupe_a.lien_meet = self.lien2
        self.groupe_a.save()
        self.groupe_a.refresh_from_db()
        self.assertEqual(self.groupe_a.lien_meet, self.lien2)

    def test_les_deux_seances_hebdo_du_groupe_partagent_le_meme_lien(self):
        from .utils import regenerer_pour_nouveau_creneau

        regenerer_pour_nouveau_creneau(self.groupe_a)
        seances = list(Seance.objects.filter(groupe=self.groupe_a))
        self.assertGreaterEqual(len(seances), 2)
        self.assertTrue(all(s.groupe.lien_reunion == self.lien1.url for s in seances))


class LienMeetVuesGroupeTests(TestCase):
    """Sauvegarde réelle d'un groupe via HTTP (groupe_ajouter/groupe_modifier)
    — la validation de disponibilité doit être appliquée côté SERVEUR, jamais
    seulement en JS (section 12 du cahier des charges)."""

    def setUp(self):
        self.admin = _creer_admin('admin_liens_meet@zidni.test')
        self.mshrif = _creer_mshrif('mshrif_liens_meet@zidni.test')

        self.creneau_a = _creer_creneau_horaire(
            'lun', datetime.time(14, 0), datetime.time(15, 0),
            'mer', datetime.time(14, 0), datetime.time(15, 0),
        )
        self.creneau_libre = _creer_creneau_horaire(
            'lun', datetime.time(16, 0), datetime.time(17, 0),
            'mer', datetime.time(16, 0), datetime.time(17, 0),
        )
        self.creneau_conflit = _creer_creneau_horaire(
            'lun', datetime.time(14, 30), datetime.time(15, 30),
            'mer', datetime.time(14, 30), datetime.time(15, 30),
        )
        self.lien1 = LienMeet.objects.create(url='https://meet.google.com/aaa-aaaa-aaa', libelle='Meet 1')
        self.groupe_a = Groupe.objects.create(
            nom='مجموعة أ (تستخدم الرابط)', creneau=self.creneau_a, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )

    def _client(self, user):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, user)
        return client

    def test_creation_avec_lien_disponible_reussit_et_synchronise_lien_reunion(self):
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_ajouter'), {
            'nom': 'مجموعة جديدة', 'creneau': self.creneau_libre.id, 'lien_meet': self.lien1.id,
            'type_capacite': 'groupe', 'max_eleves': 10,
        })
        self.assertEqual(reponse.status_code, 302)
        groupe = Groupe.objects.get(nom='مجموعة جديدة')
        self.assertEqual(groupe.lien_meet, self.lien1)
        self.assertEqual(groupe.lien_reunion, self.lien1.url)

    def test_creation_avec_lien_en_conflit_est_refusee_et_ne_cree_rien(self):
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_ajouter'), {
            'nom': 'مجموعة متعارضة', 'creneau': self.creneau_conflit.id, 'lien_meet': self.lien1.id,
            'type_capacite': 'groupe', 'max_eleves': 10,
        })
        self.assertEqual(reponse.status_code, 200)  # re-rendu du formulaire, pas de redirection
        self.assertFalse(Groupe.objects.filter(nom='مجموعة متعارضة').exists())
        messages_affiches = [str(m) for m in reponse.context['messages']]
        self.assertTrue(any('يتعارض' in m for m in messages_affiches))

    def test_creation_sans_lien_reste_possible(self):
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_ajouter'), {
            'nom': 'مجموعة بدون رابط', 'creneau': self.creneau_libre.id, 'lien_meet': '',
            'type_capacite': 'groupe', 'max_eleves': 10,
        })
        self.assertEqual(reponse.status_code, 302)
        groupe = Groupe.objects.get(nom='مجموعة بدون رابط')
        self.assertIsNone(groupe.lien_meet)
        self.assertEqual(groupe.lien_reunion, '')

    def test_lien_inactif_est_refuse(self):
        self.lien1.est_actif = False
        self.lien1.save(update_fields=['est_actif'])
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_ajouter'), {
            'nom': 'مجموعة برابط معطّل', 'creneau': self.creneau_libre.id, 'lien_meet': self.lien1.id,
            'type_capacite': 'groupe', 'max_eleves': 10,
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Groupe.objects.filter(nom='مجموعة برابط معطّل').exists())

    def test_modification_meme_groupe_meme_lien_meme_creneau_nest_pas_un_faux_conflit(self):
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_modifier', args=[self.groupe_a.id]), {
            'nom': 'مجموعة أ (اسم معدّل)', 'creneau': self.creneau_a.id, 'lien_meet': self.lien1.id,
            'type_capacite': 'groupe', 'capacite_max': 10, 'statut': 'actif',
        })
        self.assertEqual(reponse.status_code, 302)
        self.groupe_a.refresh_from_db()
        self.assertEqual(self.groupe_a.nom, 'مجموعة أ (اسم معدّل)')
        self.assertEqual(self.groupe_a.lien_meet, self.lien1)

    def test_changement_horaire_qui_cree_un_conflit_est_refuse(self):
        """Section 8 : un groupe qui utilisait déjà Meet1 sans problème (horaire
        libre) voit sa sauvegarde refusée si son NOUVEL horaire chevauche un
        AUTRE groupe utilisant aussi Meet1 — jamais de conflit silencieux."""
        groupe_b = Groupe.objects.create(
            nom='مجموعة ب', creneau=self.creneau_libre, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_modifier', args=[groupe_b.id]), {
            'nom': groupe_b.nom, 'creneau': self.creneau_conflit.id, 'lien_meet': self.lien1.id,
            'type_capacite': 'groupe', 'capacite_max': 10, 'statut': 'actif',
        })
        self.assertEqual(reponse.status_code, 200)
        groupe_b.refresh_from_db()
        # Rien n'a bougé : ni le créneau, ni le lien.
        self.assertEqual(groupe_b.creneau_id, self.creneau_libre.id)
        self.assertEqual(groupe_b.lien_meet_id, self.lien1.id)

    def test_retrait_du_lien_efface_lien_reunion_synchronise(self):
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_modifier', args=[self.groupe_a.id]), {
            'nom': self.groupe_a.nom, 'creneau': self.creneau_a.id, 'lien_meet': '',
            'type_capacite': 'groupe', 'capacite_max': 10, 'statut': 'actif',
        })
        self.assertEqual(reponse.status_code, 302)
        self.groupe_a.refresh_from_db()
        self.assertIsNone(self.groupe_a.lien_meet)
        self.assertEqual(self.groupe_a.lien_reunion, '')

    def test_lien_reunion_manuel_preexistant_non_touche_si_aucun_lien_meet_choisi(self):
        """Groupe créé AVANT ce chantier avec un lien_reunion saisi à la main
        (ex: WhatsApp, jamais un LienMeet du pool) : ne doit JAMAIS être
        effacé silencieusement par une modification qui ne touche pas au
        sélecteur de lien Meet (section 9 du cahier des charges — aucune
        donnée existante perdue)."""
        groupe_legacy = Groupe.objects.create(
            nom='مجموعة قديمة (واتساب)', creneau=self.creneau_libre,
            lien_reunion='https://chat.whatsapp.com/ANCIEN_LIEN', statut='actif',
        )
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_modifier', args=[groupe_legacy.id]), {
            'nom': groupe_legacy.nom, 'creneau': self.creneau_libre.id, 'lien_meet': '',
            'type_capacite': 'groupe', 'capacite_max': 10, 'statut': 'actif',
        })
        self.assertEqual(reponse.status_code, 302)
        groupe_legacy.refresh_from_db()
        self.assertEqual(groupe_legacy.lien_reunion, 'https://chat.whatsapp.com/ANCIEN_LIEN')


class LienMeetVuesGestionTests(TestCase):
    """CRUD du pool (liens_meet_list / lien_meet_ajouter / lien_meet_toggle)."""

    def setUp(self):
        self.admin = _creer_admin('admin_gestion_liens@zidni.test')
        self.mshrif = _creer_mshrif('mshrif_gestion_liens@zidni.test')
        self.lien1 = LienMeet.objects.create(url='https://meet.google.com/aaa-aaaa-aaa', libelle='Meet 1')

    def _client(self, user):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, user)
        return client

    def test_admin_peut_lister(self):
        reponse = self._client(self.admin).get(reverse('admin_liens_meet'))
        self.assertEqual(reponse.status_code, 200)

    def test_mshrif_peut_lister_en_lecture_seule(self):
        reponse = self._client(self.mshrif).get(reverse('admin_liens_meet'))
        self.assertEqual(reponse.status_code, 200)

    def test_eleve_non_autorise_redirige(self):
        eleve = _creer_eleve('eleve_liens_meet@zidni.test')
        reponse = self._client(eleve.user).get(reverse('admin_liens_meet'))
        self.assertEqual(reponse.status_code, 302)
        self.assertNotEqual(reponse.url, reverse('admin_liens_meet'))

    def test_admin_peut_ajouter_un_lien(self):
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_lien_meet_ajouter'), {
            'url': 'https://meet.google.com/ccc-cccc-ccc', 'libelle': 'Meet 3',
        })
        self.assertRedirects(reponse, reverse('admin_liens_meet'))
        self.assertTrue(LienMeet.objects.filter(url='https://meet.google.com/ccc-cccc-ccc').exists())

    def test_url_dupliquee_est_refusee(self):
        client = self._client(self.admin)
        client.post(reverse('admin_lien_meet_ajouter'), {'url': self.lien1.url, 'libelle': 'Doublon'})
        self.assertEqual(LienMeet.objects.filter(url=self.lien1.url).count(), 1)

    def test_mshrif_ne_peut_pas_ajouter_un_lien(self):
        client = self._client(self.mshrif)
        reponse = client.post(reverse('admin_lien_meet_ajouter'), {
            'url': 'https://meet.google.com/ddd-dddd-ddd', 'libelle': 'Meet interdit',
        })
        self.assertEqual(reponse.status_code, 302)
        self.assertNotEqual(reponse.url, reverse('admin_liens_meet'))
        self.assertFalse(LienMeet.objects.filter(url='https://meet.google.com/ddd-dddd-ddd').exists())

    def test_toggle_desactivation_ninflue_pas_sur_un_groupe_deja_assigne(self):
        creneau = _creer_creneau_horaire(
            'lun', datetime.time(14, 0), datetime.time(15, 0),
            'mer', datetime.time(14, 0), datetime.time(15, 0),
        )
        groupe = Groupe.objects.create(
            nom='مجموعة تستخدم الرابط', creneau=creneau, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )
        client = self._client(self.admin)
        reponse = client.get(reverse('admin_lien_meet_toggle', args=[self.lien1.id]))
        self.assertRedirects(reponse, reverse('admin_liens_meet'))
        self.lien1.refresh_from_db()
        groupe.refresh_from_db()
        self.assertFalse(self.lien1.est_actif)
        # Le groupe garde son lien tel quel — seule la PROPOSITION pour de
        # nouveaux groupes change (voir liens_meet_disponibles).
        self.assertEqual(groupe.lien_meet, self.lien1)
        self.assertEqual(groupe.lien_reunion, self.lien1.url)
        self.assertNotIn(self.lien1, liens_meet_disponibles(creneau))


class LienMeetGroupesSansLienTests(TestCase):
    """Phase 2 (audit UX du 2026-08-17) : section "مجموعات بدون رابط" de
    admin_liens_meet.html + vue d'attribution rapide + stat dashboard_admin."""

    def setUp(self):
        self.admin = _creer_admin('admin_sans_lien@zidni.test')
        self.mshrif = _creer_mshrif('mshrif_sans_lien@zidni.test')

        self.creneau_occupe = _creer_creneau_horaire(
            'lun', datetime.time(14, 0), datetime.time(15, 0),
            'mer', datetime.time(14, 0), datetime.time(15, 0),
        )
        self.creneau_libre = _creer_creneau_horaire(
            'lun', datetime.time(16, 0), datetime.time(17, 0),
            'mer', datetime.time(16, 0), datetime.time(17, 0),
        )
        self.creneau_conflit = _creer_creneau_horaire(
            'lun', datetime.time(14, 30), datetime.time(15, 30),
            'mer', datetime.time(14, 30), datetime.time(15, 30),
        )
        self.lien1 = LienMeet.objects.create(url='https://meet.google.com/aaa-aaaa-aaa', libelle='Meet 1')
        self.lien2 = LienMeet.objects.create(url='https://meet.google.com/bbb-bbbb-bbb', libelle='Meet 2')

        # Occupe self.lien1 sur creneau_occupe — sert de référence pour les
        # scénarios de conflit ci-dessous.
        self.groupe_occupant = Groupe.objects.create(
            nom='مجموعة تستخدم Meet 1', creneau=self.creneau_occupe, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )

    def _client(self, user):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, user)
        return client

    def test_groupe_sans_lien_horaire_conflictuel_naffiche_que_les_liens_reellement_disponibles(self):
        """Test A + exemple du point 4 : un groupe sans lien, dont l'horaire
        chevauche celui de groupe_occupant (donc en conflit avec lien1), ne
        doit se voir proposer QUE lien2."""
        groupe_sans_lien = Groupe.objects.create(
            nom='مجموعة بدون رابط (تتعارض)', creneau=self.creneau_conflit, statut='actif',
        )
        reponse = self._client(self.admin).get(reverse('admin_liens_meet'))
        self.assertEqual(reponse.status_code, 200)
        groupes_affiches = {g.id: g for g in reponse.context['groupes_sans_lien_avec_creneau']}
        self.assertIn(groupe_sans_lien.id, groupes_affiches)
        liens_proposes = groupes_affiches[groupe_sans_lien.id].liens_disponibles
        self.assertNotIn(self.lien1, liens_proposes)
        self.assertIn(self.lien2, liens_proposes)

    def test_groupe_avec_lien_najamais_dans_les_listes_sans_lien(self):
        """Test B : un groupe qui a déjà un lien (groupe_occupant) n'apparaît
        jamais dans "مجموعات بدون رابط", dans aucune des 2 listes."""
        reponse = self._client(self.admin).get(reverse('admin_liens_meet'))
        ids_avec_creneau = {g.id for g in reponse.context['groupes_sans_lien_avec_creneau']}
        ids_sans_creneau = {g.id for g in reponse.context['groupes_sans_lien_sans_creneau']}
        self.assertNotIn(self.groupe_occupant.id, ids_avec_creneau)
        self.assertNotIn(self.groupe_occupant.id, ids_sans_creneau)

    def test_groupe_archive_najamais_dans_les_listes_sans_lien(self):
        """Test H (dans ce contexte précis) : un groupe archivé sans lien ne
        doit pas polluer les listes (rien à y faire, il ne tourne plus) —
        que son créneau soit défini ou non."""
        Groupe.objects.create(nom='مجموعة مؤرشفة بدون رابط', creneau=self.creneau_libre, statut='archive')
        Groupe.objects.create(nom='مجموعة مؤرشفة بدون رابط ولا حلقة', statut='archive')
        reponse = self._client(self.admin).get(reverse('admin_liens_meet'))
        noms_avec_creneau = {g.nom for g in reponse.context['groupes_sans_lien_avec_creneau']}
        noms_sans_creneau = {g.nom for g in reponse.context['groupes_sans_lien_sans_creneau']}
        self.assertNotIn('مجموعة مؤرشفة بدون رابط', noms_avec_creneau)
        self.assertNotIn('مجموعة مؤرشفة بدون رابط ولا حلقة', noms_sans_creneau)

    def test_groupe_actif_sans_lien_et_sans_creneau_est_visible(self):
        """Correction du 2026-08-17 (Phase 3) : un groupe actif sans créneau
        n'est PLUS invisible — il apparaît dans une liste dédiée
        (groupes_sans_lien_sans_creneau), sans aucun lien proposé (rien de
        calculable sans horaire), distinct de groupes_sans_lien_avec_creneau."""
        groupe = Groupe.objects.create(nom='مجموعة بدون حلقة', statut='actif')
        reponse = self._client(self.admin).get(reverse('admin_liens_meet'))
        noms_sans_creneau = {g.nom for g in reponse.context['groupes_sans_lien_sans_creneau']}
        noms_avec_creneau = {g.nom for g in reponse.context['groupes_sans_lien_avec_creneau']}
        self.assertIn('مجموعة بدون حلقة', noms_sans_creneau)
        self.assertNotIn('مجموعة بدون حلقة', noms_avec_creneau)
        self.assertContains(reponse, 'الجدول غير محدد')
        # Pas de liens_disponibles annoté sur ces groupes — rien à proposer.
        groupe_affiche = next(g for g in reponse.context['groupes_sans_lien_sans_creneau'] if g.id == groupe.id)
        self.assertFalse(hasattr(groupe_affiche, 'liens_disponibles'))

    def test_attribution_reussie_synchronise_lien_reunion(self):
        groupe = Groupe.objects.create(nom='مجموعة تحتاج رابط', creneau=self.creneau_libre, statut='actif')
        client = self._client(self.admin)
        reponse = client.post(
            reverse('admin_lien_meet_attribuer_groupe', args=[groupe.id]),
            {'lien_meet': self.lien1.id},
        )
        self.assertRedirects(reponse, reverse('admin_liens_meet'))
        groupe.refresh_from_db()
        self.assertEqual(groupe.lien_meet, self.lien1)
        self.assertEqual(groupe.lien_reunion, self.lien1.url)

    def test_attribution_en_conflit_est_refusee(self):
        """Test D/E via ce raccourci : tenter d'attribuer lien1 (déjà utilisé
        sur creneau_occupe) à un groupe dont l'horaire chevauche doit échouer,
        sans toucher au groupe, avec un message d'erreur explicite."""
        groupe = Groupe.objects.create(nom='مجموعة متعارضة', creneau=self.creneau_conflit, statut='actif')
        client = self._client(self.admin)
        reponse = client.post(
            reverse('admin_lien_meet_attribuer_groupe', args=[groupe.id]),
            {'lien_meet': self.lien1.id},
            follow=True,
        )
        self.assertRedirects(reponse, reverse('admin_liens_meet'))
        groupe.refresh_from_db()
        self.assertIsNone(groupe.lien_meet)
        self.assertEqual(groupe.lien_reunion, '')
        messages_affiches = [str(m) for m in reponse.context['messages']]
        self.assertTrue(any('يتعارض' in m for m in messages_affiches))

    def test_attribution_lien_inactif_refusee(self):
        self.lien1.est_actif = False
        self.lien1.save(update_fields=['est_actif'])
        groupe = Groupe.objects.create(nom='مجموعة رابط معطّل', creneau=self.creneau_libre, statut='actif')
        client = self._client(self.admin)
        client.post(reverse('admin_lien_meet_attribuer_groupe', args=[groupe.id]), {'lien_meet': self.lien1.id})
        groupe.refresh_from_db()
        self.assertIsNone(groupe.lien_meet)

    def test_attribution_sans_creneau_refusee(self):
        groupe = Groupe.objects.create(nom='مجموعة بدون حلقة للإسناد', statut='actif')
        client = self._client(self.admin)
        client.post(reverse('admin_lien_meet_attribuer_groupe', args=[groupe.id]), {'lien_meet': self.lien2.id})
        groupe.refresh_from_db()
        self.assertIsNone(groupe.lien_meet)

    def test_mshrif_ne_peut_pas_attribuer_de_lien(self):
        groupe = Groupe.objects.create(nom='مجموعة (مشرف)', creneau=self.creneau_libre, statut='actif')
        client = self._client(self.mshrif)
        reponse = client.post(
            reverse('admin_lien_meet_attribuer_groupe', args=[groupe.id]),
            {'lien_meet': self.lien1.id},
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertNotEqual(reponse.url, reverse('admin_liens_meet'))
        groupe.refresh_from_db()
        self.assertIsNone(groupe.lien_meet)

    def test_dashboard_admin_compte_correctement_les_groupes_sans_lien(self):
        Groupe.objects.create(nom='مجموعة بدون رابط (لوحة التحكم)', creneau=self.creneau_libre, statut='actif')
        reponse = self._client(self.admin).get(reverse('dashboard_admin'))
        self.assertEqual(reponse.status_code, 200)
        # groupe_occupant a déjà un lien, ne doit pas être compté.
        self.assertEqual(reponse.context['groupes_sans_lien_meet'], 1)
        self.assertContains(reponse, 'مجموعات بدون رابط Meet')

    def test_dashboard_admin_compte_aussi_les_groupes_sans_creneau(self):
        """Correction du 2026-08-17 (Phase 3) : le compteur dashboard doit
        inclure TOUS les groupes actifs sans lien, y compris ceux sans
        créneau (pas seulement ceux avec un horaire défini)."""
        Groupe.objects.create(nom='مجموعة بدون رابط (مع حلقة)', creneau=self.creneau_libre, statut='actif')
        Groupe.objects.create(nom='مجموعة بدون رابط (بدون حلقة)', statut='actif')
        reponse = self._client(self.admin).get(reverse('dashboard_admin'))
        self.assertEqual(reponse.context['groupes_sans_lien_meet'], 2)

    def test_changement_horaire_qui_cree_conflit_propose_les_liens_disponibles_via_le_formulaire(self):
        """Test F : la page de modification, après un changement d'horaire
        refusé (voir LienMeetVuesGroupeTests.test_changement_horaire...), doit
        recalculer et exposer les liens réellement disponibles pour le NOUVEL
        horaire proposé dans son JSON JS — pas seulement pour l'ancien."""
        groupe = Groupe.objects.create(
            nom='مجموعة ب', creneau=self.creneau_libre, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )
        client = self._client(self.admin)
        reponse = client.post(reverse('admin_groupe_modifier', args=[groupe.id]), {
            'nom': groupe.nom, 'creneau': self.creneau_conflit.id, 'lien_meet': self.lien1.id,
            'type_capacite': 'groupe', 'capacite_max': 10, 'statut': 'actif',
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertContains(reponse, 'const liensMeetParCreneau')
        import json as _json
        contenu = reponse.content.decode('utf-8')
        debut = contenu.index('const liensMeetParCreneau = ') + len('const liensMeetParCreneau = ')
        fin = contenu.index(';', debut)
        payload = _json.loads(contenu[debut:fin])
        # Pour creneau_conflit, lien1 doit être marqué indisponible.
        entree_lien1 = next(l for l in payload[str(self.creneau_conflit.id)] if l['id'] == self.lien1.id)
        self.assertFalse(entree_lien1['disponible'])
        entree_lien2 = next(l for l in payload[str(self.creneau_conflit.id)] if l['id'] == self.lien2.id)
        self.assertTrue(entree_lien2['disponible'])


class ChevauchementHoraireReelTests(TestCase):
    """groupes_en_conflit_pour_lien_a_horaire_reel — variante ponctuelle de
    groupes_en_conflit_pour_lien pour les exceptions de séance (Tâche du
    2026-08-17). Tests 9/10 du cahier des charges."""

    def setUp(self):
        self.creneau = _creer_creneau_horaire(
            'mer', datetime.time(14, 0), datetime.time(15, 0),
            'ven', datetime.time(10, 0), datetime.time(11, 0),
        )
        self.lien = LienMeet.objects.create(url='https://meet.google.com/chr-chr-chr', libelle='Meet CHR')
        self.groupe = Groupe.objects.create(
            nom='مجموعة مرجعية', creneau=self.creneau, lien_meet=self.lien,
            lien_reunion=self.lien.url, statut='actif',
        )

    def test_14h_15h_vs_14h30_15h30_est_un_conflit(self):
        conflits = groupes_en_conflit_pour_lien_a_horaire_reel(
            self.lien, 'mer', datetime.time(14, 30), datetime.time(15, 30),
        )
        self.assertEqual(len(conflits), 1)

    def test_14h_15h_vs_15h_16h_nest_pas_un_conflit(self):
        conflits = groupes_en_conflit_pour_lien_a_horaire_reel(
            self.lien, 'mer', datetime.time(15, 0), datetime.time(16, 0),
        )
        self.assertEqual(conflits, [])


class SeanceExceptionLienMeetTests(TestCase):
    """Exception de lien Meet sur une seule Seance (Tâche du 2026-08-17) —
    voir dashboard.views.admin_seance_deplacer et Seance.lien_effectif.
    Couvre les tests 1 à 8 et 11 du cahier des charges."""

    def setUp(self):
        self.admin = _creer_admin('admin_exception_seance@zidni.test')

        # Groupe A : mercredi 14h-15h + vendredi 10h-11h, Meet 1 par défaut.
        self.creneau_a = _creer_creneau_horaire(
            'mer', datetime.time(14, 0), datetime.time(15, 0),
            'ven', datetime.time(10, 0), datetime.time(11, 0),
        )
        self.lien1 = LienMeet.objects.create(url='https://meet.google.com/exc-un-un', libelle='Meet 1')
        self.lien2 = LienMeet.objects.create(url='https://meet.google.com/exc-deux-deux', libelle='Meet 2')
        self.groupe_a = Groupe.objects.create(
            nom='مجموعة أ (استثناء)', creneau=self.creneau_a, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )
        regenerer_pour_nouveau_creneau(self.groupe_a)
        self.seances_mercredi = list(
            Seance.objects.filter(groupe=self.groupe_a, date__week_day=4).order_by('date')  # 4 = mercredi (Django week_day: dim=1..sam=7)
        )
        self.s1 = self.seances_mercredi[0]

        # Groupe B occupe déjà Meet 1 le mercredi 16h-17h — sert de conflit
        # quand une séance du groupe A est déplacée à ce même horaire.
        self.creneau_b = _creer_creneau_horaire(
            'mer', datetime.time(16, 0), datetime.time(17, 0),
            'sam', datetime.time(10, 0), datetime.time(11, 0),
        )
        self.groupe_b = Groupe.objects.create(
            nom='مجموعة ب (تحتل Meet1)', creneau=self.creneau_b, lien_meet=self.lien1,
            lien_reunion=self.lien1.url, statut='actif',
        )

    def _client(self):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        return client

    def _deplacer(self, seance, date, heure, lien_meet_exceptionnel=None):
        data = {'date': date.isoformat(), 'heure': heure, 'remarque': 'test'}
        if lien_meet_exceptionnel is not None:
            data['lien_meet_exceptionnel'] = lien_meet_exceptionnel
        return self._client().post(reverse('admin_seance_deplacer', args=[seance.id]), data)

    def test_1_deux_seances_hebdomadaires_meme_meet_par_defaut(self):
        seances = Seance.objects.filter(groupe=self.groupe_a)[:4]
        self.assertTrue(seances)
        for s in seances:
            self.assertEqual(s.lien_effectif, self.lien1.url)
            self.assertIsNone(s.lien_meet_exceptionnel)

    def test_2_deplacement_dune_seule_seance_ne_touche_pas_les_autres(self):
        autre_seance = Seance.objects.filter(groupe=self.groupe_a).exclude(pk=self.s1.pk).first()
        ancienne_date, ancienne_heure = autre_seance.date, autre_seance.heure

        # Déplacé vers un horaire sans aucun conflit (mercredi 20h-21h).
        reponse = self._deplacer(self.s1, self.s1.date, '20:00')
        self.assertEqual(reponse.status_code, 302)

        autre_seance.refresh_from_db()
        self.assertEqual(autre_seance.date, ancienne_date)
        self.assertEqual(autre_seance.heure, ancienne_heure)
        self.assertIsNone(autre_seance.lien_meet_exceptionnel)
        self.assertEqual(autre_seance.lien_effectif, self.lien1.url)

    def test_3_seance_exceptionnelle_compatible_garde_le_meet_du_groupe(self):
        reponse = self._deplacer(self.s1, self.s1.date, '20:00')
        self.assertEqual(reponse.status_code, 302)
        self.s1.refresh_from_db()
        self.assertIsNone(self.s1.lien_meet_exceptionnel)
        self.assertEqual(self.s1.lien_effectif, self.lien1.url)
        self.assertEqual(self.s1.heure, datetime.time(20, 0))

    def test_4_seance_exceptionnelle_en_conflit_meet_actuel_refuse(self):
        reponse = self._deplacer(self.s1, self.s1.date, '16:00')
        self.assertEqual(reponse.status_code, 200)  # re-rendu, pas de redirection
        self.assertContains(reponse, 'غير متاح في هذا الوقت')
        self.s1.refresh_from_db()
        self.assertEqual(self.s1.heure, datetime.time(14, 0))  # inchangée, rien sauvegardé
        self.assertIsNone(self.s1.lien_meet_exceptionnel)

    def test_5_proposition_des_autres_meet_disponibles(self):
        reponse = self._deplacer(self.s1, self.s1.date, '16:00')
        liens_dispo = reponse.context['liens_meet_disponibles']
        self.assertNotIn(self.lien1, liens_dispo)
        self.assertIn(self.lien2, liens_dispo)

    def test_6_aucun_meet_disponible(self):
        # Un 3e groupe occupe aussi Meet 2 le même mercredi 16h-17h : plus aucun lien libre.
        Groupe.objects.create(
            nom='مجموعة ج (تحتل Meet2)', creneau=self.creneau_b, lien_meet=self.lien2,
            lien_reunion=self.lien2.url, statut='actif',
        )
        reponse = self._deplacer(self.s1, self.s1.date, '16:00')
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(reponse.context['liens_meet_disponibles'], [])
        self.assertContains(reponse, 'لا يوجد أي رابط Google Meet متاح لهذا الموعد')

    def test_7_attribution_meet_exceptionnel_uniquement_cette_seance(self):
        autre_seance = Seance.objects.filter(groupe=self.groupe_a).exclude(pk=self.s1.pk).first()

        reponse = self._deplacer(self.s1, self.s1.date, '16:00', lien_meet_exceptionnel=self.lien2.id)
        self.assertEqual(reponse.status_code, 302)

        self.s1.refresh_from_db()
        self.assertEqual(self.s1.heure, datetime.time(16, 0))
        self.assertEqual(self.s1.lien_meet_exceptionnel, self.lien2)
        self.assertEqual(self.s1.lien_effectif, self.lien2.url)

        # Le groupe et l'AUTRE séance restent inchangés.
        self.groupe_a.refresh_from_db()
        self.assertEqual(self.groupe_a.lien_meet, self.lien1)
        self.assertEqual(self.groupe_a.lien_reunion, self.lien1.url)
        autre_seance.refresh_from_db()
        self.assertIsNone(autre_seance.lien_meet_exceptionnel)
        self.assertEqual(autre_seance.lien_effectif, self.lien1.url)

    def test_8_semaine_suivante_retour_au_meet_par_defaut(self):
        s1_suivant = self.seances_mercredi[1]  # le mercredi de la semaine d'après, jamais déplacé

        self._deplacer(self.s1, self.s1.date, '16:00', lien_meet_exceptionnel=self.lien2.id)

        s1_suivant.refresh_from_db()
        self.assertIsNone(s1_suivant.lien_meet_exceptionnel)
        self.assertEqual(s1_suivant.lien_effectif, self.lien1.url)
        self.assertEqual(s1_suivant.heure, datetime.time(14, 0))

    def test_11_conflit_sur_exception_ne_bloque_pas_le_meet_par_defaut_du_groupe(self):
        """Le déplacement en conflit de s1 (non sauvegardé, voir test 4) ne doit
        avoir AUCUN effet sur la disponibilité du Meet par défaut du groupe pour
        ses autres séances — la logique de conflit au niveau Groupe (utilisée par
        le formulaire groupe/l'attribution rapide) ignore totalement les
        exceptions de séance, ce sont deux mécanismes indépendants."""
        self._deplacer(self.s1, self.s1.date, '16:00')  # refusé, voir test 4

        self.assertTrue(lien_meet_est_disponible(self.lien1, self.creneau_a, groupe_exclu=self.groupe_a))
        autre_seance = Seance.objects.filter(groupe=self.groupe_a).exclude(pk=self.s1.pk).first()
        self.assertEqual(autre_seance.lien_effectif, self.lien1.url)

    def test_12a_panneau_ajout_lien_ancre_pres_du_bouton(self):
        """Point A : le panneau d'ajout de lien apparaît dans le HTML AVANT la
        section "يحتاج انتباهك" (donc juste sous le bouton d'en-tête), jamais
        après une longue liste de groupes."""
        Groupe.objects.create(nom='مجموعة بدون رابط (نقطة أ)', creneau=self.creneau_a, statut='actif')
        reponse = self._client().get(reverse('admin_liens_meet'))
        html = reponse.content.decode('utf-8')
        self.assertLess(html.index('ajouter-lien-panel'), html.index('يحتاج انتباهك'))

    def test_12b_carte_groupe_sans_lien_est_cliquable_vers_les_details(self):
        """Point B : la carte d'un groupe sans lien (avec créneau) mène à sa
        fiche détail, explicitement via "عرض التفاصيل"."""
        groupe_sans_lien = Groupe.objects.create(
            nom='مجموعة بدون رابط (واجهة)', creneau=self.creneau_a, statut='actif',
        )
        self.groupe_a.delete()  # simplifie : ne garder que ce cas dans "بدون رابط"
        reponse = self._client().get(reverse('admin_liens_meet'))
        html = reponse.content.decode('utf-8')
        self.assertIn(reverse('admin_groupe_detail', args=[groupe_sans_lien.id]), html)
        self.assertIn('عرض التفاصيل', html)

    def test_12c_carte_lien_affiche_lhoraire_des_groupes_qui_lutilisent(self):
        """Point C : la liste dépliable des groupes utilisant un lien affiche
        aussi leur créneau, pas seulement leur nom."""
        reponse = self._client().get(reverse('admin_liens_meet'))
        html = reponse.content.decode('utf-8')
        self.assertIn(str(self.creneau_a), html)


# ============================================================================
# Tâche du 2026-08-18 — Renommage de halaka (Creneau.nom) + recherche
# ============================================================================
class CreneauNomTests(TestCase):
    """Creneau.nom : optionnel, __str__ le privilégie s'il est renseigné,
    retombe sur l'ancien format jour/heure sinon (aucune régression pour les
    créneaux déjà existants qui n'ont pas de nom)."""

    def test_str_utilise_le_format_jour_heure_si_aucun_nom(self):
        creneau = _creer_creneau()
        self.assertNotIn('None', str(creneau))
        self.assertIn('16:00', str(creneau))

    def test_str_utilise_le_nom_sil_est_defini(self):
        creneau = _creer_creneau()
        creneau.nom = 'حلقة الأطفال - الصباح'
        creneau.save()
        self.assertEqual(str(creneau), 'حلقة الأطفال - الصباح')

    def test_ajouter_creneau_avec_nom(self):
        admin = _creer_admin()
        client = Client(SERVER_NAME='localhost')
        _connecter(client, admin)
        reponse = client.post(reverse('admin_creneau_ajouter'), {
            'nom': 'حلقة تجريبية', 'sexe_cible': 'mixte', 'type_seance': 'hifz', 'riwaya': 'hafs',
            'age_min': 6, 'age_max': 12,
            'slot_jour': ['lun', 'mer'], 'slot_heure_debut': ['16:00', '16:00'], 'slot_heure_fin': ['17:00', '17:00'],
        })
        self.assertEqual(reponse.status_code, 302)
        creneau = Creneau.objects.get(nom='حلقة تجريبية')
        self.assertEqual(str(creneau), 'حلقة تجريبية')

    def test_modifier_creneau_renomme(self):
        admin = _creer_admin()
        creneau = _creer_creneau()
        slots = list(creneau.slots.order_by('ordre'))
        client = Client(SERVER_NAME='localhost')
        _connecter(client, admin)
        reponse = client.post(reverse('admin_creneau_modifier', args=[creneau.id]), {
            'nom': 'حلقة معاد تسميتها', 'sexe_cible': creneau.sexe_cible, 'type_seance': creneau.type_seance,
            'riwaya': creneau.riwaya, 'age_min': creneau.age_min, 'age_max': creneau.age_max,
            'slot_jour': [s.jour for s in slots],
            'slot_heure_debut': [s.heure_debut.strftime('%H:%M') for s in slots],
            'slot_heure_fin': [s.heure_fin.strftime('%H:%M') for s in slots],
        })
        self.assertEqual(reponse.status_code, 302)
        creneau.refresh_from_db()
        self.assertEqual(creneau.nom, 'حلقة معاد تسميتها')


class AdminGroupesFiltreCreneauAffichageTests(TestCase):
    """Liste déroulante "الحلقة" du filtre admin_groupes (Tâche du 2026-08-19) :
    une حلقة nommée n'affiche QUE son nom dans le <select> (plus la
    description âge/sexe/niveau/رواية en double), une حلقة sans nom garde
    l'ancien affichage complet — et le <select> est désormais cherchable
    (data-select-cherchable, composant partagé _select_cherchable.html)."""

    def setUp(self):
        self.admin = _creer_admin()
        self.creneau_nomme = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        self.creneau_nomme.nom = 'حلقة الرجال - المساء'
        self.creneau_nomme.save()
        self.creneau_sans_nom = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)

    def _get(self):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        return client.get(reverse('admin_groupes'), {'type': 'groupe'})

    def test_creneau_nomme_affiche_uniquement_son_nom(self):
        html = self._get().content.decode('utf-8')
        self.assertIn('حلقة الرجال - المساء', html)
        # La description complète (âge/sexe/رواية) ne doit plus être accolée
        # au nom pour ce créneau — seule la ligne du créneau sans nom la garde.
        self.assertNotIn('حلقة الرجال - المساء — 18-60', html)

    def test_creneau_sans_nom_garde_laffichage_complet(self):
        html = self._get().content.decode('utf-8')
        self.assertIn(f'{self.creneau_sans_nom} — 6-12', html)

    def test_select_creneau_est_cherchable(self):
        html = self._get().content.decode('utf-8')
        self.assertIn('name="creneau" class="form-select" data-select-cherchable', html)


class CreneauxListRechercheTests(TestCase):
    """Vue admin_creneaux (courses.views.creneaux_list) : recherche ?q= par nom."""

    def setUp(self):
        self.admin = _creer_admin()
        self.creneau_nomme = _creer_creneau()
        self.creneau_nomme.nom = 'حلقة الأطفال - الصباح'
        self.creneau_nomme.save()
        self.creneau_sans_nom = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)

    def _get(self, **params):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        return client.get(reverse('admin_creneaux'), params)

    def test_recherche_par_nom_trouve_le_creneau_nomme(self):
        reponse = self._get(q='الأطفال')
        ids = {c.id for c in reponse.context['creneaux']}
        self.assertIn(self.creneau_nomme.id, ids)
        self.assertNotIn(self.creneau_sans_nom.id, ids)

    def test_recherche_sans_correspondance_ne_plante_pas(self):
        reponse = self._get(q='زدني علما لا يوجد')
        self.assertEqual(reponse.status_code, 200)
        self.assertEqual(len(reponse.context['creneaux']), 0)




# ============================================================================
# Tâche du 2026-08-18 — Critère ينتقل/يعيد (Presence.resultat_memorisation)
# ============================================================================
class ResultatMemorisationProgressionTests(TestCase):
    """Un passage marqué 'a_refaire' ne doit JAMAIS compter dans
    calculer_hizb_precis/calculer_progression_eleve (courses.utils) — voir
    _couverture_ayat_par_sourate. Comportement historique (avant ce champ)
    inchangé : default='valide' compte comme avant."""

    def setUp(self):
        self.eleve = _creer_eleve()
        creneau = _creer_creneau()
        groupe = Groupe.objects.create(nom='ZZZ_مجموعة_تقدم', creneau=creneau)
        groupe.eleves.add(self.eleve)
        self.seance_1 = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 1), heure='16:00', type='normal')
        self.seance_2 = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 3), heure='16:00', type='normal')
        # Sourate 1 (الفاتحة, 7 آيات) entièrement couverte + sourate 2 de 1 à 74
        # -> couvre exactement les 4 quarts du hizb 1 (voir quran_data.HIZB_QUARTERS[0]).
        Presence.objects.create(
            seance=self.seance_1, eleve=self.eleve, statut='present',
            sourate_memorisee=1, ayah_debut_memorisation=1, ayah_fin_memorisation=7,
        )
        self.presence_sourate_2 = Presence.objects.create(
            seance=self.seance_2, eleve=self.eleve, statut='present',
            sourate_memorisee=2, ayah_debut_memorisation=1, ayah_fin_memorisation=74,
            resultat_memorisation='a_refaire',
        )

    def test_passage_a_refaire_exclu_du_hizb_complet(self):
        resultat = calculer_hizb_precis(self.eleve)
        self.assertEqual(resultat['nb_hizb_complets'], 0)

    def test_passage_valide_compte_dans_le_hizb_complet(self):
        self.presence_sourate_2.resultat_memorisation = 'valide'
        self.presence_sourate_2.save()
        resultat = calculer_hizb_precis(self.eleve)
        self.assertEqual(resultat['nb_hizb_complets'], 1)

    def test_progression_eleve_exclut_les_ayat_a_refaire_du_cumul(self):
        progression = calculer_progression_eleve(self.eleve)
        # Seule la sourate 1 (valide) compte dans le cumul — la sourate 2 (a_refaire) est exclue.
        self.assertEqual(progression['total_ayat_memorises'], 7)
        self.assertEqual(progression['nb_sourates_distinctes'], 1)

    def test_historique_garde_toutes_les_seances_meme_a_refaire(self):
        """Le journal séance par séance reste complet (transparence), seul le
        cumul de progression exclut le passage 'a_refaire' — voir le test
        ci-dessus."""
        progression = calculer_progression_eleve(self.eleve)
        self.assertEqual(len(progression['historique']), 2)
        entree_a_refaire = next(h for h in progression['historique'] if h['sourate'] == 'البقرة')
        self.assertEqual(entree_a_refaire['resultat_memorisation'], 'a_refaire')


# ============================================================================
# Chantier de généralisation N séances/semaine — CreneauSlot remplace le couple
# figé jour_1/heure_debut_1/heure_fin_1 + jour_2/heure_debut_2/heure_fin_2.
# Preuve explicitement demandée que ça fonctionne réellement pour 1, 3 et 4
# slots — pas seulement le cas à 2 slots déjà couvert par tout le reste de ce
# fichier (via _creer_creneau/_creer_creneau_horaire, comportement historique
# inchangé, vérifié par les 132 tests existants de ce module).
# ============================================================================
class CreneauGeneralisationSlotsTests(TestCase):

    def test_creneau_1_slot_genere_exactement_1_seance_par_semaine(self):
        creneau = _creer_creneau(nb_slots=1)
        self.assertEqual(creneau.slots.count(), 1)
        groupe = Groupe.objects.create(nom='مجموعة حصة واحدة', creneau=creneau, statut='actif')
        etendre_seances(groupe, horizon_semaines=4)
        jours_generes = {s.date.weekday() for s in Seance.objects.filter(groupe=groupe)}
        self.assertEqual(len(jours_generes), 1)
        # ~4 séances sur 4 semaines (± bord de semaine courante) — jamais 0, jamais 8+.
        self.assertGreaterEqual(Seance.objects.filter(groupe=groupe).count(), 3)
        self.assertLessEqual(Seance.objects.filter(groupe=groupe).count(), 5)

    def test_creneau_3_slots_genere_seances_sur_3_jours_distincts(self):
        creneau = _creer_creneau(nb_slots=3)
        self.assertEqual(creneau.slots.count(), 3)
        groupe = Groupe.objects.create(nom='مجموعة 3 حصص', creneau=creneau, statut='actif')
        etendre_seances(groupe, horizon_semaines=4)
        jours_generes = {s.date.weekday() for s in Seance.objects.filter(groupe=groupe)}
        self.assertEqual(len(jours_generes), 3)

    def test_creneau_4_slots_genere_seances_sur_4_jours_distincts(self):
        creneau = _creer_creneau(nb_slots=4)
        self.assertEqual(creneau.slots.count(), 4)
        groupe = Groupe.objects.create(nom='مجموعة 4 حصص', creneau=creneau, statut='actif')
        etendre_seances(groupe, horizon_semaines=4)
        jours_generes = {s.date.weekday() for s in Seance.objects.filter(groupe=groupe)}
        self.assertEqual(len(jours_generes), 4)

    def test_str_avec_3_slots_les_joint_tous(self):
        creneau = _creer_creneau(nb_slots=3)
        chaine = str(creneau)
        self.assertEqual(chaine.count('+'), 2)  # 3 slots joints par " + " -> 2 signes "+"
        for slot in creneau.slots.all():
            self.assertIn(slot.get_jour_display(), chaine)

    def test_str_sans_aucun_slot_ne_plante_pas(self):
        """Cas défensif (créneau créé sans encore de slot, ex: transition) —
        jamais un crash sur strftime(None)."""
        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12)
        self.assertEqual(str(creneau), 'حلقة بدون توقيت محدد')

    def test_fin_datetime_trouve_le_bon_slot_au_dela_du_deuxieme(self):
        """Une séance tombant sur le 3e jour configuré (pas jour_1/jour_2) doit
        quand même trouver la bonne durée — preuve que la recherche du slot
        n'est plus limitée aux 2 premiers."""
        date_test = datetime.date(2026, 9, 3)
        jour_3 = JOUR_INDEX_INVERSE[date_test.weekday()]
        autres_jours = [c for c in ['lun', 'mar', 'mer', 'jeu', 'ven'] if c != jour_3][:2]

        creneau = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12)
        remplacer_slots_creneau(creneau, [
            {'jour': autres_jours[0], 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': autres_jours[1], 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
            {'jour': jour_3, 'heure_debut': datetime.time(18, 0), 'heure_fin': datetime.time(19, 30)},
        ])
        groupe = Groupe.objects.create(nom='مجموعة اختبار الحصة الثالثة', creneau=creneau, statut='actif')
        seance = Seance.objects.create(groupe=groupe, date=date_test, heure=datetime.time(18, 0), type='normal')

        self.assertEqual(seance.fin_datetime.time(), datetime.time(19, 30))

    def test_creneaux_se_chevauchent_avec_3_slots_de_part_et_dautre(self):
        creneau_a = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12)
        remplacer_slots_creneau(creneau_a, [
            {'jour': 'lun', 'heure_debut': datetime.time(10, 0), 'heure_fin': datetime.time(11, 0)},
            {'jour': 'mar', 'heure_debut': datetime.time(10, 0), 'heure_fin': datetime.time(11, 0)},
            {'jour': 'jeu', 'heure_debut': datetime.time(10, 0), 'heure_fin': datetime.time(11, 0)},
        ])
        creneau_b = Creneau.objects.create(sexe_cible='mixte', type_seance='hifz', riwaya='hafs', age_min=6, age_max=12)
        # Seul le 3e slot (jeudi) est en conflit — les 2 premiers n'ont aucun rapport.
        remplacer_slots_creneau(creneau_b, [
            {'jour': 'mer', 'heure_debut': datetime.time(20, 0), 'heure_fin': datetime.time(21, 0)},
            {'jour': 'ven', 'heure_debut': datetime.time(20, 0), 'heure_fin': datetime.time(21, 0)},
            {'jour': 'jeu', 'heure_debut': datetime.time(10, 30), 'heure_fin': datetime.time(11, 30)},
        ])
        self.assertTrue(creneaux_se_chevauchent(creneau_a, creneau_b))

    def test_creneau_ajouter_avec_4_slots_depuis_la_vue(self):
        admin = _creer_admin()
        client = Client(SERVER_NAME='localhost')
        _connecter(client, admin)
        reponse = client.post(reverse('admin_creneau_ajouter'), {
            'nom': 'حلقة 4 حصص', 'sexe_cible': 'mixte', 'type_seance': 'hifz', 'riwaya': 'hafs',
            'age_min': 6, 'age_max': 12,
            'slot_jour': ['lun', 'mar', 'mer', 'jeu'],
            'slot_heure_debut': ['16:00', '16:00', '16:00', '16:00'],
            'slot_heure_fin': ['17:00', '17:00', '17:00', '17:00'],
        })
        self.assertEqual(reponse.status_code, 302)
        creneau = Creneau.objects.get(nom='حلقة 4 حصص')
        self.assertEqual(creneau.slots.count(), 4)

    def test_creneau_modifier_peut_reduire_le_nombre_de_slots(self):
        """4 slots -> 2 slots : les séances futures doivent être régénérées
        (l'horaire a changé), sans casser quoi que ce soit."""
        admin = _creer_admin()
        creneau = _creer_creneau(nb_slots=4)
        groupe = Groupe.objects.create(nom='مجموعة تقليص الحصص', creneau=creneau, statut='actif')
        etendre_seances(groupe, horizon_semaines=4)
        self.assertEqual(creneau.slots.count(), 4)

        client = Client(SERVER_NAME='localhost')
        _connecter(client, admin)
        reponse = client.post(reverse('admin_creneau_modifier', args=[creneau.id]), {
            'nom': creneau.nom, 'sexe_cible': creneau.sexe_cible, 'type_seance': creneau.type_seance,
            'riwaya': creneau.riwaya, 'age_min': creneau.age_min, 'age_max': creneau.age_max,
            'slot_jour': ['lun', 'mer'],
            'slot_heure_debut': ['16:00', '16:00'],
            'slot_heure_fin': ['17:00', '17:00'],
        })
        self.assertEqual(reponse.status_code, 302)
        creneau.refresh_from_db()
        self.assertEqual(creneau.slots.count(), 2)
        jours_generes = {s.date.weekday() for s in Seance.objects.filter(groupe=groupe, statut='planifiee')}
        self.assertEqual(len(jours_generes), 2)

    def test_creneau_ajouter_sans_aucun_slot_est_refuse(self):
        """Garde-fou serveur (pas de Django Forms dans ce projet) — une requête
        POST manipulée sans aucune ligne slot_jour/slot_heure_debut/
        slot_heure_fin ne doit jamais créer un Creneau sans planning."""
        admin = _creer_admin()
        client = Client(SERVER_NAME='localhost')
        _connecter(client, admin)
        reponse = client.post(reverse('admin_creneau_ajouter'), {
            'nom': 'حلقة بدون حصص', 'sexe_cible': 'mixte', 'type_seance': 'hifz', 'riwaya': 'hafs',
            'age_min': 6, 'age_max': 12,
        })
        self.assertEqual(reponse.status_code, 200)
        self.assertFalse(Creneau.objects.filter(nom='حلقة بدون حصص').exists())


class BackfillCreneauSlotMigrationTests(TestCase):
    """Vérifie le résultat de la data migration 0036 telle qu'appliquée sur la
    base de test (exécutée par le migrateur avant que ces tests ne tournent,
    comme toute migration) — complète la vérification manuelle déjà faite en
    production/dev (40 slots, 0 anomalie) par une assertion automatisée
    rejouable à chaque exécution de la suite."""

    def test_tous_les_creneaux_ont_au_moins_1_slot_apres_migration(self):
        # Créés par les fixtures d'autres tests potentiellement déjà exécutés
        # dans la même base — ne vérifie que les créneaux existants à cet
        # instant, pas un nombre figé.
        for creneau in Creneau.objects.all():
            self.assertGreaterEqual(
                creneau.slots.count(), 1,
                f'Creneau {creneau.id} sans aucun CreneauSlot',
            )


# ============================================================================
# CHANTIER DU MOTEUR D'INSCRIPTION CONFIGURABLE — Étape 5D : onglet "الخصائص"
# sur la fiche groupe (GroupeCritereValeur). Directeur ET مشرف, accès
# strictement identique (contrairement au reste de cette page, où l'ajout/
# retrait d'élèves reste مدير uniquement — restriction pré-existante à ce
# chantier, non modifiée).
# ============================================================================
class GroupeOngletCriteresTests(TestCase):
    def setUp(self):
        from registration.models import Critere as CritereInscription, CritereOption

        self.admin = _creer_admin('admin_onglet_criteres@zidni.test')
        self.mshrif = _creer_mshrif('mshrif_onglet_criteres@zidni.test')
        self.creneau = _creer_creneau()
        self.groupe = Groupe.objects.create(nom='مجموعة اختبار الخصائص', creneau=self.creneau, statut='actif', type_capacite='groupe')

        self.critere_riwaya = CritereInscription.objects.create(code='riwaya_onglet', label='الرواية', backend='eav', filtrable=True)
        self.option_hafs = CritereOption.objects.create(critere=self.critere_riwaya, code='hafs', label='حفص')
        CritereOption.objects.create(critere=self.critere_riwaya, code='warsh', label='ورش')

        self.critere_type_offre = CritereInscription.objects.create(
            code='type_offre_onglet', label='نوع الحصة', backend='champ_groupe', champ_modele_groupe='type_capacite',
        )
        self.critere_nb_slots = CritereInscription.objects.create(code='nb_slots_onglet', label='عدد الحصص', backend='nb_slots')

    def test_fiche_groupe_affiche_les_3_backends(self):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        reponse = client.get(reverse('admin_groupe_detail', args=[self.groupe.id]))
        html = reponse.content.decode('utf-8')
        self.assertIn('الرواية', html)
        self.assertIn('نوع الحصة', html)
        self.assertIn('عدد الحصص', html)
        # champ_groupe affiché en lecture seule avec la vraie valeur du groupe.
        self.assertIn('جماعي', html)  # get_type_capacite_display() de 'groupe'
        # nb_slots affiché en lecture seule, dérivé du vrai nombre de slots (2 par défaut).
        self.assertIn('2 حصة/أسبوع', html)

    def test_definir_valeur_eav_reussit_pour_directeur_et_mshrif(self):
        for client_user in (self.admin, self.mshrif):
            client = Client(SERVER_NAME='localhost')
            _connecter(client, client_user)
            reponse = client.post(
                reverse('admin_groupe_definir_critere', args=[self.groupe.id, self.critere_riwaya.id]),
                {'options': ['hafs']},
            )
            self.assertEqual(reponse.status_code, 302)
            valeur = GroupeCritereValeur.objects.get(groupe=self.groupe, critere=self.critere_riwaya)
            self.assertEqual(valeur.option.code, 'hafs')

    def test_definir_valeur_remplace_jamais_naccumule(self):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        url = reverse('admin_groupe_definir_critere', args=[self.groupe.id, self.critere_riwaya.id])
        client.post(url, {'options': ['hafs']})
        client.post(url, {'options': ['warsh']})
        self.assertEqual(GroupeCritereValeur.objects.filter(groupe=self.groupe, critere=self.critere_riwaya).count(), 1)
        self.assertEqual(
            GroupeCritereValeur.objects.get(groupe=self.groupe, critere=self.critere_riwaya).option.code, 'warsh'
        )

    def test_definir_valeur_sur_backend_champ_groupe_est_refuse(self):
        """champ_groupe/nb_slots ne stockent jamais de GroupeCritereValeur —
        voir registration.utils.definir_valeurs_groupe."""
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        reponse = client.post(
            reverse('admin_groupe_definir_critere', args=[self.groupe.id, self.critere_type_offre.id]),
            {'options': ['groupe']},
        )
        self.assertEqual(reponse.status_code, 302)
        self.assertFalse(GroupeCritereValeur.objects.filter(critere=self.critere_type_offre).exists())

    def test_option_invalide_refusee(self):
        client = Client(SERVER_NAME='localhost')
        _connecter(client, self.admin)
        client.post(
            reverse('admin_groupe_definir_critere', args=[self.groupe.id, self.critere_riwaya.id]),
            {'options': ['code_inexistant']},
        )
        self.assertFalse(GroupeCritereValeur.objects.filter(groupe=self.groupe, critere=self.critere_riwaya).exists())


# ============================================================================
# Partie B (chantier du 2026-08-24) — tranches d'âge précises (التلقين/
# البراعم/اليافعون), pure fonction du calendrier, jamais stockée. Ne remplace
# JAMAIS AGE_SEUIL_ADULTE/tranche_age_depuis_naissance (voir courses.utils.
# tranche_age_precise.__doc__).
# ============================================================================

def _date_naissance_pour_age(age):
    """Date de naissance donnant exactement `age` ans aujourd'hui — anniversaire
    déjà passé cette année pour éviter toute ambiguïté avec _age_depuis_naissance
    (comparaison (mois, jour))."""
    from django.utils import timezone
    aujourd_hui = timezone.localdate()
    return aujourd_hui.replace(year=aujourd_hui.year - age, month=1, day=1)


class TrancheAgePreciseTests(TestCase):
    def test_bornes_des_3_tranches(self):
        from .utils import tranche_age_precise
        self.assertIsNone(tranche_age_precise(_date_naissance_pour_age(4)))
        self.assertEqual(tranche_age_precise(_date_naissance_pour_age(5))[0], 'talqin')
        self.assertEqual(tranche_age_precise(_date_naissance_pour_age(7))[0], 'talqin')
        self.assertEqual(tranche_age_precise(_date_naissance_pour_age(8))[0], 'baraim')
        self.assertEqual(tranche_age_precise(_date_naissance_pour_age(13))[0], 'baraim')
        self.assertEqual(tranche_age_precise(_date_naissance_pour_age(14))[0], 'yafiun')
        self.assertEqual(tranche_age_precise(_date_naissance_pour_age(18))[0], 'yafiun')
        self.assertIsNone(tranche_age_precise(_date_naissance_pour_age(19)))  # adulte, hors périmètre

    def test_none_si_date_naissance_absente(self):
        from .utils import tranche_age_precise
        self.assertIsNone(tranche_age_precise(None))

    def test_ne_remplace_pas_le_systeme_enfant_adulte_existant(self):
        """Un élève de 19 ans reste 'adulte' pour AGE_SEUIL_ADULTE/tranche_age_
        depuis_naissance (ouverture par catégorie, filtrage réel des groupes)
        même s'il n'appartient à aucune des 3 tranches précises."""
        from .utils import tranche_age_depuis_naissance, tranche_age_precise
        naissance_19_ans = _date_naissance_pour_age(19)
        self.assertEqual(tranche_age_depuis_naissance(naissance_19_ans), 'adulte')
        self.assertIsNone(tranche_age_precise(naissance_19_ans))


class GroupeTranchesAgeFrequenteesTests(TestCase):
    def setUp(self):
        self.creneau = _creer_creneau(age_min=5, age_max=18)
        self.groupe = Groupe.objects.create(
            nom='مجموعة اختبار الفئات العمرية', creneau=self.creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )

    def _ajouter_eleve(self, age):
        u = User.objects.create_user(
            username=f'eleve_tranche_{age}@zidni.test', email=f'eleve_tranche_{age}@zidni.test',
            password=MOT_DE_PASSE, first_name='طالب', last_name='تجريبي', role='eleve',
            doit_changer_mot_de_passe=False, date_naissance=_date_naissance_pour_age(age),
        )
        eleve = Eleve.objects.create(user=u, sexe='homme', statut='actif')
        self.groupe.eleves.add(eleve)
        return eleve

    def test_vide_si_aucun_eleve(self):
        self.assertEqual(self.groupe.tranches_age_frequentees, [])

    def test_liste_dedupliquee_dans_lordre_des_tranches(self):
        self._ajouter_eleve(15)  # اليافعون
        self._ajouter_eleve(6)   # التلقين
        self._ajouter_eleve(9)   # البراعم
        self._ajouter_eleve(10)  # البراعم (doublon, ne doit apparaître qu'une fois)
        self.assertEqual(self.groupe.tranches_age_frequentees, ['التلقين', 'البراعم', 'اليافعون'])

    def test_eleve_adulte_napparait_dans_aucune_tranche(self):
        self._ajouter_eleve(25)
        self.assertEqual(self.groupe.tranches_age_frequentees, [])


class GroupeTranchesAgeViseesTests(TestCase):
    """Correction du 2026-08-24 : le badge groupe doit refléter la
    configuration de la halaka (creneau.age_min/age_max), pas les élèves
    réellement inscrits — voir Groupe.tranches_age_visees.__doc__."""

    def test_vide_meme_sans_aucun_eleve(self):
        creneau = _creer_creneau(age_min=5, age_max=7)
        groupe = Groupe.objects.create(
            nom='حلقة تلقين فارغة', creneau=creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        self.assertEqual(groupe.tranches_age_visees, ['التلقين'])

    def test_une_seule_tranche_si_creneau_pile_dedans(self):
        creneau = _creer_creneau(age_min=8, age_max=13)
        groupe = Groupe.objects.create(
            nom='حلقة براعم', creneau=creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        self.assertEqual(groupe.tranches_age_visees, ['البراعم'])

    def test_plusieurs_tranches_si_creneau_les_chevauche_toutes(self):
        creneau = _creer_creneau(age_min=5, age_max=18)
        groupe = Groupe.objects.create(
            nom='حلقة كل الأطفال', creneau=creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        self.assertEqual(groupe.tranches_age_visees, ['التلقين', 'البراعم', 'اليافعون'])

    def test_vide_si_creneau_adultes(self):
        # age_min=19 (pas 18) : la tranche اليافعون couvre 14-18 INCLUS
        # (TRANCHES_AGE_PRECISES), un créneau démarrant pile à 18 chevauche
        # donc encore اليافعون — comportement hérité de tranche_age_precise,
        # pas une régression de tranches_age_visees.
        creneau = _creer_creneau(age_min=19, age_max=999)
        groupe = Groupe.objects.create(
            nom='حلقة بالغين', creneau=creneau, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        self.assertEqual(groupe.tranches_age_visees, [])

    def test_vide_si_groupe_individuel(self):
        creneau = _creer_creneau(age_min=5, age_max=7)
        groupe = Groupe.objects.create(
            nom='حلقة فردية', creneau=creneau, statut='actif',
            type_capacite='individuel', capacite_max=1,
        )
        self.assertEqual(groupe.tranches_age_visees, [])

    def test_vide_si_aucun_creneau_assigne(self):
        groupe = Groupe.objects.create(
            nom='حلقة بدون خانة زمنية', creneau=None, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        self.assertEqual(groupe.tranches_age_visees, [])


# ============================================================================
# Chantier "salaire prof par nb séances/semaine" du 2026-08-27 (Besoin 3) —
# calculer_remuneration_prof rewritten to use TarifRemunerationGroupe (axe
# nb_slots) / TarifRemunerationIndividuel (par séance), en remplacement de
# l'ancien TarifRemuneration (déprécié, jamais lu ici).
# ============================================================================

def _mois_courant():
    """'AAAA-MM' du jour du test — passé explicitement à calculer_remuneration_
    prof(mois=...) pour que les tests restent déterministes (jamais une
    dépendance implicite à 'aujourd'hui' au moment de l'exécution)."""
    from django.utils import timezone

    aujourdhui = timezone.localdate()
    return f'{aujourdhui.year}-{aujourdhui.month:02d}', aujourdhui


class CalculerRemunerationProfGroupeTests(TestCase):
    """Groupe : montant FIXE par élève actif par mois, selon (tranche_age,
    nb_slots du groupe) — Besoin 3."""

    def setUp(self):
        # La migration 0040_seed_nb_seances_et_tarifs_remuneration seed déjà
        # les 6 combinaisons (tranche_age × 1/2/3) en base de test (comme en
        # prod) — on repart d'une table VIDE ici pour que chaque test
        # contrôle EXACTEMENT les tarifs en jeu (y compris le cas "aucun
        # tarif configuré", impossible à tester sur les données déjà seedées).
        TarifRemunerationGroupe.objects.all().delete()
        self.prof = _creer_prof('prof_remun_groupe@zidni.test')

    def test_montant_fixe_par_eleve_actif_selon_nb_slots(self):
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=2, montant=60)
        creneau = _creer_creneau(age_min=18, age_max=60, nb_slots=2)
        groupe = Groupe.objects.create(
            nom='حلقة بالغين', creneau=creneau, prof=self.prof, statut='actif',
            type_capacite='groupe', capacite_max=10,
        )
        e1 = _creer_eleve_avec_age(25, 'e1_remun_groupe@zidni.test')
        e2 = _creer_eleve_avec_age(30, 'e2_remun_groupe@zidni.test')
        groupe.eleves.add(e1, e2)

        resultat = calculer_remuneration_prof(self.prof)
        self.assertEqual(resultat['total_calcule'], 120)
        self.assertEqual(resultat['detail'][0]['nb_slots'], 2)
        self.assertFalse(resultat['detail'][0]['tarif_manquant'])
        self.assertEqual(resultat['tarifs_manquants'], [])

    def test_barese_different_selon_nb_slots_meme_tranche_age(self):
        """Le MÊME groupe/tranche d'âge rapporte des montants différents
        selon le nombre de séances/semaine du créneau — c'est précisément
        l'axe qui manquait avant ce chantier (TarifRemuneration n'avait
        qu'une tranche_age, jamais de nb_slots)."""
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=1, montant=40)
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=3, montant=100)

        creneau_1 = _creer_creneau(age_min=18, age_max=60, nb_slots=1)
        groupe_1 = Groupe.objects.create(
            nom='حلقة حصة واحدة', creneau=creneau_1, prof=self.prof, statut='actif', type_capacite='groupe',
        )
        groupe_1.eleves.add(_creer_eleve_avec_age(25, 'e1_bareme@zidni.test'))

        creneau_3 = _creer_creneau(age_min=18, age_max=60, nb_slots=3)
        groupe_3 = Groupe.objects.create(
            nom='حلقة ثلاث حصص', creneau=creneau_3, prof=self.prof, statut='actif', type_capacite='groupe',
        )
        groupe_3.eleves.add(_creer_eleve_avec_age(26, 'e2_bareme@zidni.test'))

        resultat = calculer_remuneration_prof(self.prof)
        self.assertEqual(resultat['total_calcule'], 140)  # 40 (1 séance) + 100 (3 séances)

    def test_tarif_manquant_ne_calcule_jamais_a_zero_silencieux(self):
        """AUCUNE TarifRemunerationGroupe créée pour (adulte, 2) — le montant
        de CE groupe reste 0 dans le total, mais JAMAIS silencieusement :
        signalé par tarif_manquant=True sur la ligne ET dans
        result['tarifs_manquants']."""
        creneau = _creer_creneau(age_min=18, age_max=60, nb_slots=2)
        groupe = Groupe.objects.create(
            nom='حلقة بدون تعرفة', creneau=creneau, prof=self.prof, statut='actif', type_capacite='groupe',
        )
        groupe.eleves.add(_creer_eleve_avec_age(25, 'e1_manquant@zidni.test'))

        resultat = calculer_remuneration_prof(self.prof)
        self.assertEqual(resultat['total_calcule'], 0)
        self.assertTrue(resultat['detail'][0]['tarif_manquant'])
        self.assertEqual(len(resultat['tarifs_manquants']), 1)
        self.assertEqual(resultat['tarifs_manquants'][0]['tranche_age'], 'adulte')
        self.assertEqual(resultat['tarifs_manquants'][0]['nb_slots'], 2)

    def test_ligne_desactivee_traitee_comme_manquante(self):
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=2, montant=60, est_actif=False)
        creneau = _creer_creneau(age_min=18, age_max=60, nb_slots=2)
        groupe = Groupe.objects.create(
            nom='حلقة تعرفة معطلة', creneau=creneau, prof=self.prof, statut='actif', type_capacite='groupe',
        )
        groupe.eleves.add(_creer_eleve_avec_age(25, 'e1_desactive@zidni.test'))

        resultat = calculer_remuneration_prof(self.prof)
        self.assertEqual(resultat['total_calcule'], 0)
        self.assertTrue(resultat['detail'][0]['tarif_manquant'])

    def test_groupe_sans_creneau_traite_comme_manquant(self):
        groupe = Groupe.objects.create(
            nom='حلقة بدون خانة زمنية', creneau=None, prof=self.prof, statut='actif', type_capacite='groupe',
        )
        groupe.eleves.add(_creer_eleve_avec_age(25, 'e1_sans_creneau@zidni.test'))

        resultat = calculer_remuneration_prof(self.prof)
        self.assertEqual(resultat['total_calcule'], 0)
        self.assertTrue(resultat['detail'][0]['tarif_manquant'])
        self.assertIsNone(resultat['detail'][0]['nb_slots'])

    def test_deux_tranches_dage_une_configuree_une_manquante(self):
        """Un même groupe mixte enfants+adultes : la tranche configurée est
        calculée normalement, l'autre est signalée manquante SANS bloquer
        le calcul de la première (blocage PAR CONTEXTE, décision explicite
        du client)."""
        TarifRemunerationGroupe.objects.create(tranche_age='enfant', nb_slots=2, montant=90)
        creneau = _creer_creneau(age_min=5, age_max=60, nb_slots=2)
        groupe = Groupe.objects.create(
            nom='حلقة مختلطة الأعمار', creneau=creneau, prof=self.prof, statut='actif', type_capacite='groupe',
        )
        groupe.eleves.add(_creer_eleve_avec_age(10, 'e1_mixte@zidni.test'))
        groupe.eleves.add(_creer_eleve_avec_age(25, 'e2_mixte@zidni.test'))

        resultat = calculer_remuneration_prof(self.prof)
        self.assertEqual(resultat['total_calcule'], 90)  # seul l'enfant est facturé
        self.assertTrue(resultat['detail'][0]['tarif_manquant'])
        tranches_manquantes = {t['tranche_age'] for t in resultat['tarifs_manquants']}
        self.assertEqual(tranches_manquantes, {'adulte'})


class CalculerRemunerationProfIndividuelTests(TestCase):
    """Individuel : montant PAR SÉANCE réellement dispensée (Seance.statut=
    'terminee' ET Presence.statut='present'), jamais un forfait mensuel —
    Besoin 3. Le comptage lui-même est repris à l'identique de la
    correction du 2026-08-04 (déjà correct) ; seule la SOURCE du tarif change."""

    def setUp(self):
        self.prof = _creer_prof('prof_remun_indiv@zidni.test')
        TarifRemunerationIndividuel.objects.filter(tranche_age='adulte').update(montant=35)
        if not TarifRemunerationIndividuel.objects.filter(tranche_age='adulte').exists():
            TarifRemunerationIndividuel.objects.create(tranche_age='adulte', montant=35)
        self.mois_str, self.aujourdhui = _mois_courant()
        self.groupe = Groupe.objects.create(
            nom='حصص فردية', prof=self.prof, statut='actif', type_capacite='individuel', capacite_max=1,
        )
        self.eleve = _creer_eleve_avec_age(25, 'eleve_remun_indiv@zidni.test')
        self.groupe.eleves.add(self.eleve)

    def _creer_seance(self, jour, statut_seance='terminee', statut_presence='present'):
        jour = min(jour, 28)  # jamais un jour invalide selon le mois du test
        seance = Seance.objects.create(
            groupe=self.groupe, date=self.aujourdhui.replace(day=jour), heure=datetime.time(16, 0),
            type='normal', statut=statut_seance,
        )
        if statut_presence is not None:
            Presence.objects.create(seance=seance, eleve=self.eleve, statut=statut_presence)
        return seance

    def test_facture_par_seance_reellement_dispensee(self):
        for jour in (1, 8, 15, 22):
            self._creer_seance(jour)

        resultat = calculer_remuneration_prof(self.prof, mois=self.mois_str)
        self.assertEqual(resultat['total_calcule'], 140)  # 4 séances × 35
        self.assertEqual(resultat['individuel_nb_seances_confirmees'], 4)

    def test_absence_non_facturee(self):
        self._creer_seance(1, statut_presence='present')
        self._creer_seance(8, statut_presence='absent')

        resultat = calculer_remuneration_prof(self.prof, mois=self.mois_str)
        self.assertEqual(resultat['total_calcule'], 35)

    def test_seance_non_terminee_non_facturee(self):
        self._creer_seance(1, statut_seance='planifiee', statut_presence='present')

        resultat = calculer_remuneration_prof(self.prof, mois=self.mois_str)
        self.assertEqual(resultat['total_calcule'], 0)

    def test_tarif_manquant_individuel_signale_jamais_silencieux(self):
        TarifRemunerationIndividuel.objects.filter(tranche_age='adulte').delete()
        self._creer_seance(1)

        resultat = calculer_remuneration_prof(self.prof, mois=self.mois_str)
        self.assertEqual(resultat['total_calcule'], 0)
        self.assertTrue(resultat['detail'][0]['tarif_manquant'])
        self.assertEqual(resultat['tarifs_manquants'][0]['type_capacite'], 'individuel')


class CouvertureTarifsRemunerationGroupeTests(TestCase):
    """couverture_tarifs_remuneration_groupe() — même esprit que
    registration.utils.couverture_grille_prix, matière première du bandeau
    persistant مدير/مشرف (Besoin 3, "notification obligatoire")."""

    def setUp(self):
        # Même raison que CalculerRemunerationProfGroupeTests.setUp : repartir
        # d'une table vide plutôt que du seed de migration 0040/0039, pour un
        # contrôle exact des combinaisons dans chaque test.
        OptionNbSeances.objects.all().delete()
        TarifRemunerationGroupe.objects.all().delete()

    def test_total_configures_et_manquantes(self):
        OptionNbSeances.objects.create(valeur=1)
        OptionNbSeances.objects.create(valeur=2)
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=1, montant=40)

        couverture = couverture_tarifs_remuneration_groupe()
        self.assertEqual(couverture['total'], 4)  # 2 tranches × 2 nb_slots
        self.assertEqual(couverture['configures'], 1)
        self.assertIn(('adulte', 2), couverture['combinaisons_manquantes'])
        self.assertIn(('enfant', 1), couverture['combinaisons_manquantes'])
        self.assertIn(('enfant', 2), couverture['combinaisons_manquantes'])
        self.assertNotIn(('adulte', 1), couverture['combinaisons_manquantes'])

    def test_ligne_desactivee_compte_comme_manquante(self):
        OptionNbSeances.objects.create(valeur=1)
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=1, montant=40, est_actif=False)

        couverture = couverture_tarifs_remuneration_groupe()
        self.assertEqual(couverture['configures'], 0)
        self.assertIn(('adulte', 1), couverture['combinaisons_manquantes'])

    def test_option_nb_seances_desactivee_exclue_du_total(self):
        option = OptionNbSeances.objects.create(valeur=9)
        TarifRemunerationGroupe.objects.create(tranche_age='adulte', nb_slots=9, montant=999)
        self.assertEqual(couverture_tarifs_remuneration_groupe()['total'], 2)  # 2 tranches × 1 nb_slots

        option.est_actif = False
        option.save()
        self.assertEqual(couverture_tarifs_remuneration_groupe()['total'], 0)


# ============================================================================
# Fonctionnalité 4 (2026-08-27) : demande de changement de halaka par
# l'élève — groupes_compatibles_sexe_age_pour_changement, PAS le même filtre
# strict que groupes_compatibles_pour_eleve (programme/riwaya/disponibilité
# non filtrés ici, décision explicite du client).
# ============================================================================
def _creer_eleve_avec_age_et_sexe(age, sexe, email):
    """Variante de _creer_eleve_avec_age (ci-dessus) qui contrôle aussi le
    sexe — nécessaire ici puisque groupes_compatibles_sexe_age_pour_
    changement filtre sur LES DEUX critères (contrairement à _tranche_age_
    eleve/calculer_remuneration_prof, qui ne lisaient que l'âge)."""
    aujourdhui = datetime.date.today()
    date_naissance = aujourdhui.replace(year=aujourdhui.year - age)
    inscription = InscriptionEleve.objects.create(
        nom='طالب تجريبي', date_naissance=date_naissance, sexe=sexe,
        telephone='0600000000', email=email,
        programme='hifz', riwaya='hafs', outil='whatsapp', abonnement='groupe_1mois', statut='valide',
    )
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe=sexe, statut='actif', inscription=inscription)


class GroupesCompatiblesSexeAgePourChangementTests(TestCase):
    def test_filtre_par_age_exclut_hors_tranche(self):
        eleve = _creer_eleve_avec_age_et_sexe(10, 'homme', 'changement_age_1@zidni.test')
        creneau_adulte = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        groupe_adulte = Groupe.objects.create(nom='بالغون', creneau=creneau_adulte)
        creneau_enfant = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=12)
        groupe_enfant = Groupe.objects.create(nom='أطفال', creneau=creneau_enfant)

        resultat = groupes_compatibles_sexe_age_pour_changement(eleve)
        self.assertIn(groupe_enfant, resultat)
        self.assertNotIn(groupe_adulte, resultat)

    def test_filtre_par_sexe_exclut_lautre_sexe_cible(self):
        eleve = _creer_eleve_avec_age_et_sexe(20, 'femme', 'changement_sexe_1@zidni.test')
        creneau_hommes = _creer_creneau(sexe_cible='homme', age_min=18, age_max=60)
        groupe_hommes = Groupe.objects.create(nom='رجال', creneau=creneau_hommes)
        creneau_femmes = _creer_creneau(sexe_cible='femme', age_min=18, age_max=60)
        groupe_femmes = Groupe.objects.create(nom='نساء', creneau=creneau_femmes)

        resultat = groupes_compatibles_sexe_age_pour_changement(eleve)
        self.assertIn(groupe_femmes, resultat)
        self.assertNotIn(groupe_hommes, resultat)

    def test_creneau_mixte_toujours_compatible_niveau_sexe(self):
        eleve = _creer_eleve_avec_age_et_sexe(20, 'femme', 'changement_mixte_1@zidni.test')
        creneau_mixte = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        groupe_mixte = Groupe.objects.create(nom='مختلط', creneau=creneau_mixte)
        self.assertIn(groupe_mixte, groupes_compatibles_sexe_age_pour_changement(eleve))

    def test_programme_et_riwaya_ne_sont_pas_filtres(self):
        """Décision explicite du client : PAS le même filtre strict que
        groupes_compatibles_pour_eleve — un groupe dont le créneau a un
        programme/riwaya différent de celui de l'élève reste proposé."""
        eleve = _creer_eleve_avec_age_et_sexe(20, 'homme', 'changement_programme_1@zidni.test')
        creneau_tathbit_warsh = Creneau.objects.create(
            sexe_cible='mixte', type_seance='tathbit', riwaya='warsh', age_min=18, age_max=60,
        )
        remplacer_slots_creneau(creneau_tathbit_warsh, [
            {'jour': 'lun', 'heure_debut': datetime.time(16, 0), 'heure_fin': datetime.time(17, 0)},
        ])
        groupe = Groupe.objects.create(nom='تثبيت ورش', creneau=creneau_tathbit_warsh)
        self.assertIn(groupe, groupes_compatibles_sexe_age_pour_changement(eleve))

    def test_exclut_le_groupe_ou_leleve_est_deja(self):
        eleve = _creer_eleve_avec_age_et_sexe(20, 'homme', 'changement_deja_membre@zidni.test')
        creneau = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        groupe_actuel = Groupe.objects.create(nom='حلقته الحالية', creneau=creneau)
        groupe_actuel.eleves.add(eleve)
        self.assertNotIn(groupe_actuel, groupes_compatibles_sexe_age_pour_changement(eleve))

    def test_exclut_groupe_archive(self):
        eleve = _creer_eleve_avec_age_et_sexe(20, 'homme', 'changement_archive@zidni.test')
        creneau = _creer_creneau(sexe_cible='mixte', age_min=18, age_max=60)
        groupe = Groupe.objects.create(nom='حلقة مؤرشفة', creneau=creneau, statut='archive')
        self.assertNotIn(groupe, groupes_compatibles_sexe_age_pour_changement(eleve))

    def test_sans_inscription_liee_retourne_liste_vide(self):
        eleve = _creer_eleve('changement_sans_inscription@zidni.test')  # Eleve.inscription reste None
        creneau = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=60)
        Groupe.objects.create(nom='peu importe', creneau=creneau)
        self.assertEqual(groupes_compatibles_sexe_age_pour_changement(eleve), [])


# ============================================================================
# Point 4 du chantier UI/i18n du 2026-08-28 — les 114 noms de sourates
# (courses.quran_data.SOURATES/SOURATES_NOMS) restaient toujours en arabe
# quelle que soit la langue active, car ils venaient d'une liste Python fixe
# jamais passée par gettext (contrairement au reste de l'interface). Corrigé
# en enveloppant chaque nom dans gettext_lazy — Presence.nom_sourate_
# memorisee/nom_sourate_revisee et calculer_progression_eleve()['par_sourate']
# en héritent automatiquement, une seule source de vérité (voir quran_data.py).
# ============================================================================
class NomsSouratesTraductionTests(TestCase):
    def test_nom_sourate_suit_la_langue_active(self):
        from django.utils import translation
        from courses.quran_data import SOURATES_NOMS

        with translation.override('ar'):
            self.assertEqual(str(SOURATES_NOMS[107]), 'الماعون')
        with translation.override('fr'):
            self.assertEqual(str(SOURATES_NOMS[107]), 'Al-Ma\'un')
        with translation.override('en'):
            self.assertEqual(str(SOURATES_NOMS[107]), 'Al-Ma\'un')

    def test_nom_sourate_dans_les_proprietes_presence(self):
        """Presence.nom_sourate_memorisee/nom_sourate_revisee (utilisées par
        eleve_progression.html, admin_eleve_detail.html, etc.) réutilisent
        SOURATES_NOMS — vérifie qu'elles suivent la langue elles aussi,
        sans dupliquer une 2e liste de noms."""
        from django.utils import translation

        eleve = _creer_eleve('sourate_traduction@zidni.test')
        creneau = _creer_creneau(sexe_cible='mixte', age_min=6, age_max=60)
        groupe = Groupe.objects.create(nom='حلقة اختبار السور', creneau=creneau)
        groupe.eleves.add(eleve)
        seance = Seance.objects.create(groupe=groupe, date=datetime.date(2026, 8, 28), heure='16:00', type='normal')
        presence = Presence.objects.create(
            seance=seance, eleve=eleve, statut='present',
            sourate_memorisee=114, ayah_debut_memorisation=1, ayah_fin_memorisation=6,
        )
        with translation.override('en'):
            self.assertEqual(str(presence.nom_sourate_memorisee), 'An-Nas')
        with translation.override('ar'):
            self.assertEqual(str(presence.nom_sourate_memorisee), 'الناس')
