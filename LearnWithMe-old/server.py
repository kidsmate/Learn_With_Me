#!/usr/bin/env python3
"""HTTP server with PDF TOC extraction API"""
import http.server
import json
import os
import re
import io
from urllib.parse import unquote

PORT = 8080
ROOT = os.path.dirname(os.path.abspath(__file__))

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
        # Unit N / Starter Unit N → Section A / Section B / Pronunciation / Project
        # 注意：单元标题必须以 Unit 或 Starter Unit 开头
        'unit_re': re.compile(r'^(?:Starter\s+)?Unit\s*\d+', re.IGNORECASE),
        # 课文：Section A / Section B / Section B 1a-1d（编号子篇目）
        'lesson_re': re.compile(r'^Section\s*[AB]', re.IGNORECASE),
        # 栏目关键词
        'group_kws': ['Pronunciation', 'Grammar Focus', 'Project', 'Self Check',
                      'Reading', 'Writing', 'Listening', 'Speaking', 'Vocabulary',
                      'Words and Expressions', 'Functions', 'Strategy', 'Study skills',
                      'Notes on the Text', 'Tapescripts', 'Name List',
                      'Vocabulary Index', '不规则动词', '听力材料', 'Just for Fun'],
        'name': '英语',
    },
    'history': {
        # 第X单元 → 第N课 标题 / 活动课
        'unit_re': re.compile(r'第[一二三四五六七八九十百零〇两0-9]+单元'),
        # 第1课 / 第十课 / 第21课 + 至少一个非空白字符（标题）
        'lesson_re': re.compile(r'第[一二三四五六七八九十百零〇两0-9]+课\s*\S'),
        'group_kws': ['活动课', '单元综合', '学史方法', '课后活动',
                      '知识梳理', '单元总结', '附录', '大事年表', '知识拓展',
                      '相关史事', '材料研读', '问题思考'],
        'name': '历史',
    },
    'morality': {
        # 道德与法治：第X单元 → 第N课 标题 → 子篇目（无编号短标题）
        'unit_re': re.compile(r'第[一二三四五六七八九十百零〇两0-9]+单元'),
        # 第一课 / 第10课 等
        'lesson_re': re.compile(r'第[一二三四五六七八九十百零〇两0-9]+课\s*\S'),
        # 栏目：单元思考与行动、相关链接、阅读感悟、方法与技能、探究与分享、拓展空间
        'group_kws': ['单元思考与行动', '相关链接', '阅读感悟', '方法与技能',
                      '探究与分享', '拓展空间', '学史方法', '生活观察',
                      '方法与技能', '相关链接'],
        'name': '道德与法治',
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


def _detect_page_offset(page_num_lines, total_pages):
    """自动检测页码偏移量（参考用户 Python 程序的 offset 逻辑）。

    教材每页底部通常印有课本页码（如 2、6、14），但 PDF 第 1 页往往是封面，
    导致 PDF 真实页码 = 课本印刷页码 + offset。
    本函数扫描所有页面的纯页码行，统计 (PDF页码 - 印刷页码) 的众数作为偏移。

    例如：印刷页 2 出现在 PDF 第 9 页 → offset = 9 - 2 = 7
    """
    offset_count = {}
    for p, nums in page_num_lines.items():
        for item in nums:
            text = item['text'].strip()
            m = PAGE_NUM_RE.match(text)
            if not m:
                continue
            printed = int(m.group(1))
            # 印刷页码应在合理范围（1 ~ 总页数），且 PDF 页码应大于印刷页码
            if 1 <= printed <= total_pages and p > printed:
                offset = p - printed
                offset_count[offset] = offset_count.get(offset, 0) + 1
    if not offset_count:
        return 0
    # 取出现次数最多的偏移量（众数）
    best_offset = max(offset_count.items(), key=lambda x: x[1])
    # 至少需要 2 个页面命中才认为偏移可靠
    if best_offset[1] < 2:
        return 0
    print(f"[API] 页码偏移检测: {best_offset[0]} (命中 {best_offset[1]} 页)")
    return best_offset[0]


def _parse_toc_page(page_lines, toc_pages, rules, offset, total_pages):
    """从目录页解析三级目录（最可靠的方式）。

    目录页通常列出 "第X单元"、"1 春 ........ 2"、"写作 ... 17" 等条目，
    后面的数字是课本印刷页码。本函数解析这些条目，加上 offset 得到 PDF 真实页码。

    返回 units 结构，或 None（目录页无法解析）。
    """
    # 收集目录页所有行（按 y 坐标从小到大排序 = 从上到下）
    raw_lines = []
    for p in sorted(toc_pages):
        for line in sorted(page_lines.get(p, []), key=lambda l: l['y']):
            raw_lines.append(line['text'].strip())

    # 预处理：合并跨行条目。如果一行末尾不是页码，且下一行是纯页码，
    # 则将下一行的页码合并到当前行（PDF 文本提取可能把标题和页码拆成两行）
    toc_lines = []
    i = 0
    while i < len(raw_lines):
        line = raw_lines[i]
        if not line:
            i += 1
            continue
        # 检查当前行是否以页码结尾
        ends_with_page = bool(re.search(r'\d{1,3}\s*$', line))
        # 检查下一行是否是纯页码
        next_is_page = (
            i + 1 < len(raw_lines)
            and re.match(r'^\d{1,3}$', raw_lines[i + 1].strip()) is not None
        )
        if not ends_with_page and next_is_page:
            # 合并：标题 + 页码
            merged = line + ' ... ' + raw_lines[i + 1]
            toc_lines.append(merged)
            i += 2
        else:
            toc_lines.append(line)
            i += 1

    units = []
    cur_unit = None
    cur_l2 = None

    # 调试：打印目录页原始行（帮助诊断格式问题）
    print(f"[API] 目录页原始行数: {len(toc_lines)}")

    # 从每行末尾提取页码：找行中最后一个 1-3 位数字
    # 标题 = 该数字之前的所有文本（去除末尾的点号/空格）
    # 这种方式不依赖特定分隔符，兼容 "........"、空格、制表符等各种引导符
    def extract_title_and_page(text):
        """从目录行提取 (标题, 印刷页码)。页码是行末最后一个数字。"""
        text = text.strip()
        # 匹配行末的数字（前面可以有点号/空格等引导符）
        m = re.search(r'(\d{1,3})\s*$', text)
        if not m:
            return None, None
        book_page = int(m.group(1))
        # 标题 = 页码之前的文本，去除末尾的引导符（点号、空格、横线等）
        title = text[:m.start()].strip()
        title = re.sub(r'[\.·…\-—\s]+$', '', title).strip()
        return title, book_page

    matched = 0
    for idx, text in enumerate(toc_lines):
        text = text.strip()
        if not text:
            continue

        # 尝试提取页码
        title, book_page = extract_title_and_page(text)

        # 调试：打印前 20 行的处理情况
        if idx < 25:
            print(f"[API]   TOC行[{idx}]: '{text}' -> title='{title}', page={book_page}")

        # 单元标题（可能有页码也可能没有）
        if _is_unit_title(text, rules):
            page = 1
            unit_title = text
            if book_page is not None:
                unit_title = title
                page = book_page + offset
            cur_unit = {'title': unit_title, 'page': max(1, min(page, total_pages)), 'lessons': []}
            units.append(cur_unit)
            cur_l2 = None
            matched += 1
            continue

        # 非单元行必须有页码才是有效目录条目
        if book_page is None:
            continue

        page = max(1, min(book_page + offset, total_pages))

        # 判断是栏目还是课文
        is_group = any(kw in title for kw in rules['group_kws'])
        if cur_unit is None:
            cur_unit = {'title': '未命名单元', 'page': page, 'lessons': []}
            units.append(cur_unit)

        if is_group:
            cur_l2 = None
            cur_unit['lessons'].append({'title': title, 'type': 'group', 'page': page})
        else:
            # 课文标题可能带编号 "1 春 / 朱自清"，也可能是子篇目 "观沧海 / 曹操"
            if rules['lesson_re'].match(title):
                cur_l2 = {'title': title, 'type': 'lesson', 'startPage': page, 'children': []}
                cur_unit['lessons'].append(cur_l2)
            else:
                # 无编号的短标题 → 子篇目（L3），挂到最近的 L2 下
                if cur_l2 is not None:
                    cur_l2['children'].append({'title': title, 'type': 'sublesson', 'startPage': page})
                else:
                    cur_l2 = {'title': title, 'type': 'lesson', 'startPage': page, 'children': []}
                    cur_unit['lessons'].append(cur_l2)

    # 过滤掉没有课文的单元
    units = [u for u in units if any(l['type'] == 'lesson' for l in u['lessons'])]
    if units:
        _compute_endpages_v2(units, total_pages)
    return units if units else None


def _find_toc_pages(page_lines, rules, total_pages):
    """定位目录页（只看目录页，绝不扫描正文）。

    教材结构固定：第1页封面、第2页扉页、第3页版权页、第4页起是目录。
    目录可能有 1~3 页，需从第4页开始逐页检测，直到遇到非目录页为止。

    目录页特征：
    - 含"目录"标题字样
    - 或有多个单元标题（第X单元）
    - 或有多个带页码的条目（行末是数字）
    """
    toc_pages = set()
    # 从第4页开始检查，最多检查到第10页（目录不会超过3-4页）
    start_page = 4
    end_page = min(10, total_pages)

    for p in range(start_page, end_page + 1):
        lines = page_lines.get(p, [])
        if not lines:
            # 空白页也可能是目录页的一部分（如目录跨页时的空白），
            # 但如果前面已经有目录页且当前页完全空白，可能是目录结束
            if toc_pages:
                break
            continue

        text_all = "\n".join(l['text'] for l in lines)

        # 特征1：含"目录"标题
        has_toc_title = any(
            kw in text_all for kw in ['目录', '目錄', 'Contents', 'CONTENTS']
        )

        # 特征2：多个单元标题
        unit_count = len(rules['unit_re'].findall(text_all))

        # 特征3：多个带页码的条目（行末是数字）
        numbered_entries = 0
        for l in lines:
            if re.search(r'\d{1,3}\s*$', l['text'].strip()):
                numbered_entries += 1

        # 判定是否为目录页
        is_toc = has_toc_title or (unit_count >= 1 and numbered_entries >= 2) or numbered_entries >= 4

        if is_toc:
            toc_pages.add(p)
        else:
            # 非目录页 → 目录结束
            if toc_pages:
                break

    # 如果从第4页没找到，尝试从第3页开始（有些教材目录从第3页开始）
    if not toc_pages:
        for p in range(3, min(8, total_pages) + 1):
            lines = page_lines.get(p, [])
            if not lines:
                continue
            text_all = "\n".join(l['text'] for l in lines)
            has_toc_title = any(kw in text_all for kw in ['目录', '目錄', 'Contents'])
            numbered_entries = sum(1 for l in lines if re.search(r'\d{1,3}\s*$', l['text'].strip()))
            if has_toc_title or numbered_entries >= 4:
                toc_pages.add(p)
            elif toc_pages:
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
                for span in line.get("spans", []):
                    if not span["text"].strip():
                        continue
                    line_text += span["text"]
                    fs = round(float(span["size"]), 1)
                    if fs > line_max_font:
                        line_max_font = fs
                    line_y = float(span["bbox"][1])
                line_text = line_text.strip()
                if not line_text or len(line_text) > 60:
                    continue
                # 收集纯页码行（用于偏移量检测）
                if PAGE_NUM_RE.match(line_text):
                    page_num_lines.setdefault(page_idx + 1, []).append({
                        'text': line_text, 'y': round(line_y, 1)
                    })
                    continue
                lines.append({
                    'page': page_idx + 1,
                    'text': line_text,
                    'fontsize': line_max_font,
                    'y': round(line_y, 1)
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

    # ★ 步骤 1：自动检测页码偏移量（参考用户 Python 程序的 offset 逻辑）
    # offset = PDF 真实页码 - 课本印刷页码
    page_offset = _detect_page_offset(page_num_lines, total_pages)

    # ★ 步骤 2：定位目录页（关键：只看目录页，绝不扫描正文！）
    # 教材结构固定：第1页封面、第2页扉页、第3页版权页、第4页起是目录
    # 目录可能有 1~3 页，需动态识别目录结束位置
    toc_pages = _find_toc_pages(page_lines, rules, total_pages)

    if toc_pages:
        toc_units = _parse_toc_page(page_lines, toc_pages, rules, page_offset, total_pages)
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
    """
    units = []
    cur_unit = None
    cur_l2 = None

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
            is_group = any(kw in title for kw in rules['group_kws'])
            if is_group:
                cur_l2 = None
                cur_unit['lessons'].append({'title': title, 'type': 'group', 'page': page})
            else:
                cur_l2 = {'title': title, 'type': 'lesson', 'startPage': page, 'children': []}
                cur_unit['lessons'].append(cur_l2)
        else:  # level >= 3
            if cur_l2 is not None:
                cur_l2['children'].append({'title': title, 'type': 'sublesson', 'startPage': page})
            elif cur_unit is not None:
                # 无 L2 父 → 当作独立 lesson
                cur_unit['lessons'].append({'title': title, 'type': 'lesson', 'startPage': page, 'children': []})

    _compute_endpages_v2(units, total_pages)
    units = [u for u in units if any(l['type'] == 'lesson' for l in u['lessons'])]

    return {'units': units, 'pageOffset': 0, 'totalPages': total_pages, 'method': 'bookmark'}


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        if self.path.endswith('.zip'):
            filename = os.path.basename(unquote(self.path))
            self.send_header('Content-Disposition', f'attachment; filename="{filename}"')
            self.send_header('Content-Type', 'application/zip')
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
