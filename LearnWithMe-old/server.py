#!/usr/bin/env python3
"""HTTP server with PDF TOC extraction API"""
import http.server
import json
import os
import re
import io
import unicodedata
from urllib.parse import unquote

PORT = 8080
ROOT = os.path.dirname(os.path.abspath(__file__))


def _normalize_text(text):
    """归一化文本：全角数字→半角，全角空格→半角，兼容 PDF 排版差异。

    PDF 教材中常出现全角数字（如 ２３４５６７８９０），
    导致正则 [0-9] 无法匹配。NFKC 归一化将其转为 ASCII。
    """
    return unicodedata.normalize('NFKC', text)

# 人教版初中语文目录正则与关键词（参考用户的 Python 书签程序）
UNIT_RE = re.compile(r'第[一二三四五六七八九十百零〇两0-9]+单元')
GROUP_KEYWORDS = ['写作', '综合性学习', '名著导读', '课外古诗词诵读', '课外古诗词',
                  '口语交际', '活动·探究', '活动探究', '任务', '汉语知识', '语法知识']
LESSON_NUM_RE = re.compile(r'^\d+\*?\s*[.．、]?\s*\S')
# 版权/编目页关键词
SKIP_KEYWORDS = ['版权所有', '著作权所有', 'ISBN', 'CIP', '图书在版编目', '出版发行']

# 印刷页码检测：教材每页底部通常有印刷页码（如 "2"、"14"）
# offset = PDF 真实页码 - 印刷页码，例如印刷页2在PDF第9页 → offset=7
PAGE_NUM_RE = re.compile(r'^[\s\-—]*(\d{1,3})[\s\-—]*$')

# ===== 英语教材表格式目录支持 =====
# 圈码字符：➊-➓(1-10), ⓫-⓴(11-20)
CIRCLED_NUMS = '➊➋➌➍➎➏➐➑➒➓⓫⓬⓭⓮⓯⓰⓱⓲⓳⓴'
# Starter 页码模式（如 "S1"、"S5"）
PAGE_S_RE = re.compile(r'^S(\d{1,3})$', re.IGNORECASE)
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
        'unit_re': re.compile(r'第[一二三四五六七八九十百零〇两0-9]+单元'),
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


def _find_units_in_body(page_lines, skip_pages, rules):
    """在正文中扫描所有单元标题行（不依赖字号）。

    这是增强步骤：有些 PDF 的单元标题用粗体而非更大字号，
    仅靠"字号 > 正文"会漏掉单元。这里直接用正则在所有正文页中找，
    确保每个单元都被识别为一级书签。

    每个单元只记录第一次出现的页码，避免页眉中重复的 "Unit 1" 被多次识别。
    """
    units = []   # [{page, text}]
    seen = set()
    for p in sorted(page_lines.keys()):
        if p in skip_pages:
            continue
        # 一页可能有多个 line，按 y 从上到下找第一个单元标题
        page_lines_sorted = sorted(page_lines[p], key=lambda l: -l['y'])
        for line in page_lines_sorted:
            text = line['text'].strip()
            if _is_unit_title(text, rules):
                key = text
                if key in seen:
                    continue
                seen.add(key)
                units.append({'page': p, 'text': text})
                break   # 一页只取第一个单元标题
    return units


def _find_lessons_in_body(page_lines, skip_pages, rules, units):
    """在正文中按学科正则扫描所有课文标题行（不依赖字号）。

    与单元检测同理：很多非语文学科的课文标题（"1.1 正数和负数" /
    "第1课 中国早期人类的代表——北京人" / "Section A"）字号可能与正文一致，
    仅靠"字号 > 正文"会漏掉所有课文，导致最终 units 被过滤为空。

    本函数在 units 给定的页码区间内，按 lesson_re 找出所有课文标题，
    返回 [{page, text, unit_idx}] 列表，供 build_structure 使用。
    """
    if not units:
        return []

    # 每个 unit 的页码范围 = [unit.page, next_unit.page - 1]
    ranges = []
    for i, u in enumerate(units):
        start = u['page']
        end = units[i + 1]['page'] - 1 if i + 1 < len(units) else 10 ** 9
        ranges.append((start, end))

    lessons = []
    seen_keys = set()  # (unit_idx, text) 去重，避免页眉重复
    for p in sorted(page_lines.keys()):
        if p in skip_pages:
            continue
        # 找到当前页所属的 unit 区间
        unit_idx = -1
        for i, (s, e) in enumerate(ranges):
            if s <= p <= e:
                unit_idx = i
                break
        if unit_idx < 0:
            continue

        page_all_lines = page_lines[p]
        if not page_all_lines:
            continue
        # ★ 页面位置过滤：课文标题在页面顶部，正文在中下部
        # 计算本页所有行的 y 范围，只接受位于顶部 40% 的行
        ys = [l['y'] for l in page_all_lines]
        y_min, y_max = min(ys), max(ys)
        y_range = y_max - y_min if y_max > y_min else 1
        # y 越小越靠上；阈值 = y_min + 40% * range
        y_threshold = y_min + y_range * 0.40

        page_lines_sorted = sorted(page_all_lines, key=lambda l: -l['y'])
        for line in page_lines_sorted:
            text = line['text'].strip()
            if not text:
                continue
            # ★ 位置过滤：只接受页面顶部的行（y <= 阈值）
            if line['y'] > y_threshold:
                continue
            # 跳过单元标题本身
            if _is_unit_title(text, rules):
                continue
            # 必须匹配 lesson_re
            if not rules['lesson_re'].match(text):
                continue
            # ★ 严格过滤：排除正文/习题行（短标题、无句末标点、无正文特征词）
            if not _is_valid_lesson_title(text, rules):
                continue
            key = (unit_idx, text)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            lessons.append({'page': p, 'text': text, 'unit_idx': unit_idx})

    return lessons


def _is_lesson_l2(text, rules=None):
    """判定二级文章：按学科规则的编号/关键词开头。"""
    text = text.strip()
    if rules is None:
        rules = SUBJECT_RULES['chinese']
    if rules['lesson_re'].match(text):
        return True
    for kw in rules['group_kws']:
        if text.startswith(kw) or kw in text[:15]:
            return True
    return False


# 正文/习题特征词：这些词出现在行中说明不是课文标题
BODY_MARKERS = [
    '下列', '以下', '如图', '证明', '计算', '求证', '解答', '解：', '答：',
    '分析', '说明', '解释', '判断', '选择', '填空', '简答', '阅读',
    '材料', '问题', '思考', '讨论', '探究', '实践', '活动',
    '（1）', '（2）', '（3）', '（4）', '（5）',
    '①', '②', '③', '④', '⑤',
    '甲', '乙', '丙', '丁',
    '给下列', '给加点', '注音', '解释下列', '翻译下列',
    '用现代汉语', '用原文', '用自己', '用简洁',
    '读读写写', '读一读', '写一写', '背一背', '记一记',
    '预习', '复习', '巩固', '拓展', '提升',
]
# 指令动词开头：正文/习题常以动词开头，课文标题不会
INSTRUCTION_VERBS = ['给', '读', '写', '看', '听', '说', '想', '做', '用', '选', '填', '答', '背', '记', '抄', '画', '圈', '标', '注']
# 谓语动词/助词：课文标题是名词短语，不含这些；正文句子含这些
SENTENCE_VERBS = ['是', '了', '着', '过', '有', '在', '爱', '喜欢', '要', '会', '能', '可以', '应该', '必须', '叫', '叫做', '称为', '属于', '包括', '表示']
# 程度副词/句末语气词：出现在句子中，不出现在课文标题中
SENTENCE_PARTICLES = ['很', '真', '太', '非常', '十分', '极其', '格外', '呢', '吧', '啊', '呀', '吗', '嘛']
# 句末标点：课文标题不会以这些结尾
SENTENCE_END = '。！？.!?；;：:'


def _is_valid_lesson_title(text, rules=None):
    """严格判定一行是否为合法的课文标题（排除正文/习题）。

    课文标题特征：短、名词短语、不以句末标点结尾、不含正文特征词、不是指令句、不含谓语动词。
    正文/习题特征：长句、以问号/句号结尾、含"下列/如图/证明"等、以动词开头、含"是/了/着"等谓语。
    """
    text = text.strip()
    if not text or len(text) > 30:
        return False
    # 不以句末标点结尾（课文标题是名词性短语，不是句子）
    if text[-1] in SENTENCE_END:
        return False
    # 不含正文/习题特征词
    for marker in BODY_MARKERS:
        if marker in text:
            return False
    # 编号 + 标题 之间不应有句号（如 "1.下列..." 是习题）
    m = re.match(r'^(\d+\*?)\s*[.．、]?\s*(.+)', text)
    if m:
        title_part = m.group(2).strip()
    else:
        title_part = text

    # 标题部分不应包含逗号/句号（正文句子才有）
    # 例外1：作者名用 / 分隔，如 "春 / 朱自清"
    # 例外2：栏目名（写作/综合性学习/名著导读等）可含逗号，如 "写作 热爱生活，热爱写作"
    is_group_title = any(text.startswith(kw) or kw in text[:10] for kw in (rules or SUBJECT_RULES['chinese'])['group_kws'])
    if any(c in title_part for c in '，。、；'):
        if '/' not in title_part and not is_group_title:
            return False
    # 标题部分不应以指令动词开头（如 "1 给加点字注音"）
    # 例外：栏目名以"写作/阅读"等开头是合法的
    if title_part and title_part[0] in INSTRUCTION_VERBS and not is_group_title:
        return False
    # ★ 课文标题是名词短语，不应含谓语动词/助词（如 "2 济南的冬天是温晴的"）
    # 也不应含程度副词/语气词（如 "2 济南的冬天很美"）
    # 例外1：带作者名的标题 "春 / 朱自清" 中，作者名可能含这些字
    # 例外2：栏目名（写作/名著导读等）可能含动词，如 "写作 热爱生活"
    if '/' not in title_part and not is_group_title:
        for word in SENTENCE_VERBS + SENTENCE_PARTICLES:
            if word in title_part:
                return False
    return True


def _is_running_header(text_pages_map, text, total_pages):
    """页眉/页脚判定：在多页重复出现的文本。"""
    pages = text_pages_map.get(text)
    if not pages:
        return False
    if len(pages) > 5 or len(pages) > max(3, total_pages * 0.1):
        return True
    return False


def _detect_skip_pages(page_lines, rules):
    """检测需要跳过的页：目录页、版权页。封面靠"L3 必须有 L2 父"规则自动过滤。"""
    skip = set()
    for p, lines in page_lines.items():
        text_all = "\n".join(l['text'] for l in lines)
        # 版权/编目页
        if any(kw in text_all for kw in SKIP_KEYWORDS):
            skip.add(p)
            continue
        # 目录页：含"目录"/"目 录"/"Contents"标题字样，
        # 或同时出现多个单元 + 多个编号条目
        # 注意 "目 录" 中间可能含全角/半角空格，统一去空白再比较
        has_toc_title = any(
            (
                '目录' in l['text'].replace(' ', '').replace('\u3000', '')
                or 'Contents' in l['text']
                or '目錄' in l['text'].replace(' ', '').replace('\u3000', '')
            )
            and len(l['text'].strip().replace(' ', '').replace('\u3000', '')) <= 8
            and l['fontsize'] > 12
            for l in lines
        )
        unit_count = len(rules['unit_re'].findall(text_all))
        numbered_count = sum(1 for l in lines if rules['lesson_re'].match(l['text']))
        if has_toc_title or (unit_count >= 2 and numbered_count >= 3):
            skip.add(p)
    return skip


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


def _detect_page_offset(page_num_lines, page_lines, total_pages, toc_pages=None):
    """自动检测页码偏移量。

    offset = PDF 真实页码 - 课本印刷页码。
    教材每页底部通常印有课本页码，但 PDF 前几页（封面、扉页、版权页、目录）
    没有印刷页码，导致 PDF 页码 ≠ 印刷页码。

    策略（按优先级）：
    1. 扫描正文页的纯页码行，统计 (PDF页码 - 印刷页码) 的众数
    2. 若正文纯页码行不足，扫描页脚短行（末尾是数字的短行）作为补充
    3. 若仍不足，根据目录结构估算：offset ≈ 目录结束页 - 首个目录条目的印刷页码

    重要：仅使用目录页之后的正文页页码，避免目录中的条目页码干扰偏移计算。
         偏移量限制在 1~30 页范围内（教材前置页不会超过 30 页）。
    """
    toc_end = max(toc_pages) if toc_pages else 0
    offset_count = {}

    def _is_valid_offset(off):
        """偏移量合理性校验：1~30 页。"""
        return 1 <= off <= 30

    # 策略1：纯页码行（仅目录页之后的正文页）
    for p, nums in page_num_lines.items():
        if p <= toc_end:
            continue
        for item in nums:
            text = item['text'].strip()
            m = PAGE_NUM_RE.match(text)
            if not m:
                continue
            printed = int(m.group(1))
            if 1 <= printed <= total_pages and p > printed:
                offset = p - printed
                if _is_valid_offset(offset):
                    offset_count[offset] = offset_count.get(offset, 0) + 1

    # 策略2：页脚短行（末尾是数字的短行，可能是页码，仅正文页）
    if not offset_count or max(offset_count.values()) < 2:
        for p in range(toc_end + 1, total_pages + 1):
            for l in page_lines.get(p, []):
                t = l['text'].strip()
                if len(t) > 20:
                    continue
                m = re.search(r'(\d{1,3})\s*$', t)
                if m:
                    printed = int(m.group(1))
                    if 1 <= printed <= total_pages and p > printed and printed > 0:
                        offset = p - printed
                        if _is_valid_offset(offset):
                            offset_count[offset] = offset_count.get(offset, 0) + 1

    if offset_count:
        best_offset = max(offset_count.items(), key=lambda x: x[1])
        if best_offset[1] >= 2:
            print(f"[API] 页码偏移检测: {best_offset[0]} (命中 {best_offset[1]} 行, 目录结束页={toc_end})")
            return best_offset[0]

    # 策略3：根据目录结构估算偏移
    # 目录从第4页开始，内容在目录之后；首个目录条目的印刷页码通常为1
    if toc_pages and len(toc_pages) >= 1:
        # 估算内容起始页 = 目录结束页 + 1（可能有空白页，取 +1）
        estimated_content_start = toc_end + 1
        # 首个目录条目的印刷页码通常是1，偏移量 = 内容起始页 - 1
        estimated_offset = estimated_content_start - 1
        if _is_valid_offset(estimated_offset):
            print(f"[API] 页码偏移估算(目录结构): {estimated_offset} (目录结束页={toc_end})")
            return estimated_offset

    print(f"[API] ⚠️ 页码偏移检测失败，使用默认偏移 0")
    return 0


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
    # ★ PDF 坐标系：原点在左下角，y 值越大越靠上
    # 所以从上到下排序应为 y 降序（-y）
    raw_lines = []  # [(text, y, page)]
    for p in sorted(toc_pages):
        for line in sorted(page_lines.get(p, []), key=lambda l: -l['y']):
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
    # 目录从第4页开始，最多3页，检查第4~6页
    start_page = 4
    end_page = min(6, total_pages)

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
    import fitz

    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    total_pages = len(doc)

    # 一次性扫描全文行（含字号/y 坐标），供学科检测和字号提取共用
    page_lines = {}      # page -> [lines]
    text_pages = {}      # text -> set of pages（页眉页脚检测）
    font_count = {}
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
        return {'units': [], 'pageOffset': 0, 'totalPages': total_pages, 'method': 'none'}

    # ★ 步骤 1：定位目录页（关键：只看目录页，绝不扫描正文！）
    # 教材结构固定：第1页封面、第2页扉页、第3页版权页、第4页起是目录
    # 目录可能有 1~3 页，需动态识别目录结束位置
    toc_pages = _find_toc_pages(page_lines, rules, total_pages)

    # ★ 步骤 2：自动检测页码偏移量
    # offset = PDF 真实页码 - 课本印刷页码
    # 若正文页码检测失败，可用目录结构作为 fallback 估算
    page_offset = _detect_page_offset(page_num_lines, page_lines, total_pages, toc_pages)

    if toc_pages:
        toc_units = _parse_toc_page(page_lines, page_num_lines, toc_pages, rules, page_offset, total_pages)
        if toc_units:
            print(f"[API] ✅ 目录页解析成功: {len(toc_units)} 个单元, "
                  f"目录页={sorted(toc_pages)}, offset={page_offset}")
            return {
                'units': toc_units,
                'pageOffset': 0,    # 目录页页码已加 offset 转为真实 PDF 页，前端无需再加
                'totalPages': total_pages,
                'method': 'toc_page',
                'subject': subject_key,
                'subjectName': rules['name'],
                'detectedOffset': page_offset,
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
        'detectedOffset': page_offset,
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
            result = extract_toc_with_fitz(body)
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
