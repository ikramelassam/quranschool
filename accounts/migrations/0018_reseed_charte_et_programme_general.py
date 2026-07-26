# Migration de données — Tâche 22, Parties A et B du 2026-07-26.
#
# PARTIE B (bug ميثاق vide) : le contenu structuré de CharteEnseignement était
# vide en base malgré la migration 0013 qui l'avait pourtant correctement
# rempli. Cause identifiée : dashboard.views.mshrif_charte réécrit
# INCONDITIONNELLEMENT chaque champ depuis request.POST.get(champ, '') à
# chaque sauvegarde, sans aucune protection contre une soumission partielle ou
# vide — n'importe quel POST dont un champ serait absent du corps de la
# requête écrase silencieusement ce champ avec une chaîne vide, sans
# confirmation ni trace. Les deux singletons CharteEnseignement ET
# ProgrammeGeneral se sont retrouvés vidés à ~0.15s d'intervalle (voir
# date_modification des deux lignes), ce qui pointe vers un même événement de
# test/soumission plutôt que deux pertes indépendantes. Cette migration ne
# corrige pas la vue elle-même (design existant, hors périmètre demandé) mais
# restaure le contenu réel — copié à l'identique depuis la migration 0013
# (déjà vérifiée fidèle au document Word source
# "ميثاق التدريس في مقرأة زدني علمًا.docx" présent à la racine du projet).
#
# PARTIE A (contenu برنامج العام) : ProgrammeGeneral n'avait jamais eu de
# contenu réel (les champs enfants/adultes ont été ajoutés vides en 0017,
# sans donnée à migrer). Rempli ici avec le contenu fourni par le client.

from django.db import migrations

# ===== ميثاق التدريس — recopié à l'identique depuis 0013_migrer_charte_vers_champs_structures =====

CHARTE_INTRO = (
    "الحمد لله الذي علّم بالقلم، علّم الإنسان ما لم يعلم، وجعل العلم نوراً يهدي به من "
    "يشاء إلى صراطٍ مستقيم، والصلاة والسلام على المعلّم الأول، والقدوة الأكمل، سيّدنا "
    "محمدٍ صلى الله عليه وسلم، وعلى آله وصحبه أجمعين.\n\n"
    "أما بعد،\n"
    "فإنّ التدريس في منصّة زدني علماً ليس مجرّد أداءٍ لمهمةٍ تعليمية، بل هو عبادةٌ يُبتغى "
    "بها وجه الله، ورسالةٌ ربانيةٌ تُسهم في بناء جيلٍ قارئٍ للقرآن، متخلّقٍ بأدب العلم، "
    "عاملٍ بما تعلّم.\n\n"
    "ومن هذا المنطلق، كان لزاماً على كل من تشرف بحمل هذه الأمانة أن يلتزم بميثاقٍ يذكّره "
    "بمقاصد التعليم الشرعي، ويربط عمله بالنية الصادقة، والإتقان، والرحمة بالمتعلمين، "
    "امتثالاً لقوله ﷺ: «إنَّ الله يحبُّ إذا عمل أحدكم عملاً أن يُتقنه.»\n\n"
    "فهذا ميثاق التدريس في منصّة زدني علماً، نضعه بين أيدي الأساتذة الأفاضل؛ ليكون عهدَ "
    "صدقٍ بينهم وبين ربهم أولاً، ثم بينهم وبين طلابهم، في أداء الأمانة، ونشر العلم، وبذل "
    "النصح، وإحياء أثر القرآن في القلوب والسلوك.\n\n"
    "نسأل الله أن يبارك في هذا الجهد، وأن يجعله خالصاً لوجهه الكريم، وأن يرزقنا الإخلاص "
    "في القول والعمل، والتعليم والتعلم."
)

CHARTE_VERSET_OUVERTURE = "﴿ وَقُل رَّبِّ زِدْنِي عِلْمًا ﴾"

CHARTE_TITRE_BUNUD = "بنود ميثاق التدريس في مقرأة زدني علماً للقرآن الكريم"

CHARTE_SECTION1_TITRE = "المجال العلمي"
CHARTE_SECTION1_INTRO = "حرصًا على تحقيق المقاصد القرآنية والتعليمية في مقرأة زدني علماً، يلتزم الأستاذ في المجال العلمي بما يلي:"
CHARTE_SECTION1_ITEMS = "\n".join([
    "تصحيح اللحن الجلي والخفي: الحرص على متابعة تلاوة الطلاب وتصحيح أخطائهم بدقة، مع مراعاة التدرج المناسب لمستوياتهم، حتى لا ينتقل الطالب من آية إلى أخرى إلا بعد إتقانها.",
    "الشرح النظري لقواعد التجويد: تخصيص وقتٍ خلال الحصة لشرح القواعد النظرية للتجويد، بأسلوبٍ مبسطٍ ومناسبٍ لمستوى الطلاب، وربطها بالتطبيق العملي في التلاوة.",
    "متابعة التقدم العلمي للطلاب: الحرص على الارتقاء بمستوى الطلاب من الجانبين النظري والتطبيقي، مع ملاحظة تطور أدائهم، وتشجيعهم على الاستمرار والتحسين المستمر.",
    "تعاهد المراجعة: حث الطلاب على المراجعة المنتظمة لما سبق دراسته من السور والآيات، لضمان ثبات الحفظ وجودة الأداء، وتوضيح أثر المراجعة في تثبيت العلم والعمل به.",
])

CHARTE_SECTION2_TITRE = "المجال الإداري"
CHARTE_SECTION2_INTRO = "حرصًا على انتظام العمل وجودة الأداء في مقرأة زدني علماً، يلتزم الأستاذ في الجانب الإداري بما يلي:"
CHARTE_SECTION2_ITEMS = "\n".join([
    "الانضباط الزمني للحصة: الحرص على استيفاء وقت الحصة كاملاً (مدة لا تقل عن ساعة ونصف)، وذلك بالدخول إلى الحلقة مع بدايتها، وعدم مغادرتها إلا بعد انتهائها، حفاظًا على حق الطلاب واستثمارًا كاملاً لوقت التعليم.",
    "التفاعل مع إدارة المقرأة: الالتزام بالتجاوب الفعّال مع توجيهات الإدارة، ومتابعة الإعلانات والتنبيهات الصادرة عنها، وحثّ الطلاب على الالتزام بها، تعزيزًا لروح التعاون والتنظيم داخل المنصة.",
    "استيفاء التسميع لجميع الطلاب: العناية بتسميع جميع الطلاب خلال الحصة بقدر الإمكان، وضبط تتابع الأدوار بما يضمن العدالة في المتابعة، وتحقيق الإفادة العلمية لكل مشارك.",
])

CHARTE_SECTION3_TITRE = "المجال التربوي"
CHARTE_SECTION3_INTRO = "انطلاقًا من رسالة مقرأة زدني علماً في غرس القيم القرآنية والتزكية الإيمانية، يلتزم الأستاذ في المجال التربوي بما يلي:"
CHARTE_SECTION3_ITEMS = "\n".join([
    "تحبيب القرآن للطلاب: غرس محبة كتاب الله في قلوب الطلاب من خلال الوعظ والتذكير بفضله، وتعظيم شأنه، وربطهم به تلاوةً وتدبّراً وعملاً.",
    "إيقاد الهمة والتنافس: بث روح الهمة العالية، وإحياء التنافس الشريف بين الطلاب في الحفظ والإتقان والمراجعة، بما يحفّزهم على التقدّم والمثابرة.",
    "تفقد أحوال الطلاب: الحرص على تفقد الطالب الغائب بعد الحصة، بالسؤال عنه أو التواصل الودّي معه، توطيدًا للعلاقة بين الأستاذ وتلاميذه، وتنميةً لروح الأخوّة والمودّة.",
    "التحلي بالأخلاق الحسنة: حث الطلاب على التخلّق بالأدب والحياء، والتحذير من الأخلاق المذمومة التي لا تليق بحامل القرآن، ليكون الطالب قدوة في سلوكه كما هو في تلاوته.",
    "الرفق في الخطاب والتعامل: تجنّب أي أسلوبٍ سلبي أو جافّ في مخاطبة الطلاب، مع استحضار توجيه الله تعالى لنبيّه ﷺ في قوله:",
])
CHARTE_VERSET_RAHMA_TEXTE = (
    "﴿ فَبِمَا رَحْمَةٍ مِّنَ اللَّهِ لِنتَ لَهُمْ ۖ وَلَوْ كُنتَ فَظًّا غَلِيظَ الْقَلْبِ لَانفَضُّوا مِنْ "
    "حَوْلِكَ ۖ فَاعْفُ عَنْهُمْ وَاسْتَغْفِرْ لَهُمْ وَشَاوِرْهُمْ فِي الْأَمْرِ ۖ فَإِذَا عَزَمْتَ فَتَوَكَّلْ "
    "عَلَى اللَّهِ ۚ إِنَّ اللَّهَ يُحِبُّ الْمُتَوَكِّلِينَ ﴾"
)
CHARTE_VERSET_RAHMA_REFERENCE = "(سورة آل عمران: 159)"
CHARTE_SECTION3_CONCLUSION = "اقتداءً بهديه ﷺ في اللين والرحمة، وإيصال العلم بلطفٍ وحكمةٍ ومحبّةٍ صادقة."

CHARTE_SECTION4_TITRE = "المجال التقني"
CHARTE_SECTION4_INTRO = "حرصًا على جودة التواصل وحُسن الأداء في بيئة التعليم عن بُعد بمقرأة زدني علماً، يلتزم الأستاذ في المجال التقني بما يلي:"
CHARTE_SECTION4_ITEMS = "\n".join([
    "وضوح الصوت وجودة البيئة التعليمية: الحرص على وضوح الصوت أثناء الحصة، وضبط إعدادات الميكروفون، والتأكد من هدوء المكان وخلوّه من الضوضاء أو ما يُشوش على تركيز الطلاب.",
    "التأكد من جودة الاتصال: التحقق من استقرار الاتصال بالإنترنت قبل الدخول إلى الحصة، ومعالجة أي خلل تقني قد يؤثر في سير الدرس وجودة التواصل.",
    "إدخال تقييمات الطلاب: الالتزام بإدخال تقييمات الطلاب بدقة وموضوعية، وفق استمارة تقييم الحصة المعتمدة من الإدارة، بما يعكس المستوى الحقيقي لكل طالب.",
    "الالتزام بالمدة الزمنية للتقييم: إدخال التقييمات خلال مدة لا تتجاوز (24) ساعة بعد انتهاء الحصة، ضمانًا لتحديث البيانات بانتظام وتيسير المتابعة الأكاديمية والإدارية.",
])

CHARTE_SECTION5_TITRE = "الملاحظات وما يترتب عليها"
CHARTE_SECTION5_INTRO = "حرصًا على ترسيخ الانضباط، وضمان جودة الأداء التعليمي والإداري في مقرأة زدني علماً، يعتمد ما يلي من ضوابط تتعلق بالملاحظات التي تُسجّل على الأستاذ، مع ما يترتب عليها من إجراءات تأديبية تدريجية."
CHARTE_SECTION5_NOTE = "⁕ ملاحظة: يُحدَّد مقدار الخصم من الراتب من طرف إدارة المقرأة بحسب أهمية الملاحظة، ومدى تجاوب الأستاذ مع التنبيه أو الإصلاح المطلوب."

CHARTE_SANCTIONS = [
    ("سوء الأدب وعدم احترام المادة القرآنية", "immediate"),
    ("سوء التعامل مع الإدارة أو عدم التفاعل مع توجيهاتها", "immediate"),
    ("عدم تصحيح أخطاء الحفظ", "progressive"),
    ("عدم تصحيح اللحن الجلي أو الخفي", "progressive"),
    ("عدم استيفاء المدة الزمنية المخصصة للحصة", "progressive"),
    ("الاشتغال أثناء الحصة بأمور خارجة عن إطار التدريس", "progressive"),
    ("عدم الحرص على هدوء المكان أثناء الحصة", "progressive"),
    ("عدم تعبئة استمارة تقييم الحصة", "progressive"),
    ("ضعف الشبكة أو الصوت بما يؤثر على سير الحصة", "progressive"),
    ("عدم الالتزام بمنهجية التدريس المعتمدة", "progressive"),
    ("عدم تدريس أحكام التجويد عند توفر الوقت لذلك", "progressive"),
    ("عدم ضبط الحلقة وحسن تسييرها", "progressive"),
    ("تراجع عدد الطلاب في الحلقة بسبب ضعف الأداء أو التواصل", "progressive"),
]

CHARTE_SECTION6_TITRE = "التعويضات المادية مقابل تأطير الحصص"
CHARTE_SECTION6_INTRO = "حرصًا على الإنصاف وتحفيز الأداء المتميز للأستاذ، تعتمد مقرأة زدني علماً ما يلي بخصوص التعويضات المالية:"
CHARTE_SECTION6_ITEMS = "\n".join([
    "التعويض عن الطلاب: يعوض الأستاذ عن كل تلميذ لديه في الحلقة بمبلغ 50 درهمًا كحد أدنى، قابل للزيادة حسب التقييم المحصّل عليه من إدارة المقرأة واستمارات تقييم الحصة.",
    "أثر التهاون على التعويضات: كل تقصير أو تهاون في إدخال التقييمات أو عدم الالتزام بالجودة العلمية والتربوية للحصة ينعكس سلبًا على التعويضات المالية، بما يحفّز الأستاذ على الالتزام بالمستوى المطلوب.",
    "الفترة التجريبية للمؤطرين الجدد: يمر كل مؤطر جديد بفترة تجريبية تمتد لشهر واحد كحد أقصى، وخلال هذه الفترة يتم تقييمه من قبل الإدارة وفق جودة التأطير ومستوى التفاعل مع الطلاب والمنصة. بناءً على نتائج التقييم، تقرر الإدارة ترسيمه أو إعفاءه من العمل.",
])

CHARTE_SECTION7_TITRE = "إدارة الغياب وتعويض الحصص"
CHARTE_SECTION7_INTRO = "حرصًا على انتظام الحصص واستمرارية التعليم بجودة عالية، تضع مقرأة زدني علماً الضوابط التالية لإدارة الغياب وتعويض الحصص:"
CHARTE_SECTION7_ITEMS = "\n".join([
    "الإخبار بالغياب مسبقًا: يجب على المؤطر إبلاغ الإدارة والطلاب بالغياب قبل ست ساعات على الأقل من موعد الحصة، لتسهيل الترتيبات اللازمة.",
    "التعويض عن الحصص الغائبة: يلزم المؤطر بتعويض الحصص التي تغيب عنها، على أن يكون الأستاذ المعوض مؤطرًا مسجلاً في مقرأة زدني علماً.",
    "التعويضات المالية للحصص المعوضة: الحصص التي يتم تعويضها من طرف مؤطر آخر يُستفاد من تعويضاتها المادية، مع خصم التعويض المالي من راتب الأستاذ المعوض عنه.",
    "المدة القصوى للتعويض: يحق للمؤطر أن يُعوض حصصه لمدة طويلة لا تتجاوز شهرًا واحدًا في السنة، على أن يخبر الإدارة قبل أسبوعين على الأقل.",
    "التأخر عن موعد الحصة: يجب إعلام الطلاب بأي تأخر عن موعد الحصة، وعلى من يتكرر معه التأخر دون سبب مشروع أن يخضع لخصم في الراتب.",
    "غياب بدون عذر: كل مؤطر يتغيب بدون عذر وبدون إبلاغ مسبق مرتين خلال الشهر يُعفى من العمل في المقرأة.",
])

# ===== برنامج العام — contenu fourni par le client (Tâche 22, Partie A) =====

PROGRAMME_TITRE_ENFANTS = "برنامج الأطفال"
PROGRAMME_ITEMS_ENFANTS = "\n".join([
    "الحصة الأولى: استظهار + تصحيح التلاوة",
    "الحصة الثانية: مراجعة + درس تربوي",
])

PROGRAMME_TITRE_ADULTES = "برنامج الحصص"
PROGRAMME_ITEMS_ADULTES = "\n".join([
    "الحصة الأولى: استظهار الجديد مع تصحيح التلاوة",
    "الحصة الثانية: مراجعة المحفوظ (بصورة اختبار أو بشكل متتابع) مع درس في مادة التجويد",
    "ملاحظة: يمكن استظهار الجديد لمن لم يستظهر في الحصة الأولى",
])


def reseed(apps, schema_editor):
    CharteEnseignement = apps.get_model('accounts', 'CharteEnseignement')
    CharteSanctionLigne = apps.get_model('accounts', 'CharteSanctionLigne')
    ProgrammeGeneral = apps.get_model('accounts', 'ProgrammeGeneral')

    charte, _ = CharteEnseignement.objects.get_or_create(pk=1)
    charte.intro = CHARTE_INTRO
    charte.verset_ouverture = CHARTE_VERSET_OUVERTURE
    charte.titre_bunud = CHARTE_TITRE_BUNUD

    charte.section1_titre = CHARTE_SECTION1_TITRE
    charte.section1_intro = CHARTE_SECTION1_INTRO
    charte.section1_items = CHARTE_SECTION1_ITEMS

    charte.section2_titre = CHARTE_SECTION2_TITRE
    charte.section2_intro = CHARTE_SECTION2_INTRO
    charte.section2_items = CHARTE_SECTION2_ITEMS

    charte.section3_titre = CHARTE_SECTION3_TITRE
    charte.section3_intro = CHARTE_SECTION3_INTRO
    charte.section3_items = CHARTE_SECTION3_ITEMS
    charte.verset_rahma_texte = CHARTE_VERSET_RAHMA_TEXTE
    charte.verset_rahma_reference = CHARTE_VERSET_RAHMA_REFERENCE
    charte.section3_conclusion = CHARTE_SECTION3_CONCLUSION

    charte.section4_titre = CHARTE_SECTION4_TITRE
    charte.section4_intro = CHARTE_SECTION4_INTRO
    charte.section4_items = CHARTE_SECTION4_ITEMS

    charte.section5_titre = CHARTE_SECTION5_TITRE
    charte.section5_intro = CHARTE_SECTION5_INTRO
    charte.section5_note = CHARTE_SECTION5_NOTE

    charte.section6_titre = CHARTE_SECTION6_TITRE
    charte.section6_intro = CHARTE_SECTION6_INTRO
    charte.section6_items = CHARTE_SECTION6_ITEMS

    charte.section7_titre = CHARTE_SECTION7_TITRE
    charte.section7_intro = CHARTE_SECTION7_INTRO
    charte.section7_items = CHARTE_SECTION7_ITEMS
    charte.save()

    charte.sanctions.all().delete()
    for ordre, (violation, severite) in enumerate(CHARTE_SANCTIONS):
        CharteSanctionLigne.objects.create(
            charte=charte, ordre=ordre, violation=violation, severite=severite,
        )

    programme, _ = ProgrammeGeneral.objects.get_or_create(pk=1)
    programme.titre_enfants = PROGRAMME_TITRE_ENFANTS
    programme.items_enfants = PROGRAMME_ITEMS_ENFANTS
    programme.titre_adultes = PROGRAMME_TITRE_ADULTES
    programme.items_adultes = PROGRAMME_ITEMS_ADULTES
    programme.save()


def inverser(apps, schema_editor):
    # Pas de retour en arrière significatif (retour à l'état vide constaté en bug) — no-op volontaire.
    pass


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0017_programme_general_deux_versions'),
    ]

    operations = [
        migrations.RunPython(reseed, inverser),
    ]
