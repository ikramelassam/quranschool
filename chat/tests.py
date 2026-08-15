import datetime

from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import User, Eleve, Prof, Superviseur
from courses.models import Groupe

from .models import Conversation, Message, LectureConversation, get_configuration_chat
from .permissions import can_access_conversation, get_conversations_accessibles
from .services import (
    conversations_avec_apercu, total_messages_non_lus, marquer_comme_lu,
    purger_messages_expires,
)

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


class IdorTests(TestCase):
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

    def test_envoi_message_refuse(self):
        response = self.client.post(f'/chat/{self.autre_groupe.id}/envoyer/', {'contenu': 'salut'})
        self.assertEqual(response.status_code, 403)

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
