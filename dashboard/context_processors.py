def badges_sidebar_direction(request):
    """Compteurs affichés en badge sur la sidebar مدير/مشرف — sur l'item de
    menu PARENT « إدارة المستخدمين » (visible sans déplier) ET sur ses
    sous-items « طلبات التسجيل » / « طلبات الأساتذة ».

    Calcul volontairement minimal (2 à 3 count() indexés) et réservé aux rôles
    admin/mshrif : zéro coût sur les pages élève/prof/مؤطر et pour les
    visiteurs. À NE PAS confondre avec le panneau 🔔 (dashboard.notifications),
    qui lui reste hors context processor pour la raison détaillée dans son
    docstring — ici il ne s'agit que d'un compteur de tâches en attente (déjà
    présent sur la sidebar مشرف avant ce chantier via nb_demandes_en_attente),
    pas d'un flux de notifications daté.

    Cycle de vie des inscriptions (rappel) :
        InscriptionEleve : en_attente -> valide / rejete
        InscriptionProf  : en_attente -> validee_directeur -> valide / rejete
    donc `en_attente` (nouvelle demande, pas encore traitée) et
    `validee_directeur` (pré-validée par le مدير, attend le تصديق du مشرف) sont
    des états EXCLUSIFS — aucun double comptage.

    Compteurs exposés :
    - `nb_inscriptions_attente` (مدير + مشرف) : sous-item « طلبات التسجيل » —
      demandes neuves non traitées, élèves + profs confondus
      (InscriptionEleve/InscriptionProf.statut='en_attente'). Même périmètre
      que la liste mixte admin_inscriptions.
    - `nb_profs_a_valider` (مشرف uniquement) : sous-item « طلبات الأساتذة » —
      candidatures prof pré-validées par le مدير, en attente de la validation
      finale du مشرف (InscriptionProf.statut='validee_directeur'). Doublon
      volontaire de `nb_demandes_en_attente` (dashboard.views._contexte_base_mshrif) :
      ce dernier reste la source du badge historique de ce sous-item, on ne le
      touche pas ; `nb_profs_a_valider` ne sert qu'au total du parent ci-dessous.
    - `badge_gestion_utilisateurs` : total porté par l'item PARENT, = somme des
      badges des sous-items visibles pour ce rôle.
        * مشرف : nb_inscriptions_attente + nb_profs_a_valider
        * مدير : nb_inscriptions_attente  (pas de sous-item « طلبات الأساتذة »)
      Choix assumé côté مشرف : on y inclut les candidatures prof `en_attente`
      que seul le مدير traite — le badge reflète la VISIBILITÉ (ces demandes
      apparaissent dans la liste « طلبات التسجيل » partagée), pas uniquement
      l'action requise par ce rôle, et le total du parent doit rester égal à
      la somme des sous-badges affichés sous peine d'incohérence perçue.
    - `nb_changement_halaka_attente` (مدير + مشرف) : sous-item « طلبات تغيير
      الحلقة » (groupe « الحصص والجدولة ») — chantier du 2026-09-18, ajouté
      suite à un signalement : le panneau 🔔 (dashboard.notifications.
      notifications_direction) est un historique qui peut noyer une demande
      peu fréquente sous des évènements à haute fréquence (voir son correctif
      du même jour) — ce badge, LUI, est un compte BRUT en temps réel
      (DemandeChangementHalaka.statut='en_attente'), jamais tronqué ni
      dépendant d'une visite passée, donc jamais manqué. Volontairement PAS
      inclus dans `badge_gestion_utilisateurs` (groupe de menu différent,
      « الحصص والجدولة » et non « إدارة المستخدمين »).
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or getattr(user, 'role', None) not in ('admin', 'mshrif'):
        return {}

    from inscriptions.models import InscriptionEleve, InscriptionProf
    from courses.models import DemandeChangementHalaka

    nb_inscriptions_attente = (
        InscriptionEleve.objects.filter(statut='en_attente').count()
        + InscriptionProf.objects.filter(statut='en_attente').count()
    )
    nb_changement_halaka_attente = DemandeChangementHalaka.objects.filter(statut='en_attente').count()

    if user.role == 'mshrif':
        nb_profs_a_valider = InscriptionProf.objects.filter(statut='validee_directeur').count()
        return {
            'nb_inscriptions_attente': nb_inscriptions_attente,
            'nb_profs_a_valider': nb_profs_a_valider,
            'badge_gestion_utilisateurs': nb_inscriptions_attente + nb_profs_a_valider,
            'nb_changement_halaka_attente': nb_changement_halaka_attente,
        }

    return {
        'nb_inscriptions_attente': nb_inscriptions_attente,
        'badge_gestion_utilisateurs': nb_inscriptions_attente,
        'nb_changement_halaka_attente': nb_changement_halaka_attente,
    }
