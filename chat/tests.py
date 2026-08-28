import datetime

from django.test import TestCase, Client
from django.utils import timezone

from accounts.models import User, Eleve, Prof, Superviseur
from courses.models import Creneau, Groupe

from .models import Conversation, Message, LectureConversation, get_configuration_chat
from .permissions import can_access_conversation, get_conversations_accessibles
from .services import (
    annoter_separateurs_jour, backfiller_conversations_manquantes,
    conversations_avec_apercu, filtrer_conversations_par_categorie_et_recherche,
    repartition_conversations_par_categorie, total_messages_non_lus, marquer_comme_lu,
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

    def test_audio_reste_ecoutable_apres_rechargement_de_la_page(self):
        """Upload → affichage → relecture (Tâche du 2026-08-17 'messages
        vocaux') : l'audio envoyé apparaît dans un vrai lecteur <audio> lors
        d'un rechargement COMPLET de la page (pas seulement dans la réponse
        AJAX d'envoi), avec une src qui reste valide — jamais l'URL réelle du
        fichier imprimée directement, toujours via chat_fichier."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('voice.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'audio', 'fichier': fichier,
        })
        message = self.groupe.conversation.messages.first()
        url_fichier = f'/chat/{self.groupe.id}/fichier/{message.id}/'

        page = self.client.get(f'/chat/{self.groupe.id}/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, '<audio')
        self.assertContains(page, url_fichier)
        message.fichier.delete(save=False)

    def test_audio_reecoutable_plusieurs_fois(self):
        """La src d'un message audio n'est PAS une URL à usage unique — chaque
        GET de chat_fichier renvoie de nouveau le même contenu, encore et
        encore (comportement natif attendu d'un <audio controls>, proche de
        WhatsApp/Messenger : on peut réécouter un vocal indéfiniment)."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('voice.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'audio', 'fichier': fichier,
        })
        message = self.groupe.conversation.messages.first()
        url_fichier = f'/chat/{self.groupe.id}/fichier/{message.id}/'

        premiere_ecoute = self.client.get(url_fichier)
        deuxieme_ecoute = self.client.get(url_fichier)
        self.assertEqual(premiere_ecoute.status_code, 200)
        self.assertEqual(deuxieme_ecoute.status_code, 200)
        self.assertEqual(b''.join(premiere_ecoute.streaming_content), b''.join(deuxieme_ecoute.streaming_content))
        message.fichier.delete(save=False)

    def test_audio_content_type_est_audio_pas_video(self):
        """Bug remonté le 2026-08-17 ("aucun lecteur visible, juste l'icône
        🎤 statique") : ni Cloudinary ni le module `mimetypes` de Python ne
        renvoient un Content-Type 'audio/*' pour un .webm (les deux le
        détectent comme 'video/webm', vérifié en interrogeant le compte
        Cloudinary réel du projet en lecture seule) — un <audio> à qui le
        navigateur annonce 'video/*' refuse d'initialiser tout lecteur.
        chat_fichier doit donc TOUJOURS répondre avec un Content-Type
        commençant par 'audio/' pour un message audio, jamais rediriger vers
        l'URL brute du stockage (voir CONTENT_TYPES_AUDIO dans chat.services)."""
        from django.core.files.uploadedfile import SimpleUploadedFile
        fichier = SimpleUploadedFile('voice.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'audio', 'fichier': fichier,
        })
        message = self.groupe.conversation.messages.first()
        url_fichier = f'/chat/{self.groupe.id}/fichier/{message.id}/'

        reponse = self.client.get(url_fichier)
        self.assertEqual(reponse.status_code, 200)
        self.assertTrue(reponse['Content-Type'].startswith('audio/'), reponse['Content-Type'])
        self.assertEqual(b''.join(reponse.streaming_content), b'\x1a\x45\xdf\xa3contenu-audio-factice')
        message.fichier.delete(save=False)


class ReessaiAudioEnErreurJsRenduTests(TestCase):
    """Chantier du 2026-08-27 — bug remonté côté prof ("vocal inaudible
    jusqu'à reconnexion"), confirmé par le client : un simple rafraîchissement
    de la page corrige le problème (pas besoin de se déconnecter). Cause la
    plus probable : le tout premier <audio preload="metadata"> inséré par AJAX
    (envoi ou poll()) peut lancer sa requête avant que le fichier ne soit
    réellement disponible côté stockage, et un <audio> en erreur ne réessaie
    jamais tout seul — voir templates/chat/chat.html, reessayerAudioEnErreur().

    Comportement RÉEL au runtime (retry après délai) non testable sans
    exécution JS réelle (aucun framework/harness JS dans ce projet, voir
    CLAUDE.md "pas de framework JS") — ce test suit donc le même patron que
    ComposerJsRenduTests ci-dessus : vérifie que le script atteint bien le
    navigateur (régression possible si un {% block extra_js %} venait à
    manquer pour un rôle), pas son exécution."""

    def test_prof_recoit_le_js_de_reessai_audio(self):
        client = Client()
        prof = _creer_prof()
        _connecter(client, prof.user)
        groupe = Groupe.objects.create(nom='مجموعة اختبار إعادة محاولة الصوت')
        groupe.prof = prof
        groupe.save()

        response = client.get(f'/chat/{groupe.id}/')
        self.assertEqual(response.status_code, 200)
        contenu = response.content.decode('utf-8')
        self.assertIn('function reessayerAudioEnErreur', contenu)
        self.assertIn("addEventListener('error'", contenu)


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


def _image_upload(nom='photo.png', couleur=(200, 30, 30)):
    """Un vrai fichier image (PIL réel, pas juste renommé) — nécessaire car
    courses.utils.valider_photo_groupe (réutilisée telle quelle par
    chat.views.chat_modifier_photo_groupe) ouvre/vérifie le fichier avec
    Pillow. Même patron que courses.tests._image_upload."""
    import io
    from django.core.files.uploadedfile import SimpleUploadedFile
    from PIL import Image

    buffer = io.BytesIO()
    Image.new('RGB', (10, 10), couleur).save(buffer, format='PNG')
    buffer.seek(0)
    return SimpleUploadedFile(nom, buffer.read(), content_type='image/png')


class PhotoGroupeDepuisChatTests(TestCase):
    """chat_modifier_photo_groupe (Tâche du 2026-08-17 "changer la photo
    depuis le chat, façon WhatsApp") — écrit sur le MÊME Groupe.photo que le
    formulaire de gestion de groupe existant dans courses/ (non testé ici,
    inchangé), donc rien à vérifier de ce côté-là hormis que la valeur
    stockée est bien identique quel que soit le point d'entrée."""

    def setUp(self):
        self.client = Client()
        self.groupe = Groupe.objects.create(nom='مجموعة صورة الدردشة')

    def test_admin_peut_changer_la_photo(self):
        admin = _creer_admin()
        _connecter(self.client, admin)
        response = self.client.post(f'/chat/{self.groupe.id}/photo/', {'photo': _image_upload()})
        self.assertEqual(response.status_code, 200)
        self.assertIn('avatar_html', response.json())
        self.assertIn('<img', response.json()['avatar_html'])
        self.groupe.refresh_from_db()
        self.assertTrue(self.groupe.photo)
        self.groupe.photo.delete(save=False)

    def test_prof_du_groupe_refuse(self):
        """Décision explicite (2026-08-17) : réservé au مدير UNIQUEMENT — même
        le prof responsable de CE groupe précis, qui a pourtant accès au
        chat, ne peut pas changer sa photo."""
        prof = _creer_prof()
        self.groupe.prof = prof
        self.groupe.save()
        _connecter(self.client, prof.user)
        response = self.client.post(f'/chat/{self.groupe.id}/photo/', {'photo': _image_upload()})
        self.assertEqual(response.status_code, 403)
        self.groupe.refresh_from_db()
        self.assertFalse(self.groupe.photo)

    def test_superviseur_du_prof_refuse(self):
        """Même s'il supervise le prof de ce groupe — réservé au مدير."""
        prof = _creer_prof()
        superviseur = _creer_superviseur()
        superviseur.profs_assignes.add(prof)
        self.groupe.prof = prof
        self.groupe.save()
        _connecter(self.client, superviseur.user)
        response = self.client.post(f'/chat/{self.groupe.id}/photo/', {'photo': _image_upload()})
        self.assertEqual(response.status_code, 403)
        self.groupe.refresh_from_db()
        self.assertFalse(self.groupe.photo)

    def test_eleve_du_groupe_refuse(self):
        """A bien accès au chat (membre du groupe) mais ne peut pas changer
        la photo — réservé au مدير uniquement."""
        eleve = _creer_eleve()
        self.groupe.eleves.add(eleve)
        _connecter(self.client, eleve.user)
        response = self.client.post(f'/chat/{self.groupe.id}/photo/', {'photo': _image_upload()})
        self.assertEqual(response.status_code, 403)
        self.groupe.refresh_from_db()
        self.assertFalse(self.groupe.photo)

    def test_fichier_invalide_refuse(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        admin = _creer_admin()
        _connecter(self.client, admin)
        fichier = SimpleUploadedFile('malware.exe', b'MZ', content_type='application/octet-stream')
        response = self.client.post(f'/chat/{self.groupe.id}/photo/', {'photo': fichier})
        self.assertEqual(response.status_code, 400)
        self.groupe.refresh_from_db()
        self.assertFalse(self.groupe.photo)

    def test_utilisateur_hors_groupe_refuse_avant_meme_verification_photo(self):
        """Un utilisateur sans AUCUN accès à ce chat (403 de
        _conversation_ou_403) ne doit jamais atteindre la vérification de
        droit sur la photo — même comportement que toutes les autres vues
        chat pour un groupe étranger."""
        autre_eleve = _creer_eleve(email='eleve_etranger_photo@zidni.test')
        _connecter(self.client, autre_eleve.user)
        response = self.client.post(f'/chat/{self.groupe.id}/photo/', {'photo': _image_upload()})
        self.assertEqual(response.status_code, 403)


class SuppressionMessageTests(TestCase):
    """chat_supprimer_message (Tâche du 2026-08-17 "supprimer un message,
    façon WhatsApp") — suppression douce : la ligne reste en base, son
    contenu est vidé et remplacé par un placeholder côté template."""

    def setUp(self):
        self.eleve = _creer_eleve()
        self.autre_eleve = _creer_eleve(email='autre_eleve_suppr@zidni.test')
        self.groupe = Groupe.objects.create(nom='مجموعة اختبار حذف الرسائل')
        self.groupe.eleves.add(self.eleve, self.autre_eleve)
        self.client = Client()

    def _envoyer_message_texte(self, user, contenu='رسالة للاختبار'):
        _connecter(self.client, user)
        self.client.post(f'/chat/{self.groupe.id}/envoyer/', {'contenu': contenu, 'type_message': 'texte'})
        return self.groupe.conversation.messages.order_by('-id').first()

    def test_auteur_peut_supprimer_son_propre_message(self):
        message = self._envoyer_message_texte(self.eleve.user)
        _connecter(self.client, self.eleve.user)
        response = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.est_supprime)
        self.assertEqual(message.contenu, '')
        self.assertIn('تم حذف هذه الرسالة', response.json()['html'])

    def test_autre_participant_ne_peut_pas_supprimer(self):
        """Protection STRICTE côté serveur : un autre membre de la MÊME
        conversation (donc avec accès chat légitime) ne peut pas supprimer
        le message de quelqu'un d'autre, même en connaissant son id."""
        message = self._envoyer_message_texte(self.eleve.user, contenu='ne pas supprimer')
        _connecter(self.client, self.autre_eleve.user)
        response = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertFalse(message.est_supprime)
        self.assertEqual(message.contenu, 'ne pas supprimer')

    def test_admin_ne_peut_pas_supprimer_le_message_dun_autre(self):
        """Même le مدير (qui voit TOUTES les conversations) ne peut supprimer
        que ses PROPRES messages — la règle est "auteur == utilisateur",
        jamais un rôle particulier qui contournerait la vérification."""
        message = self._envoyer_message_texte(self.eleve.user, contenu='message élève')
        admin = _creer_admin()
        _connecter(self.client, admin)
        response = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertFalse(message.est_supprime)

    def test_suppression_dun_vocal_supprime_le_fichier_stocke(self):
        from django.core.files.uploadedfile import SimpleUploadedFile
        _connecter(self.client, self.eleve.user)
        fichier = SimpleUploadedFile('voice.webm', b'\x1a\x45\xdf\xa3contenu-audio-factice', content_type='audio/webm')
        self.client.post(f'/chat/{self.groupe.id}/envoyer/', {
            'contenu': '', 'type_message': 'audio', 'fichier': fichier,
        })
        message = self.groupe.conversation.messages.order_by('-id').first()
        self.assertTrue(message.fichier)

        response = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        self.assertEqual(response.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.est_supprime)
        self.assertFalse(message.fichier)

    def test_suppression_idempotente(self):
        message = self._envoyer_message_texte(self.eleve.user)
        _connecter(self.client, self.eleve.user)
        premiere = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        deuxieme = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        self.assertEqual(premiere.status_code, 200)
        self.assertEqual(deuxieme.status_code, 200)
        message.refresh_from_db()
        self.assertTrue(message.est_supprime)

    def test_utilisateur_sans_acces_a_la_conversation_refuse(self):
        """403 dès _conversation_ou_403, avant même de comparer l'auteur —
        un étranger à la conversation ne doit rien pouvoir déduire."""
        message = self._envoyer_message_texte(self.eleve.user)
        etranger = _creer_eleve(email='etranger_suppr@zidni.test')
        _connecter(self.client, etranger.user)
        response = self.client.post(f'/chat/{self.groupe.id}/messages/{message.id}/supprimer/')
        self.assertEqual(response.status_code, 403)
        message.refresh_from_db()
        self.assertFalse(message.est_supprime)


# ============================================================================
# Partie B (chantier du 2026-08-24) — tranche d'âge précise affichée à côté
# du nom de chaque élève dans le panneau "membres" (voir chat.permissions.
# participants_conversation.__doc__).
# ============================================================================

class ParticipantsTrancheAgeTests(TestCase):
    def setUp(self):
        from .permissions import participants_conversation

        self.participants_conversation = participants_conversation
        self.groupe = Groupe.objects.create(nom='مجموعة اختبار الفئة العمرية')

    def _ajouter_eleve(self, age, email):
        naissance = timezone.localdate().replace(year=timezone.localdate().year - age, month=1, day=1)
        u = User.objects.create_user(
            username=email, email=email, password=MOT_DE_PASSE,
            first_name='طالب', last_name='تجريبي', role='eleve',
            doit_changer_mot_de_passe=False, date_naissance=naissance,
        )
        eleve = Eleve.objects.create(user=u, sexe='homme', statut='actif')
        self.groupe.eleves.add(eleve)
        return eleve

    def test_eleve_dans_une_tranche_porte_le_bon_label(self):
        Conversation.objects.get_or_create(groupe=self.groupe)
        self._ajouter_eleve(9, 'eleve_baraim@zidni.test')
        conversation = Conversation.objects.get(groupe=self.groupe)
        participants = self.participants_conversation(conversation)
        eleve_entry = next(p for p in participants if p['role_code'] == 'eleve')
        self.assertEqual(eleve_entry['tranche_age_label'], 'البراعم')

    def test_eleve_adulte_naffiche_aucune_tranche(self):
        Conversation.objects.get_or_create(groupe=self.groupe)
        self._ajouter_eleve(25, 'eleve_adulte_chat@zidni.test')
        conversation = Conversation.objects.get(groupe=self.groupe)
        participants = self.participants_conversation(conversation)
        eleve_entry = next(p for p in participants if p['role_code'] == 'eleve')
        self.assertEqual(eleve_entry['tranche_age_label'], '')


class OngletsChatTranchesAgeTests(TestCase):
    """Correction du 2026-08-24, demande explicite d'Ikram : les onglets
    "المجموعات" du Chat divisent désormais الأطفال en التلقين/البراعم/اليافعون
    (basé sur Groupe.tranches_age_visees, donc le créneau — pas les élèves),
    tout en gardant النساء/الرجال inchangés. Voir chat.services.ONGLETS_CHAT/
    _conversation_dans_onglet_chat."""

    def _groupe_mineur(self, nom, age_min, age_max):
        creneau = Creneau.objects.create(sexe_cible='mixte', age_min=age_min, age_max=age_max)
        return Groupe.objects.create(
            nom=nom, creneau=creneau, categorie='mineurs',
            type_capacite='groupe', statut='actif', capacite_max=10,
        )

    def _groupe_adulte(self, nom, categorie):
        creneau = Creneau.objects.create(sexe_cible='mixte', age_min=18, age_max=999)
        return Groupe.objects.create(
            nom=nom, creneau=creneau, categorie=categorie,
            type_capacite='groupe', statut='actif', capacite_max=10,
        )

    def test_onglets_chat_couvrent_2_adultes_et_3_tranches_enfants(self):
        from .services import ONGLETS_CHAT
        codes = [onglet['code'] for onglet in ONGLETS_CHAT]
        self.assertEqual(codes, ['femmes_adultes', 'hommes_adultes', 'talqin', 'baraim', 'yafiun'])

    def test_repartition_compte_un_groupe_adulte_sous_son_onglet(self):
        groupe = self._groupe_adulte('حلقة نساء اختبار', 'femmes_adultes')
        conversation = Conversation.objects.get(groupe=groupe)
        repartition = repartition_conversations_par_categorie([conversation])
        compte = {r['code']: r['count'] for r in repartition}
        self.assertEqual(compte['femmes_adultes'], 1)
        self.assertEqual(compte['hommes_adultes'], 0)
        self.assertEqual(compte[''], 1)

    def test_repartition_compte_une_halaka_pile_dans_une_tranche(self):
        groupe = self._groupe_mineur('حلقة براعم اختبار', age_min=8, age_max=13)
        conversation = Conversation.objects.get(groupe=groupe)
        repartition = repartition_conversations_par_categorie([conversation])
        compte = {r['code']: r['count'] for r in repartition}
        self.assertEqual(compte['baraim'], 1)
        self.assertEqual(compte['talqin'], 0)
        self.assertEqual(compte['yafiun'], 0)

    def test_halaka_large_compte_dans_les_3_tranches_a_la_fois(self):
        groupe = self._groupe_mineur('حلقة كل الأطفال اختبار', age_min=5, age_max=18)
        conversation = Conversation.objects.get(groupe=groupe)
        repartition = repartition_conversations_par_categorie([conversation])
        compte = {r['code']: r['count'] for r in repartition}
        self.assertEqual(compte['talqin'], 1)
        self.assertEqual(compte['baraim'], 1)
        self.assertEqual(compte['yafiun'], 1)
        self.assertEqual(compte[''], 1)

    def test_groupe_mineur_sans_creneau_najoute_a_aucune_tranche(self):
        groupe = Groupe.objects.create(
            nom='حلقة أطفال بدون خانة زمنية', creneau=None, categorie='mineurs',
            type_capacite='groupe', statut='actif', capacite_max=10,
        )
        conversation = Conversation.objects.get(groupe=groupe)
        repartition = repartition_conversations_par_categorie([conversation])
        compte = {r['code']: r['count'] for r in repartition}
        self.assertEqual(compte['talqin'], 0)
        self.assertEqual(compte['baraim'], 0)
        self.assertEqual(compte['yafiun'], 0)
        self.assertEqual(compte[''], 1)  # reste visible dans "الكل"

    def test_filtrer_par_tranche_ne_garde_que_les_halakat_concernees(self):
        groupe_baraim = self._groupe_mineur('حلقة براعم فقط', age_min=8, age_max=13)
        groupe_talqin = self._groupe_mineur('حلقة تلقين فقط', age_min=5, age_max=7)
        conv_baraim = Conversation.objects.get(groupe=groupe_baraim)
        conv_talqin = Conversation.objects.get(groupe=groupe_talqin)
        resultat = filtrer_conversations_par_categorie_et_recherche(
            [conv_baraim, conv_talqin], categorie='baraim'
        )
        self.assertEqual(resultat, [conv_baraim])

    def test_filtrer_par_tranche_garde_une_halaka_large_meme_filtree_ailleurs(self):
        groupe_large = self._groupe_mineur('حلقة واسعة', age_min=5, age_max=18)
        conversation = Conversation.objects.get(groupe=groupe_large)
        for code in ('talqin', 'baraim', 'yafiun'):
            with self.subTest(code=code):
                resultat = filtrer_conversations_par_categorie_et_recherche([conversation], categorie=code)
                self.assertEqual(resultat, [conversation])


# ============================================================================
# Chantier "fix accès public aux fichiers du chat (Cloudinary 401)" du 2026-08-27.
# ============================================================================
class PieceJointeAccesPublicCloudinaryTests(TestCase):
    """chat.storage.ChatAttachmentStorage doit forcer access_mode='public' à
    CHAQUE upload — vérifié en conditions réelles (vrai upload Cloudinary),
    même patron que les autres tests fichiers de ce module (aucun mock)."""

    def test_storage_selectionne_est_bien_le_storage_dedie_chat(self):
        """Vérification rapide, sans réseau : tant que Cloudinary est
        configuré (comme dans cet environnement, voir CLOUDINARY_CLOUD_NAME),
        le champ Message.fichier doit utiliser ChatAttachmentStorage — jamais
        le storage global nu (RawMediaCloudinaryStorage sans le fix)."""
        from django.conf import settings

        from .storage import ChatAttachmentStorage

        storage_utilise = Message._meta.get_field('fichier').storage
        if getattr(settings, 'CLOUDINARY_CLOUD_NAME', ''):
            self.assertIsInstance(storage_utilise, ChatAttachmentStorage)
        else:
            self.skipTest("CLOUDINARY_CLOUD_NAME non configuré dans cet environnement.")

    def test_nouvel_upload_est_accessible_sans_authentification(self):
        """Bout en bout : envoie un vrai fichier via le champ Message.fichier
        (donc via ChatAttachmentStorage._upload, avec access_mode='public'
        forcé), puis requête RÉELLEMENT l'URL retournée (sans aucune session/
        signature) pour confirmer un 200 — pas un mock, la preuve observable
        que le fichier est bien accessible publiquement.

        IMPORTANT — limite CONNUE et documentée (voir le rapport du chantier
        "fix accès public aux fichiers du chat") : ce test utilise .docx,
        JAMAIS .pdf/.zip. Cloudinary applique aux fichiers .pdf/.zip une
        restriction de sécurité DISTINCTE de access_mode ("Allow delivery of
        PDF and ZIP files"), réglable UNIQUEMENT depuis la Console Cloudinary
        (aucun paramètre d'upload ni d'appel Admin API ne la contourne —
        vérifié empiriquement : access_mode='public' et access_control=
        [{'access_type': 'anonymous'}] passés à l'upload n'ont AUCUN effet
        sur un .pdf/.zip). Ce fix corrige donc bien l'accès pour tout type de
        pièce jointe SAUF .pdf/.zip, qui restent 401 tant que ce réglage
        Console n'est pas activé par un administrateur du compte Cloudinary."""
        from django.conf import settings

        if not getattr(settings, 'CLOUDINARY_CLOUD_NAME', ''):
            self.skipTest("CLOUDINARY_CLOUD_NAME non configuré dans cet environnement.")

        import requests
        from django.core.files.uploadedfile import SimpleUploadedFile

        groupe = Groupe.objects.create(nom='مجموعة اختبار الوصول العام')
        conversation = Conversation.objects.get(groupe=groupe)
        fichier = SimpleUploadedFile(
            'audit_acces_public.docx', b'contenu factice non-pdf/zip',
            content_type='application/vnd.openxmlformats-officedocument.wordprocessingml.document',
        )
        message = Message.objects.create(
            conversation=conversation, type_message='fichier', contenu='',
            fichier=fichier, nom_fichier_original='audit_acces_public.docx',
        )
        try:
            reponse = requests.get(message.fichier.url, timeout=15)
            self.assertEqual(reponse.status_code, 200)
        finally:
            message.fichier.delete(save=False)

