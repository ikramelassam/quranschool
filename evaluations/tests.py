import datetime

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from accounts.models import User, Eleve, Prof, Superviseur, DerniereVisiteNotification
from courses.models import Groupe, Seance
from .models import Evaluation


def _creer_eleve(email='eleve_eval_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme')


def _creer_prof(email='prof_eval_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    return Prof.objects.create(user=u, ville='الرباط', niveau_memorisation='كامل')


def _creer_superviseur(email='superviseur_eval_test@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password='xX!test12345',
        first_name='مؤطر', last_name='تجريبي', role='superviseur', doit_changer_mot_de_passe=False,
    )
    return Superviseur.objects.create(user=u)


class ProfEvaluationsRecuesTests(TestCase):
    """"تقييمات المؤطر لي" (Chantier notifications du 2026-08-19) — manque
    fonctionnel comblé par ce chantier : jusqu'ici aucune vue ne permettait
    au prof de consulter les évaluations écrites sur lui par son مؤطر."""

    def setUp(self):
        self.prof = _creer_prof()
        self.autre_prof = _creer_prof(email='autre_prof_eval_test@zidni.test')
        self.superviseur = _creer_superviseur()
        self.groupe = Groupe.objects.create(nom='مجموعة', prof=self.prof, statut='actif')
        self.seance = Seance.objects.create(
            groupe=self.groupe, date=datetime.date(2026, 8, 10), heure=datetime.time(17, 0),
            type='normal', statut='terminee',
        )
        self.evaluation = Evaluation.objects.create(
            seance=self.seance, superviseur=self.superviseur, prof=self.prof,
            commentaire='أداء جيد.',
        )

    def test_prof_voit_sa_propre_evaluation(self):
        self.client.force_login(self.prof.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'أداء جيد')

    def test_prof_ne_voit_jamais_les_evaluations_dun_autre_prof(self):
        """Le queryset est scopé à prof=request.user.prof — pas de fuite
        même si un autre prof partage un groupe/مؤطر."""
        self.client.force_login(self.autre_prof.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, 'أداء جيد')

    def test_role_eleve_refuse(self):
        eleve = _creer_eleve()
        self.client.force_login(eleve.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertNotEqual(response.status_code, 200)

    def test_role_superviseur_refuse(self):
        self.client.force_login(self.superviseur.user)
        response = self.client.get(reverse('evaluations_prof_recues'))
        self.assertNotEqual(response.status_code, 200)

    def test_visiter_la_page_marque_evaluations_recues_comme_lu(self):
        self.client.force_login(self.prof.user)
        self.assertFalse(
            DerniereVisiteNotification.objects.filter(user=self.prof.user, cle='evaluations_recues').exists()
        )
        self.client.get(reverse('evaluations_prof_recues'))
        self.assertTrue(
            DerniereVisiteNotification.objects.filter(user=self.prof.user, cle='evaluations_recues').exists()
        )
