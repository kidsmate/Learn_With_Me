#!/usr/bin/env python3
"""HTTP server with PDF TOC extraction API"""
import http.server
import json
import os
import re
import io
import unicodedata
from urllib.parse import unquote

# PyMuPDF 兼容导入：新版推荐 pymupdf，旧版用 fitz
try:
    import pymupdf as fitz
except ImportError:
    try:
        import fitz
    except ImportError:
        fitz = None

PORT = 8080
ROOT = os.path.dirname(os.path.abspath(__file__))


def _normalize_text(text):
    """归一化文本：全角数字→半角，全角空格→半角，兼容 PDF 排版差异。

    PDF 教材中常出现全角数字（如 ２３４５６７８９０），
    导致正则 [0-9] 无法匹配。NFKC 归一化将其转为 ASCII。
    """
    return unicodedata.normalize('NFKC', text)

# 印刷页码检测：教材每页底部通常有印刷页码（如 "2"、"14"）
# 用于目录页双栏布局的页码配对（通过 y 坐标与左栏标题配对）
PAGE_NUM_RE = re.compile(r'^[\s\-—]*(\d{1,3})[\s\-—]*$')

# ===== 英语教材表格式目录支持 =====
# 圈码字符：➊-➓(1-10), ⓫-⓴(11-20)
CIRCLED_NUMS = '➊➋➌➍➎➏➐➑➒➓⓫⓬⓭⓮⓯⓰⓱⓲⓳⓴'
# 英语目录页码引用模式（如 "Page S1"、"Page 5"）
PAGE_REF_RE = re.compile(r'^Page\s+(S?\d+)', re.IGNORECASE)


def _circled_to_num(text):
    """圈码字符 → 数字（➊→1, ➋→2, ...），非圈码返回 None。"""
    text = text.strip()
    if len(text) == 1 and text in CIRCLED_NUMS:
        return CIRCLED_NUMS.index(text) + 1
    return None


def _find_starter_page(page_lines, starter_num, total_pages):
    """在 PDF 正文中查找 starter 页码（如 "S1"）对应的 PDF 真实页码。

    英语教材 starter 单元使用独立的 S 页码体系（S1, S2, ...），
    不在常规页码偏移范围内。本函数扫描正文页查找 "S1" 等独立文本行。
    """
    target = f'S{starter_num}'
    for p in sorted(page_lines.keys()):
        for line in page_lines[p]:
            if line['text'].strip() == target:
                return p
    return None

# ===== 学科自适应：不同学科的单元/课文识别规则 =====
# 每种学科一套 (unit_re, lesson_re, group_kws, name)
# 注意：subject key 与前端 js/data.js 中的 subject.id 保持一致
#   - chinese  -> 语文
#   - math     -> 数学
#   - english  -> 英语
#   - history  -> 历史
#   - morality -> 道德与法治（前端 id 为 morality，故服务端也用 morality）
SUBJECT_RULES = {
    'chinese': {
        # 第X单元 → 1 春 / 3* 雨的四季 / 写作… / 综合性学习…
        # OCR 容错：单元可能被误读为"里元"/"丫元"/"二单元"等，
        # 所以只要求"第"+数字+任意一字符+"元"的模式
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*\S?元'),
        'lesson_re': re.compile(r'^\d+\*?\s*[.．、]?\s*\S'),
        'group_kws': ['写作', '综合性学习', '名著导读', '课外古诗词诵读', '课外古诗词',
                      '口语交际', '活动·探究', '活动探究', '任务', '汉语知识', '语法知识',
                      '阅读综合实践'],
        'name': '语文',
    },
    'math': {
        # 第X章 → 1.1 正数和负数 / 1.2.1 数轴 / 阅读与思考…
        'unit_re': re.compile(r'第[一二三四五六七八九十百零〇两0-9]+章'),
        # 1.1 / 1.2.1 / 1.2.3 三级编号都算课文；不要求编号后必跟非空白，
        # 因为目录中可能出现 "1.1正数和负数" 这样无空格的写法
        'lesson_re': re.compile(r'^\d+(?:\.\d+){1,2}\s*\S?'),
        # 数学的栏目（与正文并列的扩展模块）
        'group_kws': ['阅读与思考', '实验与探究', '观察与猜想', '观察与思考',
                      '信息技术应用', '数学活动', '小结', '复习题', '习题',
                      '课题学习', '归纳与复习', '部分中英文词汇索引', '内容介绍'],
        'name': '数学',
    },
    'english': {
        # Unit N / Starter Unit N / 圈码（➊➋➌，表格式目录单元标识）
        # 注意：去掉 ^ 前缀，使 findall 在整页文本中也能匹配
        'unit_re': re.compile(r'(?:Starter\s+)?Unit\s*\d+|[' + CIRCLED_NUMS + ']', re.IGNORECASE),
        # 课文：Section A / Section B / Section B 1a-1d（编号子篇目）
        'lesson_re': re.compile(r'^Section\s*[AB]', re.IGNORECASE),
        # 栏目关键词（含表格式目录列标题）
        'group_kws': ['Pronunciation', 'Grammar Focus', 'Project', 'Self Check',
                      'Reading', 'Writing', 'Listening', 'Speaking', 'Vocabulary',
                      'Words and Expressions', 'Functions', 'Strategy', 'Study skills',
                      'Notes on the Text', 'Tapescripts', 'Name List',
                      'Vocabulary Index', '不规则动词', '听力材料', 'Just for Fun',
                      'Topics', 'Letters and Structures', 'Starter Units'],
        'name': '英语',
    },
    'history': {
        # 第X单元 → 第N课 标题 / 活动课
        # 注意：PDF 提取可能出现 "第 1 课"（数字前后有空格），用 \s* 兼容
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*单元'),
        # 第1课 / 第十课 / 第21课 + 至少一个非空白字符（标题）
        'lesson_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*课\s*\S'),
        'group_kws': ['活动课', '单元综合', '学史方法', '课后活动',
                      '知识梳理', '单元总结', '附录', '大事年表', '知识拓展',
                      '相关史事', '材料研读', '问题思考'],
        'name': '历史',
    },
    'morality': {
        # 道德与法治：第X单元 → 第N课 标题 → 子篇目（无编号短标题）
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*单元'),
        # 第一课 / 第10课 等
        'lesson_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*课\s*\S'),
        # 栏目：单元思考与行动、相关链接、阅读感悟、方法与技能、探究与分享、拓展空间
        'group_kws': ['单元思考与行动', '相关链接', '阅读感悟', '方法与技能',
                      '探究与分享', '拓展空间', '学史方法', '生活观察',
                      '方法与技能', '相关链接'],
        'name': '道德与法治',
    },
    'geography': {
        # 人教版地理：第X章 → 第X节 标题
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*章'),
        # 第一节 / 第2节 等
        'lesson_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*节\s*\S'),
        # 栏目：阅读、活动、拓展、探索、链接
        'group_kws': ['阅读', '活动', '拓展', '探索', '链接', '知识之窗',
                      '本章小结', '参考资料', '想一想', '读图', '阅读材料',
                      '附录', '地理热点', '专题'],
        'name': '地理',
    },
    'biology': {
        # 人教版生物：单元X → 第X章 → 第X节
        # 单元标题如 "第二单元 生物体的结构层次"
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*单元'),
        # 第一节 / 第2节 等（章节标题）
        'lesson_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*[章节]\s*\S'),
        # 栏目：观察与思考、课外实践、科学·技术·社会、技能训练、资料分析、模拟实验
        'group_kws': ['观察与思考', '课外实践', '科学·技术·社会', '技能训练',
                      '资料分析', '模拟实验', '生物学与文学', '探究',
                      '实验', '调查', '设计', '分析', '表达交流', '演示',
                      '想一想', '讨论', '本章小结', '单元小结', '附录',
                      '课外读', '科学·技术·社会·环境'],
        'name': '生物',
    },
    'physics': {
        # 人教版物理：第X章 → 第X节 标题
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*章'),
        # 第一节 / 第2节 等
        'lesson_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*节\s*\S'),
        # 栏目：阅读、科学世界、动手动脑学物理、想想做做、想想议议、STS
        'group_kws': ['阅读', '科学世界', '动手动脑学物理', '想想做做', '想想议议',
                      'STS', '科学技术社会', '科学技术 社会', '扩展性实验',
                      '物理学史', '本章小结', '学到了什么', '附录', '索引'],
        'name': '物理',
    },
    'chemistry': {
        # 人教版化学：单元X → 课题X 标题（注意：化学用"单元"而非"章"）
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*单元'),
        # 课题1 / 课题2 等
        'lesson_re': re.compile(r'课题\s*[一二三四五六七八九十百零〇两0-9]+\s*\S'),
        # 栏目：实验活动、拓展性课题、调查与研究、化学·技术·社会、练习与应用
        'group_kws': ['实验活动', '拓展性课题', '调查与研究', '化学·技术·社会',
                      '练习与应用', '化学与生活', '习题', '课外实验',
                      '本章小结', '单元小结', '附录', '元素周期表', '索引'],
        'name': '化学',
    },
    'pe': {
        # 体育与健康：第X章 → 第X节 标题
        'unit_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*章'),
        # 第一节 / 第2节 等
        'lesson_re': re.compile(r'第\s*[一二三四五六七八九十百零〇两0-9]+\s*节\s*\S'),
        # 栏目：思考与练习、拓展、链接、活动建议、知识窗
        'group_kws': ['思考与练习', '拓展', '链接', '活动建议', '知识窗',
                      '阅读', '本章小结', '附录', '相关资料', '评价',
                      '体育明星', '运动与健康', '安全提示'],
        'name': '体育',
    },
}

# 学科识别关键词（按页扫描，统计每套规则命中数，取最高）
SUBJECT_DETECT_KEYWORDS = {
    'chinese': ['语文', '课文', '生字', '识字', '写字', '综合性学习', '名著导读',
                '课外古诗词', '口语交际', '写作', '阅读综合实践'],
    'math': ['数学', '例题', '练习', '习题', '定理', '公理', '几何', '代数', '函数', '方程',
             '有理数', '整式', '一元一次', '阅读与思考', '实验与探究', '数学活动',
             '小结', '复习题', '正数和负数', '数轴', '绝对值'],
    'english': ['English', 'Listening', 'Speaking', 'Reading', 'Section', 'Grammar',
                'Pronunciation', 'Vocabulary', 'Unit', 'Project', 'Words', 'Name List',
                'Self Check', 'Grammar Focus'],
    'history': ['历史', '朝代', '皇帝', '秦朝', '汉代', '汉朝', '唐代', '唐朝',
                '宋代', '宋朝', '元代', '元朝', '明代', '明朝', '清代', '清朝',
                '第1课', '第2课', '第3课', '活动课', '单元综合', '学史方法', '大事年表',
                '北京人', '半坡', '河姆渡', '夏商周', '春秋', '战国', '秦汉',
                '三国', '南北朝', '隋唐', '甲骨文', '青铜器', '分封制', '丝绸之路'],
    'morality': ['道德', '法治', '宪法', '公民', '权利', '义务', '国家', '法律', '品德',
                 '中学时代', '学习新天地', '友谊', '师生', '亲情', '生命',
                 '单元思考与行动', '相关链接', '阅读感悟', '探究与分享', '拓展空间'],
    'geography': ['地理', '地图', '经度', '纬度', '经纬', '地球', '大洲', '大洋',
                  '气候', '地形', '河流', '聚落', '区域', '亚洲', '欧洲', '非洲',
                  '美洲', '南极洲', '北冰洋', '太平洋', '大西洋', '印度洋',
                  '经线', '纬线', '赤道', '本初子午线', '时区', '海拔', '等高线',
                  '人口', '人种', '语言', '宗教', '国家', '城市化', '可持续发展',
                  '第一/二/三产业', '畜牧业', '林业', '渔业', '工业', '旅游业',
                  '地形图', '比例尺', '图例', '指向标', '海拔', '相对高度'],
    'biology': ['生物', '细胞', '组织', '器官', '系统', '细胞膜', '细胞核', '细胞质',
                '细胞壁', '液泡', '叶绿体', '线粒体', '光合作用', '呼吸作用',
                '蒸腾作用', '种子', '根', '茎', '叶', '花', '果实', '导管', '筛管',
                '动物', '植物', '微生物', '病毒', '细菌', '真菌', '生态系统',
                '生产者', '消费者', '分解者', '食物链', '食物网', '生物圈',
                '遗传', '变异', '进化', '基因', '染色体', 'DNA', '性状',
                '哺乳动物', '鸟类', '爬行动物', '两栖动物', '鱼类', '昆虫',
                '关节', '骨骼肌', '先天性行为', '学习行为', '社会行为'],
    'physics': ['物理', '力学', '电学', '光学', '热学', '声学', '电磁学',
                '速度', '加速度', '力', '质量', '重力', '摩擦力', '压力', '压强',
                '浮力', '杠杆', '滑轮', '功', '功率', '能', '动能', '势能',
                '电流', '电压', '电阻', '欧姆定律', '电功率', '电功',
                '电荷', '正电荷', '负电荷', '电路', '串联', '并联',
                '磁体', '磁极', '磁场', '磁感线', '电磁感应', '发电机', '电动机',
                '声音', '振动', '回声', '超声波', '次声波',
                '反射', '折射', '透镜', '凸透镜', '凹透镜', '焦距',
                '温度', '熔化', '凝固', '汽化', '液化', '升华', '凝华',
                '内能', '比热容', '热值', '热机', '能量守恒'],
    'chemistry': ['化学', '物质', '元素', '分子', '原子', '离子', '质子', '中子', '电子',
                  '化合价', '化学式', '化学方程式', '反应', '化合反应', '分解反应',
                  '置换反应', '复分解反应', '氧化反应', '还原反应',
                  '溶液', '溶质', '溶剂', '饱和溶液', '溶解度', '质量分数',
                  '酸', '碱', '盐', '氧化物', '指示剂', '石蕊', '酚酞', 'pH',
                  '中和反应', '金属', '合金', '生铁', '钢',
                  '氧气', '二氧化碳', '氢气', '氮气', '稀有气体',
                  '燃烧', '灭火', '化石燃料', '可再生能源',
                  '化学肥料', '塑料', '合成纤维', '合成橡胶',
                  '铁', '铜', '铝', '锌', '银', '金', '盐酸', '硫酸', '氢氧化钠',
                  '氢氧化钙', '氯化钠', '碳酸钠', '碳酸钙'],
    'pe': ['体育', '运动', '锻炼', '健康', '体能', '力量', '速度', '耐力', '柔韧',
           '灵敏', '田径', '篮球', '足球', '排球', '乒乓球', '羽毛球', '网球',
           '游泳', '体操', '武术', '健美操', '跳绳', '踢毽', '跑步', '跳远', '跳高',
           '投掷', '铅球', '标枪', '接力', '跨栏', '马拉松',
           '营养', '膳食', '睡眠', '心理健康', '社会适应', '运动损伤', '急救',
           '奥林匹克', '体育精神', '公平竞争', '团队合作', '终身体育',
           '足球场', '篮球场', '田径场', '游泳馆'],
}


def _detect_subject(page_lines):
    """根据全文统计各学科关键词命中数，返回命中最多的学科 key。"""
    text_all = ""
    for p, lines in page_lines.items():
        for l in lines:
            text_all += l['text'] + " "
    scores = {}
    for subj, kws in SUBJECT_DETECT_KEYWORDS.items():
        score = sum(text_all.count(kw) for kw in kws)
        scores[subj] = score
    print(f"[API] 学科检测分数: {scores}")
    best = max(scores.items(), key=lambda x: x[1])
    if best[1] == 0:
        return 'chinese'   # 默认按语文
    return best[0]


def _is_unit_title(text, rules=None):
    """严格判定单元标题（按学科规则）。"""
    text = text.strip()
    if rules is None:
        rules = SUBJECT_RULES['chinese']
    if not rules['unit_re'].search(text) and not rules['unit_re'].match(text):
        return False
    # 单元标题很短（≤ 30 字），避免误把含单元词的长句识别为标题
    # 注：历史/道法的单元标题可能较长，如 "第一单元 史前时期：中国境内人类的活动"
    if len(text) > 40:
        return False
    return True


def _compute_endpages_v2(units, total_pages):
    """为所有 lesson/sublesson 计算 endPage。

    叶子按 unit→lesson→sublesson 顺序扁平排列，每个叶子的 endPage = 下一个叶子的 startPage - 1。
    含 children 的 lesson 的 endPage = 最后一个 child 的 endPage（覆盖它和所有子篇目的范围）。
    """
    leaves = []
    for u in units:
        for l in u['lessons']:
            if l['type'] == 'lesson':
                leaves.append(l)
                for sub in l.get('children', []):
                    leaves.append(sub)
    for i, leaf in enumerate(leaves):
        sp = leaf.get('startPage', 1)
        leaf['startPage'] = sp
        nxt = leaves[i + 1]['startPage'] if i + 1 < len(leaves) else total_pages + 1
        leaf['endPage'] = max(sp, nxt - 1)
        if leaf['endPage'] > total_pages:
            leaf['endPage'] = total_pages
    # 含 children 的 lesson，endPage 取末位 child 的 endPage
    for u in units:
        for l in u['lessons']:
            if l['type'] == 'lesson' and l.get('children'):
                last = l['children'][-1]
                l['endPage'] = last.get('endPage', l.get('endPage', total_pages))
    return units


def _find_lesson_pdf_page_by_title(page_lines, title, toc_pages, start_search_page,
                                    total_pages, rules, prev_pdf_page=1):
    """根据目录条目标题在正文中搜索，定位真实 PDF 物理页码。

    新思路：不再用 offset = PDF真实页 - 印刷页码 间接换算，
    而是直接在正文页中搜索标题文本，找到第一个匹配页作为真实 PDF 页。

    匹配策略（按优先级）：
    1. 精确匹配：页面顶部某行 == 清理后的标题（去编号/页码）
    2. 包含匹配：页面顶部某行包含标题核心词
    3. 跨行匹配：标题拆词后，在页面顶部多行连续出现

    只扫描页面顶部（前 50% 区域，大字号标题 y 可能偏下），避免误匹配正文引用。
    搜索范围：从上一个匹配页开始往后扫，限制在合理窗口内（≤200页）。
    """
    # 标题预处理：去掉编号前缀（"1 春" → "春"）、作者（"春 / 朱自清" → "春"）
    # 保留核心标题用于匹配
    norm_title = title.strip()
    # 去掉编号前缀
    m = re.match(r'^(?:\d+\*?\s*[.．、]?\s*|第\s*[一二三四五六七八九十百零〇两0-9]+\s*(?:课|节)\s*|课题\s*[一二三四五六七八九十百零〇两0-9]+\s*|Section\s*[AB]\s*\d*[a-z]*[-–]\d*[a-z]*\s*)', norm_title, re.IGNORECASE)
    if m:
        norm_title = norm_title[m.end():].strip()
    # 去掉作者（保留 / 前部分）
    if '/' in norm_title:
        norm_title = norm_title.split('/')[0].strip()
    # 去掉首尾标点空白
    norm_title = re.sub(r'^[\s·、，,]+|[\s·、，,]+$', '', norm_title)
    if not norm_title or len(norm_title) == 0:
        return prev_pdf_page  # 标题过短，无法搜索

    # 拆出核心词（用于包含匹配），单字标题保留
    core_words = [w for w in re.split(r'[\s·、，,/]+', norm_title) if len(w) >= 1]
    if not core_words:
        core_words = [norm_title]

    # 单字/双字标题专用：短标题匹配要更精准，避免误匹配正文
    is_short_title = len(norm_title) <= 2

    toc_set = set(toc_pages)
    search_start = max(start_search_page, prev_pdf_page)
    # 搜索窗口：往后最多扫 200 页，避免无限扫描
    search_end = min(total_pages, search_start + 200)

    def _is_page_top(line_y, all_ys):
        """判断行是否在页面顶部区域（放宽到 50%，有些大字号标题 y 偏下）。"""
        if not all_ys:
            return True
        y_min = min(all_ys)
        y_max = max(all_ys)
        y_range = y_max - y_min if y_max > y_min else 1
        # PDF 坐标 y 越大越靠上，顶部 = y 接近 y_max
        return line_y >= (y_min + y_range * 0.50)

    for p in range(search_start, search_end + 1):
        if p in toc_set:
            continue
        lines = page_lines.get(p, [])
        if not lines:
            continue
        all_ys = [l['y'] for l in lines]
        # 只看顶部行
        top_lines = [l for l in lines if _is_page_top(l['y'], all_ys)]

        for line in top_lines:
            line_text = line['text'].strip()
            if not line_text:
                continue
            # 策略1：精确匹配（行 == 标题，或去掉编号后 == 标题）
            line_clean = re.sub(r'^[\s·、，,\-—]+|[\s·、，,\-—]+$', '', line_text)
            if line_clean == norm_title:
                return p
            # 行去掉编号后等于标题
            m2 = re.match(r'^(?:\d+\*?\s*[.．、]?\s*|第\s*[一二三四五六七八九十百零〇两0-9]+\s*(?:课|节)\s*|课题\s*[一二三四五六七八九十百零〇两0-9]+\s*)', line_text)
            if m2:
                rest = line_text[m2.end():].strip()
                if rest == norm_title:
                    return p
            # 策略2：包含匹配（行包含完整标题，且行长度限制避免匹配正文长句）
            if norm_title in line_text:
                # 短标题更严格：行长度不应超过 norm_title + 8（匹配 "春 朱自清" 这种）
                # 长标题宽松：norm_title + 20
                max_len = (len(norm_title) + 8) if is_short_title else (len(norm_title) + 20)
                if len(line_text) <= max_len:
                    return p
            # 长标题的多核心词匹配
            if not is_short_title and len(core_words) >= 2 and all(w in line_text for w in core_words) and len(line_text) <= 40:
                return p

    # 跨行匹配：仅长标题用（短标题跨行基本不存在）
    if not is_short_title:
        for p in range(search_start, search_end + 1):
            if p in toc_set:
                continue
            lines = page_lines.get(p, [])
            if not lines:
                continue
            all_ys = [l['y'] for l in lines]
            top_lines = [l['text'].strip() for l in lines if _is_page_top(l['y'], all_ys)]
            # 标题所有核心词都出现在顶部连续的几行中
            if len(core_words) >= 2:
                text_block = ' '.join(top_lines[:5])
                if all(w in text_block for w in core_words):
                    return p

    # 找不到匹配，用上一个匹配页 + 1 估算
    return min(prev_pdf_page + 1, total_pages)


def _parse_toc_page(page_lines, page_num_lines, toc_pages, rules, offset, total_pages):
    """从目录页解析三级目录（最可靠的方式）。

    目录页通常列出 "第X单元"、"1 春 ........ 2"、"写作 ... 17" 等条目，
    后面的数字是课本印刷页码。本函数解析这些条目，加上 offset 得到 PDF 真实页码。

    支持两种布局：
    1. 单栏：页码在行末（"1 春 ........ 2"）
    2. 双栏：页码在右栏独立文本块，通过 y 坐标与左栏标题配对

    返回 units 结构，或 None（目录页无法解析）。
    """
    # 收集目录页所有行
    # ★ PyMuPDF 的 bbox 用顶部原点坐标系：y0 是顶部坐标，y 向下递增
    # 所以从上到下排序应为 y 升序
    raw_lines = []  # [(text, y, page)]
    for p in sorted(toc_pages):
        for line in sorted(page_lines.get(p, []), key=lambda l: l['y']):
            raw_lines.append((line['text'].strip(), line['y'], p))

    # 构建页码索引：每页的 [(y, page_number, x)]
    # 只用纯页码行（双栏布局/文本拆分时页码独立成行）
    page_num_index = {}  # page -> [(y, num, x)]
    for p in toc_pages:
        nums = []
        for pn in page_num_lines.get(p, []):
            try:
                nums.append((pn['y'], int(pn['text']), pn.get('x', 0)))
            except ValueError:
                continue
        nums.sort(key=lambda x: x[0])
        page_num_index[p] = nums

    def find_page_by_y(page, y):
        """通过 y 坐标在同行找页码，优先选最右侧的数字（页码通常在页面最右）。"""
        nums = page_num_index.get(page, [])
        if not nums:
            return None
        # 找 y 坐标最接近的页码（容差 15 点），同 y 时取 x 最大的（最右）
        candidates = []
        for ny, num, nx in nums:
            dist = abs(ny - y)
            if dist <= 15.0:
                candidates.append((dist, nx, num))
        if not candidates:
            return None
        # 按 y 距离升序、x 降序排序，取第一个
        candidates.sort(key=lambda x: (x[0], -x[1]))
        return candidates[0][2]

    # 预处理：合并跨行条目。如果一行末尾不是页码，且下一行是纯页码，
    # 则将下一行的页码合并到当前行（PDF 文本提取可能把标题和页码拆成两行）
    toc_lines = []  # [(text, y, page)]
    i = 0
    while i < len(raw_lines):
        text, y, page = raw_lines[i]
        if not text:
            i += 1
            continue
        ends_with_page = bool(re.search(r'\d{1,3}\s*$', text))
        next_is_page = (
            i + 1 < len(raw_lines)
            and re.match(r'^\d{1,3}$', raw_lines[i + 1][0].strip()) is not None
        )
        if not ends_with_page and next_is_page:
            merged = text + ' ... ' + raw_lines[i + 1][0]
            toc_lines.append((merged, y, page))
            i += 2
        else:
            toc_lines.append((text, y, page))
            i += 1

    units = []
    cur_unit = None
    cur_l2 = None

    print(f"[API] 目录页原始行数: {len(toc_lines)}", flush=True)

    def extract_title_and_page(text, y, page):
        """从目录行提取 (标题, 印刷页码)。
        先尝试行末页码（单栏），失败则用 y 坐标找（双栏/文本拆分）。
        无论哪种情况，都清理标题末尾的省略号/连线符。
        """
        text = text.strip()
        m = re.search(r'(\d{1,3})\s*$', text)
        if m:
            book_page = int(m.group(1))
            title = text[:m.start()].strip()
        else:
            book_page = find_page_by_y(page, y)
            title = text
        # 清理标题末尾的省略号、连线符、空格
        title = re.sub(r'[\.·…\-—_\s]+$', '', title).strip()
        return title, book_page

    matched = 0
    for idx, (text, y, page) in enumerate(toc_lines):
        text = text.strip()
        if not text:
            continue

        # ★ 跳过英语目录的 "Page Sx"/"Page x" 行（已在圈码单元中处理页码）
        if PAGE_REF_RE.match(text):
            continue

        title, book_page = extract_title_and_page(text, y, page)

        if idx < 30:
            print(f"[API]   TOC行[{idx}]: '{text}' -> title='{title}', page={book_page}", flush=True)

        # 单元标题（可能有页码也可能没有）
        # ★ 用清理后的 title（不含页码）判断，避免长标题+页码超 40 字被误判
        if _is_unit_title(title, rules):
            page_num = 1
            unit_title = title
            if book_page is not None:
                page_num = book_page + offset

            # ★ 英语表格式目录：圈码单元向前查找 "Page Sx"/"Page x" 设置页码
            circled_num = _circled_to_num(text)
            if circled_num is not None:
                unit_title = f"Unit {circled_num}"
                for j in range(idx + 1, min(idx + 20, len(toc_lines))):
                    next_text_raw = toc_lines[j][0].strip()
                    # 遇到下一个圈码/Unit 标题，停止
                    if _circled_to_num(next_text_raw) is not None:
                        break
                    if _is_unit_title(next_text_raw, rules):
                        break
                    m_ref = PAGE_REF_RE.match(next_text_raw)
                    if m_ref:
                        ref = m_ref.group(1)
                        if ref.upper().startswith('S'):
                            # Starter 页码：在正文中查找 "S1" 等独立页码行
                            starter_num = int(ref[1:])
                            pdf_page = _find_starter_page(page_lines, starter_num, total_pages)
                            if pdf_page:
                                page_num = pdf_page
                            else:
                                page_num = max(1, min(starter_num + offset, total_pages))
                            unit_title = f"Starter Unit {circled_num}"
                        else:
                            # 普通页码
                            page_num = max(1, min(int(ref) + offset, total_pages))
                        break
                print(f"[API]     → 圈码单元 {circled_num}: page={page_num}", flush=True)
                cur_unit = {'title': unit_title, 'page': max(1, min(page_num, total_pages)), 'lessons': []}
                units.append(cur_unit)
                cur_l2 = None
                matched += 1
                continue

            # ★ 检查下一行是否为单元副标题（如"隋唐时期：繁荣与开放的时代"）
            # 副标题特征：无页码、不是单元标题、不是课文/栏目、长度适中
            if idx + 1 < len(toc_lines):
                next_text = toc_lines[idx + 1][0].strip()
                next_title, next_page = extract_title_and_page(next_text, toc_lines[idx + 1][1], toc_lines[idx + 1][2])
                if (next_page is None
                        and not _is_unit_title(next_title, rules)
                        and not rules['lesson_re'].match(next_title)
                        and not any(kw in next_title for kw in rules['group_kws'])
                        and 2 <= len(next_title) <= 40
                        and next_title not in ['目录', '目錄', 'Contents']):
                    unit_title = f"{unit_title} {next_title}"
                    print(f"[API]     → 单元副标题合并: '{next_title}'", flush=True)
            cur_unit = {'title': unit_title, 'page': max(1, min(page_num, total_pages)), 'lessons': []}
            units.append(cur_unit)
            cur_l2 = None
            matched += 1
            continue

        # 判断是栏目还是课文
        is_group = any(kw in title for kw in rules['group_kws'])
        is_lesson = rules['lesson_re'].match(title) is not None

        # 无页码的非课文非栏目短行 → 单元副标题（已合并到单元标题）或装饰文字，跳过
        if book_page is None and not is_lesson and not is_group and 2 <= len(title) <= 40:
            continue

        # 无页码的栏目直接跳过（栏目不是必须的书签）
        if book_page is None and is_group:
            continue

        # 无页码的课文/子篇目：估算页码（用上一篇的页码+1，确保不遗漏书签）
        if book_page is not None:
            real_page = max(1, min(book_page + offset, total_pages))
        else:
            # 估算：找最近一个有页码的兄弟条目
            last_page = 1
            if cur_unit and cur_unit['lessons']:
                for sib in reversed(cur_unit['lessons']):
                    if sib.get('startPage'):
                        last_page = sib['startPage'] + 1
                        break
                    elif sib.get('page'):
                        last_page = sib['page'] + 1
                        break
            real_page = min(last_page, total_pages)

        if cur_unit is None:
            cur_unit = {'title': '未命名单元', 'page': real_page, 'lessons': []}
            units.append(cur_unit)

        if is_group:
            cur_l2 = None
            cur_unit['lessons'].append({'title': title, 'type': 'group', 'page': real_page})
        else:
            # 课文标题可能带编号 "1 春 / 朱自清"，也可能是子篇目 "观沧海 / 曹操"
            if is_lesson:
                cur_l2 = {'title': title, 'type': 'lesson', 'startPage': real_page, 'children': []}
                cur_unit['lessons'].append(cur_l2)
            else:
                # 无编号的短标题 → 子篇目（L3），挂到最近的 L2 下
                if cur_l2 is not None:
                    cur_l2['children'].append({'title': title, 'type': 'sublesson', 'startPage': real_page})
                else:
                    cur_l2 = {'title': title, 'type': 'lesson', 'startPage': real_page, 'children': []}
                    cur_unit['lessons'].append(cur_l2)

    # ★ 英语表格式目录的单元可能没有课文条目（Section A/B 不在目录中列出）
    # 为这些单元添加占位课文，确保每个单元至少有一个可点击的书签
    if rules['name'] == '英语':
        for u in units:
            if not any(l['type'] == 'lesson' for l in u['lessons']):
                u['lessons'].append({
                    'title': u['title'], 'type': 'lesson',
                    'startPage': u['page'], 'children': []
                })

    # 过滤掉没有课文的单元
    units = [u for u in units if any(l['type'] == 'lesson' for l in u['lessons'])]
    if units:
        _compute_endpages_v2(units, total_pages)
    return units if units else None


def _relocate_units_by_body_search(units, page_lines, toc_pages, total_pages, rules):
    """根据书签标题在正文中匹配，重新定位每个 lesson 的真实 PDF 页码。

    新思路核心：不再用 offset = PDF真实页 - 印刷页码 间接换算（这是
    页码从 96 起跳等错误的根因），而是把目录条目的标题当作"关键字"，
    在正文中搜索第一次出现的页面，作为真实 PDF 物理页码。

    这样书签直接指向真实 PDF 页，pageOffset=0，前端跳转无需加偏移。

    处理顺序：按目录顺序逐个搜索，每个 lesson 的搜索起点 = 上一个
    lesson 的真实页码（保证后一个 lesson 的页码 ≥ 前一个）。
    """
    if not units:
        return units
    toc_end = max(toc_pages) if toc_pages else 3
    # 正文从目录结束页 + 1 开始搜索
    search_start = toc_end + 1

    prev_page = max(1, search_start)
    for u in units:
        # 单元标题页：用单元第一个 lesson 的页码或单元标题搜索
        unit_first_page = None
        for l in u['lessons']:
            if l.get('type') == 'lesson':
                # lesson 自身
                real_page = _find_lesson_pdf_page_by_title(
                    page_lines, l['title'], toc_pages, search_start,
                    total_pages, rules, prev_page
                )
                l['startPage'] = real_page
                prev_page = real_page
                if unit_first_page is None:
                    unit_first_page = real_page
                # sublessons
                for sub in l.get('children', []):
                    sub_page = _find_lesson_pdf_page_by_title(
                        page_lines, sub['title'], toc_pages, search_start,
                        total_pages, rules, prev_page
                    )
                    sub['startPage'] = sub_page
                    prev_page = sub_page
            elif l.get('type') == 'group':
                # 栏目无独立正文，跳过（不更新 prev_page）
                continue
        # 更新单元 page 为首个 lesson 的页码
        if unit_first_page is not None:
            u['page'] = unit_first_page

    # 重新计算 endPage
    _compute_endpages_v2(units, total_pages)
    print(f"[API] ✅ 正文标题匹配定位完成: {sum(len(u['lessons']) for u in units)} 个书签, "
          f"首个单元页={units[0]['page']}")
    return units


def _find_toc_pages(page_lines, rules, total_pages):
    """定位目录页（只看目录页，绝不扫描正文）。

    教材结构固定：第1页封面、第2页扉页、第3页版权页、第4页起是目录。
    目录可能有 1~3 页，从第4页开始逐页检测，遇到非目录页即停止。

    目录页判定核心特征：
    - 含"目录"标题字样（首页通常有）
    - 大量行以数字结尾（页码），且数字在合理范围内（1~总页数）
    - 含多个单元/课文标题
    """
    toc_pages = set()
    # 目录从第4页开始，最多4页，检查第4~7页
    # 用户描述：目录页可能 1~4 页，需动态判断结束位置
    start_page = 4
    end_page = min(7, total_pages)

    for p in range(start_page, end_page + 1):
        lines = page_lines.get(p, [])
        if not lines:
            if toc_pages:
                break
            continue

        text_all = "\n".join(l['text'] for l in lines)
        # 归一化空白（处理"目 录"中特殊空格字符 U+2002/U+2003 等）
        text_normalized = re.sub(r'\s+', '', text_all)

        # 特征1：含"目录"标题（归一化后匹配，兼容特殊空格）
        has_toc_title = any(
            kw in text_normalized for kw in ['目录', '目錄', 'Contents', 'CONTENTS']
        )

        # 特征2：多个单元标题
        unit_count = len(rules['unit_re'].findall(text_all))

        # 特征3：带页码的有效目录条目
        # 有效条目 = 行末是数字（1~总页数范围），且数字前有非数字标题文本
        valid_toc_entries = 0
        for l in lines:
            t = l['text'].strip()
            m = re.search(r'(\d{1,3})\s*$', t)
            if m:
                num = int(m.group(1))
                # 页码应在合理范围内（1 ~ 总页数），且标题部分非空
                title_part = t[:m.start()].strip()
                if 1 <= num <= total_pages and len(title_part) >= 1:
                    valid_toc_entries += 1

        # 特征4：英语表格式目录的 "Page Sx"/"Page x" 引用行
        page_ref_count = sum(1 for l in lines if PAGE_REF_RE.match(l['text'].strip()))

        # 判定是否为目录页
        # 有效目录条目数达到阈值即判定为目录页（目录页通常有5+条带页码条目）
        is_toc = has_toc_title or valid_toc_entries >= 4 or unit_count >= 2 or page_ref_count >= 2

        print(f"[API]   目录检测 第{p}页: has_toc_title={has_toc_title}, "
              f"valid_toc_entries={valid_toc_entries}, unit_count={unit_count}, "
              f"page_refs={page_ref_count}, is_toc={is_toc}", flush=True)

        if not is_toc and p <= start_page + 1:
            preview = text_all[:300].replace('\n', ' | ')
            print(f"[API]     内容预览: {preview}", flush=True)

        if is_toc:
            toc_pages.add(p)
        else:
            if toc_pages:
                break

    if toc_pages:
        print(f"[API] 检测到目录页: {sorted(toc_pages)}")
    else:
        print(f"[API] ⚠️ 未检测到目录页")
    return toc_pages


def extract_toc_with_ocr(pdf_bytes):
    """截图 + OCR 方案：渲染目录页为高清图片，用 Tesseract 识别文字，
    再解析为三级目录结构。

    流程：
      1. PyMuPDF 打开 PDF
      2. 渲染第4~7页为高分辨率图片（DPI=300）
      3. Tesseract OCR 识别中文（chi_sim + eng）
      4. 解析 OCR 文本为结构化目录（复用 unit/lesson/sublesson 逻辑）
      5. 用正文标题搜索定位真实 PDF 页码（复用 _relocate_units_by_body_search）

    返回与 extract_toc_with_fitz 相同结构的 result dict。
    """

    doc = None
    for attempt in range(2):
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            break
        except Exception as e:
            if attempt == 0:
                print(f"[OCR] ⚠️ fitz.open 第1次失败: {e}，正在重试...", flush=True)
                continue
            print(f"[OCR] ❌ fitz.open 第2次失败: {e}", flush=True)
            raise

    total_pages = len(doc)
    print(f"[OCR] PDF 已打开: {total_pages} 页", flush=True)

    # 同时扫描全文行（供学科检测和正文匹配复用）
    page_lines = {}
    font_count = {}
    font_info = {}

    for page_idx in range(total_pages):
        page = doc[page_idx]
        blocks = page.get_text("dict")["blocks"]
        lines = []
        for blk in blocks:
            if blk.get("type", 0) != 0:
                continue
            for line in blk.get("lines", []):
                line_text = ""
                line_max_font = 0.0
                line_y = 0.0
                line_x = 0.0
                for span in line.get("spans", []):
                    if not span["text"].strip():
                        continue
                    line_text += span["text"]
                    fs = round(float(span["size"]), 1)
                    if fs > line_max_font:
                        line_max_font = fs
                    line_y = float(span["bbox"][1])
                    line_x = float(span["bbox"][0])
                    fname = span.get("font", "unknown")
                    font_info[fname] = font_info.get(fname, 0) + 1
                line_text = _normalize_text(line_text).strip()
                if not line_text or len(line_text) > 120:
                    continue
                if PAGE_NUM_RE.match(line_text):
                    continue
                lines.append({
                    'page': page_idx + 1, 'text': line_text,
                    'fontsize': line_max_font, 'y': round(line_y, 1), 'x': round(line_x, 1)
                })
                fs_key = str(line_max_font)
                font_count[fs_key] = font_count.get(fs_key, 0) + 1
        page_lines[page_idx + 1] = lines

    if font_info:
        top_fonts = sorted(font_info.items(), key=lambda x: -x[1])[:5]
        print(f"[OCR] 字体分布(top5): {top_fonts}", flush=True)

    # 学科检测（初始，用可提取文字）
    subject_key = _detect_subject(page_lines)
    rules = SUBJECT_RULES[subject_key]
    print(f"[OCR] 学科检测(初始): {rules['name']} (key={subject_key})", flush=True)

    # 先试 PDF 自带书签
    existing_toc = doc.get_toc()
    if existing_toc:
        result = parse_existing_toc(existing_toc, total_pages, rules)
        if result['units']:
            result['subject'] = subject_key
            result['subjectName'] = rules['name']
            doc.close()
            print(f"[OCR] ✅ 使用 PDF 自带书签: {len(result['units'])} 个单元", flush=True)
            return result

    # ★ 核心：渲染目录页为图片并 OCR
    # 目录从第4页开始，最多4页（第4~7页）
    toc_start = 4
    toc_end = min(7, total_pages)

    # 先用文字检测确定目录页范围（如果文字可提取）
    toc_pages = _find_toc_pages(page_lines, rules, total_pages) if font_count else set()

    # 如果文字检测到目录页，用它们；否则默认扫描4~7页
    if toc_pages:
        ocr_pages = sorted(toc_pages)
    else:
        ocr_pages = list(range(toc_start, toc_end + 1))

    print(f"[OCR] 需要OCR的目录页: {ocr_pages}", flush=True)

    # 渲染目录页为图片并 OCR
    try:
        import pytesseract
        from PIL import Image
        import io as _io
    except ImportError as ie:
        missing = str(ie)
        print(f"[OCR] ❌ OCR 依赖缺失: {missing}", flush=True)
        print(f"[OCR] 请安装: pip install pytesseract Pillow && apt-get install tesseract-ocr tesseract-ocr-chi-sim", flush=True)
        doc.close()
        return {'units': [], 'pageOffset': 0, 'totalPages': total_pages,
                'method': 'ocr_dep_missing', 'error': f'OCR 依赖缺失: {missing}',
                'subject': subject_key, 'subjectName': rules['name']}

    # 验证 tesseract 二进制可用
    import shutil as _shutil
    if not _shutil.which('tesseract'):
        print("[OCR] ❌ tesseract 二进制未安装", flush=True)
        doc.close()
        return {'units': [], 'pageOffset': 0, 'totalPages': total_pages,
                'method': 'ocr_no_binary', 'error': 'tesseract 未安装',
                'subject': subject_key, 'subjectName': rules['name']}

    ocr_text_all = ""
    ocr_lines = []  # [(text, page_num)]

    for page_num in ocr_pages:
        page = doc[page_num - 1]  # 0-indexed
        # 高分辨率渲染：DPI=400 确保小字清晰（400 比 300 中文识别率更高）
        mat = fitz.Matrix(400/72, 400/72)
        pix = page.get_pixmap(matrix=mat)
        img_data = pix.tobytes("png")
        img = Image.open(_io.BytesIO(img_data))

        # OCR 识别：仅用 chi_sim（chi_sim+eng 混合时 Tesseract 会把
        # 中文字符误认为英文字母，如"春"→"@"，"朱自清"→"KBB"）
        # --psm 6 = 假设为统一文本块，适合目录页
        config = '--psm 6 -l chi_sim'
        try:
            text = pytesseract.image_to_string(img, config=config)
        except Exception as ocr_err:
            print(f"[OCR] ⚠️ 第{page_num}页 OCR 失败: {ocr_err}，跳过此页", flush=True)
            continue

        print(f"[OCR] 第{page_num}页 OCR 完成: {len(text)} 字符", flush=True)

        # 逐行收集
        for line in text.split('\n'):
            line = line.strip()
            if line:
                ocr_lines.append((line, page_num))
                ocr_text_all += line + '\n'

    doc.close()

    # ★ 用 OCR 文本重新检测学科（OCR 文本比 CID 噪声更可靠）
    ocr_scores = {}
    for subj, kws in SUBJECT_DETECT_KEYWORDS.items():
        score = sum(ocr_text_all.count(kw) for kw in kws)
        ocr_scores[subj] = score
    ocr_best = max(ocr_scores.items(), key=lambda x: x[1])
    if ocr_best[1] > 0:
        subject_key = ocr_best[0]
        rules = SUBJECT_RULES[subject_key]
        print(f"[OCR] 学科检测(OCR修正): {rules['name']} (key={subject_key}, 分数={dict(ocr_scores)})", flush=True)

    if not ocr_lines:
        print("[OCR] ❌ OCR 未识别到任何文字", flush=True)
        return {'units': [], 'pageOffset': 0, 'totalPages': total_pages,
                'method': 'ocr_empty', 'subject': subject_key,
                'subjectName': rules['name']}

    # ★ 解析 OCR 文本为结构化目录
    units = _parse_ocr_toc_lines(ocr_lines, rules, total_pages)

    if not units:
        print(f"[OCR] ❌ OCR 目录解析失败，OCR文本前500字: {ocr_text_all[:500]}", flush=True)
        return {'units': [], 'pageOffset': 0, 'totalPages': total_pages,
                'method': 'ocr_parse_fail', 'subject': subject_key,
                'subjectName': rules['name'],
                'ocrDebug': ocr_text_all[:2000]}

    # ★ 用正文标题搜索定位真实 PDF 页码
    toc_page_set = set(ocr_pages)
    units = _relocate_units_by_body_search(
        units, page_lines, toc_page_set, total_pages, rules
    )

    print(f"[OCR] ✅ OCR 目录提取成功: {len(units)} 个单元, "
          f"{sum(len(u['lessons']) for u in units)} 个书签", flush=True)

    return {
        'units': units,
        'pageOffset': 0,
        'totalPages': total_pages,
        'method': 'ocr_screenshot',
        'subject': subject_key,
        'subjectName': rules['name'],
        'detectedOffset': 0,
        'ocrDebug': ocr_text_all[:2000],
    }


def _parse_ocr_toc_lines(ocr_lines, rules, total_pages):
    """解析 OCR 识别出的目录文本行为三级目录结构。

    OCR 输出的每行是目录页上的一行文字，如：
      "第一单元 春秋战国时期"          → 单元
      "第1课 隋唐的统一 ........ 2"    → 课文（带页码）
      "1 春 朱自清 .... 5"             → 课文（带页码）
      "写作 ........ 17"               → 栏目

    与 _parse_toc_page 类似，但无 y 坐标信息，
    所以只能靠行末页码模式提取。
    """
    units = []
    cur_unit = None
    cur_l2 = None

    # 预处理：合并跨行条目（OCR 可能把标题和页码拆成两行）
    merged_lines = []
    i = 0
    while i < len(ocr_lines):
        text, page = ocr_lines[i]
        text = text.strip()
        if not text:
            i += 1
            continue
        # 如果当前行不以页码结尾，且下一行是纯数字，则合并
        ends_with_page = bool(re.search(r'(\d{1,3})\s*$', text))
        if not ends_with_page and i + 1 < len(ocr_lines):
            next_text = ocr_lines[i + 1][0].strip()
            if re.match(r'^\d{1,3}$', next_text):
                merged = text + ' ... ' + next_text
                merged_lines.append((merged, page))
                i += 2
                continue
        merged_lines.append((text, page))
        i += 1

    print(f"[OCR] 合并后目录行数: {len(merged_lines)}", flush=True)

    # ★ 拆分合并行：OCR 可能把 "第一单元 阅读 1 春/朱自清 2" 合并成一行
    # 需要拆成：单元行 "第一单元" + 课文行 "1 春/朱自清 2"
    split_lines = []
    for text, page in merged_lines:
        text = text.strip()
        # 检查是否同时包含单元标题和课文编号
        unit_match = rules['unit_re'].search(text)
        if unit_match:
            unit_part = unit_match.group()
            rest = text[unit_match.end():].strip()
            # 先去掉 "阅读" 等前缀词，再检查课文编号
            lesson_text = rest
            for prefix in ['阅读与写作', '阅读', '写作', '口语交际', '语文园地']:
                if lesson_text.startswith(prefix):
                    lesson_text = lesson_text[len(prefix):].strip()
                    break
            # 在清理后的 rest 中查找课文编号开头
            lesson_match = rules['lesson_re'].match(lesson_text) if lesson_text else None
            if lesson_match:
                # 拆分：单元行 + 课文行
                split_lines.append((unit_part, page))
                if lesson_text:
                    split_lines.append((lesson_text, page))
                continue
        split_lines.append((text, page))

    merged_lines = split_lines
    print(f"[OCR] 拆分后目录行数: {len(merged_lines)}", flush=True)

    for idx, (text, page) in enumerate(merged_lines):
        text = text.strip()
        if not text:
            continue

        # 跳过纯页码行
        if PAGE_NUM_RE.match(text):
            continue

        # 跳过英语 "Page Sx" 行
        if PAGE_REF_RE.match(text):
            continue

        # ★ 修复 OCR 页码空格：OCR 可能将 "17" 读成 "1 7"，"28" 读成 "2 8"
        # 合并行末数字间的空格（仅末尾连续数字，不影响标题中间的数字）
        while True:
            new_text = re.sub(r'(\d)\s+(\d)(?=\s*$)', r'\1\2', text)
            if new_text == text:
                break
            text = new_text

        # 提取标题和页码
        m = re.search(r'(\d{1,3})\s*$', text)
        if m:
            book_page = int(m.group(1))
            title = text[:m.start()].strip()
        else:
            book_page = None
            title = text

        # 清理标题末尾的省略号、连线符
        title = re.sub(r'[\.·…\-—_\s]+$', '', title).strip()
        # 清理标题开头的省略号（OCR 有时会在行首加点）
        title = re.sub(r'^[\.·…\-—_\s]+', '', title).strip()

        if not title or len(title) > 120:
            continue

        if idx < 30:
            print(f"[OCR]   行[{idx}]: '{text}' -> title='{title}', page={book_page}", flush=True)

        # 判断单元标题
        if _is_unit_title(title, rules):
            page_num = max(1, min(book_page, total_pages)) if book_page else 1

            # 检查下一行是否为单元副标题
            if idx + 1 < len(merged_lines):
                next_text = merged_lines[idx + 1][0].strip()
                next_m = re.search(r'(\d{1,3})\s*$', next_text)
                next_title = re.sub(r'[\.·…\-—_\s]+$', '', next_text[:next_m.start()] if next_m else next_text).strip()
                next_has_page = next_m is not None
                if (not next_has_page
                        and not _is_unit_title(next_title, rules)
                        and not rules['lesson_re'].match(next_title)
                        and not any(kw in next_title for kw in rules['group_kws'])
                        and 2 <= len(next_title) <= 40
                        and next_title not in ['目录', '目錄', 'Contents', 'CONTENTS']):
                    title = f"{title} {next_title}"
                    print(f"[OCR]     → 单元副标题合并: '{next_title}'", flush=True)

            cur_unit = {'title': title, 'page': page_num, 'lessons': []}
            units.append(cur_unit)
            cur_l2 = None
            continue

        # 判断栏目还是课文
        is_group = any(kw in title for kw in rules['group_kws'])
        is_lesson = rules['lesson_re'].match(title) is not None

        # 无页码的非课文非栏目短行 → 跳过
        if book_page is None and not is_lesson and not is_group and 2 <= len(title) <= 40:
            continue

        # 无页码的栏目 → 跳过
        if book_page is None and is_group:
            continue

        # 页码处理
        if book_page is not None:
            real_page = max(1, min(book_page, total_pages))
        else:
            # 估算
            last_page = 1
            if cur_unit and cur_unit['lessons']:
                for sib in reversed(cur_unit['lessons']):
                    if sib.get('startPage'):
                        last_page = sib['startPage'] + 1
                        break
                    elif sib.get('page'):
                        last_page = sib['page'] + 1
                        break
            real_page = min(last_page, total_pages)

        if cur_unit is None:
            cur_unit = {'title': '未命名单元', 'page': real_page, 'lessons': []}
            units.append(cur_unit)

        if is_group:
            cur_l2 = None
            cur_unit['lessons'].append({'title': title, 'type': 'group', 'page': real_page})
        elif is_lesson:
            cur_l2 = {'title': title, 'type': 'lesson', 'startPage': real_page, 'children': []}
            cur_unit['lessons'].append(cur_l2)
        else:
            # 无编号短标题 → 子篇目或独立 lesson
            if cur_l2 is not None:
                cur_l2['children'].append({'title': title, 'type': 'sublesson', 'startPage': real_page})
            else:
                cur_l2 = {'title': title, 'type': 'lesson', 'startPage': real_page, 'children': []}
                cur_unit['lessons'].append(cur_l2)

    # 英语占位
    if rules['name'] == '英语':
        for u in units:
            if not any(l['type'] == 'lesson' for l in u['lessons']):
                u['lessons'].append({
                    'title': u['title'], 'type': 'lesson',
                    'startPage': u['page'], 'children': []
                })

    # 过滤无课文的单元
    units = [u for u in units if any(l['type'] == 'lesson' for l in u['lessons'])]
    if units:
        _compute_endpages_v2(units, total_pages)
    return units if units else None


def _build_page_lines_with_pdfplumber(pdf_bytes, total_pages_hint=None):
    """用 pdfplumber (基于 pdfminer.six) 构造 page_lines。

    pdfplumber 有独立的 CID 字体处理逻辑,某些 PyMuPDF 提取不到的
    CID 字体, pdfplumber 能正确解码。

    返回与 extract_toc_with_fitz 相同结构的 (page_lines, page_num_lines,
    font_count, font_info, total_pages)，失败返回 None。
    """
    try:
        import pdfplumber
    except ImportError:
        print("[pdfplumber] 未安装，跳过", flush=True)
        return None

    import io as _io
    try:
        pdf = pdfplumber.open(_io.BytesIO(pdf_bytes))
    except Exception as e:
        print(f"[pdfplumber] 打开失败: {e}", flush=True)
        return None

    total_pages = len(pdf.pages)
    print(f"[pdfplumber] PDF 已打开: {total_pages} 页", flush=True)

    page_lines = {}
    page_num_lines = {}
    font_count = {}
    font_info = {}

    for page_idx in range(total_pages):
        page = pdf.pages[page_idx]
        # extract_words 返回每个词的信息：text, x0, x1, top, bottom, size 等
        try:
            words = page.extract_words(extra_attrs=["size", "fontname"])
        except Exception:
            words = page.extract_words()

        # 按 top 坐标分行（pdfplumber 的 y 坐标是 top，向下递增）
        lines_by_y = {}
        for w in words:
            y = round(float(w.get('top', 0)), 1)
            # 找相近的 y（误差 3px 内视为同行）
            line_key = y
            for k in lines_by_y:
                if abs(k - y) <= 3:
                    line_key = k
                    break
            lines_by_y.setdefault(line_key, []).append(w)

        lines = []
        for y in sorted(lines_by_y.keys()):
            ws = sorted(lines_by_y[y], key=lambda w: float(w.get('x0', 0)))
            line_text = "".join(w.get('text', '') for w in ws).strip()
            if not line_text:
                continue
            line_text = _normalize_text(line_text)
            if not line_text or len(line_text) > 120:
                continue
            # 字号：取行内最大 size
            sizes = [float(w.get('size', 0)) for w in ws if w.get('size')]
            line_fs = round(max(sizes), 1) if sizes else 0.0
            x = round(float(ws[0].get('x0', 0)), 1)
            # 字体名收集
            for w in ws:
                fname = w.get('fontname', 'unknown')
                font_info[fname] = font_info.get(fname, 0) + 1

            if PAGE_NUM_RE.match(line_text):
                page_num_lines.setdefault(page_idx + 1, []).append(
                    {'text': line_text, 'y': y, 'x': x})
                continue
            lines.append({
                'page': page_idx + 1, 'text': line_text,
                'fontsize': line_fs, 'y': y, 'x': x
            })
            fs_key = str(line_fs)
            font_count[fs_key] = font_count.get(fs_key, 0) + 1
        page_lines[page_idx + 1] = lines

    pdf.close()

    if not font_count:
        print("[pdfplumber] 未提取到任何文字", flush=True)
        return None

    total_text = sum(len(l['text']) for ls in page_lines.values() for l in ls)
    print(f"[pdfplumber] ✅ 提取成功: {total_pages} 页, {total_text} 字符", flush=True)
    return (page_lines, page_num_lines, font_count, font_info, total_pages)


def _build_page_lines_with_pypdfium2(pdf_bytes, total_pages_hint=None):
    """用 pypdfium2 (Google PDFium 绑定) 构造 page_lines。

    PDFium 有强大的 CID 字体处理能力,带 ToUnicode CMap 的 CID 字体
    通常都能正确解码。

    返回与 extract_toc_with_fitz 相同结构，失败返回 None。
    """
    try:
        import pypdfium2 as pdfium
    except ImportError:
        print("[pypdfium2] 未安装，跳过", flush=True)
        return None

    try:
        pdf = pdfium.PdfDocument(pdf_bytes)
    except Exception as e:
        print(f"[pypdfium2] 打开失败: {e}", flush=True)
        return None

    total_pages = len(pdf)
    print(f"[pypdfium2] PDF 已打开: {total_pages} 页", flush=True)

    page_lines = {}
    page_num_lines = {}
    font_count = {}
    font_info = {'PDFium-internal': total_pages}  # pypdfium2 不暴露字体名

    for page_idx in range(total_pages):
        page = pdf[page_idx]
        try:
            tp = page.get_textpage()
        except Exception as e:
            page_lines[page_idx + 1] = []
            continue

        # get_text_bounded 返回 [(text, x, y, w, h), ...] 或类似结构
        # pypdfium2 的 textpage API：get_text_range 返回纯文本
        try:
            # 尝试获取带位置信息的文本
            # pypdfium2 的 TextPage 有 get_text_bounded 方法
            text_rects = []
            if hasattr(tp, 'get_text_bounded'):
                # get_text_bounded(left, bottom, right, top) 返回区域内文本
                # 这里获取整个页面
                page_rect = page.get_size()  # (width, height)
                text_rects = tp.get_text_bounded(0, 0, page_rect[0], page_rect[1])
            elif hasattr(tp, 'get_text_range'):
                # 退化：只有纯文本，无位置
                full_text = tp.get_text_range()
                lines = [(t, 0.0, float(page_idx * 20 + i * 12), 0.0, 0.0)
                         for i, t in enumerate(full_text.split('\n'))]
                text_rects = lines
        except Exception as e:
            text_rects = []

        # 按 y 坐标分行
        lines_by_y = {}
        for item in text_rects:
            if isinstance(item, (tuple, list)) and len(item) >= 3:
                text = item[0] if isinstance(item[0], str) else str(item[0])
                x = float(item[1]) if item[1] else 0.0
                y = float(item[2]) if item[2] else 0.0
            else:
                continue
            text = text.strip()
            if not text:
                continue
            line_key = round(y, 1)
            for k in lines_by_y:
                if abs(k - y) <= 3:
                    line_key = k
                    break
            lines_by_y.setdefault(line_key, []).append((text, x, y))

        lines = []
        for y in sorted(lines_by_y.keys()):
            ws = sorted(lines_by_y[y], key=lambda w: w[1])
            line_text = "".join(t for t, _, _ in ws).strip()
            if not line_text:
                continue
            line_text = _normalize_text(line_text)
            if not line_text or len(line_text) > 120:
                continue
            # pypdfium2 不直接给字号，用 0 标记（字号不影响目录页解析主逻辑）
            line_fs = 0.0
            x = round(ws[0][1], 1)
            if PAGE_NUM_RE.match(line_text):
                page_num_lines.setdefault(page_idx + 1, []).append(
                    {'text': line_text, 'y': y, 'x': x})
                continue
            lines.append({
                'page': page_idx + 1, 'text': line_text,
                'fontsize': line_fs, 'y': y, 'x': x
            })
            font_count['0.0'] = font_count.get('0.0', 0) + 1
        page_lines[page_idx + 1] = lines

    pdf.close()

    if not font_count:
        print("[pypdfium2] 未提取到任何文字", flush=True)
        return None

    total_text = sum(len(l['text']) for ls in page_lines.values() for l in ls)
    print(f"[pypdfium2] ✅ 提取成功: {total_pages} 页, {total_text} 字符", flush=True)
    return (page_lines, page_num_lines, font_count, font_info, total_pages)


def extract_toc_with_fitz(pdf_bytes):
    """用 pymupdf 提取三级目录（参考用户 Python 书签程序的层级规则）。

    层级规则：
      L1（单元）= 严格匹配"第X单元"/"第X章"/"Unit N"的标题
      L2（文章）= 编号开头（1 春 / 3* 雨的四季）或栏目关键词开头
                  （写作 / 综合性学习 / 名著导读 / 课外古诗词诵读）
      L3（子篇目）= L2 下面的子标题（金色花 / 观沧海 / 咏雪 等）
    跳过：封面（靠 L3 必须有 L2 父规则）、版权页、目录页、页眉页脚。
    页码即真实 PDF 页码，pageOffset=0，点击书签直达正文。
    """

    # ★ 重试逻辑：某些 PDF 首次打开可能因结构异常失败
    doc = None
    for attempt in range(2):
        try:
            doc = fitz.open(stream=pdf_bytes, filetype="pdf")
            break
        except Exception as e:
            if attempt == 0:
                print(f"[API] ⚠️ fitz.open 第1次失败: {e}，正在重试...", flush=True)
                continue
            print(f"[API] ❌ fitz.open 第2次失败: {e}", flush=True)
            raise

    total_pages = len(doc)
    print(f"[API] PDF 已打开: {total_pages} 页", flush=True)

    # 一次性扫描全文行（含字号/y 坐标），供学科检测和字号提取共用
    page_lines = {}      # page -> [lines]
    text_pages = {}      # text -> set of pages（页眉页脚检测）
    font_count = {}
    font_info = {}       # font_name -> count（字体信息日志）
    page_num_lines = {}  # page -> [纯页码行]，用于偏移量检测

    for page_idx in range(total_pages):
        page = doc[page_idx]
        blocks = page.get_text("dict")["blocks"]
        lines = []
        for blk in blocks:
            if blk.get("type", 0) != 0:
                continue
            for line in blk.get("lines", []):
                line_text = ""
                line_max_font = 0.0
                line_y = 0.0
                line_x = 0.0
                for span in line.get("spans", []):
                    if not span["text"].strip():
                        continue
                    line_text += span["text"]
                    fs = round(float(span["size"]), 1)
                    if fs > line_max_font:
                        line_max_font = fs
                    line_y = float(span["bbox"][1])
                    line_x = float(span["bbox"][0])
                    # 收集字体名称（用于诊断 CID 字体问题）
                    fname = span.get("font", "unknown")
                    font_info[fname] = font_info.get(fname, 0) + 1
                # 归一化：全角数字→半角，全角空格→半角
                line_text = _normalize_text(line_text).strip()
                if not line_text or len(line_text) > 120:
                    continue
                # 收集纯页码行（用于偏移量检测和双栏页码配对）
                if PAGE_NUM_RE.match(line_text):
                    page_num_lines.setdefault(page_idx + 1, []).append({
                        'text': line_text, 'y': round(line_y, 1), 'x': round(line_x, 1)
                    })
                    continue
                lines.append({
                    'page': page_idx + 1,
                    'text': line_text,
                    'fontsize': line_max_font,
                    'y': round(line_y, 1),
                    'x': round(line_x, 1)
                })
                text_pages.setdefault(line_text, set()).add(page_idx + 1)
                fs_key = str(line_max_font)
                font_count[fs_key] = font_count.get(fs_key, 0) + 1
        page_lines[page_idx + 1] = lines

    # ★ 字体信息日志（诊断 CID 字体提取问题）
    if font_info:
        top_fonts = sorted(font_info.items(), key=lambda x: -x[1])[:5]
        print(f"[API] 字体分布(top5): {top_fonts}", flush=True)

    # ★ 学科自适应：根据全文关键词命中数选择提取规则
    subject_key = _detect_subject(page_lines)
    rules = SUBJECT_RULES[subject_key]
    print(f"[API] 学科检测: {rules['name']} (key={subject_key})")

    # 1. 优先使用 PDF 自带书签（最准确，已含层级信息）
    existing_toc = doc.get_toc()
    if existing_toc:
        result = parse_existing_toc(existing_toc, total_pages, rules)
        if result['units']:
            result['subject'] = subject_key
            result['subjectName'] = rules['name']
            doc.close()
            return result

    doc.close()

    if not font_count:
        # ★ PyMuPDF 提取不到文字（大概率 CID 字体），尝试其他库
        if font_info:
            cid_fonts = [f for f in font_info if 'CID' in f or 'Identity' in f]
            print(f"[API] ⚠️ PyMuPDF 检测到 CID 字体但无法提取: {cid_fonts or list(font_info.keys())[:3]}", flush=True)

        # ★ 多库兜底：依次尝试 pdfplumber 和 pypdfium2
        for lib_name, build_fn in [
            ('pdfplumber', _build_page_lines_with_pdfplumber),
            ('pypdfium2', _build_page_lines_with_pypdfium2),
        ]:
            print(f"[API] 尝试 {lib_name} 提取...", flush=True)
            alt_result = build_fn(pdf_bytes, total_pages)
            if alt_result:
                page_lines, page_num_lines, font_count, font_info, alt_total = alt_result
                # 用新库的数据重新检测学科
                subject_key = _detect_subject(page_lines)
                rules = SUBJECT_RULES[subject_key]
                print(f"[API] ✅ {lib_name} 提取成功，学科: {rules['name']}", flush=True)
                # 跳出循环，继续走下面的目录解析逻辑
                break
        else:
            # 三个库都失败
            print("[API] ❌ 所有库都无法提取文字", flush=True)
            return {'units': [], 'pageOffset': 0, 'totalPages': total_pages,
                    'method': 'none', 'subject': subject_key,
                    'subjectName': rules['name']}

    # ★ 步骤 1：定位目录页（关键：只看目录页，绝不扫描正文！）
    # 教材结构固定：第1页封面、第2页扉页、第3页版权页、第4页起是目录
    # 目录可能有 1~4 页，需动态识别目录结束位置
    toc_pages = _find_toc_pages(page_lines, rules, total_pages)

    # ★ 步骤 2：解析目录页提取条目（标题 + 印刷页码）
    # 此处不再依赖 offset 计算真实页码，offset 仅作为兜底估算
    page_offset = 0  # 默认偏移量设为 0，由正文标题匹配决定真实页

    if toc_pages:
        toc_units = _parse_toc_page(page_lines, page_num_lines, toc_pages, rules, page_offset, total_pages)
        if toc_units:
            # ★ 步骤 3：根据书签标题在正文中匹配，定位真实 PDF 物理页码
            # 这是新思路核心：不通过 offset 间接换算，直接在正文搜索标题
            toc_units = _relocate_units_by_body_search(
                toc_units, page_lines, toc_pages, total_pages, rules
            )
            print(f"[API] ✅ 目录页解析+正文匹配定位成功: {len(toc_units)} 个单元, "
                  f"目录页={sorted(toc_pages)}, pageOffset=0")
            return {
                'units': toc_units,
                'pageOffset': 0,    # 已通过正文匹配定位真实 PDF 页，前端无需加偏移
                'totalPages': total_pages,
                'method': 'toc_body_match',
                'subject': subject_key,
                'subjectName': rules['name'],
                'detectedOffset': 0,
            }
        print(f"[API] ⚠️ 目录页解析失败，目录页={sorted(toc_pages)}，返回空结果")

    # 目录页解析失败 → 不回退到正文扫描（避免正文混入书签）
    return {
        'units': [],
        'pageOffset': 0,
        'totalPages': total_pages,
        'method': 'toc_failed',
        'subject': subject_key,
        'subjectName': rules['name'],
        'detectedOffset': 0,
    }


def parse_existing_toc(toc_list, total_pages, rules):
    """解析 PDF 自带书签为三级结构（与字号扫描结果同构）。

    层级 1 → 单元；层级 2 → lesson（或栏目 group）；层级 3 → sublesson（挂在最近 L2 下）。
    页码即真实 PDF 页码，偏移 = 0。

    容错处理：
    - 若书签全部为 level 1（无层级结构），则全部作为同一单元的 lesson
    - 若某单元下无 lesson，将其首个条目作为 lesson 保底，避免单元被丢弃
    - 不再按 group 关键词过滤，确保所有书签都能展示
    """
    units = []
    cur_unit = None
    cur_l2 = None

    # 统计最大层级，判断是否有层级结构
    max_level = max((e[0] for e in toc_list if len(e) >= 3), default=1)

    for entry in toc_list:
        if len(entry) < 3:
            continue
        level, title, page = entry[0], entry[1].strip(), entry[2]
        if not title or page < 1:
            continue
        # 页码钳制（参考用户 Python 程序：pg = max(1, min(pg, max_p))）
        page = max(1, min(page, total_pages))

        if level == 1:
            cur_unit = {'title': title, 'page': page, 'lessons': []}
            units.append(cur_unit)
            cur_l2 = None
        elif level == 2:
            if cur_unit is None:
                cur_unit = {'title': '未命名单元', 'page': page, 'lessons': []}
                units.append(cur_unit)
            cur_l2 = {'title': title, 'type': 'lesson', 'startPage': page, 'children': []}
            cur_unit['lessons'].append(cur_l2)
        else:  # level >= 3
            if cur_l2 is not None:
                cur_l2['children'].append({'title': title, 'type': 'sublesson', 'startPage': page})
            elif cur_unit is not None:
                # 无 L2 父 → 当作独立 lesson
                cur_unit['lessons'].append({'title': title, 'type': 'lesson', 'startPage': page, 'children': []})

    # 容错：若书签全部为 level 1，将它们合并为一个"全书目录"单元下的 lesson
    if max_level == 1 and len(units) > 1:
        merged = {'title': '全书目录', 'page': units[0]['page'], 'lessons': []}
        for u in units:
            merged['lessons'].append({
                'title': u['title'], 'type': 'lesson',
                'startPage': u['page'], 'children': []
            })
        units = [merged]

    # 容错：若某单元下无 lesson，将单元本身作为唯一 lesson 保底
    for u in units:
        if not any(l['type'] == 'lesson' for l in u['lessons']):
            u['lessons'].append({
                'title': u['title'], 'type': 'lesson',
                'startPage': u['page'], 'children': []
            })

    _compute_endpages_v2(units, total_pages)

    return {'units': units, 'pageOffset': 0, 'totalPages': total_pages, 'method': 'bookmark'}


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.endswith('.zip'):
            filename = os.path.basename(unquote(self.path))
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Type', 'application/zip')
        # HTML 文件不缓存，确保浏览器始终获取最新版本
        if self.path.endswith('.html') or self.path == '/' or self.path == '/index.html':
            self.send_header('Cache-Control', 'no-cache, no-store, must-revalidate')
        super().end_headers()

    def log_message(self, format, *args):
        print(f"[{self.log_date_time_string()}] {args[0]}")

    def do_POST(self):
        if self.path == '/api/extract-toc':
            self.handle_extract_toc()
        else:
            self.send_error(404)

    def handle_extract_toc(self):
        content_length = int(self.headers.get('Content-Length', 0))
        print(f"[API] 收到提取请求: {content_length} bytes", flush=True)
        if content_length == 0:
            self.send_json({'error': 'No data received'})
            return

        body = self.rfile.read(content_length)
        print(f"[API] 已读取 PDF 数据，开始提取...", flush=True)

        try:
            # ★ 新策略：文字提取优先（100%准确），OCR 仅作兜底
            # 1) PyMuPDF 文字提取（自带多库兜底：pdfplumber + pypdfium2）
            print(f"[API] ★ 尝试文字提取方案（PyMuPDF + 多库兜底）...", flush=True)
            result = extract_toc_with_fitz(body)
            if result.get('units'):
                print(f"[API] ✅ 文字提取成功: {len(result['units'])} 个单元, 方法={result.get('method')}", flush=True)
                self.send_json(result)
                return

            # 2) 文字提取失败 → 回退到 OCR 截图方案（兜底）
            print(f"[API] 文字提取未成功 (method={result.get('method')}), 回退到 OCR 截图方案...", flush=True)
            result = extract_toc_with_ocr(body)
            print(f"[API] 提取完成: {len(result.get('units', []))} 个单元, 方法={result.get('method')}", flush=True)
            self.send_json(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[API] 提取失败: {e}", flush=True)
            self.send_json({'error': str(e), 'units': [], 'pageOffset': 0})

    def send_json(self, data):
        body = json.dumps(data, ensure_ascii=False).encode('utf-8')
        self.send_response(200)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Content-Length', len(body))
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(body)


if __name__ == '__main__':
    os.chdir(ROOT)
    server = http.server.HTTPServer(('', PORT), Handler)
    print(f"Serving {ROOT} on port {PORT}")
    print(f"API: POST /api/extract-toc (upload PDF bytes)")
    server.serve_forever()
