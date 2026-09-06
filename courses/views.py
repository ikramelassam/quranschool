from django.core.exceptions import ValidationError
from django.core.validators import URLValidator
from django.db import transaction
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from django.utils import timezone
from django.utils.translation import gettext as gettext_
from django.views.decorators.http import require_POST
from accounts.decorators import role_required
from core.utils import paginer
from .models import Groupe, Creneau, HistoriqueGroupeEleve, LienMeet
from .utils import (
    regenerer_pour_nouveau_creneau, raison_incompatibilite_groupe, avertissements_groupe,
    avertissements_prof_creneau, groupe_peut_etre_supprime,
    description_conflit_lien_meet, matrice_disponibilite_liens_meet,
    valider_photo_groupe, remplacer_slots_creneau, TRANCHES_AGE_PRECISES,
)
from accounts.models import Prof, Eleve


def _base_template_admin_ou_mshrif(request):
    """Équivalent local de dashboard.views._base_template_admin_ou_mshrif — pages
    admin de gestion des groupes/créneaux réutilisées en lecture seule par المشرف."""
    return 'dashboard/base_mshrif.html' if request.user.role == 'mshrif' else 'dashboard/base_admin.html'


def _contexte_base_mshrif(request):
    """Équivalent local de dashboard.views._contexte_base_mshrif (badge sidebar)."""
    if request.user.role != 'mshrif':
        return {}
    from inscriptions.models import InscriptionProf
    return {'nb_demandes_en_attente': InscriptionProf.objects.filter(statut='validee_directeur').count()}


def _resoudre_lien_meet_pour_formulaire(request):
    """Détermine le LienMeet retenu par un formulaire de groupe à partir du POST.

    Deux origines possibles, dans cet ordre de priorité :
      1. `lien_meet_nouveau` : une URL collée à la main par le مدير (champ
         texte ajouté le 2026-08-31) — absente du pool. On l'y ajoute
         (get_or_create par url) pour qu'elle emprunte EXACTEMENT le même
         chemin de validation que n'importe quel lien du pool (verrou
         select_for_update + description_conflit_lien_meet dans les vues
         appelantes) et qu'elle devienne réutilisable ensuite ;
      2. `lien_meet` : l'id d'un LienMeet déjà dans le pool (le <select>).

    Retourne (id_str_ou_None, message_erreur_ou_None). L'id renvoyé pointe
    toujours vers un LienMeet réel : aucune autre vue n'a besoin de changer.
    NB : si la sauvegarde échoue ensuite (conflit d'horaire…), le lien créé
    reste dans le pool, simplement "غير مستخدم حالياً" — c'est un pool
    réutilisable, pas une réservation."""
    url_collee = (request.POST.get('lien_meet_nouveau') or '').strip()
    if url_collee:
        try:
            URLValidator()(url_collee)
        except ValidationError:
            return None, gettext_('الرابط الذي ألصقته غير صالح. تأكّد من نسخه كاملاً (يبدأ بـ https://).')
        lien, _cree = LienMeet.objects.get_or_create(url=url_collee)
        return str(lien.id), None
    return (request.POST.get('lien_meet') or None), None


@role_required('admin', 'mshrif')
def groupes_list(request):
    from django.db.models import Q, Count

    statut = request.GET.get('statut', '')
    prof_id = request.GET.get('prof', '')
    q = request.GET.get('q', '').strip()
    # Navigation par pastilles المجموعات/الفردية/الجماعية puis, si الجماعية،
    # النساء/الرجال/الأطفال (Chantier du 2026-08-18) — filtre directement
    # Groupe.categorie, PLUS Groupe.categorie_collectif (property dérivée du
    # créneau — laissée intacte dans le modèle, mais plus utilisée nulle part
    # dans cette page : décision explicite du client, l'ancienne dérivation
    # âge/sexe-du-créneau était jugée peu fiable). Le formulaire détaillé
    # avait un 2e filtre "فئة المجموعة" (paramètre `cat`) sur ce même champ
    # Groupe.categorie — doublon pur avec les pastilles ci-dessous depuis ce
    # chantier, retiré (décision explicite du client, pas juste un oubli si
    # vous le voyez manquer en relisant l'historique). type_filtre et
    # categorie_filtre sont appliqués indépendamment l'un de l'autre plus
    # bas : ils se combinent toujours en ET, y compris ?type=individuel avec
    # ?categorie=... même si l'UI n'affiche la sous-navigation catégorie que
    # sous المجموعات الجماعية.
    type_filtre = request.GET.get('type', '')
    categorie_filtre = request.GET.get('categorie', '')
    # 3e niveau, affiché seulement sous الأطفال (categorie='mineurs') — les 3
    # tranches d'âge précises التلقين/البراعم/اليافعون (courses.utils.
    # TRANCHES_AGE_PRECISES), calculées à partir de la halaka elle-même
    # (Creneau.age_min/age_max de la حلقة assignée au groupe), JAMAIS à partir
    # de l'âge individuel de chaque élève — même source de vérité que
    # Groupe.tranches_age_visees déjà utilisée pour le badge de la carte
    # ci-dessous, décision explicite d'Ikram (ne pas recalculer un 2e système
    # basé sur les élèves réellement inscrits). Une tranche apparaît dès que
    # son intervalle chevauche ne serait-ce que partiellement celui de la
    # حلقة, exactement la même règle de recouvrement.
    tranche_filtre = request.GET.get('tranche', '')

    # annotate(Count('eleves')) (Correctif perf du 2026-08-30) : le template
    # affichait groupe.eleves.count dans la boucle -> 1 requête COUNT par
    # groupe affiché (jusqu'à 10, la page est paginée) au lieu d'une seule
    # requête pour toute la page. distinct=True : Groupe.eleves est un M2M,
    # nécessaire pour un compte exact même si un futur filtre rejoint une
    # autre relation multi-valuée sur ce même queryset.
    groupes = Groupe.objects.select_related('prof__user', 'creneau').annotate(
        nb_eleves=Count('eleves', distinct=True)
    ).order_by('id')
    if statut:
        groupes = groupes.filter(statut=statut)
    else:
        # Tâche du 2026-08-08 : les groupes archivés restent hors de la liste
        # par défaut (statut réversible, pas une suppression) sauf recherche
        # explicite via le menu "الحالة" — même principe qu'admin_eleves/
        # admin_profs (Eleve.actifs/Prof.actifs).
        groupes = groupes.exclude(statut='archive')
    if prof_id:
        groupes = groupes.filter(prof_id=prof_id)
    if type_filtre in ('individuel', 'groupe'):
        groupes = groupes.filter(type_capacite=type_filtre)
    if categorie_filtre:
        groupes = groupes.filter(categorie=categorie_filtre)
    tranche_info = next((t for t in TRANCHES_AGE_PRECISES if t[0] == tranche_filtre), None)
    if categorie_filtre == 'mineurs' and tranche_info:
        _, _, tranche_age_min, tranche_age_max = tranche_info
        groupes = groupes.filter(
            creneau__age_max__gte=tranche_age_min, creneau__age_min__lte=tranche_age_max,
        )
    if q:
        # Même logique que dashboard.recherche._filtrer (Chantier recherche
        # globale du 2026-08-14) : icontains (sous-chaîne, cas courant) OU
        # trigram_similar (fautes de frappe, utilise l'index GIN déjà posé
        # sur Groupe.nom — migration courses.0027) — pas une 3e logique de
        # recherche recodée à part, le lien "عرض كل النتائج" de la recherche
        # globale pointe justement ici avec ce même paramètre ?q=.
        groupes = groupes.filter(Q(nom__icontains=q) | Q(nom__trigram_similar=q))

    # Icône 💬 chat par groupe (Chantier icône-chat du 2026-08-18) — UNE seule
    # requête pour toute la page paginée plutôt qu'un can_access_conversation
    # par groupe affiché (voir chat.permissions.groupes_chat_accessibles_ids).
    # mshrif n'a jamais accès au chat (règle existante, non modifiée) : cet
    # ensemble est alors simplement vide, l'icône ne s'affiche nulle part sur
    # cette même page pour lui, sans code séparé à écrire pour ce cas.
    from chat.permissions import groupes_chat_accessibles_ids

    context = {
        'groupes': paginer(request, groupes, 10),
        'profs': Prof.actifs.select_related('user').order_by('user__first_name'),
        'chat_groupe_ids': groupes_chat_accessibles_ids(request.user),
        'tranches_age': TRANCHES_AGE_PRECISES,
        'filtres': {
            'statut': statut,
            'prof': prof_id,
            'type': type_filtre,
            'categorie': categorie_filtre,
            'tranche': tranche_filtre,
            'q': q,
        },
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'courses/admin_groupes.html', context)


@role_required('admin')
# @transaction.atomic (audit du 2026-09-05) : le Creneau privé est créé
# (Creneau.objects.create) plusieurs lignes avant le Groupe.objects.create()
# final qui l'adopte — sans transaction englobante, un échec tardif (ex:
# capacite_max invalide) laissait le Creneau + ses CreneauSlot orphelins en
# base, jamais nettoyés. Toute la vue commite ou annule d'un bloc.
@transaction.atomic
def groupe_ajouter(request):
    # select_related('user') : le template affiche prof.user.get_full_name
    # pour chaque prof du <select> — sans lui, 1 requête par prof actif de
    # toute l'école à chaque ouverture de cette page (Correctif du 2026-08-30).
    profs = Prof.actifs.select_related('user').all()
    liens_meet = LienMeet.objects.filter(est_actif=True)

    if request.method == 'POST':
        # Photo (Tâche du 2026-08-17) — validée AVANT toute autre étape, pour
        # ne jamais créer/modifier un groupe avec un fichier refusé. Le
        # fichier validé reste utilisable plus loin (le curseur est remis à
        # zéro par valider_photo_groupe).
        photo = request.FILES.get('photo')
        if photo:
            erreur_photo = valider_photo_groupe(photo)
            if erreur_photo:
                messages.error(request, erreur_photo)
                return render(request, 'courses/admin_groupe_ajouter.html', {
                    'profs': profs,
                    'liens_meet': liens_meet,
                    'categorie_choices': Groupe.CATEGORIE_CHOICES,
                    'valeurs_creneau': _valeurs_creneau_depuis_post(request),
                    'slots_saisis': _slots_depuis_post(request),
                })

        slots = _slots_depuis_post(request)
        if not slots:
            messages.error(request, gettext_('يجب إضافة حصة واحدة على الأقل.'))
            return render(request, 'courses/admin_groupe_ajouter.html', {
                'profs': profs,
                'liens_meet': liens_meet,
                'categorie_choices': Groupe.CATEGORIE_CHOICES,
                'valeurs_creneau': _valeurs_creneau_depuis_post(request),
                'slots_saisis': slots,
            })

        age_min, age_max, erreur_age = _ages_creneau_depuis_post(request)
        if erreur_age:
            messages.error(request, erreur_age)
            return render(request, 'courses/admin_groupe_ajouter.html', {
                'profs': profs,
                'liens_meet': liens_meet,
                'categorie_choices': Groupe.CATEGORIE_CHOICES,
                'valeurs_creneau': _valeurs_creneau_depuis_post(request),
                'slots_saisis': slots,
            })

        # Horaire (chantier « fusion horaire/groupe » du 2026-09-04, décision
        # explicite du client) : plus d'écran « الحلقات » séparé — un Creneau
        # PRIVÉ à ce groupe est créé directement depuis les champs du
        # formulaire, jamais partagé avec un autre groupe (contrairement à
        # avant ce chantier, où plusieurs Groupe pouvaient pointer vers le
        # même Creneau). Créé tout de suite, pas seulement à la sauvegarde
        # finale : avertissements_prof_creneau et le contrôle de conflit de
        # lien Meet lisent creneau.slots.all(), qui a besoin d'un Creneau
        # PERSISTÉ — supprimé plus bas (_redisplay) si la soumission ne va
        # pas à son terme (avertissement non confirmé, conflit de lien),
        # pour ne jamais laisser de ligne orpheline.
        creneau_obj = Creneau.objects.create(
            sexe_cible=request.POST.get('sexe_cible'),
            type_seance=request.POST.get('type_seance'),
            riwaya=request.POST.get('riwaya'),
            age_min=age_min,
            age_max=age_max,
        )
        remplacer_slots_creneau(creneau_obj, slots)

        def _redisplay(**contexte_supplementaire):
            creneau_obj.delete()
            contexte = {
                'profs': profs,
                'liens_meet': liens_meet,
                'categorie_choices': Groupe.CATEGORIE_CHOICES,
                'valeurs_creneau': _valeurs_creneau_depuis_post(request),
                'slots_saisis': slots,
            }
            contexte.update(contexte_supplementaire)
            return render(request, 'courses/admin_groupe_ajouter.html', contexte)

        # Lien Meet retenu : soit un lien du pool (le <select>), soit une URL
        # collée à la main (champ "lien_meet_nouveau") qui rejoint alors le
        # pool — voir _resoudre_lien_meet_pour_formulaire. Résolu ICI, avant
        # l'éventuel ré-affichage pour avertissement prof, pour ne pas perdre
        # l'URL collée entre deux soumissions.
        lien_meet_id, erreur_lien_meet = _resoudre_lien_meet_pour_formulaire(request)
        if erreur_lien_meet:
            messages.error(request, erreur_lien_meet)
            return _redisplay()

        prof_id = request.POST.get('prof') or None
        confirme = request.POST.get('confirme') == '1'
        avertissements_prof = []
        if prof_id:
            # Revalidé côté serveur même si le <select> exclut déjà les profs
            # archivés (Prof.actifs) — se protège contre un POST direct avec un
            # id manipulé (chantier d'archivage du 2026-08-03).
            prof_obj = get_object_or_404(Prof, id=prof_id)
            if prof_obj.statut == 'archive':
                messages.error(request, gettext_('تعذّر إسناد %(v0)s: هذا الأستاذ مؤرشف.') % {'v0': prof_obj.user.get_full_name()})
                return _redisplay()
            # Tâche du 2026-08-09 : l'incompatibilité d'horaire n'est plus
            # bloquante — elle est désormais remontée par
            # avertissements_prof_creneau, au même titre que l'âge/le sexe
            # (décision explicite du client). Avant cette date, un bloc
            # séparé ici bloquait sans recours (creneaux_manquants_pour_prof
            # + _message_incompatibilite, les deux retirés — le premier reste
            # utilisé, mais depuis courses.utils.avertissements_prof_creneau).
            avertissements_prof = avertissements_prof_creneau(prof_obj, creneau_obj)
            if avertissements_prof and not confirme:
                groupe_previsualise = Groupe(
                    nom=request.POST.get('nom'),
                    nom_fr=request.POST.get('nom_fr', ''),
                    nom_en=request.POST.get('nom_en', ''),
                    prof_id=prof_id,
                    description=request.POST.get('description', ''),
                    description_fr=request.POST.get('description_fr', ''),
                    description_en=request.POST.get('description_en', ''),
                    capacite_max=_capacite_max_depuis_post(request),
                    type_capacite=request.POST.get('type_capacite', 'groupe'),
                    lien_meet_id=lien_meet_id,
                    categorie=request.POST.get('categorie', ''),
                )
                return _redisplay(groupe=groupe_previsualise, avertissements_prof=avertissements_prof)

        # Lien Meet (Tâche du 2026-08-17) : UN groupe = AU PLUS UN lien du pool.
        # Depuis le 2026-08-31 une URL collée à la main est acceptée mais rejoint
        # le pool (lien_meet_id résolu plus haut) — elle passe donc par la même
        # vérification. Revérifié ICI côté serveur (jamais une confiance dans le
        # JS du formulaire — section 12 du cahier des charges), sous verrou sur
        # le LienMeet choisi le temps de la vérification+affectation pour fermer
        # la fenêtre de course entre deux créations concurrentes visant le même
        # lien (aucune architecture de concurrence plus lourde n'est nécessaire).
        lien_meet_obj = None
        if lien_meet_id:
            with transaction.atomic():
                lien_meet_obj = get_object_or_404(LienMeet.objects.select_for_update(), id=lien_meet_id)
                if not lien_meet_obj.est_actif:
                    messages.error(request, gettext_('هذا الرابط معطّل حالياً — اختر رابطاً آخر.'))
                    return _redisplay()
                conflit = description_conflit_lien_meet(lien_meet_obj, creneau_obj)
                if conflit:
                    messages.error(request, gettext_('تعذّر استخدام "%(v0)s" لهذا التوقيت: %(v1)s') % {'v0': lien_meet_obj, 'v1': conflit})
                    return _redisplay()

        groupe = Groupe.objects.create(
            nom=request.POST.get('nom'),
            nom_fr=request.POST.get('nom_fr', ''),
            nom_en=request.POST.get('nom_en', ''),
            prof_id=prof_id,
            creneau=creneau_obj,
            description=request.POST.get('description', ''),
            description_fr=request.POST.get('description_fr', ''),
            description_en=request.POST.get('description_en', ''),
            capacite_max=_capacite_max_depuis_post(request),
            type_capacite=request.POST.get('type_capacite', 'groupe'),
            lien_meet=lien_meet_obj,
            lien_reunion=lien_meet_obj.url if lien_meet_obj else '',
            categorie=request.POST.get('categorie', ''),
            photo=photo or None,
        )
        regenerer_pour_nouveau_creneau(groupe)
        for avertissement in avertissements_prof:
            messages.warning(request, avertissement)
        messages.success(request, gettext_('تمت إضافة المجموعة وتوليد حصصها تلقائياً بنجاح.'))
        return redirect('admin_groupes')

    return render(request, 'courses/admin_groupe_ajouter.html', {
        'profs': profs,
        'liens_meet': liens_meet,
        'categorie_choices': Groupe.CATEGORIE_CHOICES,
        'valeurs_creneau': _valeurs_creneau_depuis_post(request),
        'slots_saisis': [],
    })


def _ajouter_eleve_au_groupe(eleve, groupe):
    """Ajout effectif (M2M + ouverture d'une ligne d'historique) — utilisé par
    l'ajout direct, la confirmation après avertissement, et le transfert."""
    groupe.eleves.add(eleve)
    HistoriqueGroupeEleve.objects.create(eleve=eleve, groupe=groupe)


def _retirer_eleve_du_groupe(eleve, groupe):
    """Retrait effectif (M2M + fermeture de la ligne d'historique ouverte).
    Ne touche jamais aux Presence/Evaluation passées: elles sont liées à la
    Seance, pas à l'appartenance M2M au groupe (Tâche 18 du 2026-07-26)."""
    groupe.eleves.remove(eleve)
    HistoriqueGroupeEleve.objects.filter(eleve=eleve, groupe=groupe, date_fin__isnull=True).update(date_fin=timezone.now())


@role_required('admin', 'mshrif')
def groupe_detail(request, groupe_id):
    from chat.permissions import peut_voir_chat_groupe

    # select_related('prof__user', 'creneau') (Correctif perf du 2026-08-30) :
    # le template affiche groupe.prof.user.get_full_name/.email/.telephone et
    # groupe.creneau.get_riwaya_display — sans ça, 2-3 requêtes de plus à
    # chaque ouverture de cette page (la plus visitée par l'admin).
    groupe = get_object_or_404(
        Groupe.objects.select_related('prof__user', 'creneau'), id=groupe_id
    )
    # select_related('user') (même correctif) : le template affiche
    # eleve.user.get_full_name pour chaque élève actif non membre — sans ça,
    # 1 requête par élève actif de toute l'école (voir eleves_du_groupe
    # ci-dessous pour le même correctif côté élèves déjà membres).
    eleves_disponibles = Eleve.actifs.exclude(groupes=groupe).select_related('user')
    # eleves_du_groupe/nb_eleves calculés une seule fois ici (Correctif perf
    # du 2026-08-30) : le template appelait groupe.eleves.all (1 requête par
    # élève membre, pas de select_related) et groupe.eleves.count 2 fois (2
    # requêtes COUNT identiques) — remplacés par ces 2 variables de contexte.
    eleves_du_groupe = list(groupe.eleves.select_related('user').all())
    nb_eleves = len(eleves_du_groupe)
    autres_groupes_actifs = (
        Groupe.objects.filter(statut='actif')
        .exclude(id=groupe.id)
        .exclude(prof__statut='archive')
        .select_related('creneau')
    )

    # État "en attente de confirmation" (Tâche 18, Partie D) — recalculé à
    # chaque affichage à partir du seul ID transmis par l'URL, jamais depuis
    # un avertissement mémorisé côté client, pour ne jamais afficher un
    # avertissement obsolète ou fabriqué.
    eleve_en_attente = None
    avertissements_en_attente = []
    action_en_attente = None
    destination_en_attente = None

    confirmer_ajout_id = request.GET.get('confirmer_ajout')
    confirmer_transfert_id = request.GET.get('confirmer_transfert')
    destination_id = request.GET.get('destination')

    if confirmer_ajout_id:
        candidat = Eleve.objects.filter(id=confirmer_ajout_id).select_related('user').first()
        if candidat and raison_incompatibilite_groupe(candidat, groupe) is None:
            avertissements = avertissements_groupe(candidat, groupe)
            if avertissements:
                eleve_en_attente = candidat
                avertissements_en_attente = avertissements
                action_en_attente = 'ajout'
    elif confirmer_transfert_id and destination_id:
        candidat = Eleve.objects.filter(id=confirmer_transfert_id).select_related('user').first()
        destination = Groupe.objects.filter(id=destination_id).select_related('creneau').first()
        if candidat and destination and raison_incompatibilite_groupe(candidat, destination) is None:
            avertissements = avertissements_groupe(candidat, destination)
            if avertissements:
                eleve_en_attente = candidat
                avertissements_en_attente = avertissements
                action_en_attente = 'transfert'
                destination_en_attente = destination

    # Onglet "الخصائص" (Étape 5D du chantier du moteur d'inscription
    # configurable) — un item par Critere ACTIF, quel que soit son backend,
    # pour que le مدير/مشرف voie TOUJOURS l'état complet d'un groupe (y
    # compris les critères backend='champ_groupe'/'nb_slots', affichés en
    # lecture seule puisqu'ils ne stockent jamais de GroupeCritereValeur —
    # voir registration.utils.definir_valeurs_groupe). Recalculé à chaque
    # affichage, jamais mis en cache.
    from registration.models import Critere, GroupeCritereValeur

    criteres_config = []
    for critere in Critere.objects.filter(est_actif=True).order_by('ordre', 'id').prefetch_related('options'):
        if critere.backend == 'eav':
            valeurs_actuelles_ids = set(
                GroupeCritereValeur.objects.filter(groupe=groupe, critere=critere)
                .values_list('option_id', flat=True)
            )
            criteres_config.append({
                'critere': critere,
                'options': [o for o in critere.options.all() if o.est_actif],
                'valeurs_actuelles_ids': valeurs_actuelles_ids,
            })
        elif critere.backend == 'champ_groupe':
            # get_<champ>_display() si le champ réel a des choices (cas de
            # type_capacite) — sinon retombe sur la valeur brute.
            accesseur_affichage = getattr(groupe, f'get_{critere.champ_modele_groupe}_display', None)
            valeur_affichee = accesseur_affichage() if callable(accesseur_affichage) else getattr(groupe, critere.champ_modele_groupe, None)
            criteres_config.append({
                'critere': critere,
                'valeur_reelle': valeur_affichee,
            })
        else:  # 'nb_slots'
            criteres_config.append({
                'critere': critere,
                'valeur_derivee': groupe.creneau.slots.count() if groupe.creneau else None,
            })

    context = {
        'groupe': groupe,
        'eleves_disponibles': eleves_disponibles,
        'eleves_du_groupe': eleves_du_groupe,
        'nb_eleves': nb_eleves,
        'autres_groupes_actifs': autres_groupes_actifs,
        'eleve_en_attente': eleve_en_attente,
        'avertissements_en_attente': avertissements_en_attente,
        'action_en_attente': action_en_attente,
        'destination_en_attente': destination_en_attente,
        # Tâche du 2026-08-08 : même raisonnement que creneaux_list — calculé
        # ici pour que le bouton "حذف" et la vérification serveur avant
        # suppression utilisent EXACTEMENT le même critère.
        'peut_supprimer': groupe_peut_etre_supprime(groupe),
        # Icône 💬 chat (Chantier icône-chat du 2026-08-18) — même règle
        # d'accès que /chat/<id>/ elle-même, voir chat.permissions.
        # peut_voir_chat_groupe.__doc__.
        'peut_voir_chat': peut_voir_chat_groupe(request.user, groupe),
        'criteres_config': criteres_config,
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'courses/admin_groupe_detail.html', context)


@role_required('admin', 'mshrif')
@require_POST
def groupe_definir_critere(request, groupe_id, critere_id):
    """Enregistre la/les valeur(s) d'UN critère backend='eav' pour ce groupe
    (onglet "الخصائص") — Directeur ET مشرف, accès strictement identique
    (contrairement au reste de cette page, où l'ajout/retrait d'élèves reste
    مدير uniquement — voir le template : cette restriction pré-existante n'a
    pas de raison de s'appliquer au nouveau système de critères, demande
    explicite et répétée du client pour CE système précis)."""
    from registration.models import Critere
    from registration.utils import definir_valeurs_groupe

    groupe = get_object_or_404(Groupe, id=groupe_id)
    critere = get_object_or_404(Critere, id=critere_id)

    if critere.backend != 'eav':
        messages.error(request, gettext_('هذا المعيار مشتق تلقائياً ولا يمكن تعديله يدوياً من هنا.'))
        return redirect('admin_groupe_detail', groupe.id)

    codes = request.POST.getlist('options')
    options = list(critere.options.filter(est_actif=True, code__in=codes))
    if len(options) != len(set(codes)):
        messages.error(request, gettext_('أحد الخيارات المرسلة غير صالح لهذا المعيار.'))
        return redirect('admin_groupe_detail', groupe.id)

    definir_valeurs_groupe(groupe, critere, options)
    messages.success(request, gettext_('تم تحديث "%(v0)s" لهذه المجموعة.') % {'v0': critere.label})
    return redirect('admin_groupe_detail', groupe.id)


@role_required('admin')
def groupe_ajouter_eleve(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve_id = request.POST.get('eleve_id')
    confirme = request.POST.get('confirme') == '1'
    if eleve_id:
        eleve = get_object_or_404(Eleve, id=eleve_id)
        raison = raison_incompatibilite_groupe(eleve, groupe)
        if raison:
            messages.error(request, gettext_('تعذّرت إضافة الطالب إلى المجموعة: %(v0)s') % {'v0': raison})
        else:
            avertissements = avertissements_groupe(eleve, groupe)
            if avertissements and not confirme:
                url = reverse('admin_groupe_detail', args=[groupe_id]) + f'?confirmer_ajout={eleve.id}'
                return redirect(url)
            with transaction.atomic():
                _ajouter_eleve_au_groupe(eleve, groupe)
            for avertissement in avertissements:
                messages.warning(request, avertissement)
            messages.success(request, gettext_('تمت إضافة الطالب إلى المجموعة.'))
    return redirect('admin_groupe_detail', groupe_id=groupe_id)


@role_required('admin')
def groupe_retirer_eleve(request, groupe_id, eleve_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve = get_object_or_404(Eleve, id=eleve_id)
    if request.method == 'POST':
        with transaction.atomic():
            _retirer_eleve_du_groupe(eleve, groupe)
        messages.success(request, gettext_('تمت إزالة %(v0)s من المجموعة (سجل حصصه وتقييماته محفوظ).') % {'v0': eleve.user.get_full_name()})
    return redirect('admin_groupe_detail', groupe_id=groupe_id)


@role_required('admin')
def groupe_transferer_eleve(request, groupe_id, eleve_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    eleve = get_object_or_404(Eleve, id=eleve_id)
    destination_id = request.POST.get('destination_id')
    confirme = request.POST.get('confirme') == '1'

    if not destination_id:
        messages.error(request, gettext_('يجب اختيار مجموعة الوجهة قبل النقل.'))
        return redirect('admin_groupe_detail', groupe_id=groupe_id)

    destination = get_object_or_404(Groupe, id=destination_id)
    raison = raison_incompatibilite_groupe(eleve, destination)
    if raison:
        messages.error(request, gettext_('تعذّر نقل الطالب: %(v0)s') % {'v0': raison})
        return redirect('admin_groupe_detail', groupe_id=groupe_id)

    avertissements = avertissements_groupe(eleve, destination)
    if avertissements and not confirme:
        url = (
            reverse('admin_groupe_detail', args=[groupe_id])
            + f'?confirmer_transfert={eleve.id}&destination={destination.id}'
        )
        return redirect(url)

    with transaction.atomic():
        _retirer_eleve_du_groupe(eleve, groupe)
        _ajouter_eleve_au_groupe(eleve, destination)
    for avertissement in avertissements:
        messages.warning(request, avertissement)
    messages.success(request, gettext_('تم نقل %(v0)s إلى مجموعة %(v1)s (سجل حصصه وتقييماته في المجموعة السابقة محفوظ).') % {'v0': eleve.user.get_full_name(), 'v1': destination.nom})
    return redirect('admin_groupe_detail', groupe_id=groupe_id)

@role_required('admin')
# @transaction.atomic : même raison que groupe_ajouter (audit du 2026-09-05) —
# creneau_candidat est créé avant le bloc atomic interne qui sauvegarde le
# groupe et supprime ancien_creneau ; sans cette transaction englobante, un
# échec dans ce bloc interne laissait creneau_candidat orphelin.
@transaction.atomic
def groupe_modifier(request, groupe_id):
    groupe = get_object_or_404(Groupe.objects.select_related('creneau'), id=groupe_id)
    # Prof.actifs exclut les archivés du choix — SAUF le prof déjà assigné à ce
    # groupe s'il vient d'être archivé: on le garde visible (étiqueté "مؤرشف"
    # dans le template) pour que l'admin voie clairement qui est en place et
    # puisse le réassigner explicitement, plutôt que de le faire disparaître
    # silencieusement du formulaire (chantier d'archivage du 2026-08-03).
    # select_related('user') : même correctif que groupe_ajouter ci-dessus
    # (Correctif du 2026-08-30) — le template affiche prof.user.get_full_name
    # pour chaque prof, sans quoi c'est 1 requête par prof actif de toute
    # l'école à chaque ouverture de cette page.
    profs = list(Prof.actifs.select_related('user').all())
    if groupe.prof_id and groupe.prof and groupe.prof.statut == 'archive' and groupe.prof not in profs:
        profs.append(groupe.prof)
    liens_meet = LienMeet.objects.filter(est_actif=True)

    if request.method == 'POST':
        # Photo (Tâche du 2026-08-17) — validée AVANT toute autre étape, même
        # patron que groupe_ajouter. `supprimer_photo=1` (case à cocher dédiée
        # du formulaire) retire la photo actuelle quand AUCUN nouveau fichier
        # n'est fourni — un nouveau fichier envoyé remplace toujours la photo
        # existante, que la case soit cochée ou non (voir plus bas).
        nouvelle_photo = request.FILES.get('photo')
        if nouvelle_photo:
            erreur_photo = valider_photo_groupe(nouvelle_photo)
            if erreur_photo:
                messages.error(request, erreur_photo)
                return render(request, 'courses/admin_groupe_modifier.html', {
                    'groupe': groupe,
                    'profs': profs,
                    'liens_meet': liens_meet,
                    'categorie_choices': Groupe.CATEGORIE_CHOICES,
                    'valeurs_creneau': _valeurs_creneau_pour_affichage(request, groupe.creneau),
                    'slots_saisis': _slots_pour_affichage(request, groupe.creneau),
                })

        slots = _slots_depuis_post(request)
        if not slots:
            messages.error(request, gettext_('يجب إضافة حصة واحدة على الأقل.'))
            return render(request, 'courses/admin_groupe_modifier.html', {
                'groupe': groupe,
                'profs': profs,
                'liens_meet': liens_meet,
                'categorie_choices': Groupe.CATEGORIE_CHOICES,
                'valeurs_creneau': _valeurs_creneau_pour_affichage(request, groupe.creneau),
                'slots_saisis': slots,
            })

        age_min, age_max, erreur_age = _ages_creneau_depuis_post(request)
        if erreur_age:
            messages.error(request, erreur_age)
            return render(request, 'courses/admin_groupe_modifier.html', {
                'groupe': groupe,
                'profs': profs,
                'liens_meet': liens_meet,
                'categorie_choices': Groupe.CATEGORIE_CHOICES,
                'valeurs_creneau': _valeurs_creneau_pour_affichage(request, groupe.creneau),
                'slots_saisis': slots,
            })

        # Horaire (chantier « fusion horaire/groupe » du 2026-09-04, décision
        # explicite du client) : au lieu de choisir un Creneau existant
        # (potentiellement partagé, ancien écran « الحلقات » retiré ce même
        # chantier), on construit un Creneau CANDIDAT privé depuis les champs
        # du formulaire — même patron que groupe_ajouter, pour les mêmes
        # raisons (avertissements_prof_creneau/conflit de lien Meet ont
        # besoin d'un Creneau PERSISTÉ). Adopté par le groupe seulement si la
        # sauvegarde va à son terme (voir plus bas) ; supprimé sinon.
        ancien_creneau = groupe.creneau
        anciens_slots = (
            list(ancien_creneau.slots.order_by('ordre').values_list('jour', 'heure_debut', 'heure_fin'))
            if ancien_creneau else []
        )
        creneau_candidat = Creneau.objects.create(
            sexe_cible=request.POST.get('sexe_cible'),
            type_seance=request.POST.get('type_seance'),
            riwaya=request.POST.get('riwaya'),
            age_min=age_min,
            age_max=age_max,
        )
        remplacer_slots_creneau(creneau_candidat, slots)
        nouveaux_slots = list(
            creneau_candidat.slots.order_by('ordre').values_list('jour', 'heure_debut', 'heure_fin')
        )
        # Ne redéclenche la régénération des séances futures (destructive pour
        # les séances déjà planifiées) que si l'horaire RÉEL (jour/heure) a
        # changé — pas pour un simple ajustement d'âge/sexe/type/riwaya sans
        # rapport avec le planning. Même principe que l'ancien creneau_modifier.
        horaire_a_change = [str(v) for v in anciens_slots] != [str(v) for v in nouveaux_slots]

        def _valeur_str(valeur):
            return '' if valeur is None else str(valeur)

        # Périmètre plus large que horaire_a_change ci-dessus : sert seulement
        # à décider si l'avertissement prof/créneau doit être réévalué (âge et
        # sexe comptent aussi pour cette compatibilité-là, pas seulement le
        # jour/l'heure) — même rôle que l'ancien creneau_a_change (basé sur un
        # changement d'id), qui ne peut plus être utilisé tel quel puisqu'un
        # NOUVEAU Creneau est désormais créé à chaque modification.
        creneau_pertinent_a_change = horaire_a_change or (ancien_creneau is None) or any(
            _valeur_str(getattr(ancien_creneau, champ)) != _valeur_str(request.POST.get(champ))
            for champ in ('sexe_cible', 'type_seance', 'riwaya', 'age_min', 'age_max')
        )

        def _redisplay(**contexte_supplementaire):
            creneau_candidat.delete()
            contexte = {
                'groupe': groupe,
                'profs': profs,
                'liens_meet': liens_meet,
                'categorie_choices': Groupe.CATEGORIE_CHOICES,
                'valeurs_creneau': _valeurs_creneau_pour_affichage(request, groupe.creneau),
                'slots_saisis': slots,
            }
            contexte.update(contexte_supplementaire)
            return render(request, 'courses/admin_groupe_modifier.html', contexte)

        # Lien Meet retenu : lien du pool (<select>) ou URL collée à la main
        # (champ "lien_meet_nouveau", qui rejoint alors le pool) — résolu ICI,
        # avant l'éventuel ré-affichage pour avertissement prof.
        nouveau_lien_meet_id, erreur_lien_meet = _resoudre_lien_meet_pour_formulaire(request)
        if erreur_lien_meet:
            messages.error(request, erreur_lien_meet)
            return _redisplay()

        nouveau_prof_id = request.POST.get('prof') or None
        prof_a_change = str(groupe.prof_id) != str(nouveau_prof_id)
        confirme = request.POST.get('confirme') == '1'
        avertissements_prof = []
        # Ne revalider la compatibilité prof/créneau que si l'un des deux change réellement —
        # sinon un groupe déjà assigné avant durcissement des disponibilités (ou avec une
        # matrice de dispo incomplète) devient bloqué pour toute autre modification (ex: lien_reunion).
        if nouveau_prof_id and (creneau_pertinent_a_change or prof_a_change):
            prof_obj = get_object_or_404(Prof, id=nouveau_prof_id)
            # Revalidé côté serveur (le <select> exclut déjà les archivés, sauf le
            # prof déjà en place — voir plus haut) — se protège contre un POST
            # direct choisissant un AUTRE prof archivé que celui déjà assigné.
            if prof_a_change and prof_obj.statut == 'archive':
                messages.error(request, gettext_('تعذّر إسناد %(v0)s: هذا الأستاذ مؤرشف.') % {'v0': prof_obj.user.get_full_name()})
                return _redisplay()
            # Tâche du 2026-08-09 : l'incompatibilité d'horaire n'est plus
            # bloquante — voir le même commentaire dans groupe_ajouter.
            avertissements_prof = avertissements_prof_creneau(prof_obj, creneau_candidat)
            if avertissements_prof and not confirme:
                groupe_previsualise = Groupe(
                    id=groupe.id,
                    nom=request.POST.get('nom'),
                    nom_fr=request.POST.get('nom_fr', ''),
                    nom_en=request.POST.get('nom_en', ''),
                    description=request.POST.get('description', ''),
                    description_fr=request.POST.get('description_fr', ''),
                    description_en=request.POST.get('description_en', ''),
                    capacite_max=_capacite_max_depuis_post(request),
                    type_capacite=request.POST.get('type_capacite', 'groupe'),
                    statut=request.POST.get('statut'),
                    prof_id=nouveau_prof_id,
                    lien_meet_id=nouveau_lien_meet_id,
                    categorie=request.POST.get('categorie', ''),
                    cache_du_wizard_public=request.POST.get('cache_du_wizard_public') == 'on',
                )
                return _redisplay(groupe=groupe_previsualise, avertissements_prof=avertissements_prof)

        # Lien Meet (Tâche du 2026-08-17) : REVÉRIFIÉ à chaque sauvegarde, même
        # quand le lien choisi est déjà celui en place — un changement de créneau
        # à lui seul peut rendre un lien déjà assigné en conflit avec un autre
        # groupe (section 8 du cahier des charges : jamais de confiance silencieuse
        # dans un ancien état). Verrou sur le LienMeet choisi le temps de la
        # vérification+affectation (concurrence — même principe que groupe_ajouter).
        with transaction.atomic():
            nouveau_lien_meet_obj = None
            if nouveau_lien_meet_id:
                nouveau_lien_meet_obj = get_object_or_404(LienMeet.objects.select_for_update(), id=nouveau_lien_meet_id)
                if not nouveau_lien_meet_obj.est_actif:
                    messages.error(request, gettext_('هذا الرابط معطّل حالياً — اختر رابطاً آخر.'))
                    return _redisplay()
                conflit = description_conflit_lien_meet(nouveau_lien_meet_obj, creneau_candidat, groupe_exclu=groupe)
                if conflit:
                    messages.error(request, gettext_('تعذّر استخدام "%(v0)s" لهذا التوقيت: %(v1)s') % {'v0': nouveau_lien_meet_obj, 'v1': conflit})
                    return _redisplay()

            groupe.nom = request.POST.get('nom')
            groupe.nom_fr = request.POST.get('nom_fr', '')
            groupe.nom_en = request.POST.get('nom_en', '')
            groupe.description = request.POST.get('description', '')
            groupe.description_fr = request.POST.get('description_fr', '')
            groupe.description_en = request.POST.get('description_en', '')
            groupe.capacite_max = _capacite_max_depuis_post(request)
            groupe.type_capacite = request.POST.get('type_capacite', 'groupe')
            groupe.statut = request.POST.get('statut')
            groupe.prof_id = nouveau_prof_id
            # Audit du 2026-09-05 : seulement si un champ pertinent a changé —
            # sinon groupe.creneau reste ancien_creneau tel quel (voir plus bas,
            # creneau_candidat jetable est alors supprimé au lieu d'être adopté).
            if creneau_pertinent_a_change:
                groupe.creneau = creneau_candidat
            groupe.categorie = request.POST.get('categorie', '')
            # Chantier du 2026-08-23 ("exclusion manuelle d'un groupe") —
            # n'affecte QUE le nouveau parcours public (registration.utils.
            # groupes_compatibles), jamais ce formulaire ni le reste du
            # projet : voir Groupe.cache_du_wizard_public.__doc__.
            groupe.cache_du_wizard_public = request.POST.get('cache_du_wizard_public') == 'on'
            if nouvelle_photo:
                groupe.photo = nouvelle_photo
            elif request.POST.get('supprimer_photo') == '1':
                groupe.photo.delete(save=False)
                groupe.photo = None
            ancien_lien_meet_id = groupe.lien_meet_id
            ancien_lien_meet_url = groupe.lien_meet.url if groupe.lien_meet_id else None
            if nouveau_lien_meet_obj:
                groupe.lien_meet = nouveau_lien_meet_obj
                groupe.lien_reunion = nouveau_lien_meet_obj.url
            else:
                # Retrait explicite d'un lien du pool : n'efface lien_reunion QUE s'il
                # correspondait bien à ce lien_meet — jamais un lien saisi manuellement
                # avant ce chantier (ex. WhatsApp), voir Groupe.lien_reunion.
                if ancien_lien_meet_id and groupe.lien_reunion == ancien_lien_meet_url:
                    groupe.lien_reunion = ''
                groupe.lien_meet = None
            groupe.save()
            if creneau_pertinent_a_change:
                # L'ancien Creneau n'est plus jamais partagé (chantier du
                # 2026-09-04) : il n'est référencé que par CE groupe, donc sûr à
                # supprimer maintenant que groupe.creneau pointe déjà vers le
                # nouveau (voir la migration 0045 pour les données pré-existantes).
                if ancien_creneau is not None:
                    ancien_creneau.delete()
            else:
                # Audit du 2026-09-05 : rien de pertinent n'a changé (même
                # horaire/âge/sexe/type/riwaya) — creneau_candidat n'était
                # qu'un jetable créé pour permettre le calcul des
                # avertissements prof (avertissements_prof_creneau a besoin
                # d'un Creneau persisté), jamais adopté par le groupe. Sans ce
                # else, CHAQUE sauvegarde du formulaire (même un simple
                # changement de photo/description) recréait et détruisait un
                # Creneau + ses CreneauSlot pour rien.
                creneau_candidat.delete()

        for avertissement in avertissements_prof:
            messages.warning(request, avertissement)
        if horaire_a_change:
            regenerer_pour_nouveau_creneau(groupe)
            messages.success(request, gettext_('تم تعديل المجموعة وإعادة توليد حصصها حسب الحلقة الجديدة.'))
        else:
            messages.success(request, gettext_('تم تعديل المجموعة بنجاح.'))
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    return render(request, 'courses/admin_groupe_modifier.html', {
        'groupe': groupe,
        'profs': profs,
        'liens_meet': liens_meet,
        'categorie_choices': Groupe.CATEGORIE_CHOICES,
        'valeurs_creneau': _valeurs_creneau_pour_affichage(request, groupe.creneau),
        'slots_saisis': _slots_pour_affichage(request, groupe.creneau),
    })


def _slots_depuis_post(request):
    """Parse les listes parallèles slot_jour[]/slot_heure_debut[]/slot_heure_fin[]
    soumises par le formulaire créneau (1 à N lignes, chantier de généralisation N
    séances/semaine) en une liste ordonnée de dicts {'jour','heure_debut','heure_fin'}
    — même ordre que reçu, devient l'ordre (CreneauSlot.ordre) à l'enregistrement.
    Une ligne incomplète (un des 3 champs vide, ex: JS désactivé/POST manipulé) est
    ignorée plutôt que de faire planter la création — pas de Django Forms dans ce
    projet, la validation reste manuelle."""
    jours = request.POST.getlist('slot_jour')
    debuts = request.POST.getlist('slot_heure_debut')
    fins = request.POST.getlist('slot_heure_fin')
    return [
        {'jour': jour, 'heure_debut': debut, 'heure_fin': fin}
        for jour, debut, fin in zip(jours, debuts, fins)
        if jour and debut and fin
    ]


def _capacite_max_depuis_post(request):
    """Capacité max du groupe depuis le POST, castée en int (défaut 10,
    plancher 1). Nom de champ unifié le 2026-09-05 : l'écran d'AJOUT postait
    `max_eleves`, l'écran de MODIF `capacite_max` — désormais `capacite_max`
    des deux côtés, `max_eleves` gardé en repli pour un vieux formulaire en
    cache. Le cast int évite qu'une valeur reste en str sur l'instance en
    mémoire (même classe de piège que _ages_creneau_depuis_post)."""
    brut = request.POST.get('capacite_max') or request.POST.get('max_eleves') or ''
    try:
        return max(int(brut), 1)
    except (TypeError, ValueError):
        return 10


def _ages_creneau_depuis_post(request):
    """(age_min, age_max) en int depuis le POST du formulaire groupe, ou
    (None, None, message d'erreur) si l'un des deux est absent/non entier/hors
    plage — garde-fou serveur (pas de Django Forms dans ce projet, `required`
    HTML contournable par un POST forgé ou JS désactivé).

    Le cast en int est OBLIGATOIRE ici : Creneau.age_min/age_max sont des
    IntegerField NOT NULL, mais Creneau.objects.create(age_min='6') ne caste
    PAS la valeur sur l'instance en mémoire — elle resterait la str du POST,
    ce qui casse _categorie_age_creneau (`'6' < AGE_SEUIL_ADULTE`) au moment
    du calcul des avertissements prof dans groupe_ajouter/groupe_modifier
    (audit du 2026-09-05, HTTP 500 sur toute création/modif de groupe avec un
    enseignant assigné)."""
    brut_min = (request.POST.get('age_min') or '').strip()
    brut_max = (request.POST.get('age_max') or '').strip()
    try:
        age_min, age_max = int(brut_min), int(brut_max)
    except (TypeError, ValueError):
        return None, None, gettext_('يجب إدخال السن الأدنى والسن الأقصى كرقمين صحيحين.')
    if age_min < 1 or age_max < age_min:
        return None, None, gettext_('نطاق السن غير صالح: تأكد أن السن الأدنى لا يقل عن 1 وأنه لا يتجاوز السن الأقصى.')
    return age_min, age_max, None


def _valeurs_creneau_depuis_post(request):
    """Valeurs du gabarit horaire (sexe/type/rewaya/âge) telles que soumises
    dans le POST du formulaire groupe — chantier « fusion horaire/groupe » du
    2026-09-04 (voir groupe_ajouter/groupe_modifier). Sert à re-préremplir le
    formulaire quand la soumission est ré-affichée (erreur, avertissement non
    confirmé) : le Creneau créé pour la validation est alors supprimé, donc
    plus rien en base à relire — on repart des valeurs telles que tapées.
    request.POST est un QueryDict vide sur un GET, donc .get() retombe déjà
    sur les valeurs par défaut ci-dessous dans ce cas (formulaire de création
    vierge)."""
    return {
        'sexe_cible': request.POST.get('sexe_cible', 'mixte'),
        'type_seance': request.POST.get('type_seance', 'hifz'),
        'riwaya': request.POST.get('riwaya', 'hafs'),
        'age_min': request.POST.get('age_min', ''),
        'age_max': request.POST.get('age_max', ''),
    }


def _valeurs_creneau_pour_affichage(request, creneau_existant):
    """Valeurs à préremplir dans les champs horaire du formulaire groupe :
    celles du POST si une soumission a été refusée (ré-affichage — voir
    _valeurs_creneau_depuis_post), sinon celles du Creneau déjà attaché au
    groupe (ouverture d'un formulaire de MODIFICATION), sinon les valeurs par
    défaut (ouverture d'un formulaire de CRÉATION, creneau_existant=None)."""
    if request.method == 'POST':
        return _valeurs_creneau_depuis_post(request)
    if creneau_existant:
        return {
            'sexe_cible': creneau_existant.sexe_cible,
            'type_seance': creneau_existant.type_seance,
            'riwaya': creneau_existant.riwaya,
            'age_min': creneau_existant.age_min,
            'age_max': creneau_existant.age_max,
        }
    return _valeurs_creneau_depuis_post(request)


def _slots_pour_affichage(request, creneau_existant):
    """Même principe que _valeurs_creneau_pour_affichage, pour les حصص
    hebdomadaires (slot_jour/slot_heure_debut/slot_heure_fin)."""
    if request.method == 'POST':
        return _slots_depuis_post(request)
    if creneau_existant:
        return [
            {
                'jour': slot.jour,
                'heure_debut': slot.heure_debut.strftime('%H:%M'),
                'heure_fin': slot.heure_fin.strftime('%H:%M'),
            }
            for slot in creneau_existant.slots.order_by('ordre')
        ]
    return []


@role_required('admin')
def groupe_supprimer(request, groupe_id):
    """Suppression réelle (Tâche du 2026-08-08) — UNIQUEMENT si aucune
    donnée n'est rattachée (voir courses.utils.groupe_peut_etre_supprime,
    revérifié ici côté serveur). Sinon, seule "تعطيل" (statut='archive' via
    admin_groupe_modifier, existant) reste possible. POST uniquement."""
    groupe = get_object_or_404(Groupe, id=groupe_id)
    if not groupe_peut_etre_supprime(groupe):
        messages.error(
            request,
            gettext_('تعذّر الحذف: هذه المجموعة مرتبطة بحصص أو طلاب أو سجل تاريخي — يمكنك أرشفتها بدلاً من ذلك (تعديل ← الحالة).')
        )
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    if request.method != 'POST':
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    nom = groupe.nom
    # Chantier « fusion horaire/groupe » du 2026-09-04 : le Creneau de ce
    # groupe n'appartient plus qu'à lui (unique=True depuis l'audit du
    # 2026-09-05) — supprimer le groupe sans supprimer aussi son Creneau
    # laisserait une ligne orpheline invisible pour toujours (l'ancien écran
    # « الحلقات » qui permettait de les voir/nettoyer a été retiré ce même
    # chantier). SET_NULL sur Groupe.creneau, donc groupe.delete() seul ne
    # le touche pas — suppression explicite ici.
    creneau = groupe.creneau
    with transaction.atomic():
        groupe.delete()
        if creneau is not None:
            creneau.delete()
    messages.success(request, gettext_('تم حذف المجموعة "%(v0)s" نهائياً.') % {'v0': nom})
    return redirect('admin_groupes')


# ==================== ARCHIVAGE GROUPE (Tâche du 2026-08-08) ====================
# Groupe.statut avait déjà le choix 'archive' depuis le début, mais jamais
# exploité par une action dédiée (seulement modifiable via le formulaire
# d'édition) — voir GroupeActifsManager pour l'exclusion des listes.
# Élargi à مدير + مشرف (demande explicite de ce chantier), contrairement à
# admin_prof_archiver/admin_eleve_archiver qui restent مدير uniquement — pas
# de blocage de connexion à gérer ici (un Groupe n'est pas un compte).

@role_required('admin', 'mshrif')
def groupe_archiver(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    groupe.statut = 'archive'
    groupe.save(update_fields=['statut'])
    messages.info(request, gettext_('تمت أرشفة المجموعة "%(v0)s" — لن تظهر في القوائم إلا عبر تصفية "الحالة". سجلها الكامل يبقى محفوظاً.') % {'v0': groupe.nom})
    return redirect('admin_groupe_detail', groupe_id=groupe.id)


@role_required('admin', 'mshrif')
def groupe_reactiver(request, groupe_id):
    groupe = get_object_or_404(Groupe, id=groupe_id)
    groupe.statut = 'actif'
    groupe.save(update_fields=['statut'])
    messages.success(request, gettext_('تمت إعادة تفعيل المجموعة "%(v0)s".') % {'v0': groupe.nom})
    return redirect('admin_groupe_detail', groupe_id=groupe.id)


# ==================== SUPPRESSION DÉFINITIVE AVEC HISTORIQUE (Tâche du 2026-08-08, point 2 — révisé le 2026-08-08) ====================
# Distincte de groupe_supprimer/creneau_supprimer (qui refusent tout net si
# une donnée existe) : ici, on supprime QUAND MÊME, même avec des séances/
# présences/évaluations liées — مدير UNIQUEMENT (pas مشرف, contrairement à
# l'archivage ci-dessus), confirmation par saisie EXACTE du nom (aucune case
# à cocher ne suffit pour une action de cette gravité). Décision explicite du
# client : AUCUNE trace conservée après coup (le JournalSuppression construit
# initialement a été retiré — modèle supprimé du projet, voir migration
# 0025_delete_journalsuppression) — la suppression est réellement définitive,
# sans journal d'audit.

@role_required('admin')
def groupe_supprimer_definitivement(request, groupe_id):
    from .models import Presence

    groupe = get_object_or_404(Groupe, id=groupe_id)
    if request.method != 'POST':
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    confirmation_nom = request.POST.get('confirmation_nom', '').strip()
    if confirmation_nom != groupe.nom:
        messages.error(request, gettext_('الاسم المُدخل لا يطابق اسم المجموعة بالضبط — لم يتم حذف أي شيء.'))
        return redirect('admin_groupe_detail', groupe_id=groupe.id)

    nb_seances = groupe.seances.count()
    nb_presences = Presence.objects.filter(seance__groupe=groupe).count()
    nom = groupe.nom
    # Même correctif que groupe_supprimer ci-dessus — voir son commentaire.
    creneau = groupe.creneau

    with transaction.atomic():
        groupe.delete()
        if creneau is not None:
            creneau.delete()

    messages.success(
        request,
        gettext_('تم حذف المجموعة "%(v0)s" نهائياً مع كامل سجلها (%(v1)s حصة، %(v2)s حضور).') % {'v0': nom, 'v1': nb_seances, 'v2': nb_presences}
    )
    return redirect('admin_groupes')


# ==================== POOL DE LIENS GOOGLE MEET (Tâche du 2026-08-17) ====================
# Pool centralisé du مدير : un lien Meet enregistré une seule fois, réutilisable par
# plusieurs groupes (voir courses.utils.liens_meet_disponibles pour la logique de
# disponibilité). Lecture partagée مدير+مشرف (même patron que groupes_list/
# creneaux_list) ; ajout/désactivation restent مدير uniquement — aucune demande
# explicite d'élargir ces écritures à مشرف pour ce chantier précis.

@role_required('admin', 'mshrif')
def liens_meet_list(request):
    """Phase 2 (audit UX du 2026-08-17) puis Phase 3 (correction du
    2026-08-17, suite) : TOUT groupe ACTIF sans lien doit être visible ici,
    avec OU sans créneau — un groupe sans créneau n'a pas de disponibilité
    calculable (voir liens_meet_disponibles(None)), mais rester invisible
    laissait le مدير croire qu'il n'y avait rien à faire alors qu'il y a bien
    un problème (juste un problème différent : "aucun horaire", pas "aucun
    lien"). D'où 2 listes distinctes plutôt qu'une seule mélangée : le
    template les affiche comme 2 états visuellement différents (carte
    actionnable "إسناد رابط" vs carte "الجدول غير محدد"), chacun avec sa
    propre action. AUCUN changement à la logique de conflit elle-même
    (courses.utils.liens_meet_disponibles), seulement à QUELS groupes sont
    listés ici et comment ils sont affichés."""
    from django.db.models import Count, Prefetch

    liens = list(LienMeet.objects.annotate(nb_groupes=Count('groupes', distinct=True)).prefetch_related(
        Prefetch('groupes', queryset=Groupe.objects.select_related('creneau'))
    ).order_by('libelle', 'id'))

    groupes_sans_lien_avec_creneau = list(
        Groupe.actifs.filter(creneau__isnull=False, lien_reunion='')
        .select_related('creneau').order_by('nom')
    )
    # Correctif du 2026-08-30 (voir courses.utils.matrice_disponibilite_liens_meet) :
    # la disponibilité de CHAQUE lien actif pour CHAQUE groupe de cette liste était
    # auparavant recalculée indépendamment (liens_meet_disponibles par groupe, donc
    # par groupe x par lien x conflit) — désormais un seul appel en lot, chaque
    # groupe s'excluant ensuite lui-même de SES résultats (groupe_exclu diffère par
    # groupe ici, contrairement à un groupe_exclu global — d'où le filtrage
    # en Python plutôt qu'un groupe_exclu unique passé à l'appel en lot).
    liens_actifs = [lien for lien in liens if lien.est_actif]
    conflits_par_couple = matrice_disponibilite_liens_meet(
        liens_actifs, [groupe.creneau for groupe in groupes_sans_lien_avec_creneau],
    )
    for groupe in groupes_sans_lien_avec_creneau:
        disponibles = []
        for lien in liens_actifs:
            conflits = conflits_par_couple.get((lien.id, groupe.creneau_id), [])
            # Un groupe SANS lien assigné (c'est le cas de tous ceux de cette
            # liste, lien_reunion='') n'apparaît jamais lui-même dans conflits
            # (matrice_disponibilite_liens_meet ne liste que les candidats
            # ayant déjà `lien` assigné) — filtré quand même par sécurité,
            # pour un comportement identique à l'ancien groupe_exclu=groupe.
            if not [g for g in conflits if g.id != groupe.id]:
                disponibles.append(lien)
        groupe.liens_disponibles = disponibles

    groupes_sans_lien_sans_creneau = list(
        Groupe.actifs.filter(creneau__isnull=True, lien_reunion='').order_by('nom')
    )

    groupes_configures = list(
        Groupe.actifs.exclude(lien_reunion='').select_related('creneau', 'lien_meet').order_by('nom')
    )

    context = {
        'liens': liens,
        'groupes_sans_lien_avec_creneau': groupes_sans_lien_avec_creneau,
        'groupes_sans_lien_sans_creneau': groupes_sans_lien_sans_creneau,
        'nb_groupes_sans_lien_total': len(groupes_sans_lien_avec_creneau) + len(groupes_sans_lien_sans_creneau),
        'groupes_configures': groupes_configures,
        'nb_liens_actifs': sum(1 for lien in liens if lien.est_actif),
        'base_template': _base_template_admin_ou_mshrif(request),
    }
    context.update(_contexte_base_mshrif(request))
    return render(request, 'courses/admin_liens_meet.html', context)


@role_required('admin')
def lien_meet_ajouter(request):
    """POST uniquement (formulaire inline dans admin_liens_meet.html — pas de
    page dédiée, les 2 seuls champs ne le justifient pas)."""
    if request.method == 'POST':
        url = request.POST.get('url', '').strip()
        libelle = request.POST.get('libelle', '').strip()
        libelle_fr = request.POST.get('libelle_fr', '').strip()
        libelle_en = request.POST.get('libelle_en', '').strip()
        if not url:
            messages.error(request, gettext_('يجب إدخال رابط.'))
        elif LienMeet.objects.filter(url=url).exists():
            messages.error(request, gettext_('هذا الرابط مسجَّل مسبقاً في القائمة.'))
        else:
            LienMeet.objects.create(url=url, libelle=libelle, libelle_fr=libelle_fr, libelle_en=libelle_en)
            messages.success(request, gettext_('تمت إضافة الرابط بنجاح.'))
    return redirect('admin_liens_meet')


@role_required('admin')
def lien_meet_attribuer_groupe(request, groupe_id):
    """Attribution rapide depuis la section "المجموعات بدون رابط" de
    admin_liens_meet.html (Phase 2) — POST uniquement. Réutilise EXACTEMENT
    la même validation serveur que groupe_ajouter/groupe_modifier (actif +
    disponibilité recalculée sur les 2 créneaux + verrou sur le LienMeet le
    temps de la vérification), sans dupliquer cette logique : c'est un
    raccourci d'UI, pas un second chemin de validation."""
    groupe = get_object_or_404(Groupe, id=groupe_id)

    if request.method != 'POST':
        return redirect('admin_liens_meet')

    # Lien du pool (formulaire "إسناد رابط") OU URL collée à la main (champ
    # "lien_meet_nouveau"), qui rejoint alors le pool — voir
    # _resoudre_lien_meet_pour_formulaire. La suite est inchangée.
    lien_meet_id, erreur_lien_meet = _resoudre_lien_meet_pour_formulaire(request)
    if erreur_lien_meet:
        messages.error(request, erreur_lien_meet)
        return redirect('admin_liens_meet')
    if not lien_meet_id:
        return redirect('admin_liens_meet')

    if not groupe.creneau_id:
        messages.error(request, gettext_('تعذّر إسناد الرابط: هذه المجموعة بدون حلقة (جدول) محددة.'))
        return redirect('admin_liens_meet')

    with transaction.atomic():
        lien_meet_obj = get_object_or_404(LienMeet.objects.select_for_update(), id=lien_meet_id)
        if not lien_meet_obj.est_actif:
            messages.error(request, gettext_('هذا الرابط معطّل حالياً — اختر رابطاً آخر.'))
            return redirect('admin_liens_meet')

        conflit = description_conflit_lien_meet(lien_meet_obj, groupe.creneau, groupe_exclu=groupe)
        if conflit:
            messages.error(request, gettext_('تعذّر إسناد "%(v0)s" لمجموعة "%(v1)s": %(v2)s') % {'v0': lien_meet_obj, 'v1': groupe.nom, 'v2': conflit})
            return redirect('admin_liens_meet')

        groupe.lien_meet = lien_meet_obj
        groupe.lien_reunion = lien_meet_obj.url
        groupe.save(update_fields=['lien_meet', 'lien_reunion'])

    messages.success(request, gettext_('تم إسناد "%(v0)s" إلى مجموعة "%(v1)s".') % {'v0': lien_meet_obj, 'v1': groupe.nom})
    return redirect('admin_liens_meet')


@role_required('admin')
def lien_meet_toggle(request, lien_id):
    """Active/désactive un lien — même principe que creneau_toggle
    (Creneau.est_actif) : un lien désactivé disparaît seulement des
    propositions pour un NOUVEAU choix, les groupes qui l'utilisent déjà ne
    sont JAMAIS affectés (pas de dé-affectation automatique, pas de
    notification — voir Groupe.lien_meet, on_delete=SET_NULL réservé à une
    suppression réelle, jamais utilisée ici)."""
    lien = get_object_or_404(LienMeet, id=lien_id)
    lien.est_actif = not lien.est_actif
    lien.save()
    if lien.est_actif:
        messages.info(request, gettext_('تمت إعادة تفعيل الرابط.'))
    else:
        messages.info(request, gettext_('تم تعطيل الرابط — لن يُقترح للمجموعات الجديدة. المجموعات التي تستخدمه حالياً غير متأثرة.'))
    return redirect('admin_liens_meet')
