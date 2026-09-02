def badges_sidebar_direction(request):
    """Compteurs affichés en badge sur la sidebar مدير/مشرف — notamment sur
    l'item de menu PARENT « إدارة المستخدمين » lui-même (visible sans déplier
    le sous-menu), en miroir du badge déjà porté par le sous-item une fois
    déplié.

    Calcul volontairement minimal (1 à 2 count() indexés) et réservé aux
    rôles admin/mshrif : zéro coût sur les pages élève/prof/مؤطر et pour les
    visiteurs. À NE PAS confondre avec le panneau 🔔 (dashboard.notifications),
    qui lui reste hors context processor pour la raison détaillée dans son
    docstring — ici il ne s'agit que d'un compteur de tâches en attente (déjà
    présent sur la sidebar مشرف avant ce chantier via nb_demandes_en_attente),
    pas d'un flux de notifications daté.

    - مشرف : `badge_gestion_utilisateurs` = candidatures profs pré-validées par
      le مدير et en attente de SA validation finale (InscriptionProf.statut=
      'validee_directeur') — exactement la même requête que le sous-item
      « طلبات الأساتذة ».
    - مدير : `badge_gestion_utilisateurs` = `badge_inscriptions_en_attente` =
      demandes d'inscription encore en attente, élèves + profs confondus
      (InscriptionEleve/InscriptionProf.statut='en_attente') — le même
      périmètre que la liste mixte « طلبات التسجيل » (admin_inscriptions).
    """
    user = getattr(request, 'user', None)
    if user is None or not user.is_authenticated or getattr(user, 'role', None) not in ('admin', 'mshrif'):
        return {}

    from inscriptions.models import InscriptionEleve, InscriptionProf

    if user.role == 'mshrif':
        return {
            'badge_gestion_utilisateurs': InscriptionProf.objects.filter(
                statut='validee_directeur'
            ).count()
        }

    total = (
        InscriptionEleve.objects.filter(statut='en_attente').count()
        + InscriptionProf.objects.filter(statut='en_attente').count()
    )
    return {
        'badge_gestion_utilisateurs': total,
        'badge_inscriptions_en_attente': total,
    }
