from django.db import migrations


def dupliquer_creneaux_partages(apps, schema_editor):
    """Chantier « fusion horaire/groupe » du 2026-09-04 : décision explicite
    du client — chaque Groupe a désormais SON PROPRE Creneau, jamais partagé
    avec un autre (courses/views.py groupe_ajouter/groupe_modifier n'en
    créent plus jamais qu'un privé par groupe, dès ce chantier). Pour les
    données déjà en place où plusieurs Groupe pointaient vers le MÊME
    Creneau (cas normal avant ce chantier — voir l'ancien écran « الحلقات »),
    le 1er groupe (id le plus petit) garde le Creneau original, chaque AUTRE
    groupe reçoit une copie indépendante (mêmes champs + mêmes CreneauSlot).
    Aucune perte de données : mêmes horaires, juste dépliés en autant de
    lignes que de groupes concernés. Migration à sens unique (reverse = noop)
    — refusionner des Creneau après coup n'aurait aucun sens métier."""
    Creneau = apps.get_model('courses', 'Creneau')
    CreneauSlot = apps.get_model('courses', 'CreneauSlot')
    Groupe = apps.get_model('courses', 'Groupe')

    for creneau in Creneau.objects.all():
        groupes = list(Groupe.objects.filter(creneau=creneau).order_by('id'))
        if len(groupes) <= 1:
            continue
        slots = list(
            creneau.slots.order_by('ordre').values('jour', 'heure_debut', 'heure_fin', 'ordre')
        )
        for groupe in groupes[1:]:
            copie = Creneau.objects.create(
                nom=creneau.nom, nom_fr=creneau.nom_fr, nom_en=creneau.nom_en,
                sexe_cible=creneau.sexe_cible, type_seance=creneau.type_seance,
                riwaya=creneau.riwaya, age_min=creneau.age_min, age_max=creneau.age_max,
                est_actif=creneau.est_actif,
            )
            CreneauSlot.objects.bulk_create([
                CreneauSlot(
                    creneau=copie, jour=s['jour'],
                    heure_debut=s['heure_debut'], heure_fin=s['heure_fin'], ordre=s['ordre'],
                )
                for s in slots
            ])
            groupe.creneau = copie
            groupe.save(update_fields=['creneau'])


class Migration(migrations.Migration):

    dependencies = [
        ('courses', '0044_creneau_nom_en_creneau_nom_fr_lienmeet_libelle_en_and_more'),
    ]

    operations = [
        migrations.RunPython(dupliquer_creneaux_partages, migrations.RunPython.noop),
    ]
