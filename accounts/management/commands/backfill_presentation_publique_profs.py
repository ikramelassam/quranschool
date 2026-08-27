from django.core.management.base import BaseCommand

from accounts.models import Prof
from accounts.services import generer_presentation_publique


class Command(BaseCommand):
    """Backfill rétroactif de Prof.presentation_publique pour les profs créés
    AVANT le chantier du 2026-08-27 (voir accounts.services.generer_presentation_publique
    et dashboard.views._creer_compte_prof) — ces profs n'ont jamais eu ce champ
    généré automatiquement à la création de leur compte, cette logique n'existant
    pas encore à l'époque.

    Ne touche QUE les profs dont presentation_publique est vide — jamais ceux
    qui ont déjà un texte, qu'il soit auto-généré ou modifié à la main par
    مدير/مشرف (voir dashboard.views.admin_prof_presentation_modifier), même
    principe que chat.migrer_acces_public_pieces_jointes_chat pour un backfill
    rétroactif ponctuel.

    À exécuter une fois, après déploiement de ce chantier :

        python manage.py backfill_presentation_publique_profs
    """
    help = "Régénère Prof.presentation_publique pour les profs existants dont le champ est vide."

    def handle(self, *args, **options):
        profs_vides = Prof.objects.filter(presentation_publique='')
        total = profs_vides.count()
        rempli = 0
        toujours_vide = 0

        for prof in profs_vides:
            texte = generer_presentation_publique(prof)
            if texte:
                prof.presentation_publique = texte
                prof.save(update_fields=['presentation_publique'])
                rempli += 1
            else:
                # Prof sans aucune donnée exploitable (niveau_memorisation,
                # parcours, certifications, langues, préférences toutes vides)
                # — rien à générer, reste vide légitimement.
                toujours_vide += 1

        self.stdout.write(f"{total} prof(s) avaient presentation_publique vide.")
        self.stdout.write(self.style.SUCCESS(f"{rempli} rempli(s) avec succès."))
        if toujours_vide:
            self.stdout.write(self.style.WARNING(
                f"{toujours_vide} resté(s) vide(s) — aucune donnée exploitable pour générer un texte."
            ))
