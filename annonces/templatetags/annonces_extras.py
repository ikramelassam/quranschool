from django import template

register = template.Library()


@register.filter
def taille_lisible(taille_octets):
    """1536 -> '1.5 ك.ب', 3_145_728 -> '3.0 م.ب' — carte document d'une
    publication. Dupliqué de chat.templatetags (même logique, volontairement
    pas importé : les 2 apps restent indépendantes, voir annonces.services)."""
    if not taille_octets:
        return ''
    taille_octets = float(taille_octets)
    if taille_octets < 1024:
        return f'{int(taille_octets)} بايت'
    if taille_octets < 1024 * 1024:
        return f'{taille_octets / 1024:.1f} ك.ب'
    return f'{taille_octets / (1024 * 1024):.1f} م.ب'


@register.filter
def get_item(dictionnaire, cle):
    """Lookup par clé dynamique dans un dict — la syntaxe {{ dict.cle }} de
    Django ne résout que des clés LITTÉRALES, jamais la valeur d'une variable
    de boucle. Utilisé par templates/examens/passage.html (app examens) —
    NE PAS supprimer même si annonces/ ne s'en sert plus directement."""
    if dictionnaire is None:
        return None
    return dictionnaire.get(cle)


@register.filter
def canal_nom(code_cible):
    """Nom d'affichage du canal (ex: 'femmes_adultes' -> 'النساء') — pour le
    badge de canal dans le flux "آخر النشاط عبر القنوات" (admin_annonces.html).
    Renvoie le code tel quel si inconnu plutôt qu'une chaîne vide, pour ne
    jamais masquer silencieusement un problème de données."""
    from annonces.services import canal_pour_code
    canal = canal_pour_code(code_cible)
    return canal['nom'] if canal else code_cible
