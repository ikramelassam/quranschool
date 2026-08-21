# Bascule progressive — moteur d'inscription configurable

Ce fichier est une **check-list pour une décision humaine**, écrite à la fin
du chantier (Étape 8, 2026-08-21). Rien ici ne doit être exécuté
automatiquement par un script ou une session Claude Code future — chaque
case cochée doit l'être par vous (ou avec votre accord explicite), au moment
qui vous convient.

## État actuel (à la fin du chantier)

- L'**ancien formulaire à une page** (`/register/student`, `inscriptions/views.py`
  `inscription_eleve_*`) est toujours le seul chemin réellement exposé au
  public. Il n'a été ni modifié ni désactivé à aucun moment de ce chantier.
- Le **nouveau parcours** (wizard public `/registration/wizard/` en 6 étapes
  + ajout manuel Directeur/مشرف `/dashboard/admin/eleves/ajouter-manuel/`)
  est complet, testé (registration 66/66, dashboard 192/192, inscriptions
  15/15 — voir les commits de ce chantier), mais **le lien public
  `/registration/wizard/` n'est affiché nulle part** sur le site actuel — il
  n'est atteignable qu'en connaissant l'URL directement.
- Les deux parcours écrivent dans le **même modèle** (`InscriptionEleve`) et
  passent par le **même écran de validation** (`admin_valider_eleve`) — un
  Directeur/مشرف qui consulte "طلبات التسجيل" voit les candidatures des deux
  origines mélangées, sans distinction visuelle autre que le remplissage ou
  non de `ReponseInscription` (voir le fallback d'affichage
  Programme/Riwaya, déjà en place).

## Check-list avant d'activer le nouveau parcours en conditions réelles

- [ ] **Configuration de départ vérifiée** : ouvrir chaque écran du dashboard
  (الأسئلة/المعايير، المراحل، القواعد الشرطية، طرق الدفع، تقديم التسجيل) et
  confirmer que le contenu par défaut (posé par la migration de seed,
  Étape 6A) correspond à ce que vous voulez réellement montrer à un
  visiteur — labels, textes de présentation, moyens de paiement actifs.
- [ ] **Essai à blanc** : vous (ou le مشرف) remplissez vous-même le wizard
  public de bout en bout (avec un email de test), vérifiez le rendu sur
  mobile, et rejetez la candidature test créée.
- [ ] **Formation courte du personnel** : montrer au مشرف (et à vous-même si
  besoin d'un rappel) le nouvel écran d'ajout manuel et les écrans de
  configuration — ils sont nouveaux, contrairement à "طلبات التسجيل" qui
  reste identique dans son usage quotidien.
- [ ] **Décision d'activation du lien public** : remplacer le lien existant
  du site vers `/register/student` par `/registration/wizard/`, OU les
  laisser coexister un temps (les deux créent des `InscriptionEleve`
  valides, aucun conflit). C'est vous qui décidez du moment.
- [ ] **Période d'observation** : une fois le nouveau lien actif, surveiller
  les candidatures entrantes pendant quelques semaines (durée à votre
  appréciation) — en particulier les avertissements de couverture
  incomplète sur les critères filtrables (fiche de chaque critère, section
  "couverture"), qui signalent des groupes existants sans valeur configurée.

## Quand retirer l'ancien formulaire à une page

Ne rien supprimer avant que le nouveau parcours ait tourné seul, sans
incident, pendant une durée que vous jugez suffisante (suggestion : au moins
un cycle d'inscription complet, ex. un mois ou un trimestre selon votre
rythme réel de candidatures). Quand vous êtes prêt·e :

- [ ] Retirer le lien public vers `/register/student` (garder les vues
  `inscriptions/views.py` et les URLs en place tant qu'un doute subsiste —
  les supprimer est une étape séparée, plus tardive et moins urgente).
- [ ] Informer le Directeur/مشرف que seul le nouveau parcours reste actif.

## Quand supprimer les anciennes colonnes de `Creneau`

`Creneau.jour_1/heure_debut_1/heure_fin_1/jour_2/heure_debut_2/heure_fin_2`
sont `null=True, blank=True` depuis l'Étape 3 (généralisation à N séances via
`CreneauSlot`) — conservées pour une transition sans risque, plus lues nulle
part dans le code actif (`CreneauSlot` est la seule source de vérité). Avant
de les supprimer réellement (migration destructive, irréversible) :

- [ ] Confirmer par une requête que **tous** les `Creneau` réels ont bien des
  `CreneauSlot` équivalents (le backfill de l'Étape 3 l'a fait une fois —
  revérifier qu'aucun `Creneau` créé depuis n'a été mal saisi).
- [ ] S'assurer qu'une sauvegarde de la base de production existe,
  indépendamment de cette suppression.
- [ ] Laisser passer un temps de recul en production sur `CreneauSlot` seul
  (suggestion : 2 à 3 mois sans anomalie liée aux créneaux) avant de
  considérer la suppression réellement sans risque.
- [ ] Décision humaine explicite avant d'écrire la migration de suppression
  — jamais automatique.

## Ce qui ne change PAS avec cette bascule

- `ReponseInscription` reste strictement immuable (aucune vue de
  modification, public ou admin) — ce n'est pas prévu de changer.
- La validation d'une candidature en compte réel (`admin_valider_eleve`)
  reste un geste humain explicite dans tous les cas, y compris pour une
  candidature créée par l'ajout manuel Directeur/مشرف (choix délibéré,
  voir le commit de l'Étape 7 — pas de validation automatique en un clic).
