from django.db import migrations

CONTENU_INITIAL = """
<div style="text-align:center; color:var(--color-text-muted); font-size:0.95rem; line-height:2; margin-bottom:24px;">
<p>الحمد لله الذي علّم بالقلم، علّم الإنسان ما لم يعلم، وجعل العلم نوراً يهدي به من يشاء إلى صراطٍ مستقيم، والصلاة والسلام على المعلّم الأول، والقدوة الأكمل، سيّدنا محمدٍ صلى الله عليه وسلم، وعلى آله وصحبه أجمعين.</p>
<p>أما بعد،<br>
فإنّ التدريس في منصّة زدني علماً ليس مجرّد أداءٍ لمهمةٍ تعليمية، بل هو عبادةٌ يُبتغى بها وجه الله، ورسالةٌ ربانيةٌ تُسهم في بناء جيلٍ قارئٍ للقرآن، متخلّقٍ بأدب العلم، عاملٍ بما تعلّم.</p>
<p>ومن هذا المنطلق، كان لزاماً على كل من تشرف بحمل هذه الأمانة أن يلتزم بميثاقٍ يذكّره بمقاصد التعليم الشرعي، ويربط عمله بالنية الصادقة، والإتقان، والرحمة بالمتعلمين، امتثالاً لقوله ﷺ: «إنَّ الله يحبُّ إذا عمل أحدكم عملاً أن يُتقنه.»</p>
<p>فهذا ميثاق التدريس في منصّة زدني علماً، نضعه بين أيدي الأساتذة الأفاضل؛ ليكون عهدَ صدقٍ بينهم وبين ربهم أولاً، ثم بينهم وبين طلابهم، في أداء الأمانة، ونشر العلم، وبذل النصح، وإحياء أثر القرآن في القلوب والسلوك.</p>
<p>نسأل الله أن يبارك في هذا الجهد، وأن يجعله خالصاً لوجهه الكريم، وأن يرزقنا الإخلاص في القول والعمل، والتعليم والتعلم.</p>
</div>

<div style="text-align:center; color:var(--color-brand-gold-dark); font-weight:700; font-size:1.15rem; margin:24px 0; padding:16px; background:var(--color-bg-cream); border-radius:10px;">
﴿ وَقُل رَّبِّ زِدْنِي عِلْمًا ﴾
</div>

<h3 style="color:var(--color-text-primary); border-bottom:2px solid var(--color-brand-gold); padding-bottom:8px; margin:32px 0 16px;">بنود ميثاق التدريس في مقرأة زدني علماً للقرآن الكريم</h3>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">أولاً: المجال العلمي</h3>
<p>حرصًا على تحقيق المقاصد القرآنية والتعليمية في مقرأة زدني علماً، يلتزم الأستاذ في المجال العلمي بما يلي:</p>
<ul style="padding-right:20px; line-height:1.9;">
<li><strong>تصحيح اللحن الجلي والخفي:</strong> الحرص على متابعة تلاوة الطلاب وتصحيح أخطائهم بدقة، مع مراعاة التدرج المناسب لمستوياتهم، حتى لا ينتقل الطالب من آية إلى أخرى إلا بعد إتقانها.</li>
<li><strong>الشرح النظري لقواعد التجويد:</strong> تخصيص وقتٍ خلال الحصة لشرح القواعد النظرية للتجويد، بأسلوبٍ مبسطٍ ومناسبٍ لمستوى الطلاب، وربطها بالتطبيق العملي في التلاوة.</li>
<li><strong>متابعة التقدم العلمي للطلاب:</strong> الحرص على الارتقاء بمستوى الطلاب من الجانبين النظري والتطبيقي، مع ملاحظة تطور أدائهم، وتشجيعهم على الاستمرار والتحسين المستمر.</li>
<li><strong>تعاهد المراجعة:</strong> حث الطلاب على المراجعة المنتظمة لما سبق دراسته من السور والآيات، لضمان ثبات الحفظ وجودة الأداء، وتوضيح أثر المراجعة في تثبيت العلم والعمل به.</li>
</ul>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">ثانياً: المجال الإداري</h3>
<p>حرصًا على انتظام العمل وجودة الأداء في مقرأة زدني علماً، يلتزم الأستاذ في الجانب الإداري بما يلي:</p>
<ul style="padding-right:20px; line-height:1.9;">
<li><strong>الانضباط الزمني للحصة:</strong> الحرص على استيفاء وقت الحصة كاملاً (مدة لا تقل عن ساعة ونصف)، وذلك بالدخول إلى الحلقة مع بدايتها، وعدم مغادرتها إلا بعد انتهائها، حفاظًا على حق الطلاب واستثمارًا كاملاً لوقت التعليم.</li>
<li><strong>التفاعل مع إدارة المقرأة:</strong> الالتزام بالتجاوب الفعّال مع توجيهات الإدارة، ومتابعة الإعلانات والتنبيهات الصادرة عنها، وحثّ الطلاب على الالتزام بها، تعزيزًا لروح التعاون والتنظيم داخل المنصة.</li>
<li><strong>استيفاء التسميع لجميع الطلاب:</strong> العناية بتسميع جميع الطلاب خلال الحصة بقدر الإمكان، وضبط تتابع الأدوار بما يضمن العدالة في المتابعة، وتحقيق الإفادة العلمية لكل مشارك.</li>
</ul>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">ثالثاً: المجال التربوي</h3>
<p>انطلاقًا من رسالة مقرأة زدني علماً في غرس القيم القرآنية والتزكية الإيمانية، يلتزم الأستاذ في المجال التربوي بما يلي:</p>
<ul style="padding-right:20px; line-height:1.9;">
<li><strong>تحبيب القرآن للطلاب:</strong> غرس محبة كتاب الله في قلوب الطلاب من خلال الوعظ والتذكير بفضله، وتعظيم شأنه، وربطهم به تلاوةً وتدبّراً وعملاً.</li>
<li><strong>إيقاد الهمة والتنافس:</strong> بث روح الهمة العالية، وإحياء التنافس الشريف بين الطلاب في الحفظ والإتقان والمراجعة، بما يحفّزهم على التقدّم والمثابرة.</li>
<li><strong>تفقد أحوال الطلاب:</strong> الحرص على تفقد الطالب الغائب بعد الحصة، بالسؤال عنه أو التواصل الودّي معه، توطيدًا للعلاقة بين الأستاذ وتلاميذه، وتنميةً لروح الأخوّة والمودّة.</li>
<li><strong>التحلي بالأخلاق الحسنة:</strong> حث الطلاب على التخلّق بالأدب والحياء، والتحذير من الأخلاق المذمومة التي لا تليق بحامل القرآن، ليكون الطالب قدوة في سلوكه كما هو في تلاوته.</li>
<li><strong>الرفق في الخطاب والتعامل:</strong> تجنّب أي أسلوبٍ سلبي أو جافّ في مخاطبة الطلاب، مع استحضار توجيه الله تعالى لنبيّه ﷺ في قوله:</li>
</ul>
<div style="text-align:center; color:var(--color-brand-gold-dark); font-weight:600; font-size:1.05rem; margin:16px 0; padding:16px; background:var(--color-bg-cream); border-radius:10px; line-height:2;">
﴿ فَبِمَا رَحْمَةٍ مِّنَ اللَّهِ لِنتَ لَهُمْ ۖ وَلَوْ كُنتَ فَظًّا غَلِيظَ الْقَلْبِ لَانفَضُّوا مِنْ حَوْلِكَ ۖ فَاعْفُ عَنْهُمْ وَاسْتَغْفِرْ لَهُمْ وَشَاوِرْهُمْ فِي الْأَمْرِ ۖ فَإِذَا عَزَمْتَ فَتَوَكَّلْ عَلَى اللَّهِ ۚ إِنَّ اللَّهَ يُحِبُّ الْمُتَوَكِّلِينَ ﴾
<div style="font-size:0.8rem; color:var(--color-text-muted); margin-top:6px;">(سورة آل عمران: 159)</div>
</div>
<p>اقتداءً بهديه ﷺ في اللين والرحمة، وإيصال العلم بلطفٍ وحكمةٍ ومحبّةٍ صادقة.</p>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">رابعاً: المجال التقني</h3>
<p>حرصًا على جودة التواصل وحُسن الأداء في بيئة التعليم عن بُعد بمقرأة زدني علماً، يلتزم الأستاذ في المجال التقني بما يلي:</p>
<ul style="padding-right:20px; line-height:1.9;">
<li><strong>وضوح الصوت وجودة البيئة التعليمية:</strong> الحرص على وضوح الصوت أثناء الحصة، وضبط إعدادات الميكروفون، والتأكد من هدوء المكان وخلوّه من الضوضاء أو ما يُشوش على تركيز الطلاب.</li>
<li><strong>التأكد من جودة الاتصال:</strong> التحقق من استقرار الاتصال بالإنترنت قبل الدخول إلى الحصة، ومعالجة أي خلل تقني قد يؤثر في سير الدرس وجودة التواصل.</li>
<li><strong>إدخال تقييمات الطلاب:</strong> الالتزام بإدخال تقييمات الطلاب بدقة وموضوعية، وفق استمارة تقييم الحصة المعتمدة من الإدارة، بما يعكس المستوى الحقيقي لكل طالب.</li>
<li><strong>الالتزام بالمدة الزمنية للتقييم:</strong> إدخال التقييمات خلال مدة لا تتجاوز (24) ساعة بعد انتهاء الحصة، ضمانًا لتحديث البيانات بانتظام وتيسير المتابعة الأكاديمية والإدارية.</li>
</ul>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">خامساً: الملاحظات وما يترتب عليها</h3>
<p>حرصًا على ترسيخ الانضباط، وضمان جودة الأداء التعليمي والإداري في مقرأة زدني علماً، يعتمد ما يلي من ضوابط تتعلق بالملاحظات التي تُسجّل على الأستاذ، مع ما يترتب عليها من إجراءات تأديبية تدريجية.</p>
<div style="overflow-x:auto; margin:16px 0;">
<table style="width:100%; border-collapse:collapse; font-size:0.92rem;">
<thead>
<tr style="background:var(--color-brand-gold-dark); color:white;">
<th style="padding:10px 14px; text-align:right;">المخالفة</th>
<th style="padding:10px 14px; text-align:center;">الإجراء الأول</th>
<th style="padding:10px 14px; text-align:center;">الإجراء الثاني</th>
<th style="padding:10px 14px; text-align:center;">الإجراء الثالث</th>
</tr>
</thead>
<tbody>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">سوء الأدب وعدم احترام المادة القرآنية</td><td style="padding:10px 14px; text-align:center;" colspan="3">الإعفاء الفوري</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">سوء التعامل مع الإدارة أو عدم التفاعل مع توجيهاتها</td><td style="padding:10px 14px; text-align:center;" colspan="3">الإعفاء الفوري</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم تصحيح أخطاء الحفظ</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم تصحيح اللحن الجلي أو الخفي</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم استيفاء المدة الزمنية المخصصة للحصة</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">الاشتغال أثناء الحصة بأمور خارجة عن إطار التدريس</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم الحرص على هدوء المكان أثناء الحصة</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم تعبئة استمارة تقييم الحصة</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">ضعف الشبكة أو الصوت بما يؤثر على سير الحصة</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم الالتزام بمنهجية التدريس المعتمدة</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم تدريس أحكام التجويد عند توفر الوقت لذلك</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr style="border-bottom:1px solid #eee;"><td style="padding:10px 14px;">عدم ضبط الحلقة وحسن تسييرها</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
<tr><td style="padding:10px 14px;">تراجع عدد الطلاب في الحلقة بسبب ضعف الأداء أو التواصل</td><td style="padding:10px 14px; text-align:center;">الإنذار الأول</td><td style="padding:10px 14px; text-align:center;">الإنذار الثاني</td><td style="padding:10px 14px; text-align:center;">خصم من الراتب</td></tr>
</tbody>
</table>
</div>
<p style="font-size:0.85rem; color:var(--color-text-muted);">⁕ ملاحظة: يُحدَّد مقدار الخصم من الراتب من طرف إدارة المقرأة بحسب أهمية الملاحظة، ومدى تجاوب الأستاذ مع التنبيه أو الإصلاح المطلوب.</p>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">التعويضات المادية مقابل تأطير الحصص</h3>
<p>حرصًا على الإنصاف وتحفيز الأداء المتميز للأستاذ، تعتمد مقرأة زدني علماً ما يلي بخصوص التعويضات المالية:</p>
<ul style="padding-right:20px; line-height:1.9;">
<li><strong>التعويض عن الطلاب:</strong> يعوض الأستاذ عن كل تلميذ لديه في الحلقة بمبلغ 50 درهمًا كحد أدنى، قابل للزيادة حسب التقييم المحصّل عليه من إدارة المقرأة واستمارات تقييم الحصة.</li>
<li><strong>أثر التهاون على التعويضات:</strong> كل تقصير أو تهاون في إدخال التقييمات أو عدم الالتزام بالجودة العلمية والتربوية للحصة ينعكس سلبًا على التعويضات المالية، بما يحفّز الأستاذ على الالتزام بالمستوى المطلوب.</li>
<li><strong>الفترة التجريبية للمؤطرين الجدد:</strong> يمر كل مؤطر جديد بفترة تجريبية تمتد لشهر واحد كحد أقصى، وخلال هذه الفترة يتم تقييمه من قبل الإدارة وفق جودة التأطير ومستوى التفاعل مع الطلاب والمنصة. بناءً على نتائج التقييم، تقرر الإدارة ترسيمه أو إعفاءه من العمل.</li>
</ul>

<h3 style="color:var(--color-brand-gold-dark); margin:28px 0 10px;">إدارة الغياب وتعويض الحصص</h3>
<p>حرصًا على انتظام الحصص واستمرارية التعليم بجودة عالية، تضع مقرأة زدني علماً الضوابط التالية لإدارة الغياب وتعويض الحصص:</p>
<ul style="padding-right:20px; line-height:1.9;">
<li><strong>الإخبار بالغياب مسبقًا:</strong> يجب على المؤطر إبلاغ الإدارة والطلاب بالغياب قبل ست ساعات على الأقل من موعد الحصة، لتسهيل الترتيبات اللازمة.</li>
<li><strong>التعويض عن الحصص الغائبة:</strong> يلزم المؤطر بتعويض الحصص التي تغيب عنها، على أن يكون الأستاذ المعوض مؤطرًا مسجلاً في مقرأة زدني علماً.</li>
<li><strong>التعويضات المالية للحصص المعوضة:</strong> الحصص التي يتم تعويضها من طرف مؤطر آخر يُستفاد من تعويضاتها المادية، مع خصم التعويض المالي من راتب الأستاذ المعوض عنه.</li>
<li><strong>المدة القصوى للتعويض:</strong> يحق للمؤطر أن يُعوض حصصه لمدة طويلة لا تتجاوز شهرًا واحدًا في السنة، على أن يخبر الإدارة قبل أسبوعين على الأقل.</li>
<li><strong>التأخر عن موعد الحصة:</strong> يجب إعلام الطلاب بأي تأخر عن موعد الحصة، وعلى من يتكرر معه التأخر دون سبب مشروع أن يخضع لخصم في الراتب.</li>
<li><strong>غياب بدون عذر:</strong> كل مؤطر يتغيب بدون عذر وبدون إبلاغ مسبق مرتين خلال الشهر يُعفى من العمل في المقرأة.</li>
</ul>
"""


def seed_charte(apps, schema_editor):
    CharteEnseignement = apps.get_model('accounts', 'CharteEnseignement')
    CharteEnseignement.objects.get_or_create(pk=1, defaults={'contenu': CONTENU_INITIAL})


def reverse_seed_charte(apps, schema_editor):
    CharteEnseignement = apps.get_model('accounts', 'CharteEnseignement')
    CharteEnseignement.objects.filter(pk=1).delete()


class Migration(migrations.Migration):

    dependencies = [
        ('accounts', '0010_charteenseignement_prof_charte_acceptee_and_more'),
    ]

    operations = [
        migrations.RunPython(seed_charte, reverse_seed_charte),
    ]
