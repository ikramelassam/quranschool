import datetime

from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, Client
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Eleve, Prof, Superviseur
from courses.models import Groupe

from .models import Examen, Question, ChoixQuestion, Copie, Reponse
from .permissions import (
    get_examens_accessibles, can_access_examen, can_gerer_examen, can_corriger_examen,
    can_access_copie, can_modifier_copie,
)
from .services import (
    corriger_automatiquement, recalculer_note_totale, soumettre_copie,
    enregistrer_correction_manuelle, motif_non_publiable, valider_fichier_audio,
    valider_fichier_video, demarrer_ou_recuperer_copie, finaliser_si_expiree,
)

MOT_DE_PASSE = 'xX!test12345'


# ==================== Fabriques (même patron que chat/tests.py) ====================

def _creer_admin(email='admin_examens@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مدير', last_name='تجريبي', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif(email='mshrif_examens@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مشرف', last_name='تجريبي', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_eleve(email='eleve_examens@zidni.test', statut='actif'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme', statut=statut)


def _creer_prof(email='prof_examens@zidni.test', statut='actif'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    return Prof.objects.create(
        user=u, ville='الرباط', niveau_memorisation='كامل', statut=statut,
        parcours_scolaire='', parcours_enseignant='', compte_bancaire='', rib='', agence_bancaire='',
    )


def _creer_superviseur(email='superviseur_examens@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مؤطر', last_name='تجريبي', role='superviseur', doit_changer_mot_de_passe=False,
    )
    return Superviseur.objects.create(user=u)


def _creer_groupe(nom='مجموعة تجريبية', prof=None):
    return Groupe.objects.create(nom=nom, prof=prof)


def _connecter(client, user):
    client.force_login(user)


def _creer_examen(groupe, prof=None, statut='brouillon', debut_decalage_min=-60,
                   limite_decalage_min=180, duree_minutes=45, titre='اختبار تجريبي'):
    """debut_decalage_min/limite_decalage_min: minutes par rapport à
    maintenant — négatif = dans le passé. Par défaut : déjà disponible
    (commencé il y a 1h, ferme dans 3h), pratique pour la majorité des tests."""
    maintenant = timezone.now()
    return Examen.objects.create(
        groupe=groupe, prof=prof, titre=titre, instructions='تعليمات الاختبار',
        statut=statut,
        date_debut=maintenant + datetime.timedelta(minutes=debut_decalage_min),
        date_limite=maintenant + datetime.timedelta(minutes=limite_decalage_min),
        duree_minutes=duree_minutes,
    )


def _ajouter_question_choix(examen, ordre=1, points=2, textes=('أ', 'ب', 'ج'), index_correct=0):
    question = Question.objects.create(
        examen=examen, type_question='choix', enonce=f'سؤال {ordre}', ordre=ordre, points=points,
    )
    choix = []
    for i, texte in enumerate(textes):
        choix.append(ChoixQuestion.objects.create(
            question=question, texte=texte, ordre=i, est_correct=(i == index_correct),
        ))
    return question, choix


def _ajouter_question_vrai_faux(examen, ordre=2, points=1, correct=True):
    return Question.objects.create(
        examen=examen, type_question='vrai_faux', enonce=f'سؤال {ordre}', ordre=ordre,
        points=points, reponse_correcte_bool=correct,
    )


def _ajouter_question_texte(examen, ordre=3, points=3):
    return Question.objects.create(
        examen=examen, type_question='texte', enonce=f'سؤال {ordre}', ordre=ordre, points=points,
    )


def _ajouter_question_audio(examen, ordre=4, points=3):
    return Question.objects.create(
        examen=examen, type_question='audio', enonce=f'سؤال {ordre}', ordre=ordre, points=points,
    )


def _ajouter_question_video(examen, ordre=5, points=3):
    return Question.objects.create(
        examen=examen, type_question='video', enonce=f'سؤال {ordre}', ordre=ordre, points=points,
    )


def _examen_complet(groupe, prof, statut='publie'):
    """Un examen avec les 4 types de questions, prêt à être publié/passé."""
    examen = _creer_examen(groupe, prof=prof, statut='brouillon')
    q_choix, choix = _ajouter_question_choix(examen, ordre=1, points=2)
    q_vf = _ajouter_question_vrai_faux(examen, ordre=2, points=1, correct=True)
    q_texte = _ajouter_question_texte(examen, ordre=3, points=3)
    q_audio = _ajouter_question_audio(examen, ordre=4, points=3)
    if statut == 'publie':
        examen.statut = 'publie'
        examen.date_publication = timezone.now()
        examen.save()
    return examen, {'choix': q_choix, 'vf': q_vf, 'texte': q_texte, 'audio': q_audio}, choix


# ==================== Modèles ====================

class ModeleExamenTests(TestCase):
    def test_creation_examen_basique(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        self.assertEqual(examen.statut, 'brouillon')
        self.assertEqual(examen.nb_questions, 0)
        self.assertEqual(examen.points_max, 0)

    def test_points_max_somme_les_points_des_questions(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        _ajouter_question_choix(examen, points=2)
        _ajouter_question_vrai_faux(examen, points=1)
        self.assertEqual(examen.points_max, 3)

    def test_examen_sans_copie_est_entierement_modifiable(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        self.assertTrue(examen.chrono_modifiable)
        self.assertTrue(examen.structure_modifiable)

    def test_verrou_chrono_des_la_premiere_copie_demarree(self):
        """Décision validée le 2026-08-16 : le chrono se verrouille dès
        qu'une copie existe, MÊME non soumise — plus strict que le verrou de
        structure."""
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve()
        groupe.eleves.add(eleve)
        examen = _creer_examen(groupe, prof=prof, statut='publie')

        self.assertTrue(examen.chrono_modifiable)
        demarrer_ou_recuperer_copie(examen, eleve)
        examen.refresh_from_db()
        self.assertFalse(examen.chrono_modifiable)
        # La structure, elle, reste modifiable tant qu'aucune copie n'est SOUMISE.
        self.assertTrue(examen.structure_modifiable)

    def test_verrou_structure_seulement_apres_soumission(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve()
        groupe.eleves.add(eleve)
        examen, _, _ = _examen_complet(groupe, prof, statut='publie')

        copie, _ = demarrer_ou_recuperer_copie(examen, eleve)
        examen.refresh_from_db()
        self.assertTrue(examen.structure_modifiable)  # en_cours seulement

        soumettre_copie(copie)
        examen.refresh_from_db()
        self.assertFalse(examen.structure_modifiable)


class OrdreQuestionsTests(TestCase):
    def test_questions_renvoyees_dans_lordre_explicite_jamais_aleatoire(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        Question.objects.create(examen=examen, type_question='texte', enonce='C', ordre=3, points=1)
        Question.objects.create(examen=examen, type_question='texte', enonce='A', ordre=1, points=1)
        Question.objects.create(examen=examen, type_question='texte', enonce='B', ordre=2, points=1)

        enonces = list(examen.questions.values_list('enonce', flat=True))
        self.assertEqual(enonces, ['A', 'B', 'C'])

    def test_choix_renvoyes_dans_leur_ordre(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        question, _ = _ajouter_question_choix(examen, textes=('Z', 'Y', 'X'), index_correct=2)
        self.assertEqual(list(question.choix.values_list('texte', flat=True)), ['Z', 'Y', 'X'])


class TypesQuestionsTests(TestCase):
    def test_question_choix_a_une_seule_bonne_reponse(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        question, choix = _ajouter_question_choix(examen, index_correct=1)
        self.assertEqual(sum(1 for c in choix if c.est_correct), 1)
        self.assertTrue(choix[1].est_correct)

    def test_question_vrai_faux_stocke_la_bonne_reponse(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        question = _ajouter_question_vrai_faux(examen, correct=False)
        self.assertFalse(question.reponse_correcte_bool)

    def test_question_texte_et_audio_sans_bonne_reponse_stockee(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        examen = _creer_examen(groupe, prof=prof)
        q_texte = _ajouter_question_texte(examen)
        q_audio = _ajouter_question_audio(examen)
        self.assertIsNone(q_texte.reponse_correcte_bool)
        self.assertIsNone(q_audio.reponse_correcte_bool)


class ContraintesUniciteTests(TestCase):
    def test_une_seule_copie_par_examen_et_eleve(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve()
        examen = _creer_examen(groupe, prof=prof, statut='publie')
        Copie.objects.create(examen=examen, eleve=eleve)
        with self.assertRaises(Exception):
            Copie.objects.create(examen=examen, eleve=eleve)

    def test_get_or_create_ne_cree_jamais_de_2e_copie(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve()
        examen = _creer_examen(groupe, prof=prof, statut='publie')
        demarrer_ou_recuperer_copie(examen, eleve)
        demarrer_ou_recuperer_copie(examen, eleve)
        self.assertEqual(Copie.objects.filter(examen=examen, eleve=eleve).count(), 1)

    def test_une_seule_reponse_par_copie_et_question(self):
        prof = _creer_prof()
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve()
        examen = _creer_examen(groupe, prof=prof, statut='publie')
        question = _ajouter_question_texte(examen)
        copie = Copie.objects.create(examen=examen, eleve=eleve)
        Reponse.objects.create(copie=copie, question=question)
        with self.assertRaises(Exception):
            Reponse.objects.create(copie=copie, question=question)


# ==================== Permissions (fonctions) ====================

class PermissionsFonctionsTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_perm@zidni.test')
        self.autre_prof = _creer_prof('autre_prof_perm@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_perm@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.autre_eleve = _creer_eleve('autre_eleve_perm@zidni.test')
        self.superviseur = _creer_superviseur('sup_perm@zidni.test')
        self.superviseur.profs_assignes.add(self.prof)
        self.admin = _creer_admin('admin_perm@zidni.test')
        self.mshrif = _creer_mshrif('mshrif_perm@zidni.test')
        self.examen_brouillon = _creer_examen(self.groupe, prof=self.prof, statut='brouillon')
        self.examen_publie = _creer_examen(self.groupe, prof=self.prof, statut='publie', titre='publié')

    def test_eleve_voit_seulement_examens_publies_ou_fermes_de_ses_groupes(self):
        qs = get_examens_accessibles(self.eleve.user)
        self.assertIn(self.examen_publie, qs)
        self.assertNotIn(self.examen_brouillon, qs)

    def test_eleve_retire_du_groupe_perd_immediatement_lacces(self):
        self.assertTrue(can_access_examen(self.eleve.user, self.examen_publie))
        self.groupe.eleves.remove(self.eleve)
        self.assertFalse(can_access_examen(self.eleve.user, self.examen_publie))

    def test_eleve_dun_autre_groupe_navigue_pas_lexamen(self):
        self.assertFalse(can_access_examen(self.autre_eleve.user, self.examen_publie))

    def test_prof_proprietaire_peut_gerer_son_examen(self):
        self.assertTrue(can_gerer_examen(self.prof.user, self.examen_brouillon))

    def test_prof_non_proprietaire_ne_peut_pas_gerer(self):
        self.assertFalse(can_gerer_examen(self.autre_prof.user, self.examen_brouillon))

    def test_superviseur_lecture_seule_jamais_ecriture(self):
        self.assertTrue(can_access_examen(self.superviseur.user, self.examen_publie))
        self.assertFalse(can_gerer_examen(self.superviseur.user, self.examen_publie))
        self.assertFalse(can_corriger_examen(self.superviseur.user, self.examen_publie))

    def test_superviseur_non_assigne_na_pas_acces(self):
        autre_superviseur = _creer_superviseur('sup2_perm@zidni.test')
        self.assertFalse(can_access_examen(autre_superviseur.user, self.examen_publie))

    def test_admin_acces_global_mais_pas_gestion(self):
        # _creer_admin renvoie directement le User (role='admin'), pas un
        # profil séparé — contrairement à Eleve/Prof/Superviseur qui ont
        # chacun leur propre modèle wrappant un User.
        self.assertTrue(can_access_examen(self.admin, self.examen_brouillon))
        self.assertFalse(can_gerer_examen(self.admin, self.examen_brouillon))

    def test_mshrif_lecture_seule_globale_decision_validee_2026_08_16(self):
        self.assertTrue(can_access_examen(self.mshrif, self.examen_brouillon))
        self.assertFalse(can_gerer_examen(self.mshrif, self.examen_brouillon))
        self.assertFalse(can_corriger_examen(self.mshrif, self.examen_brouillon))

    def test_eleve_archive_perd_lacces(self):
        self.eleve.statut = 'archive'
        self.eleve.save()
        self.assertFalse(can_access_examen(self.eleve.user, self.examen_publie))

    def test_prof_archive_perd_la_gestion(self):
        self.prof.statut = 'archive'
        self.prof.save()
        self.assertFalse(can_gerer_examen(self.prof.user, self.examen_brouillon))

    def test_copie_accessible_uniquement_par_son_proprietaire_cote_eleve(self):
        copie = Copie.objects.create(examen=self.examen_publie, eleve=self.eleve)
        self.assertTrue(can_access_copie(self.eleve.user, copie))
        self.assertFalse(can_access_copie(self.autre_eleve.user, copie))
        self.assertTrue(can_access_copie(self.prof.user, copie))
        self.assertTrue(can_access_copie(self.superviseur.user, copie))

    def test_can_modifier_copie_refuse_si_deja_soumise(self):
        copie = Copie.objects.create(examen=self.examen_publie, eleve=self.eleve, statut='soumise')
        self.assertFalse(can_modifier_copie(self.eleve.user, copie))


# ==================== Chrono ====================

class ChronoTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_chrono@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_chrono@zidni.test')
        self.groupe.eleves.add(self.eleve)

    def test_date_expiration_effective_par_duree_quand_limite_est_loin(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie', limite_decalage_min=600, duree_minutes=45)
        copie, _ = demarrer_ou_recuperer_copie(examen, self.eleve)
        attendu = copie.date_debut + datetime.timedelta(minutes=45)
        self.assertEqual(copie.date_expiration_effective, attendu)

    def test_date_limite_globale_toujours_prioritaire_sur_la_duree(self):
        """Exemple exact du cahier des charges : examen ferme à +20min, élève
        commence avec 60 min accordées -> limité à +20min, pas +60min."""
        maintenant = timezone.now()
        examen = Examen.objects.create(
            groupe=self.groupe, prof=self.prof, titre='ex', statut='publie',
            date_debut=maintenant - datetime.timedelta(minutes=5),
            date_limite=maintenant + datetime.timedelta(minutes=20),
            duree_minutes=60,
        )
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=maintenant)
        self.assertEqual(copie.date_expiration_effective, examen.date_limite)

    def test_chrono_ne_redemarre_jamais_a_un_nouvel_acces(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        copie1, cree1 = demarrer_ou_recuperer_copie(examen, self.eleve)
        premiere_date_debut = copie1.date_debut
        copie2, cree2 = demarrer_ou_recuperer_copie(examen, self.eleve)
        self.assertTrue(cree1)
        self.assertFalse(cree2)
        self.assertEqual(copie2.date_debut, premiere_date_debut)

    def test_copie_non_demarree_nest_jamais_expiree(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        copie = Copie.objects.create(examen=examen, eleve=self.eleve)  # date_debut=None
        self.assertFalse(copie.est_expiree)
        self.assertIsNone(copie.date_expiration_effective)

    def test_copie_expiree_par_la_duree(self):
        maintenant = timezone.now()
        examen = Examen.objects.create(
            groupe=self.groupe, prof=self.prof, titre='ex', statut='publie',
            date_debut=maintenant - datetime.timedelta(hours=2),
            date_limite=maintenant + datetime.timedelta(hours=5),
            duree_minutes=10,
        )
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=maintenant - datetime.timedelta(minutes=30))
        self.assertTrue(copie.est_expiree)
        self.assertEqual(copie.temps_restant_secondes, 0)

    def test_finaliser_si_expiree_soumet_automatiquement(self):
        maintenant = timezone.now()
        examen, _, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        examen.duree_minutes = 5
        examen.date_debut = maintenant - datetime.timedelta(hours=1)
        examen.date_limite = maintenant + datetime.timedelta(hours=1)
        examen.save()
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=maintenant - datetime.timedelta(minutes=30))

        copie = finaliser_si_expiree(copie)

        self.assertEqual(copie.statut, 'soumise')
        self.assertTrue(copie.soumission_automatique)
        # Le QCM/VF sont auto-corrigés même pour une soumission automatique.
        self.assertTrue(copie.reponses.filter(statut_correction='auto').exists())

    def test_copie_non_expiree_reste_intacte(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie', duree_minutes=120)
        copie, _ = demarrer_ou_recuperer_copie(examen, self.eleve)
        copie = finaliser_si_expiree(copie)
        self.assertEqual(copie.statut, 'en_cours')


# ==================== HTTP — Workflow prof ====================

class WorkflowProfHttpTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_workflow@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.client = Client()
        _connecter(self.client, self.prof.user)

    def test_creation_examen_en_brouillon(self):
        reponse = self.client.post(reverse('examens_prof_ajouter'), {
            'groupe': self.groupe.id, 'titre': 'اختباري', 'instructions': '',
            'date_debut': '2026-09-01T10:00', 'date_limite': '2026-09-05T23:59',
            'duree_minutes': '30',
        })
        examen = Examen.objects.get(titre='اختباري')
        self.assertEqual(examen.statut, 'brouillon')
        self.assertRedirects(reponse, reverse('examens_prof_detail', args=[examen.id]))

    def test_creation_refusee_avec_groupe_dun_autre_prof(self):
        autre_prof = _creer_prof('autre_workflow@zidni.test')
        autre_groupe = _creer_groupe('autre', prof=autre_prof)
        self.client.post(reverse('examens_prof_ajouter'), {
            'groupe': autre_groupe.id, 'titre': 'اختبار خبيث',
            'date_debut': '2026-09-01T10:00', 'date_limite': '2026-09-05T23:59',
            'duree_minutes': '30',
        })
        self.assertFalse(Examen.objects.filter(titre='اختبار خبيث').exists())

    def test_publication_refusee_sans_question(self):
        examen = _creer_examen(self.groupe, prof=self.prof)
        self.client.post(reverse('examens_prof_publier', args=[examen.id]))
        examen.refresh_from_db()
        self.assertEqual(examen.statut, 'brouillon')

    def test_publication_refusee_si_qcm_sans_bonne_reponse(self):
        examen = _creer_examen(self.groupe, prof=self.prof)
        Question.objects.create(examen=examen, type_question='choix', enonce='q', ordre=1, points=1)
        ChoixQuestion.objects.create(question=examen.questions.first(), texte='a', est_correct=False)
        ChoixQuestion.objects.create(question=examen.questions.first(), texte='b', est_correct=False)
        self.client.post(reverse('examens_prof_publier', args=[examen.id]))
        examen.refresh_from_db()
        self.assertEqual(examen.statut, 'brouillon')

    def test_publication_reussie(self):
        examen, _, _ = _examen_complet(self.groupe, self.prof, statut='brouillon')
        self.client.post(reverse('examens_prof_publier', args=[examen.id]))
        examen.refresh_from_db()
        self.assertEqual(examen.statut, 'publie')
        self.assertIsNotNone(examen.date_publication)

    def test_fermeture_examen_publie(self):
        examen, _, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        self.client.post(reverse('examens_prof_fermer', args=[examen.id]))
        examen.refresh_from_db()
        self.assertEqual(examen.statut, 'ferme')

    def test_fermeture_refusee_sur_un_brouillon(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='brouillon')
        self.client.post(reverse('examens_prof_fermer', args=[examen.id]))
        examen.refresh_from_db()
        self.assertEqual(examen.statut, 'brouillon')

    def test_formulaire_ajout_question_se_rend_sans_erreur(self):
        """Régression : question_form.html plantait (VariableDoesNotExist)
        au GET de cette page quand question=None (cas 'ajouter'), car
        |default:question.type_question évaluait question.type_question
        comme argument de filtre — jamais protégé par le mécanisme
        silencieux de Django, contrairement à une variable de {% if %}.
        Seul le POST était testé jusqu'ici (voir le test suivant), jamais
        ce GET — c'est ce qui a laissé passer le bug jusqu'en production."""
        examen = _creer_examen(self.groupe, prof=self.prof)
        r = self.client.get(reverse('examens_question_ajouter', args=[examen.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<option value="choix" selected>')

    def test_formulaire_modification_question_preremplit_le_bon_type(self):
        examen = _creer_examen(self.groupe, prof=self.prof)
        question = Question.objects.create(
            examen=examen, type_question='vrai_faux', enonce='سؤال', ordre=1, points=2,
            reponse_correcte_bool=True,
        )
        r = self.client.get(reverse('examens_question_modifier', args=[question.id]))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, '<option value="vrai_faux" selected>')
        self.assertNotContains(r, '<option value="choix" selected>')

    def test_ajout_modification_suppression_reordonnancement_questions(self):
        examen = _creer_examen(self.groupe, prof=self.prof)
        self.client.post(reverse('examens_question_ajouter', args=[examen.id]), {
            'type_question': 'texte', 'enonce': 'Q1', 'points': '2',
        })
        self.client.post(reverse('examens_question_ajouter', args=[examen.id]), {
            'type_question': 'texte', 'enonce': 'Q2', 'points': '3',
        })
        q1, q2 = list(examen.questions.order_by('ordre'))
        self.assertEqual([q1.enonce, q2.enonce], ['Q1', 'Q2'])

        self.client.post(reverse('examens_question_monter', args=[q2.id]))
        q1.refresh_from_db()
        q2.refresh_from_db()
        self.assertLess(q2.ordre, q1.ordre)

        self.client.post(reverse('examens_question_modifier', args=[q1.id]), {
            'type_question': 'texte', 'enonce': 'Q1 modifiée', 'points': '5',
        })
        q1.refresh_from_db()
        self.assertEqual(q1.enonce, 'Q1 modifiée')
        self.assertEqual(q1.points, 5)

        self.client.post(reverse('examens_question_supprimer', args=[q1.id]))
        self.assertFalse(Question.objects.filter(id=q1.id).exists())

    def test_modification_question_refusee_apres_soumission(self):
        examen, questions, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        eleve = _creer_eleve('eleve_verrou@zidni.test')
        self.groupe.eleves.add(eleve)
        copie, _ = demarrer_ou_recuperer_copie(examen, eleve)
        soumettre_copie(copie)

        ancien_enonce = questions['texte'].enonce
        self.client.post(reverse('examens_question_modifier', args=[questions['texte'].id]), {
            'type_question': 'texte', 'enonce': 'PIRATÉ', 'points': '99',
        })
        questions['texte'].refresh_from_db()
        self.assertEqual(questions['texte'].enonce, ancien_enonce)

    def test_modification_chrono_refusee_apres_demarrage_dune_copie(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        eleve = _creer_eleve('eleve_verrou2@zidni.test')
        self.groupe.eleves.add(eleve)
        demarrer_ou_recuperer_copie(examen, eleve)

        ancienne_duree = examen.duree_minutes
        self.client.post(reverse('examens_prof_modifier', args=[examen.id]), {
            'titre': examen.titre, 'instructions': '',
            'groupe': self.groupe.id, 'date_debut': '2030-01-01T00:00',
            'date_limite': '2030-01-02T00:00', 'duree_minutes': '999',
        })
        examen.refresh_from_db()
        self.assertEqual(examen.duree_minutes, ancienne_duree)

    def test_titre_reste_modifiable_apres_soumission(self):
        """titre/instructions ne sont pas dans la liste des champs verrouillés
        au §5 du cahier des charges."""
        examen, _, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        eleve = _creer_eleve('eleve_titre@zidni.test')
        self.groupe.eleves.add(eleve)
        copie, _ = demarrer_ou_recuperer_copie(examen, eleve)
        soumettre_copie(copie)

        self.client.post(reverse('examens_prof_modifier', args=[examen.id]), {
            'titre': 'عنوان معدَّل', 'instructions': 'تعليمات جديدة',
        })
        examen.refresh_from_db()
        self.assertEqual(examen.titre, 'عنوان معدَّل')


# ==================== HTTP — Workflow élève / soumission ====================

class WorkflowEleveHttpTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_eleve_wf@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_wf@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.examen, self.questions, self.choix = _examen_complet(self.groupe, self.prof, statut='publie')
        self.client = Client()
        _connecter(self.client, self.eleve.user)

    def test_demarrage_examen_cree_une_copie(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        self.assertTrue(Copie.objects.filter(examen=self.examen, eleve=self.eleve).exists())

    def test_autosave_texte(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions['texte'].id]),
            {'reponse_texte': 'جوابي'},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(Reponse.objects.get(copie=copie, question=self.questions['texte']).reponse_texte, 'جوابي')

    def test_autosave_choix(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        bon_choix = next(c for c in self.choix if c.est_correct)
        self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions['choix'].id]),
            {'choix_id': bon_choix.id},
        )
        reponse = Reponse.objects.get(copie=copie, question=self.questions['choix'])
        self.assertEqual(reponse.reponse_choix_id, bon_choix.id)

    def test_autosave_audio(self):
        """Chemin serveur d'une réponse audio — jamais couvert avant (seuls
        texte/choix l'étaient ici, voir Bug du 2026-08-16 : la vraie cause
        n'était PAS ce chemin serveur, qui fonctionne correctement, mais le
        JS de templates/examens/passage.html qui rechargeait la page même en
        cas d'échec, masquant tout message d'erreur — voir
        AudioAutosaveEchecTests ci-dessous pour la partie qui EST couverte
        par ce bug)."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        fichier = SimpleUploadedFile('voice.mp3', b'contenu-audio-factice', content_type='audio/mpeg')
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions['audio'].id]),
            {'reponse_audio': fichier},
        )
        self.assertEqual(r.status_code, 200)
        reponse = Reponse.objects.get(copie=copie, question=self.questions['audio'])
        self.assertTrue(reponse.reponse_audio)
        self.assertEqual(reponse.nom_fichier_audio_original, 'voice.mp3')
        reponse.reponse_audio.delete(save=False)

    def test_autosave_audio_extension_invalide_renvoie_message_precis(self):
        """Le corps JSON de l'échec doit contenir une clé 'erreur' précise —
        c'est ce que le JS de passage.html affiche désormais à l'élève au
        lieu de recharger la page en silence (bug corrigé du 2026-08-16)."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        fichier = SimpleUploadedFile('voice.3gp', b'contenu-audio-factice', content_type='audio/3gpp')
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions['audio'].id]),
            {'reponse_audio': fichier},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('erreur', r.json())
        self.assertFalse(Reponse.objects.get(copie=copie, question=self.questions['audio']).reponse_audio)

    def test_autosave_audio_enregistre_en_direct(self):
        """Le widget micro (MediaRecorder) de passage.html produit un blob
        .webm — régression du 2e passage du 2026-08-16."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        fichier = SimpleUploadedFile('voice-123.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions['audio'].id]),
            {'reponse_audio': fichier},
        )
        self.assertEqual(r.status_code, 200)
        reponse = Reponse.objects.get(copie=copie, question=self.questions['audio'])
        self.assertTrue(reponse.reponse_audio)
        reponse.reponse_audio.delete(save=False)

    def test_page_examen_affiche_le_widget_denregistrement_micro(self):
        """Régression (2026-08-16, 2e passage) : le texte d'aide promettait un
        enregistrement direct depuis le téléphone mais AUCUN widget micro
        n'était rendu (seul un <input type=file> brut) — vérifie que le vrai
        bouton d'enregistrement est bien présent dans le HTML, ET qu'aucun
        fragment de commentaire Django ne fuite dans la page (piège du tag
        {# #} qui ne supporte PAS les commentaires multi-lignes, contrairement
        à {% comment %}...{% endcomment %})."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        r = self.client.get(reverse('examens_passage', args=[copie.id]))
        html = r.content.decode('utf-8')
        self.assertContains(r, 'demarrerEnregistrementAudio(')
        self.assertContains(r, '🎤')
        # Phrase du commentaire Django {% comment %} (pas du commentaire JS //,
        # qui lui reste légitimement dans le <script> délivré) — ne doit jamais
        # apparaître comme texte visible de la page.
        self.assertNotIn("mais AUCUN", html)

    def test_page_examen_ne_propose_plus_le_choix_de_fichier_audio(self):
        """Tâche du 2026-08-18 : le repli "اختيار ملف" (import depuis
        l'appareil) est retiré pour les questions audio — seul l'enregistrement
        direct au micro reste proposé. Vérifie le HTML réellement rendu plutôt
        qu'un simple assertNotIn global sur la réponse brute (le texte peut
        encore exister dans un commentaire Django, jamais servi tel quel)."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        r = self.client.get(reverse('examens_passage', args=[copie.id]))
        html = r.content.decode('utf-8')
        self.assertNotIn('📎 اختيار ملف', html)
        self.assertNotIn('type="file"', html)

    def test_autosave_refuse_apres_soumission(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        soumettre_copie(copie)
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions['texte'].id]),
            {'reponse_texte': 'trop tard'},
        )
        self.assertEqual(r.status_code, 409)
        self.assertEqual(Reponse.objects.get(copie=copie, question=self.questions['texte']).reponse_texte, '')

    def test_soumission_valide(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        self.client.post(reverse('examens_soumettre', args=[copie.id]))
        copie.refresh_from_db()
        self.assertEqual(copie.statut, 'soumise')
        self.assertFalse(copie.soumission_automatique)

    def test_page_resultat_naffiche_pas_la_banniere_de_succes_en_double(self):
        """Régression (2026-08-16) : eleve_resultat.html incluait
        dashboard/_messages.html une 2e fois EN PLUS de celui déjà rendu par
        base_eleve.html — le message "تم تسليم إجاباتك بنجاح" apparaissait
        donc 2 fois en bannière, plus une 3e fois dans la carte de statut
        dédiée de cette même page ("📩 تم تسليم إجاباتك"). Corrigé en 2 temps :
        suppression de l'include redondant (structurel, tout le module
        examens était concerné) + suppression du messages.success() devenu
        inutile ici puisque la carte de statut dit déjà la même chose."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        reponse = self.client.post(reverse('examens_soumettre', args=[copie.id]), follow=True)
        html = reponse.content.decode('utf-8')
        self.assertEqual(html.count('تم تسليم إجاباتك بنجاح'), 0)  # plus émis du tout (carte suffit)
        self.assertEqual(html.count('📩 تم تسليم إجاباتك'), 1)     # la carte, une seule fois
        # Le conteneur de bannière lui-même (dashboard/_messages.html) ne doit
        # apparaître qu'une fois dans le HTML, même s'il n'y a rien à afficher.
        self.assertEqual(html.count('aria-label="إغلاق"'), 0)      # aucun message en attente -> pas de bannière du tout ici

    def test_double_soumission_ne_change_rien(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        self.client.post(reverse('examens_soumettre', args=[copie.id]))
        copie.refresh_from_db()
        premiere_date_soumission = copie.date_soumission
        self.client.post(reverse('examens_soumettre', args=[copie.id]))
        copie.refresh_from_db()
        self.assertEqual(copie.date_soumission, premiere_date_soumission)

    def test_soumission_apres_expiration_est_finalisee_automatiquement(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        copie.date_debut = timezone.now() - datetime.timedelta(hours=5)
        copie.save()
        self.examen.duree_minutes = 5
        self.examen.save()

        r = self.client.get(reverse('examens_passage', args=[copie.id]))
        copie.refresh_from_db()
        self.assertEqual(copie.statut, 'soumise')
        self.assertTrue(copie.soumission_automatique)
        self.assertEqual(r.status_code, 302)  # redirigé vers le résultat, plus de page de passage

    def test_impossible_de_commencer_un_examen_ferme(self):
        self.examen.statut = 'ferme'
        self.examen.save()
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        self.assertFalse(Copie.objects.filter(examen=self.examen, eleve=self.eleve).exists())

    def test_impossible_de_commencer_avant_date_debut(self):
        self.examen.date_debut = timezone.now() + datetime.timedelta(days=1)
        self.examen.save()
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        self.assertFalse(Copie.objects.filter(examen=self.examen, eleve=self.eleve).exists())


# ==================== Auto-correction ====================

class AutoCorrectionTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_correction@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_correction@zidni.test')
        self.groupe.eleves.add(self.eleve)

    def test_qcm_bonne_reponse_attribue_les_points(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        question, choix = _ajouter_question_choix(examen, points=5, index_correct=1)
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        reponse = Reponse.objects.create(copie=copie, question=question, reponse_choix=choix[1])
        corriger_automatiquement(reponse)
        self.assertEqual(reponse.points_obtenus, 5)
        self.assertEqual(reponse.statut_correction, 'auto')

    def test_qcm_mauvaise_reponse_zero_point(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        question, choix = _ajouter_question_choix(examen, points=5, index_correct=1)
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        reponse = Reponse.objects.create(copie=copie, question=question, reponse_choix=choix[0])
        corriger_automatiquement(reponse)
        self.assertEqual(reponse.points_obtenus, 0)

    def test_qcm_non_repondu_zero_point(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        question, choix = _ajouter_question_choix(examen, points=5, index_correct=1)
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        reponse = Reponse.objects.create(copie=copie, question=question)
        corriger_automatiquement(reponse)
        self.assertEqual(reponse.points_obtenus, 0)

    def test_vrai_faux_correct(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        question = _ajouter_question_vrai_faux(examen, points=4, correct=True)
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        reponse = Reponse.objects.create(copie=copie, question=question, reponse_bool=True)
        corriger_automatiquement(reponse)
        self.assertEqual(reponse.points_obtenus, 4)

    def test_vrai_faux_incorrect(self):
        examen = _creer_examen(self.groupe, prof=self.prof, statut='publie')
        question = _ajouter_question_vrai_faux(examen, points=4, correct=True)
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        reponse = Reponse.objects.create(copie=copie, question=question, reponse_bool=False)
        corriger_automatiquement(reponse)
        self.assertEqual(reponse.points_obtenus, 0)

    def test_soumission_calcule_correctement_les_types_auto_corriges(self):
        examen, questions, choix = _examen_complet(self.groupe, self.prof, statut='publie')
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        bon_choix = next(c for c in choix if c.est_correct)
        Reponse.objects.create(copie=copie, question=questions['choix'], reponse_choix=bon_choix)
        Reponse.objects.create(copie=copie, question=questions['vf'], reponse_bool=True)  # correct=True à la création

        soumettre_copie(copie)

        self.assertEqual(Reponse.objects.get(copie=copie, question=questions['choix']).points_obtenus, 2)
        self.assertEqual(Reponse.objects.get(copie=copie, question=questions['vf']).points_obtenus, 1)
        # texte/audio encore à corriger -> note_totale reste None.
        copie.refresh_from_db()
        self.assertIsNone(copie.note_totale)

    def test_note_totale_reste_none_tant_quune_reponse_manuelle_nest_pas_corrigee(self):
        examen, questions, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        soumettre_copie(copie)
        recalculer_note_totale(copie)
        copie.refresh_from_db()
        self.assertIsNone(copie.note_totale)

    def test_note_totale_calculee_une_fois_toutes_les_corrections_faites(self):
        examen, questions, choix = _examen_complet(self.groupe, self.prof, statut='publie')
        copie = Copie.objects.create(examen=examen, eleve=self.eleve, date_debut=timezone.now())
        bon_choix = next(c for c in choix if c.est_correct)
        Reponse.objects.create(copie=copie, question=questions['choix'], reponse_choix=bon_choix)
        Reponse.objects.create(copie=copie, question=questions['vf'], reponse_bool=True)
        soumettre_copie(copie)

        enregistrer_correction_manuelle(
            Reponse.objects.get(copie=copie, question=questions['texte']), 2, 'جيد'
        )
        enregistrer_correction_manuelle(
            Reponse.objects.get(copie=copie, question=questions['audio']), 3, 'ممتاز'
        )
        copie.refresh_from_db()
        # choix(2 pts, correct) + vf(1 pt, correct) + texte(2) + audio(3) = 8
        self.assertEqual(copie.note_totale, 8)
        self.assertTrue(copie.correction_complete)


class CorrectionManuelleHttpTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_manuelle@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_manuelle@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.examen, self.questions, self.choix = _examen_complet(self.groupe, self.prof, statut='publie')
        self.copie = Copie.objects.create(examen=self.examen, eleve=self.eleve, date_debut=timezone.now())
        soumettre_copie(self.copie)
        self.client = Client()
        _connecter(self.client, self.prof.user)

    def test_correction_texte_valide(self):
        reponse = Reponse.objects.get(copie=self.copie, question=self.questions['texte'])
        self.client.post(reverse('examens_copie_correction', args=[self.copie.id]), {
            'reponse_id': reponse.id, 'points_obtenus': '3', 'commentaire': 'أحسنت',
        })
        reponse.refresh_from_db()
        self.assertEqual(reponse.points_obtenus, 3)
        self.assertEqual(reponse.commentaire_prof, 'أحسنت')
        self.assertEqual(reponse.statut_correction, 'corrigee')

    def test_correction_refusee_si_points_hors_bareme(self):
        reponse = Reponse.objects.get(copie=self.copie, question=self.questions['texte'])
        self.client.post(reverse('examens_copie_correction', args=[self.copie.id]), {
            'reponse_id': reponse.id, 'points_obtenus': '999', 'commentaire': '',
        })
        reponse.refresh_from_db()
        self.assertNotEqual(reponse.points_obtenus, 999)

    def test_correction_refusee_sur_type_auto_corrige(self):
        reponse = Reponse.objects.get(copie=self.copie, question=self.questions['choix'])
        r = self.client.post(reverse('examens_copie_correction', args=[self.copie.id]), {
            'reponse_id': reponse.id, 'points_obtenus': '2', 'commentaire': '',
        })
        self.assertEqual(r.status_code, 400)

    def test_correction_refusee_par_un_prof_non_proprietaire(self):
        autre_prof = _creer_prof('autre_manuelle@zidni.test')
        client = Client()
        _connecter(client, autre_prof.user)
        reponse = Reponse.objects.get(copie=self.copie, question=self.questions['texte'])
        r = client.post(reverse('examens_copie_correction', args=[self.copie.id]), {
            'reponse_id': reponse.id, 'points_obtenus': '3', 'commentaire': '',
        })
        self.assertEqual(r.status_code, 403)
        reponse.refresh_from_db()
        self.assertNotEqual(reponse.points_obtenus, 3)


# ==================== Audio ====================

class AudioValidationTests(TestCase):
    def test_extension_valide_acceptee(self):
        fichier = SimpleUploadedFile('reponse.mp3', b'contenu-audio-factice', content_type='audio/mpeg')
        self.assertIsNone(valider_fichier_audio(fichier))

    def test_extension_invalide_refusee(self):
        fichier = SimpleUploadedFile('reponse.exe', b'contenu', content_type='application/octet-stream')
        self.assertIsNotNone(valider_fichier_audio(fichier))

    def test_fichier_vide_refuse(self):
        fichier = SimpleUploadedFile('reponse.mp3', b'', content_type='audio/mpeg')
        self.assertIsNotNone(valider_fichier_audio(fichier))

    def test_fichier_trop_volumineux_refuse(self):
        fichier = SimpleUploadedFile('reponse.mp3', b'0' * (16 * 1024 * 1024), content_type='audio/mpeg')
        self.assertIsNotNone(valider_fichier_audio(fichier))

    def test_aucun_fichier_refuse(self):
        self.assertIsNotNone(valider_fichier_audio(None))


class AudioAccesHttpTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_audio@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_audio@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.autre_eleve = _creer_eleve('autre_eleve_audio@zidni.test')
        self.examen, self.questions, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        self.copie = Copie.objects.create(examen=self.examen, eleve=self.eleve, date_debut=timezone.now())
        self.reponse = Reponse.objects.create(
            copie=self.copie, question=self.questions['audio'],
            reponse_audio=SimpleUploadedFile('rep.mp3', b'contenu-audio-factice'),
        )

    def tearDown(self):
        if self.reponse.reponse_audio:
            self.reponse.reponse_audio.delete(save=False)

    def test_proprietaire_peut_acceder(self):
        client = Client()
        _connecter(client, self.eleve.user)
        r = client.get(reverse('examens_reponse_audio', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 302)  # redirection vers le fichier réel

    def test_autre_eleve_refuse(self):
        client = Client()
        _connecter(client, self.autre_eleve.user)
        r = client.get(reverse('examens_reponse_audio', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 403)

    def test_prof_du_groupe_peut_acceder(self):
        client = Client()
        _connecter(client, self.prof.user)
        r = client.get(reverse('examens_reponse_audio', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 302)

    def test_prof_dun_autre_groupe_refuse(self):
        autre_prof = _creer_prof('autre_prof_audio@zidni.test')
        client = Client()
        _connecter(client, autre_prof.user)
        r = client.get(reverse('examens_reponse_audio', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 403)


# ==================== IDOR HTTP — §14 du cahier des charges ====================

class IdorHttpTests(TestCase):
    """Chaque test reproduit EXACTEMENT un des 14 cas listés au §14 du
    cahier des charges — endpoints HTTP réels via Client().force_login(),
    jamais un simple appel de fonction interne."""

    def setUp(self):
        self.prof_a = _creer_prof('prof_a_idor@zidni.test')
        self.prof_b = _creer_prof('prof_b_idor@zidni.test')
        self.groupe_a = _creer_groupe('groupe A', prof=self.prof_a)
        self.groupe_b = _creer_groupe('groupe B', prof=self.prof_b)
        self.eleve_a = _creer_eleve('eleve_a_idor@zidni.test')
        self.groupe_a.eleves.add(self.eleve_a)
        self.eleve_b = _creer_eleve('eleve_b_idor@zidni.test')
        self.groupe_b.eleves.add(self.eleve_b)
        self.superviseur = _creer_superviseur('sup_idor@zidni.test')
        self.superviseur.profs_assignes.add(self.prof_a)

        self.examen_a, self.questions_a, self.choix_a = _examen_complet(self.groupe_a, self.prof_a, statut='publie')
        self.examen_b, self.questions_b, self.choix_b = _examen_complet(self.groupe_b, self.prof_b, statut='publie')

    # 1. Élève A tente d'ouvrir examen du groupe B -> refus.
    def test_1_eleve_a_ouvre_examen_du_groupe_b(self):
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.get(reverse('examens_eleve_avant', args=[self.examen_b.id]))
        self.assertEqual(r.status_code, 403)

    # 2. Élève A tente d'ouvrir copie de l'élève B -> refus.
    def test_2_eleve_a_ouvre_copie_de_eleve_b(self):
        copie_b = Copie.objects.create(examen=self.examen_b, eleve=self.eleve_b, date_debut=timezone.now())
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.get(reverse('examens_passage', args=[copie_b.id]))
        self.assertEqual(r.status_code, 403)
        r2 = client.get(reverse('examens_eleve_resultat', args=[copie_b.id]))
        self.assertEqual(r2.status_code, 403)

    # 3. Élève A tente d'accéder à l'audio de l'élève B -> refus.
    def test_3_eleve_a_accede_audio_de_eleve_b(self):
        copie_b = Copie.objects.create(examen=self.examen_b, eleve=self.eleve_b, date_debut=timezone.now())
        reponse_b = Reponse.objects.create(
            copie=copie_b, question=self.questions_b['audio'],
            reponse_audio=SimpleUploadedFile('audio_b.mp3', b'contenu'),
        )
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.get(reverse('examens_reponse_audio', args=[reponse_b.id]))
        self.assertEqual(r.status_code, 403)
        reponse_b.reponse_audio.delete(save=False)

    # 4. Prof A tente de modifier examen du prof B -> refus.
    def test_4_prof_a_modifie_examen_du_prof_b(self):
        client = Client()
        _connecter(client, self.prof_a.user)
        ancien_titre = self.examen_b.titre
        client.post(reverse('examens_prof_modifier', args=[self.examen_b.id]), {
            'titre': 'PIRATÉ', 'instructions': '',
        })
        self.examen_b.refresh_from_db()
        self.assertEqual(self.examen_b.titre, ancien_titre)
        r = client.get(reverse('examens_prof_detail', args=[self.examen_b.id]))
        self.assertEqual(r.status_code, 403)

    # 5. Prof A tente de corriger copie d'un groupe qu'il ne gère pas -> refus.
    def test_5_prof_a_corrige_copie_du_groupe_b(self):
        copie_b = Copie.objects.create(examen=self.examen_b, eleve=self.eleve_b, date_debut=timezone.now())
        soumettre_copie(copie_b)
        client = Client()
        _connecter(client, self.prof_a.user)
        reponse_b = Reponse.objects.get(copie=copie_b, question=self.questions_b['texte'])
        r = client.post(reverse('examens_copie_correction', args=[copie_b.id]), {
            'reponse_id': reponse_b.id, 'points_obtenus': '3', 'commentaire': '',
        })
        self.assertEqual(r.status_code, 403)

    # 6. Superviseur tente de modifier -> refus.
    def test_6_superviseur_tente_de_modifier(self):
        """Les vues de gestion (examen_modifier/examen_publier) sont
        décorées @role_required('prof') — un superviseur, dont le rôle
        n'est même pas dans la liste autorisée, est redirigé vers SON
        propre dashboard AVANT d'atteindre can_gerer_examen (302, même
        comportement que role_required partout ailleurs dans le projet,
        voir accounts.decorators). Le test vérifie donc l'absence de tout
        effet — pas un code 403, réservé au cas 'bon rôle mais mauvais
        propriétaire' (voir tests 4/5 ci-dessus, où le rôle prof passe le
        décorateur et c'est can_gerer_examen qui refuse)."""
        client = Client()
        _connecter(client, self.superviseur.user)
        ancien_titre = self.examen_a.titre
        ancien_statut = self.examen_a.statut
        r1 = client.post(reverse('examens_prof_modifier', args=[self.examen_a.id]), {
            'titre': 'PIRATÉ PAR SUPERVISEUR', 'instructions': '',
        })
        self.examen_a.refresh_from_db()
        self.assertEqual(self.examen_a.titre, ancien_titre)
        self.assertNotEqual(r1.status_code, 200)

        r2 = client.post(reverse('examens_prof_publier', args=[self.examen_a.id]))
        self.examen_a.refresh_from_db()
        self.assertEqual(self.examen_a.statut, ancien_statut)
        self.assertNotEqual(r2.status_code, 200)

    # 7. Élève retiré du groupe -> accès recalculé immédiatement.
    def test_7_eleve_retire_du_groupe_perd_lacces_immediatement(self):
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.get(reverse('examens_eleve_avant', args=[self.examen_a.id]))
        self.assertEqual(r.status_code, 200)

        self.groupe_a.eleves.remove(self.eleve_a)
        r2 = client.get(reverse('examens_eleve_avant', args=[self.examen_a.id]))
        self.assertEqual(r2.status_code, 403)

    # 8. Examen fermé -> nouvelle soumission (démarrage) refusée côté serveur.
    def test_8_examen_ferme_refuse_nouvelle_participation(self):
        self.examen_a.statut = 'ferme'
        self.examen_a.save()
        client = Client()
        _connecter(client, self.eleve_a.user)
        client.post(reverse('examens_eleve_avant', args=[self.examen_a.id]))
        self.assertFalse(Copie.objects.filter(examen=self.examen_a, eleve=self.eleve_a).exists())

    # 9. Examen expiré -> modification refusée côté serveur.
    def test_9_examen_expire_refuse_modification(self):
        copie = Copie.objects.create(
            examen=self.examen_a, eleve=self.eleve_a,
            date_debut=timezone.now() - datetime.timedelta(hours=10),
        )
        self.examen_a.duree_minutes = 5
        self.examen_a.save()
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions_a['texte'].id]),
            {'reponse_texte': 'trop tard'},
        )
        self.assertEqual(r.status_code, 409)

    # 10. Copie déjà soumise -> modification refusée.
    def test_10_copie_soumise_refuse_modification(self):
        copie = Copie.objects.create(examen=self.examen_a, eleve=self.eleve_a, date_debut=timezone.now())
        soumettre_copie(copie)
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions_a['texte'].id]),
            {'reponse_texte': 'trop tard'},
        )
        self.assertEqual(r.status_code, 409)

    # 11. Modification d'un question_id appartenant à un autre examen -> refus.
    def test_11_question_id_dun_autre_examen_refuse(self):
        copie_a = Copie.objects.create(examen=self.examen_a, eleve=self.eleve_a, date_debut=timezone.now())
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.post(
            reverse('examens_reponse_autosave', args=[copie_a.id, self.questions_b['texte'].id]),
            {'reponse_texte': 'intrusion'},
        )
        self.assertEqual(r.status_code, 404)

    # 12. Modification d'une reponse_id appartenant à une autre copie -> refus.
    def test_12_reponse_id_dune_autre_copie_refuse_en_correction(self):
        copie_a = Copie.objects.create(examen=self.examen_a, eleve=self.eleve_a, date_debut=timezone.now())
        soumettre_copie(copie_a)
        copie_b = Copie.objects.create(examen=self.examen_b, eleve=self.eleve_b, date_debut=timezone.now())
        soumettre_copie(copie_b)
        reponse_b = Reponse.objects.get(copie=copie_b, question=self.questions_b['texte'])

        client = Client()
        _connecter(client, self.prof_a.user)
        # Prof A tente de corriger via SA copie (copie_a) une reponse_id qui
        # appartient en réalité à copie_b -> get_object_or_404(..., copie=copie)
        # doit échouer, aucune correction ne doit être appliquée.
        r = client.post(reverse('examens_copie_correction', args=[copie_a.id]), {
            'reponse_id': reponse_b.id, 'points_obtenus': '3', 'commentaire': '',
        })
        self.assertEqual(r.status_code, 404)
        reponse_b.refresh_from_db()
        self.assertIsNone(reponse_b.points_obtenus)

    # 13. Tentative de contourner le chrono en modifiant les valeurs frontend -> refus.
    def test_13_contournement_chrono_cote_client_ignore(self):
        """Le client envoie un champ 'temps_restant_secondes' factice élevé —
        la vue ne lit JAMAIS ce champ, seul le calcul serveur fait foi."""
        copie = Copie.objects.create(
            examen=self.examen_a, eleve=self.eleve_a,
            date_debut=timezone.now() - datetime.timedelta(hours=10),
        )
        self.examen_a.duree_minutes = 5
        self.examen_a.save()
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.questions_a['texte'].id]),
            {'reponse_texte': 'triche', 'temps_restant_secondes': '99999'},
        )
        self.assertEqual(r.status_code, 409)
        copie.refresh_from_db()
        self.assertEqual(copie.statut, 'soumise')  # finalisée automatiquement malgré la valeur envoyée

    # 14. Tentative de soumission après la date limite -> refus/finalisation conforme.
    def test_14_soumission_apres_date_limite_est_finalisee_conforme(self):
        maintenant = timezone.now()
        self.examen_a.date_limite = maintenant - datetime.timedelta(minutes=1)
        self.examen_a.save()
        copie = Copie.objects.create(
            examen=self.examen_a, eleve=self.eleve_a, date_debut=maintenant - datetime.timedelta(hours=1),
        )
        client = Client()
        _connecter(client, self.eleve_a.user)
        r = client.post(reverse('examens_soumettre', args=[copie.id]))
        copie.refresh_from_db()
        self.assertEqual(copie.statut, 'soumise')
        self.assertTrue(copie.soumission_automatique)  # finalisée par le chrono, pas par le clic
        self.assertEqual(copie.date_soumission, copie.date_expiration_effective)


# ==================== HTTP — Consultation (admin/mshrif/superviseur) ====================
# Rendu réel des templates (jamais testé jusqu'ici que via les fonctions de
# permission) — couvre aussi indirectement les liens de sidebar ajoutés dans
# base_mshrif.html/base_superviseur.html (examens_consultation_liste doit
# résoudre et se rendre sans erreur pour ces 2 rôles).

class ConsultationHttpTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof('prof_consult@zidni.test')
        self.groupe = _creer_groupe('groupe consult', prof=self.prof)
        self.eleve = _creer_eleve('eleve_consult@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.superviseur = _creer_superviseur('sup_consult@zidni.test')
        self.superviseur.profs_assignes.add(self.prof)
        self.admin = _creer_admin('admin_consult@zidni.test')
        self.mshrif = _creer_mshrif('mshrif_consult@zidni.test')
        self.examen, self.questions, self.choix = _examen_complet(self.groupe, self.prof, statut='publie')
        self.copie = Copie.objects.create(examen=self.examen, eleve=self.eleve, date_debut=timezone.now())
        soumettre_copie(self.copie)

    def test_liste_accessible_aux_3_roles(self):
        for user in (self.admin, self.mshrif, self.superviseur.user):
            client = Client()
            _connecter(client, user)
            r = client.get(reverse('examens_consultation_liste'))
            self.assertEqual(r.status_code, 200, f"échec pour {user.role}")
            self.assertContains(r, self.examen.titre)

    def test_detail_accessible_aux_3_roles(self):
        for user in (self.admin, self.mshrif, self.superviseur.user):
            client = Client()
            _connecter(client, user)
            r = client.get(reverse('examens_consultation_detail', args=[self.examen.id]))
            self.assertEqual(r.status_code, 200, f"échec pour {user.role}")

    def test_copie_accessible_aux_3_roles(self):
        for user in (self.admin, self.mshrif, self.superviseur.user):
            client = Client()
            _connecter(client, user)
            r = client.get(reverse('examens_consultation_copie', args=[self.copie.id]))
            self.assertEqual(r.status_code, 200, f"échec pour {user.role}")

    def test_superviseur_non_assigne_ne_voit_pas_lexamen_en_consultation(self):
        autre_superviseur = _creer_superviseur('sup_consult_2@zidni.test')
        client = Client()
        _connecter(client, autre_superviseur.user)
        r = client.get(reverse('examens_consultation_detail', args=[self.examen.id]))
        self.assertEqual(r.status_code, 403)

    def test_eleve_navigue_pas_a_la_consultation(self):
        client = Client()
        _connecter(client, self.eleve.user)
        r = client.get(reverse('examens_consultation_liste'))
        self.assertNotEqual(r.status_code, 200)


# ==================== HTTP — Rendu des sidebars (nav ajoutée) ====================
# Vérifie que les liens de sidebar ajoutés dans base_prof.html/base_eleve.html/
# base_superviseur.html/base_mshrif.html (5ème fichier, base_admin.html,
# volontairement NON modifié — conflit signalé, voir rapport) ne cassent
# aucune page existante de ces rôles.

class RenduSidebarSansRegressionTests(TestCase):
    def test_dashboard_prof_se_rend_toujours(self):
        prof = _creer_prof('prof_sidebar@zidni.test')
        client = Client()
        _connecter(client, prof.user)
        r = client.get(reverse('dashboard_prof'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'الاختبارات')

    def test_dashboard_eleve_se_rend_toujours(self):
        eleve = _creer_eleve('eleve_sidebar@zidni.test')
        client = Client()
        _connecter(client, eleve.user, )
        r = client.get(reverse('dashboard_eleve'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'اختباراتي')

    def test_dashboard_superviseur_se_rend_toujours(self):
        superviseur = _creer_superviseur('sup_sidebar@zidni.test')
        client = Client()
        _connecter(client, superviseur.user)
        r = client.get(reverse('dashboard_superviseur'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'الاختبارات')

    def test_dashboard_mshrif_se_rend_toujours(self):
        mshrif = _creer_mshrif('mshrif_sidebar@zidni.test')
        client = Client()
        _connecter(client, mshrif)
        r = client.get(reverse('dashboard_mshrif'))
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'الاختبارات')


# ============================================================================
# Tâche du 2026-08-18 — Type de question "vidéo" (même patron que "audio")
# ============================================================================
class VideoValidationTests(TestCase):
    def test_extension_valide_acceptee(self):
        fichier = SimpleUploadedFile('reponse.mp4', b'contenu-video-factice', content_type='video/mp4')
        self.assertIsNone(valider_fichier_video(fichier))

    def test_extension_invalide_refusee(self):
        fichier = SimpleUploadedFile('reponse.exe', b'contenu', content_type='application/octet-stream')
        self.assertIsNotNone(valider_fichier_video(fichier))

    def test_fichier_vide_refuse(self):
        fichier = SimpleUploadedFile('reponse.mp4', b'', content_type='video/mp4')
        self.assertIsNotNone(valider_fichier_video(fichier))

    def test_fichier_trop_volumineux_refuse(self):
        fichier = SimpleUploadedFile('reponse.mp4', b'0' * (41 * 1024 * 1024), content_type='video/mp4')
        self.assertIsNotNone(valider_fichier_video(fichier))

    def test_aucun_fichier_refuse(self):
        self.assertIsNotNone(valider_fichier_video(None))


class VideoAutosaveHttpTests(TestCase):
    """Chemin serveur d'une réponse vidéo — même patron que test_autosave_audio
    (WorkflowEleveHttpTests)."""

    def setUp(self):
        self.prof = _creer_prof('prof_video_wf@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_video_wf@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.examen, self.questions, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        self.question_video = _ajouter_question_video(self.examen)
        self.client = Client()
        _connecter(self.client, self.eleve.user)

    def test_page_examen_affiche_le_widget_denregistrement_camera_sans_choix_de_fichier(self):
        """Tâche du 2026-08-18 : le repli "اختيار ملف" est retiré pour les
        questions vidéo aussi — seul l'enregistrement direct à la caméra reste
        proposé."""
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        r = self.client.get(reverse('examens_passage', args=[copie.id]))
        html = r.content.decode('utf-8')
        self.assertContains(r, 'demarrerEnregistrementVideo(')
        self.assertContains(r, '📹')
        self.assertNotIn('📎 اختيار ملف', html)
        self.assertNotIn('type="file"', html)

    def test_autosave_video(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        fichier = SimpleUploadedFile('video.mp4', b'contenu-video-factice', content_type='video/mp4')
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.question_video.id]),
            {'reponse_video': fichier},
        )
        self.assertEqual(r.status_code, 200)
        reponse = Reponse.objects.get(copie=copie, question=self.question_video)
        self.assertTrue(reponse.reponse_video)
        self.assertEqual(reponse.nom_fichier_video_original, 'video.mp4')
        reponse.reponse_video.delete(save=False)

    def test_autosave_video_extension_invalide_renvoie_message_precis(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        fichier = SimpleUploadedFile('video.avi', b'contenu-video-factice', content_type='video/x-msvideo')
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.question_video.id]),
            {'reponse_video': fichier},
        )
        self.assertEqual(r.status_code, 400)
        self.assertIn('erreur', r.json())
        self.assertFalse(Reponse.objects.get(copie=copie, question=self.question_video).reponse_video)

    def test_autosave_video_supprimer(self):
        self.client.post(reverse('examens_eleve_avant', args=[self.examen.id]))
        copie = Copie.objects.get(examen=self.examen, eleve=self.eleve)
        reponse = Reponse.objects.create(
            copie=copie, question=self.question_video,
            reponse_video=SimpleUploadedFile('video.mp4', b'contenu-video-factice'),
        )
        r = self.client.post(
            reverse('examens_reponse_autosave', args=[copie.id, self.question_video.id]),
            {'supprimer': '1'},
        )
        self.assertEqual(r.status_code, 200)
        reponse.refresh_from_db()
        self.assertFalse(reponse.reponse_video)


class VideoAccesHttpTests(TestCase):
    """Même patron que AudioAccesHttpTests — reponse_video protégée derrière
    can_access_copie, jamais une URL de fichier imprimée directement."""

    def setUp(self):
        self.prof = _creer_prof('prof_video@zidni.test')
        self.groupe = _creer_groupe(prof=self.prof)
        self.eleve = _creer_eleve('eleve_video@zidni.test')
        self.groupe.eleves.add(self.eleve)
        self.autre_eleve = _creer_eleve('autre_eleve_video@zidni.test')
        self.examen, _, _ = _examen_complet(self.groupe, self.prof, statut='publie')
        self.question_video = _ajouter_question_video(self.examen)
        self.copie = Copie.objects.create(examen=self.examen, eleve=self.eleve, date_debut=timezone.now())
        self.reponse = Reponse.objects.create(
            copie=self.copie, question=self.question_video,
            reponse_video=SimpleUploadedFile('rep.mp4', b'contenu-video-factice'),
        )

    def tearDown(self):
        if self.reponse.reponse_video:
            self.reponse.reponse_video.delete(save=False)

    def test_proprietaire_peut_acceder(self):
        client = Client()
        _connecter(client, self.eleve.user)
        r = client.get(reverse('examens_reponse_video', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 302)

    def test_autre_eleve_refuse(self):
        client = Client()
        _connecter(client, self.autre_eleve.user)
        r = client.get(reverse('examens_reponse_video', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 403)

    def test_prof_du_groupe_peut_acceder(self):
        client = Client()
        _connecter(client, self.prof.user)
        r = client.get(reverse('examens_reponse_video', args=[self.reponse.id]))
        self.assertEqual(r.status_code, 302)


class VideoCorrectionManuelleTests(TestCase):
    """Une question type_question='video' se corrige manuellement, exactement
    comme 'texte'/'audio' — jamais auto-corrigée."""

    def test_video_reste_a_corriger_apres_corriger_automatiquement(self):
        prof = _creer_prof('prof_correction_video@zidni.test')
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve('eleve_correction_video@zidni.test')
        groupe.eleves.add(eleve)
        examen = _creer_examen(groupe, prof=prof, statut='publie')
        question = _ajouter_question_video(examen)
        copie = Copie.objects.create(examen=examen, eleve=eleve, date_debut=timezone.now())
        reponse = Reponse.objects.create(copie=copie, question=question)

        corriger_automatiquement(reponse)
        reponse.refresh_from_db()
        self.assertEqual(reponse.statut_correction, 'a_corriger')
        self.assertIsNone(reponse.points_obtenus)

    def test_correction_manuelle_video_acceptee_par_la_vue(self):
        prof = _creer_prof('prof_correction_video2@zidni.test')
        groupe = _creer_groupe(prof=prof)
        eleve = _creer_eleve('eleve_correction_video2@zidni.test')
        groupe.eleves.add(eleve)
        examen = _creer_examen(groupe, prof=prof, statut='publie')
        question = _ajouter_question_video(examen, points=5)
        copie = Copie.objects.create(examen=examen, eleve=eleve, date_debut=timezone.now(), statut='soumise')
        reponse = Reponse.objects.create(copie=copie, question=question)

        client = Client()
        _connecter(client, prof.user)
        r = client.post(reverse('examens_copie_correction', args=[copie.id]), {
            'reponse_id': reponse.id, 'points_obtenus': '4', 'commentaire': 'جيد',
        })
        self.assertEqual(r.status_code, 302)
        reponse.refresh_from_db()
        self.assertEqual(reponse.statut_correction, 'corrigee')
        self.assertEqual(float(reponse.points_obtenus), 4.0)
