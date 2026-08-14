from django.conf import settings
from django.test import TestCase, override_settings
from django.urls import reverse

from accounts.models import User, Eleve, Prof
from inscriptions.models import InscriptionEleve, InscriptionProf


# En production, 'staticfiles' utilise whitenoise.storage.CompressedManifestStaticFilesStorage
# (voir core/settings.py), qui exige un manifeste généré par collectstatic — jamais lancé en
# local/tests. Sans cet override, le simple fait de charger n'importe quelle page (logo dans le
# header, via accounts.context_processors.logo_context) lève une ValueError ici. Retombe sur le
# stockage simple (pas de hash, pas de manifeste) — sans rapport avec ce qu'on teste.
@override_settings(STORAGES={
    **settings.STORAGES,
    'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'},
})
class ChampsInscriptionVisiblesTests(TestCase):
    """Audit du 2026-08-09 : job_actuel n'apparaissait pas sur la page de
    candidature élève (avant validation) alors qu'il était déjà affiché sur
    la fiche finale — passé inaperçu pendant des semaines. Ces tests
    garantissent que ça ne peut plus se reproduire, de deux façons :

    1. Pour chaque champ d'InscriptionEleve/InscriptionProf qu'on sait
       actuellement affiché quelque part, on vérifie que sa VALEUR apparaît
       réellement dans le HTML rendu des pages concernées (candidature ET
       fiche finale) — pas juste que le code semble correct.
    2. CHAMPS_CONNUS_* liste EXPLICITEMENT tous les champs du modèle, classés
       'affiché' ou 'exclu (+ raison)'. test_aucun_champ_inconnu_* compare
       cette liste à Model._meta.fields : si quelqu'un ajoute un nouveau
       champ au modèle sans mettre à jour cette liste, ce test échoue
       immédiatement — impossible qu'un futur champ passe inaperçu comme
       job_actuel l'a fait, silencieusement.
    """

    @classmethod
    def setUpTestData(cls):
        cls.admin = User.objects.create_user(
            username='admin_test_champs@zidni.test',
            email='admin_test_champs@zidni.test',
            password='xX!test12345',
            role='admin',
            # Sinon ForcerChangementMotDePasseMiddleware redirige (302, corps
            # vide) toute requête vers la page de changement de mot de passe
            # avant d'atteindre la page testée.
            doit_changer_mot_de_passe=False,
        )

    def setUp(self):
        self.client.force_login(self.admin)

    # ------------------------------------------------------------------
    # InscriptionEleve
    # ------------------------------------------------------------------

    # Champs volontairement absents des pages détail, avec la raison.
    CHAMPS_EXCLUS_ELEVE = {
        'id': "identifiant technique, pas une information de candidature.",
        'veut_contribuer': (
            "jamais collecté par le vrai formulaire public (voir le commentaire "
            "sur ce champ dans inscriptions/models.py) — toujours False, donc "
            "afficher '❌ لا' serait trompeur. À réactiver seulement si le "
            "formulaire est complété pour poser réellement la question."
        ),
        'prenom': (
            "ajouté puis retiré de l'affichage le 2026-08-09 (audit exhaustif) : "
            "le formulaire public ne collecte que 'nom' comme NOM COMPLET "
            "('الاسم الكامل'), aucun input 'prenom' n'existe côté élève et "
            "inscriptions/views.py ne le lit jamais depuis request.POST — "
            "toujours vide en production (0/26 candidatures). Même raison que "
            "veut_contribuer. Voir le commentaire sur ce champ dans "
            "inscriptions/models.py. (Ne pas confondre avec InscriptionProf.prenom, "
            "un vrai champ utilisé là-bas, inchangé.)"
        ),
        'disponibilites': (
            "affiché sous forme de grille visuelle interactive (cases cochées "
            "jour/heure), pas comme une valeur textuelle isolée — non testable "
            "par une simple recherche de sous-chaîne, vérifié visuellement."
        ),
        'statut': (
            "champ de workflow (en_attente/valide/rejete) qui pilote quels "
            "boutons/sections s'affichent, ce n'est pas une donnée de "
            "candidature à afficher comme telle."
        ),
    }

    def _creer_inscription_eleve(self, **overrides):
        valeurs = dict(
            nom='NomMarqueurE7f3',
            # prenom volontairement absent : toujours '' en pratique côté élève
            # (voir CHAMPS_EXCLUS_ELEVE ci-dessus) — ne pas lui donner de valeur
            # ici garderait le test fidèle à la réalité si jamais on l'y ajoutait.
            nom_parent='ParentMarqueurL8w1',
            date_naissance='2015-05-01',
            sexe='homme',
            telephone='0600112233',
            email='candidat_e_test@zidni.test',
            job_actuel='MetierMarqueurZ4t6',
            programme='hifz',
            riwaya='hafs',
            outil='whatsapp',
            abonnement='groupe_1mois',
            accepte_conditions=True,
            remarques='RemarqueMarqueurB9x2',
            disponibilites_libres='DispoLibreMarqueurH1y5',
        )
        valeurs.update(overrides)
        return InscriptionEleve.objects.create(**valeurs)

    def test_page_candidature_eleve_affiche_les_champs_attendus(self):
        inscription = self._creer_inscription_eleve()
        url = reverse('admin_inscription_eleve_detail', args=[inscription.id])
        contenu = self.client.get(url).content.decode('utf-8')

        for valeur in [
            inscription.nom, inscription.nom_parent,
            inscription.job_actuel, inscription.telephone, inscription.email,
            inscription.remarques, inscription.disponibilites_libres,
        ]:
            self.assertIn(valeur, contenu, f"'{valeur}' absent de la page de candidature élève")

    def test_fiche_finale_eleve_affiche_les_champs_attendus(self):
        inscription = self._creer_inscription_eleve(statut='valide')
        user = User.objects.create_user(
            username='eleve_test_champs@zidni.test',
            email='eleve_test_champs@zidni.test',
            password='xX!test12345',
            first_name=inscription.nom,
            role='eleve',
        )
        eleve = Eleve.objects.create(user=user, sexe=inscription.sexe, inscription=inscription)
        url = reverse('admin_eleve_detail', args=[eleve.id])
        contenu = self.client.get(url).content.decode('utf-8')

        for valeur in [
            inscription.nom_parent, inscription.job_actuel,
            inscription.remarques, inscription.disponibilites_libres,
        ]:
            self.assertIn(valeur, contenu, f"'{valeur}' absent de la fiche finale élève")

    def test_aucun_champ_inconnu_inscription_eleve(self):
        """Casse-toi-la-tête ici si tu ajoutes un champ à InscriptionEleve sans
        te poser la question 'où est-il affiché ?' — c'est le but."""
        champs_reels = {f.name for f in InscriptionEleve._meta.fields}
        champs_verifies_affiches = {
            'nom', 'nom_parent', 'date_naissance', 'sexe', 'telephone',
            'email', 'job_actuel', 'creneau_souhaite', 'programme', 'riwaya',
            'outil', 'abonnement', 'accepte_conditions', 'remarques',
            'disponibilites_libres', 'date_soumission',
            # Chantier du 2026-08-14 (refus avec motif) — affiché
            # conditionnellement (statut='rejete' seulement), voir
            # test_motif_refus_affiche_quand_rejete ci-dessous.
            'motif_refus',
        }
        champs_connus = champs_verifies_affiches | set(self.CHAMPS_EXCLUS_ELEVE)
        champs_nouveaux = champs_reels - champs_connus
        self.assertEqual(
            champs_nouveaux, set(),
            f"Nouveau(x) champ(s) sur InscriptionEleve non classé(s) : {champs_nouveaux}. "
            "Ajoute-le à champs_verifies_affiches (+ un test de rendu) ou à "
            "CHAMPS_EXCLUS_ELEVE (+ la raison)."
        )

    def test_motif_refus_eleve_affiche_quand_rejete(self):
        """Chantier du 2026-08-14 (refus avec motif) — le motif n'est affiché
        que pour un dossier rejeté (voir admin_inscription_detail.html), donc
        vérifié séparément de test_page_candidature_eleve_affiche_les_champs_attendus
        ci-dessus (qui teste une inscription 'en_attente', où motif_refus est
        toujours vide et n'a rien à afficher)."""
        inscription = self._creer_inscription_eleve(
            statut='rejete', motif_refus='MotifRefusMarqueurQ3k7',
        )
        url = reverse('admin_inscription_eleve_detail', args=[inscription.id])
        contenu = self.client.get(url).content.decode('utf-8')
        self.assertIn('MotifRefusMarqueurQ3k7', contenu)

    # ------------------------------------------------------------------
    # InscriptionProf
    # ------------------------------------------------------------------

    CHAMPS_EXCLUS_PROF = {
        'id': "identifiant technique, pas une information de candidature.",
        'disponibilites': (
            "affiché sous forme de grille visuelle interactive, pas comme une "
            "valeur textuelle isolée — voir la même raison côté élève."
        ),
        'statut': (
            "champ de workflow (en_attente/validee_directeur/valide/rejete) qui "
            "pilote quels boutons/sections s'affichent."
        ),
    }

    def _creer_inscription_prof(self, **overrides):
        valeurs = dict(
            nom='NomProfMarqueurF3d8',
            prenom='PrenomProfMarqueurK6m2',
            date_naissance='1990-01-01',
            telephone='0600445566',
            ville='VilleMarqueurP1n4',
            statut_familial='marie',
            job_actuel='MetierProfMarqueurS7v3',
            certifications='CertifMarqueurD5c1',
            niveau_memorisation='juz_30',
            parcours_scolaire='ParcoursScolMarqueurJ8b6',
            parcours_enseignant='ParcoursEnsMarqueurW2q9',
            compte_bancaire='CompteMarqueurT4r7',
            rib='RibMarqueurY6u3',
            agence_bancaire='AgenceMarqueurN9e2',
            gestion_eleve_faible='GestionFaibleMarqueurA1z5',
            gestion_eleve_absent='GestionAbsentMarqueurX3o8',
            email='candidat_p_test@zidni.test',
        )
        valeurs.update(overrides)
        return InscriptionProf.objects.create(**valeurs)

    def test_page_candidature_prof_affiche_les_champs_attendus(self):
        inscription = self._creer_inscription_prof()
        url = reverse('admin_inscription_prof_detail', args=[inscription.id])
        contenu = self.client.get(url).content.decode('utf-8')

        for valeur in [
            inscription.nom, inscription.prenom, inscription.telephone,
            inscription.ville, inscription.job_actuel, inscription.certifications,
            inscription.parcours_scolaire, inscription.parcours_enseignant,
            inscription.gestion_eleve_faible, inscription.gestion_eleve_absent,
            inscription.compte_bancaire, inscription.rib, inscription.agence_bancaire,
        ]:
            self.assertIn(valeur, contenu, f"'{valeur}' absent de la page de candidature professeur")

    def test_fiche_finale_prof_affiche_les_champs_attendus(self):
        inscription = self._creer_inscription_prof(statut='valide')
        user = User.objects.create_user(
            username='prof_test_champs@zidni.test',
            email='prof_test_champs@zidni.test',
            password='xX!test12345',
            first_name=inscription.nom,
            last_name=inscription.prenom,
            role='prof',
        )
        prof = Prof.objects.create(
            user=user,
            ville=inscription.ville,
            job_actuel=inscription.job_actuel,
            certifications=inscription.certifications,
            niveau_memorisation=inscription.niveau_memorisation,
            parcours_scolaire=inscription.parcours_scolaire,
            parcours_enseignant=inscription.parcours_enseignant,
            gestion_eleve_faible=inscription.gestion_eleve_faible,
            gestion_eleve_absent=inscription.gestion_eleve_absent,
            compte_bancaire=inscription.compte_bancaire,
            rib=inscription.rib,
            agence_bancaire=inscription.agence_bancaire,
            inscription=inscription,
            charte_acceptee=True,
            date_acceptation_charte='2026-08-01T10:00:00Z',
        )
        url = reverse('admin_prof_detail', args=[prof.id])
        contenu = self.client.get(url).content.decode('utf-8')

        for valeur in [
            prof.ville, prof.job_actuel, prof.certifications,
            prof.parcours_scolaire, prof.parcours_enseignant,
            prof.gestion_eleve_faible, prof.gestion_eleve_absent,
            prof.compte_bancaire, prof.rib, prof.agence_bancaire,
        ]:
            self.assertIn(valeur, contenu, f"'{valeur}' absent de la fiche finale professeur")

        # Tâche du 2026-08-09 : قبول الميثاق (audit exhaustif) — vérifie qu'un
        # ✅ apparaît bien quelque part sur la page pour un prof qui a accepté.
        self.assertIn('✅', contenu)

    def test_aucun_champ_inconnu_inscription_prof(self):
        champs_reels = {f.name for f in InscriptionProf._meta.fields}
        champs_verifies_affiches = {
            'nom', 'prenom', 'date_naissance', 'telephone', 'ville',
            'statut_familial', 'job_actuel', 'certifications',
            'niveau_memorisation', 'type_eleve_preference', 'contrainte_genre',
            'langues', 'outils_maitrises', 'parcours_scolaire',
            'parcours_enseignant', 'compte_bancaire', 'rib', 'agence_bancaire',
            'audio_enregistrement', 'gestion_eleve_faible', 'gestion_eleve_absent',
            'email', 'date_soumission',
            # Chantier du 2026-08-14 (refus avec motif) — affiché
            # conditionnellement (statut='rejete' seulement), voir
            # test_motif_refus_affiche_quand_rejete ci-dessous.
            'motif_refus',
        }
        champs_connus = champs_verifies_affiches | set(self.CHAMPS_EXCLUS_PROF)
        champs_nouveaux = champs_reels - champs_connus
        self.assertEqual(
            champs_nouveaux, set(),
            f"Nouveau(x) champ(s) sur InscriptionProf non classé(s) : {champs_nouveaux}. "
            "Ajoute-le à champs_verifies_affiches (+ un test de rendu) ou à "
            "CHAMPS_EXCLUS_PROF (+ la raison)."
        )

    def test_motif_refus_prof_affiche_quand_rejete(self):
        """Chantier du 2026-08-14 (refus avec motif) — voir le même test côté
        InscriptionEleve pour le principe (affiché seulement si rejete)."""
        inscription = self._creer_inscription_prof(
            statut='rejete', motif_refus='MotifRefusProfMarqueurR5j9',
        )
        url = reverse('admin_inscription_prof_detail', args=[inscription.id])
        contenu = self.client.get(url).content.decode('utf-8')
        self.assertIn('MotifRefusProfMarqueurR5j9', contenu)
