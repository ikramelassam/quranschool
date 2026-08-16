import datetime

from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import User, Eleve, Prof, Superviseur
from courses.models import Groupe

from .models import Conversation, Message, LectureConversation, get_configuration_chat
from .permissions import can_access_conversation, get_conversations_accessibles
from .services import (
    annoter_separateurs_jour, backfiller_conversations_manquantes,
    conversations_avec_apercu, total_messages_non_lus, marquer_comme_lu,
    purger_messages_expires,
)
from .views import NB_MESSAGES_PAR_PAGE

MOT_DE_PASSE = 'xX!test12345'


def _creer_admin(email='admin_chat@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مدير', last_name='تجريبي', role='admin', doit_changer_mot_de_passe=False,
    )


def _creer_mshrif(email='mshrif_chat@zidni.test'):
    return User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مشرف', last_name='تجريبي', role='mshrif', doit_changer_mot_de_passe=False,
    )


def _creer_eleve(email='eleve_chat@zidni.test', statut='actif'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='طالب', last_name='تجريبي', role='eleve', doit_changer_mot_de_passe=False,
    )
    return Eleve.objects.create(user=u, sexe='homme', statut=statut)


def _creer_prof(email='prof_chat@zidni.test', statut='actif'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='أستاذ', last_name='تجريبي', role='prof', doit_changer_mot_de_passe=False,
    )
    return Prof.objects.create(
        user=u, ville='الرباط', niveau_memorisation='كامل', statut=statut,
        parcours_scolaire='', parcours_enseignant='', compte_bancaire='', rib='', agence_bancaire='',
    )


def _creer_superviseur(email='superviseur_chat@zidni.test'):
    u = User.objects.create_user(
        username=email, email=email, password=MOT_DE_PASSE,
        first_name='مؤطر', last_name='تجريبي', role='superviseur', doit_changer_mot_de_passe=False,
    )
    return Superviseur.objects.create(user=u)


def _connecter(client, user):
    client.force_login(user)


class CreationAutomatiqueConversationTests(TestCase):
    def test_creation_groupe_declenche_creation_conversation(self):
        groupe = Groupe.objects.create(nom='مجموعة الفجر')
        self.assertTrue(Conversation.objects.filter(groupe=groupe).exists())

    def test_aucun_doublon_meme_en_cas_dappel_repete(self):
        groupe = Groupe.objects.create(nom='مجموعة الضحى')
        self.assertEqual(Conversation.objects.filter(groupe=groupe).count(), 1)
        # Un 2e appel explicite (simulation d'une action répétée) ne doit jamais
        # créer de doublon — la contrainte UNIQUE (OneToOneField) l'empêche.
        Conversation.objects.get_or_create(groupe=groupe)
        self.assertEqual(Conversation.objects.filter(groupe=groupe).count(), 1)

    def test_sauvegarde_ulterieure_du_groupe_ne_cree_pas_de_2e_conversation(self):
        groupe = Groupe.objects.create(nom='مجموعة العصر')
        groupe.nom = 'مجموعة العصر المعدّلة'
        groupe.save()
        self.assertEqual(Conversation.objects.filter(groupe=groupe).count(), 1)


class BackfillConversationsExistantesTests(TestCase):
    """Couvre le finding CRITIQUE de l'audit du 2026-08-15 : un groupe créé
    AVANT ce chantier n'a aucune Conversation (le signal ne se déclenche
    qu'à la création). Simule cette situation en supprimant la Conversation
    auto-créée juste après coup — c'est exactement l'état d'un vieux groupe
    en base (backfillé une fois par chat/migrations/0002_backfill_conversations_existantes.py,
    voir aussi chat.services.backfiller_conversations_manquantes qu'elle réplique)."""

    def _simuler_groupe_preexistant(self, nom):
        groupe = Groupe.objects.create(nom=nom)
        Conversation.objects.filter(groupe=groupe).delete()
        self.assertFalse(Conversation.objects.filter(groupe=groupe).exists())
        return groupe

    def test_backfill_cree_une_conversation_pour_chaque_groupe_orphelin(self):
        groupe1 = self._simuler_groupe_preexistant('مجموعة قديمة 1')
        groupe2 = self._simuler_groupe_preexistant('مجموعة قديمة 2')
        groupe_recent = Groupe.objects.create(nom='مجموعة حديثة')  # a déjà sa conversation

        nb_crees = backfiller_conversations_manquantes()

        self.assertEqual(nb_crees, 2)
        self.assertTrue(Conversation.objects.filter(groupe=groupe1).exists())
        self.assertTrue(Conversation.objects.filter(groupe=groupe2).exists())
        self.assertEqual(Conversation.objects.filter(groupe=groupe_recent).count(), 1)

    def test_backfill_idempotent_aucun_doublon_si_rejoue(self):
        groupe = self._simuler_groupe_preexistant('مجموعة قديمة 3')
        premier_passage = backfiller_conversations_manquantes()
        deuxieme_passage = backfiller_conversations_manquantes()

        self.assertEqual(premier_passage, 1)
        self.assertEqual(deuxieme_passage, 0)
        self.assertEqual(Conversation.objects.filter(groupe=groupe).count(), 1)

    def test_aucun_groupe_ne_possede_deux_conversations_apres_backfill(self):
        for i in range(5):
            self._simuler_groupe_preexistant(f'مجموعة قديمة {i}')
        Groupe.objects.create(nom='مجموعة حديثة أخرى')

        backfiller_conversations_manquantes()

        from django.db.models import Count
        doublons = (
            Conversation.objects.values('groupe_id')
            .annotate(n=Count('id'))
            .filter(n__gt=1)
        )
        self.assertEqual(list(doublons), [])

    def test_groupe_backfille_devient_accessible_a_ses_membres(self):
        """Vérifie bout en bout que le backfill résout réellement le bug
        constaté : un élève de ce groupe pouvait accéder au groupe mais pas
        à son chat avant le backfill (Conversation.DoesNotExist -> 404)."""
        eleve = _creer_eleve()
        groupe = self._simuler_groupe_preexistant('مجموعة قديمة يملكها طالب')
        groupe.eleves.add(eleve)

        client = Client()
        _connecter(client, eleve.user)
        self.assertEqual(client.get(f'/chat/{groupe.id}/').status_code, 404)

        backfiller_conversations_manquantes()

        self.assertEqual(client.get(f'/chat/{groupe.id}/').status_code, 200)


class PermissionsEleveTests(TestCase):
    def setUp(self):
        self.groupe = Groupe.objects.create(nom='مجموعة الطلاب')
        self.autre_groupe = Groupe.objects.create(nom='مجموعة أخرى')
        self.eleve = _creer_eleve()
        self.groupe.eleves.add(self.eleve)

    def test_eleve_du_groupe_a_acces(self):
        conv = self.groupe.conversation
        self.assertTrue(can_access_conversation(self.eleve.user, conv))

    def test_eleve_dun_autre_groupe_refuse(self):
        conv_autre = self.autre_groupe.conversation
        self.assertFalse(can_access_conversation(self.eleve.user, conv_autre))

    def test_eleve_retire_perd_acces(self):
        self.groupe.eleves.remove(self.eleve)
        conv = self.groupe.conversation
        self.assertFalse(can_access_conversation(self.eleve.user, conv))

    def test_eleve_archive_perd_acces(self):
        self.eleve.statut = 'archive'
        self.eleve.save()
        conv = self.groupe.conversation
        self.assertFalse(can_access_conversation(self.eleve.user, conv))

    def test_eleve_reactive_recupere_acces_sil_est_toujours_membre(self):
        self.eleve.statut = 'archive'
        self.eleve.save()
        self.eleve.statut = 'actif'
        self.eleve.save()
        conv = self.groupe.conversation
        self.assertTrue(can_access_conversation(self.eleve.user, conv))

    def test_changement_de_groupe(self):
        self.groupe.eleves.remove(self.eleve)
        self.autre_groupe.eleves.add(self.eleve)
        self.assertFalse(can_access_conversation(self.eleve.user, self.groupe.conversation))
        self.assertTrue(can_access_conversation(self.eleve.user, self.autre_groupe.conversation))


class PermissionsProfTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof()
        self.autre_prof = _creer_prof(email='autre_prof_chat@zidni.test')
        self.groupe = Groupe.objects.create(nom='مجموعة الأستاذ', prof=self.prof)

    def test_prof_affecte_a_acces(self):
        self.assertTrue(can_access_conversation(self.prof.user, self.groupe.conversation))

    def test_autre_prof_refuse(self):
        self.assertFalse(can_access_conversation(self.autre_prof.user, self.groupe.conversation))

    def test_changement_de_professeur(self):
        self.groupe.prof = self.autre_prof
        self.groupe.save()
        self.assertFalse(can_access_conversation(self.prof.user, self.groupe.conversation))
        self.assertTrue(can_access_conversation(self.autre_prof.user, self.groupe.conversation))

    def test_prof_archive_perd_acces(self):
        self.prof.statut = 'archive'
        self.prof.save()
        self.assertFalse(can_access_conversation(self.prof.user, self.groupe.conversation))


class PermissionsSuperviseurTests(TestCase):
    def setUp(self):
        self.prof = _creer_prof()
        self.autre_prof = _creer_prof(email='autre_prof_sup@zidni.test')
        self.groupe = Groupe.objects.create(nom='مجموعة مؤطرة', prof=self.prof)
        self.autre_groupe = Groupe.objects.create(nom='مجموعة غير مؤطرة', prof=self.autre_prof)
        self.superviseur = _creer_superviseur()
        self.superviseur.profs_assignes.add(self.prof)

    def test_superviseur_supervise_prof_a_acces(self):
        self.assertTrue(can_access_conversation(self.superviseur.user, self.groupe.conversation))

    def test_prof_non_supervise_refuse(self):
        self.assertFalse(can_access_conversation(self.superviseur.user, self.autre_groupe.conversation))

    def test_changement_de_supervision(self):
        self.superviseur.profs_assignes.remove(self.prof)
        self.superviseur.profs_assignes.add(self.autre_prof)
        self.assertFalse(can_access_conversation(self.superviseur.user, self.groupe.conversation))
        self.assertTrue(can_access_conversation(self.superviseur.user, self.autre_groupe.conversation))

    def test_aucun_prof_supervise_aucune_conversation(self):
        nouveau_superviseur = _creer_superviseur(email='sup_seul_chat@zidni.test')
        self.assertEqual(get_conversations_accessibles(nouveau_superviseur.user).count(), 0)


class PermissionsAdminEtMshrifTests(TestCase):
    def setUp(self):
        self.admin = _creer_admin()
        self.mshrif = _creer_mshrif()
        self.groupe1 = Groupe.objects.create(nom='مجموعة 1')
        self.groupe2 = Groupe.objects.create(nom='مجموعة 2')

    def test_admin_acces_global(self):
        self.assertTrue(can_access_conversation(self.admin, self.groupe1.conversation))
        self.assertTrue(can_access_conversation(self.admin, self.groupe2.conversation))

    def test_mshrif_naccede_a_aucune_conversation(self):
        self.assertFalse(can_access_conversation(self.mshrif, self.groupe1.conversation))
        self.assertEqual(get_conversations_accessibles(self.mshrif).count(), 0)

    def test_mshrif_redirige_hors_du_chat(self):
        client = Client()
        _connecter(client, self.mshrif)
        response = client.get('/chat/')
        self.assertEqual(response.status_code, 302)
        self.assertNotEqual(response.url, '/chat/')


class IdorHttpEleveTests(TestCase):
    """Vérification IDOR par de VRAIES requêtes HTTP (pas seulement
    can_access_conversation() en direct) sur TOUS les endpoints sensibles du
    chat, pour le rôle élève (Point 4 de l'audit du 2026-08-15)."""

    def setUp(self):
        self.eleve = _creer_eleve()
        self.mon_groupe = Groupe.objects.create(nom='مجموعتي')
        self.mon_groupe.eleves.add(self.eleve)
        self.autre_groupe = Groupe.objects.create(nom='مجموعة غيري')
        self.client = Client()
        _connecter(self.client, self.eleve.user)

    def test_page_conversation_dune_autre_conversation_refusee(self):
        response = self.client.get(f'/chat/{self.autre_groupe.id}/')
        self.assertEqual(response.status_code, 403)

    def test_panneau_ajax_refuse(self):
        response = self.client.get(f'/chat/{self.autre_groupe.id}/panneau/')
        self.assertEqual(response.status_code, 403)

    def test_polling_messages_refuse(self):
        response = self.client.get(f'/chat/{self.autre_groupe.id}/messages/')
        self.assertEqual(response.status_code, 403)

    def test_chargement_historique_refuse(self):
        response = self.client.get(f'/chat/{self.autre_groupe.id}/messages/?avant=999999')
        self.assertEqual(response.status_code, 403)

    def test_polling_apres_refuse(self):
        response = self.client.get(f'/chat/{self.autre_groupe.id}/messages/?apres=0')
        self.assertEqual(response.status_code, 403)

    def test_envoi_message_refuse(self):
        response = self.client.post(f'/chat/{self.autre_groupe.id}/envoyer/', {'contenu': 'salut'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.autre_groupe.conversation.messages.count(), 0)

    def test_marquage_lu_refuse(self):
        response = self.client.post(f'/chat/{self.autre_groupe.id}/lu/')
        self.assertEqual(response.status_code, 403)

    def test_fichier_dune_autre_conversation_refuse(self):
        autre_prof = _creer_prof(email='prof_idor@zidni.test')
        self.autre_groupe.prof = autre_prof
        self.autre_groupe.save()
        message = Message.objects.create(
            conversation=self.autre_groupe.conversation, auteur=autre_prof.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='سري',
        )
        response = self.client.get(f'/chat/{self.autre_groupe.id}/fichier/{message.id}/')
        self.assertEqual(response.status_code, 403)

    def test_page_conversation_de_mon_groupe_autorisee(self):
        response = self.client.get(f'/chat/{self.mon_groupe.id}/')
        self.assertEqual(response.status_code, 200)

    def test_fichier_de_mon_propre_groupe_autorise(self):
        """Chemin positif manquant dans l'audit précédent : seul le refus était
        testé, jamais l'accès réussi à un fichier légitime."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('rapport.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        message = Message.objects.create(
            conversation=self.mon_groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='fichier',
            contenu='', fichier=fichier, nom_fichier_original='rapport.pdf',
        )
        response = self.client.get(f'/chat/{self.mon_groupe.id}/fichier/{message.id}/')
        self.assertEqual(response.status_code, 302)
        message.fichier.delete(save=False)

    def test_acces_perdu_apres_retrait_du_groupe_y_compris_fichier(self):
        """Point 13 : "un utilisateur qui n'a plus accès à une conversation ne
        doit pas pouvoir récupérer un fichier appartenant à cette
        conversation" — vérifié en conditions réelles : accès OK avant
        retrait, refusé immédiatement après, sur la page ET sur le fichier."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('doc.pdf', b'%PDF-1.4 x', content_type='application/pdf')
        message = Message.objects.create(
            conversation=self.mon_groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='fichier',
            contenu='', fichier=fichier, nom_fichier_original='doc.pdf',
        )
        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/fichier/{message.id}/').status_code, 302)

        self.mon_groupe.eleves.remove(self.eleve)

        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/').status_code, 403)
        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/fichier/{message.id}/').status_code, 403)
        message.fichier.delete(save=False)


class IdorHttpProfTests(TestCase):
    """Même couverture que IdorHttpEleveTests, pour le rôle prof — l'audit du
    2026-08-15 notait que seul le rôle élève était vérifié par de vraies
    requêtes HTTP."""

    def setUp(self):
        self.prof = _creer_prof()
        self.autre_prof = _creer_prof(email='autre_prof_idor@zidni.test')
        self.mon_groupe = Groupe.objects.create(nom='مجموعة أستاذي', prof=self.prof)
        self.autre_groupe = Groupe.objects.create(nom='مجموعة أستاذ آخر', prof=self.autre_prof)
        self.client = Client()
        _connecter(self.client, self.prof.user)

    def test_page_groupe_dont_il_est_le_prof_autorisee(self):
        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/').status_code, 200)

    def test_page_groupe_dun_autre_prof_refusee(self):
        self.assertEqual(self.client.get(f'/chat/{self.autre_groupe.id}/').status_code, 403)

    def test_panneau_dun_autre_prof_refuse(self):
        self.assertEqual(self.client.get(f'/chat/{self.autre_groupe.id}/panneau/').status_code, 403)

    def test_messages_dun_autre_prof_refuses(self):
        self.assertEqual(self.client.get(f'/chat/{self.autre_groupe.id}/messages/').status_code, 403)
        self.assertEqual(self.client.get(f'/chat/{self.autre_groupe.id}/messages/?avant=999').status_code, 403)
        self.assertEqual(self.client.get(f'/chat/{self.autre_groupe.id}/messages/?apres=0').status_code, 403)

    def test_envoi_dans_groupe_dun_autre_prof_refuse(self):
        response = self.client.post(f'/chat/{self.autre_groupe.id}/envoyer/', {'contenu': 'test'})
        self.assertEqual(response.status_code, 403)
        self.assertEqual(self.autre_groupe.conversation.messages.count(), 0)

    def test_envoi_dans_son_propre_groupe_autorise(self):
        response = self.client.post(f'/chat/{self.mon_groupe.id}/envoyer/', {'contenu': 'مرحباً بالطلاب'})
        self.assertEqual(response.status_code, 200)
        self.assertEqual(self.mon_groupe.conversation.messages.count(), 1)

    def test_marquage_lu_dun_autre_prof_refuse(self):
        self.assertEqual(self.client.post(f'/chat/{self.autre_groupe.id}/lu/').status_code, 403)

    def test_fichier_dun_autre_prof_refuse(self):
        message = Message.objects.create(
            conversation=self.autre_groupe.conversation, auteur=self.autre_prof.user,
            auteur_nom='أستاذ آخر', auteur_role='prof', type_message='texte', contenu='سري',
        )
        self.assertEqual(self.client.get(f'/chat/{self.autre_groupe.id}/fichier/{message.id}/').status_code, 403)

    def test_changement_de_groupe_recalcule_laccess_http(self):
        """Le prof change de groupe -> perd l'accès HTTP à l'ancien, gagne
        l'accès HTTP au nouveau (Point 9/16)."""
        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/').status_code, 200)
        self.mon_groupe.prof = self.autre_prof
        self.mon_groupe.save()
        self.assertEqual(self.client.get(f'/chat/{self.mon_groupe.id}/').status_code, 403)


class IdorHttpSuperviseurTests(TestCase):
    """Même couverture, pour le rôle مؤطر — accès basé sur profs_assignes
    ACTUEL, vérifié via de vraies requêtes HTTP."""

    def setUp(self):
        self.prof_supervise = _creer_prof(email='prof_supervise_idor@zidni.test')
        self.prof_non_supervise = _creer_prof(email='prof_non_supervise_idor@zidni.test')
        self.superviseur = _creer_superviseur()
        self.superviseur.profs_assignes.add(self.prof_supervise)
        self.groupe_supervise = Groupe.objects.create(nom='مجموعة مؤطرة', prof=self.prof_supervise)
        self.groupe_non_supervise = Groupe.objects.create(nom='مجموعة غير مؤطرة', prof=self.prof_non_supervise)
        self.client = Client()
        _connecter(self.client, self.superviseur.user)

    def test_page_groupe_supervise_autorisee(self):
        self.assertEqual(self.client.get(f'/chat/{self.groupe_supervise.id}/').status_code, 200)

    def test_page_groupe_non_supervise_refusee(self):
        self.assertEqual(self.client.get(f'/chat/{self.groupe_non_supervise.id}/').status_code, 403)

    def test_messages_groupe_non_supervise_refuses(self):
        self.assertEqual(self.client.get(f'/chat/{self.groupe_non_supervise.id}/messages/').status_code, 403)

    def test_envoi_groupe_non_supervise_refuse(self):
        response = self.client.post(f'/chat/{self.groupe_non_supervise.id}/envoyer/', {'contenu': 'test'})
        self.assertEqual(response.status_code, 403)

    def test_fichier_groupe_non_supervise_refuse(self):
        message = Message.objects.create(
            conversation=self.groupe_non_supervise.conversation, auteur=self.prof_non_supervise.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='سري',
        )
        self.assertEqual(
            self.client.get(f'/chat/{self.groupe_non_supervise.id}/fichier/{message.id}/').status_code, 403
        )

    def test_changement_de_supervision_recalcule_laccess_http(self):
        self.assertEqual(self.client.get(f'/chat/{self.groupe_supervise.id}/').status_code, 200)
        self.superviseur.profs_assignes.remove(self.prof_supervise)
        self.assertEqual(self.client.get(f'/chat/{self.groupe_supervise.id}/').status_code, 403)
        self.superviseur.profs_assignes.add(self.prof_non_supervise)
        self.assertEqual(self.client.get(f'/chat/{self.groupe_non_supervise.id}/').status_code, 200)


class IdorHttpAdminTests(TestCase):
    """Le مدير a un accès HTTP global — vérifié par de vraies requêtes, pas
    seulement can_access_conversation()."""

    def setUp(self):
        self.admin = _creer_admin()
        self.prof = _creer_prof()
        self.groupe_avec_prof = Groupe.objects.create(nom='مجموعة 1', prof=self.prof)
        self.groupe_sans_prof = Groupe.objects.create(nom='مجموعة 2')
        self.client = Client()
        _connecter(self.client, self.admin)

    def test_page_nimporte_quel_groupe_autorisee(self):
        self.assertEqual(self.client.get(f'/chat/{self.groupe_avec_prof.id}/').status_code, 200)
        self.assertEqual(self.client.get(f'/chat/{self.groupe_sans_prof.id}/').status_code, 200)

    def test_liste_conversations_inclut_tous_les_groupes(self):
        response = self.client.get('/chat/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.context['conversations']), 2)

    def test_envoi_dans_nimporte_quel_groupe_autorise(self):
        response = self.client.post(f'/chat/{self.groupe_sans_prof.id}/envoyer/', {'contenu': 'من المدير'})
        self.assertEqual(response.status_code, 200)


class HistoriqueTests(TestCase):
    def test_retrait_dun_eleve_ne_supprime_pas_lhistorique(self):
        eleve = _creer_eleve()
        groupe = Groupe.objects.create(nom='مجموعة تاريخية')
        groupe.eleves.add(eleve)
        Message.objects.create(
            conversation=groupe.conversation, auteur=eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='سلام',
        )
        groupe.eleves.remove(eleve)
        self.assertEqual(groupe.conversation.messages.count(), 1)

    def test_changement_de_prof_conserve_lhistorique(self):
        prof1 = _creer_prof(email='prof_hist1@zidni.test')
        prof2 = _creer_prof(email='prof_hist2@zidni.test')
        groupe = Groupe.objects.create(nom='مجموعة تغيير أستاذ', prof=prof1)
        Message.objects.create(
            conversation=groupe.conversation, auteur=prof1.user,
            auteur_nom='أستاذ 1', auteur_role='prof', type_message='texte', contenu='مرحباً',
        )
        groupe.prof = prof2
        groupe.save()
        self.assertEqual(groupe.conversation.messages.count(), 1)
        self.assertEqual(groupe.conversation.messages.first().auteur_nom, 'أستاذ 1')


class EnvoiMessagesTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve()
        self.groupe = Groupe.objects.create(nom='مجموعة الرسائل')
        self.groupe.eleves.add(self.eleve)
        self.client = Client()
        _connecter(self.client, self.eleve.user)

    def test_envoi_message_texte(self):
        response = self.client.post(f'/chat/{self.groupe.id}/envoyer/', {'contenu': 'السلام عليكم', 'type_message': 'texte'})
        self.assertEqual(response.status_code, 200)
        message = self.groupe.conversation.messages.first()
        self.assertEqual(message.contenu, 'السلام عليكم')
        self.assertEqual(message.auteur_role, 'eleve')
        self.assertEqual(message.auteur_nom, self.eleve.user.get_full_name())

    def test_message_vide_refuse(self):
        response = self.client.post(f'/chat/{self.groupe.id}/envoyer/', {'contenu': ''})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.groupe.conversation.messages.count(), 0)

    def test_envoi_piece_jointe(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('document.pdf', b'%PDF-1.4 contenu factice', content_type='application/pdf')
        response = self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'fichier', 'fichier': fichier,
        })
        self.assertEqual(response.status_code, 200)
        message = self.groupe.conversation.messages.first()
        self.assertEqual(message.type_message, 'fichier')
        self.assertTrue(message.fichier)
        message.fichier.delete(save=False)

    def test_extension_non_autorisee_refusee(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('script.exe', b'MZ', content_type='application/octet-stream')
        response = self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'fichier', 'fichier': fichier,
        })
        self.assertEqual(response.status_code, 400)
        self.assertEqual(self.groupe.conversation.messages.count(), 0)

    def test_envoi_audio(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('voice.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        response = self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'audio', 'fichier': fichier,
        })
        self.assertEqual(response.status_code, 200)
        message = self.groupe.conversation.messages.first()
        self.assertEqual(message.type_message, 'audio')
        message.fichier.delete(save=False)


class NotificationsNonLusTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve()
        self.prof = _creer_prof()
        self.groupe = Groupe.objects.create(nom='مجموعة الإشعارات', prof=self.prof)
        self.groupe.eleves.add(self.eleve)

    def test_nouveau_message_dun_autre_compte_comme_non_lu(self):
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.prof.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='مرحباً بالطلاب',
        )
        self.assertEqual(total_messages_non_lus(self.eleve.user), 1)

    def test_propre_message_jamais_compte_comme_non_lu(self):
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='سؤال',
        )
        self.assertEqual(total_messages_non_lus(self.eleve.user), 0)

    def test_marquage_comme_lu_annule_le_compteur(self):
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.prof.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='مرحباً',
        )
        marquer_comme_lu(self.groupe.conversation, self.eleve.user)
        self.assertEqual(total_messages_non_lus(self.eleve.user), 0)

    def test_ouverture_de_la_page_marque_comme_lu(self):
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.prof.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='مرحباً',
        )
        client = Client()
        _connecter(client, self.eleve.user)
        client.get(f'/chat/{self.groupe.id}/')
        self.assertEqual(total_messages_non_lus(self.eleve.user), 0)

    def test_apercu_liste_conversations_inclut_dernier_message_et_non_lus(self):
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.prof.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='آخر رسالة',
        )
        conversations = conversations_avec_apercu(self.eleve.user)
        self.assertEqual(len(conversations), 1)
        self.assertEqual(conversations[0].dernier_message['contenu'], 'آخر رسالة')
        self.assertEqual(conversations[0].nb_non_lus, 1)


class PurgeRetentionTests(TestCase):
    def setUp(self):
        self.eleve = _creer_eleve()
        self.groupe = Groupe.objects.create(nom='مجموعة الحذف')
        self.groupe.eleves.add(self.eleve)

    def _creer_message(self, contenu, date_envoi):
        message = Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu=contenu,
        )
        Message.objects.filter(id=message.id).update(date_envoi=date_envoi)
        return message

    def test_message_ancien_supprime(self):
        config = get_configuration_chat()
        config.duree_retention_jours = 7
        config.save()
        self._creer_message('رسالة قديمة', timezone.now() - datetime.timedelta(days=10))
        nb = purger_messages_expires()
        self.assertEqual(nb, 1)
        self.assertEqual(self.groupe.conversation.messages.count(), 0)

    def test_message_recent_conserve(self):
        config = get_configuration_chat()
        config.duree_retention_jours = 7
        config.save()
        self._creer_message('رسالة حديثة', timezone.now() - datetime.timedelta(days=1))
        nb = purger_messages_expires()
        self.assertEqual(nb, 0)
        self.assertEqual(self.groupe.conversation.messages.count(), 1)

    def test_duree_configurable(self):
        config = get_configuration_chat()
        config.duree_retention_jours = 30
        config.save()
        self._creer_message('رسالة عمرها 10 أيام', timezone.now() - datetime.timedelta(days=10))
        nb = purger_messages_expires()
        self.assertEqual(nb, 0)
        self.assertEqual(self.groupe.conversation.messages.count(), 1)

    def test_purge_ne_touche_pas_aux_groupes_ni_aux_comptes(self):
        self._creer_message('رسالة قديمة', timezone.now() - datetime.timedelta(days=10))
        purger_messages_expires()
        self.assertTrue(Groupe.objects.filter(id=self.groupe.id).exists())
        self.assertTrue(User.objects.filter(id=self.eleve.user.id).exists())
        self.assertTrue(Conversation.objects.filter(groupe=self.groupe).exists())


class PerformanceTests(TestCase):
    def test_liste_conversations_ne_fait_pas_de_n_plus_1(self):
        prof = _creer_prof()
        superviseur = _creer_superviseur()
        superviseur.profs_assignes.add(prof)
        for i in range(15):
            groupe = Groupe.objects.create(nom=f'مجموعة أداء {i}', prof=prof)
            Message.objects.create(
                conversation=groupe.conversation, auteur=prof.user,
                auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu=f'رسالة {i}',
            )
        with self.assertNumQueries(4):
            list(conversations_avec_apercu(superviseur.user))

    def test_total_non_lus_ne_scanne_pas_tout_lhistorique_a_chaque_appel(self):
        eleve = _creer_eleve()
        groupe = Groupe.objects.create(nom='مجموعة أداء الإشعارات')
        groupe.eleves.add(eleve)
        prof = _creer_prof()
        Message.objects.create(
            conversation=groupe.conversation, auteur=prof.user,
            auteur_nom='أستاذ', auteur_role='prof', type_message='texte', contenu='رسالة',
        )
        premier = total_messages_non_lus(eleve.user)
        with self.assertNumQueries(0):
            deuxieme = total_messages_non_lus(eleve.user)
        self.assertEqual(premier, deuxieme)


class PollingLimiteTests(TestCase):
    """Couvre le finding HIGH de l'audit du 2026-08-15 : la branche `apres=`
    de chat_messages (polling) n'était bornée par AUCUNE limite, contrairement
    aux 2 autres branches — un curseur périmé pouvait renvoyer tout
    l'historique restant d'une conversation en une seule réponse."""

    def setUp(self):
        self.eleve = _creer_eleve()
        self.groupe = Groupe.objects.create(nom='مجموعة الاستقصاء')
        self.groupe.eleves.add(self.eleve)
        self.client = Client()
        _connecter(self.client, self.eleve.user)

    def _creer_messages(self, n):
        for i in range(n):
            Message.objects.create(
                conversation=self.groupe.conversation, auteur=self.eleve.user,
                auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu=f'رسالة {i}',
            )

    def test_apres_est_borne_a_nb_messages_par_page(self):
        self._creer_messages(NB_MESSAGES_PAR_PAGE + 15)
        data = self.client.get(f'/chat/{self.groupe.id}/messages/?apres=0').json()
        self.assertEqual(data['nb_messages'], NB_MESSAGES_PAR_PAGE)
        self.assertTrue(data['a_plus_recent'])

    def test_curseur_perime_ne_charge_jamais_tout_lhistorique_en_un_lot(self):
        """Simule un onglet resté inactif longtemps : le curseur pointe vers le
        tout début, alors qu'il existe largement plus de messages que la
        limite d'une page."""
        self._creer_messages(NB_MESSAGES_PAR_PAGE * 3)
        data = self.client.get(f'/chat/{self.groupe.id}/messages/?apres=0').json()
        self.assertLessEqual(data['nb_messages'], NB_MESSAGES_PAR_PAGE)

    def test_peu_de_nouveaux_messages_najoute_pas_a_plus_recent(self):
        self._creer_messages(3)
        data = self.client.get(f'/chat/{self.groupe.id}/messages/?apres=0').json()
        self.assertEqual(data['nb_messages'], 3)
        self.assertFalse(data['a_plus_recent'])

    def test_plusieurs_lots_permettent_de_tout_rattraper(self):
        """"Si nécessaire, gérer correctement le cas où plusieurs lots sont
        nécessaires" — un client qui rejoue apres=<dernier_id> jusqu'à
        a_plus_recent=False finit par recevoir la totalité des messages, sans
        jamais recevoir plus de NB_MESSAGES_PAR_PAGE en une seule réponse."""
        total = NB_MESSAGES_PAR_PAGE + 10
        self._creer_messages(total)
        dernier_id = 0
        recus = 0
        for _ in range(10):  # garde-fou anti-boucle-infinie en cas de régression
            data = self.client.get(f'/chat/{self.groupe.id}/messages/?apres={dernier_id}').json()
            self.assertLessEqual(data['nb_messages'], NB_MESSAGES_PAR_PAGE)
            recus += data['nb_messages']
            if data['nb_messages']:
                dernier_id = data['dernier_id']
            if not data['a_plus_recent']:
                break
        else:
            self.fail("le rattrapage n'a jamais atteint a_plus_recent=False")
        self.assertEqual(recus, total)


def _dt(annee, mois, jour, heure=12):
    return timezone.make_aware(datetime.datetime(annee, mois, jour, heure))


class SeparateurJourAnnotationTests(TestCase):
    """Tests unitaires de chat.services.annoter_separateurs_jour — couvre le
    finding MEDIUM de l'audit du 2026-08-15 : {% ifchanged %} n'avait aucune
    mémoire entre deux rendus HTML indépendants (un lot de polling ou un lot
    d'historique ancien), donc réaffichait le séparateur de jour à chaque lot
    même sans changement de jour réel."""

    def test_premier_message_recoit_un_separateur_sans_ancre(self):
        m1 = Message(date_envoi=_dt(2026, 8, 10, 9))
        annoter_separateurs_jour([m1], jour_precedent=None)
        self.assertEqual(m1.jour_separateur, datetime.date(2026, 8, 10))

    def test_messages_du_meme_jour_un_seul_separateur(self):
        m1 = Message(date_envoi=_dt(2026, 8, 10, 9))
        m2 = Message(date_envoi=_dt(2026, 8, 10, 15))
        annoter_separateurs_jour([m1, m2], jour_precedent=None)
        self.assertIsNotNone(m1.jour_separateur)
        self.assertIsNone(m2.jour_separateur)

    def test_changement_de_jour_a_linterieur_du_lot_redeclenche_un_separateur(self):
        m1 = Message(date_envoi=_dt(2026, 8, 10, 23))
        m2 = Message(date_envoi=_dt(2026, 8, 11, 1))
        annoter_separateurs_jour([m1, m2], jour_precedent=None)
        self.assertIsNotNone(m1.jour_separateur)
        self.assertIsNotNone(m2.jour_separateur)
        self.assertNotEqual(m1.jour_separateur, m2.jour_separateur)

    def test_jour_precedent_identique_supprime_le_separateur_redondant(self):
        """Cœur du correctif polling : le lot commence le même jour que ce qui
        est déjà affiché côté client -> pas de séparateur redondant."""
        m1 = Message(date_envoi=_dt(2026, 8, 10, 15))
        annoter_separateurs_jour([m1], jour_precedent=datetime.date(2026, 8, 10))
        self.assertIsNone(m1.jour_separateur)

    def test_jour_precedent_different_declenche_le_separateur(self):
        m1 = Message(date_envoi=_dt(2026, 8, 11, 1))
        annoter_separateurs_jour([m1], jour_precedent=datetime.date(2026, 8, 10))
        self.assertIsNotNone(m1.jour_separateur)


class SeparateurJourHttpTests(TestCase):
    """Vérifie côté HTTP que le HTML de polling ne contient pas de séparateur
    redondant quand le nouveau lot commence le même jour que le message-ancre
    (`apres=`), et en contient bien un quand le jour a réellement changé."""

    def setUp(self):
        self.eleve = _creer_eleve()
        self.groupe = Groupe.objects.create(nom='مجموعة الفواصل')
        self.groupe.eleves.add(self.eleve)
        self.client = Client()
        _connecter(self.client, self.eleve.user)

    def test_polling_meme_jour_najoute_pas_de_separateur_redondant(self):
        m1 = Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='الأول',
        )
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='الثاني',
        )
        html = self.client.get(f'/chat/{self.groupe.id}/messages/?apres={m1.id}').json()['html']
        self.assertNotIn('chat-day-sep', html)

    def test_polling_jour_different_ajoute_un_separateur(self):
        m1 = Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='الأول',
        )
        Message.objects.filter(id=m1.id).update(date_envoi=timezone.now() - datetime.timedelta(days=2))
        Message.objects.create(
            conversation=self.groupe.conversation, auteur=self.eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='الثاني',
        )
        html = self.client.get(f'/chat/{self.groupe.id}/messages/?apres={m1.id}').json()['html']
        self.assertIn('chat-day-sep', html)


class RetentionConfigViewTests(TestCase):
    """Couvre le finding MEDIUM de l'audit du 2026-08-15 :
    admin_reglage_retention_chat n'avait aucun test."""

    def setUp(self):
        self.admin = _creer_admin()
        self.client = Client()

    def test_valeur_par_defaut_7_jours(self):
        self.assertEqual(get_configuration_chat().duree_retention_jours, 7)

    def test_admin_peut_consulter(self):
        _connecter(self.client, self.admin)
        response = self.client.get('/dashboard/admin/reglage-retention-chat/')
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.context['config'].duree_retention_jours, 7)

    def test_admin_peut_modifier_une_valeur_valide(self):
        _connecter(self.client, self.admin)
        response = self.client.post('/dashboard/admin/reglage-retention-chat/', {'duree_retention_jours': '30'})
        self.assertRedirects(response, '/dashboard/admin/reglage-retention-chat/')
        config = get_configuration_chat()
        self.assertEqual(config.duree_retention_jours, 30)
        self.assertEqual(config.derniere_modification_par, self.admin)

    def test_valeur_invalide_zero_rejetee(self):
        _connecter(self.client, self.admin)
        self.client.post('/dashboard/admin/reglage-retention-chat/', {'duree_retention_jours': '0'})
        self.assertEqual(get_configuration_chat().duree_retention_jours, 7)

    def test_valeur_invalide_negative_rejetee(self):
        _connecter(self.client, self.admin)
        self.client.post('/dashboard/admin/reglage-retention-chat/', {'duree_retention_jours': '-5'})
        self.assertEqual(get_configuration_chat().duree_retention_jours, 7)

    def test_valeur_invalide_non_numerique_rejetee(self):
        _connecter(self.client, self.admin)
        self.client.post('/dashboard/admin/reglage-retention-chat/', {'duree_retention_jours': 'abc'})
        self.assertEqual(get_configuration_chat().duree_retention_jours, 7)

    def test_non_admin_ne_peut_pas_consulter(self):
        comptes = [
            _creer_eleve(email='eleve_retention_view@zidni.test').user,
            _creer_prof(email='prof_retention_view@zidni.test').user,
            _creer_superviseur(email='sup_retention_view@zidni.test').user,
            _creer_mshrif(email='mshrif_retention_view@zidni.test'),
        ]
        for user in comptes:
            with self.subTest(role=user.role):
                client = Client()
                _connecter(client, user)
                self.assertEqual(client.get('/dashboard/admin/reglage-retention-chat/').status_code, 302)

    def test_non_admin_ne_peut_pas_modifier(self):
        eleve = _creer_eleve(email='eleve_retention_modif@zidni.test')
        client = Client()
        _connecter(client, eleve.user)
        client.post('/dashboard/admin/reglage-retention-chat/', {'duree_retention_jours': '99'})
        self.assertEqual(get_configuration_chat().duree_retention_jours, 7)

    def test_valeur_configuree_reellement_utilisee_par_la_purge(self):
        _connecter(self.client, self.admin)
        self.client.post('/dashboard/admin/reglage-retention-chat/', {'duree_retention_jours': '2'})

        eleve = _creer_eleve(email='eleve_retention_purge@zidni.test')
        groupe = Groupe.objects.create(nom='مجموعة اختبار المدة')
        groupe.eleves.add(eleve)
        message = Message.objects.create(
            conversation=groupe.conversation, auteur=eleve.user,
            auteur_nom='طالب', auteur_role='eleve', type_message='texte', contenu='رسالة',
        )
        Message.objects.filter(id=message.id).update(date_envoi=timezone.now() - datetime.timedelta(days=3))

        nb = purger_messages_expires()
        self.assertEqual(nb, 1)


class ComposerJsRenduTests(TestCase):
    """Régression (2026-08-16) : base_eleve.html et base_superviseur.html
    n'avaient PAS de `{% block extra_js %}{% endblock %}` — Django ignore
    silencieusement un bloc enfant sans bloc parent correspondant, donc tout
    le JS du composer chat.html (attache du submit, activation du bouton
    « إرسال »...) n'était jamais envoyé au navigateur pour ces deux rôles.
    Le bouton restait visuellement présent mais totalement inerte (aucun
    listener attaché). Ce test vérifie, pour CHAQUE rôle ayant accès au chat,
    que le script du composer est bien présent dans le HTML rendu."""

    def _verifier_composer_js_present(self, client, user):
        _connecter(client, user)
        groupe = Groupe.objects.create(nom=f'مجموعة اختبار الإرسال {user.role}')
        if user.role == 'eleve':
            groupe.eleves.add(user.eleve)
        elif user.role == 'prof':
            groupe.prof = user.prof
            groupe.save()
        elif user.role == 'superviseur':
            groupe.prof = _creer_prof(email=f'prof_pour_{user.role}@zidni.test')
            groupe.save()
            user.superviseur.profs_assignes.add(groupe.prof)

        response = client.get(f'/chat/{groupe.id}/')
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn("getElementById('chatComposer').addEventListener('submit'", contenu)
        self.assertIn('majEtatEnvoyer', contenu)

    def test_eleve_recoit_le_js_du_composer(self):
        self._verifier_composer_js_present(Client(), _creer_eleve().user)

    def test_prof_recoit_le_js_du_composer(self):
        self._verifier_composer_js_present(Client(), _creer_prof().user)

    def test_superviseur_recoit_le_js_du_composer(self):
        self._verifier_composer_js_present(Client(), _creer_superviseur().user)

    def test_admin_recoit_le_js_du_composer(self):
        client = Client()
        admin = _creer_admin()
        _connecter(client, admin)
        groupe = Groupe.objects.create(nom='مجموعة اختبار الإرسال admin')
        response = client.get(f'/chat/{groupe.id}/')
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn("getElementById('chatComposer').addEventListener('submit'", contenu)
        self.assertIn('majEtatEnvoyer', contenu)

