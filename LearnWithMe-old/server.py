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

        page_lines_sorted = sorted(page_lines[p], key=lambda l: -l['y'])
        for line in page_lines_sorted:
            text = line['text'].strip()
            if not text:
                continue
            # 跳过单元标题本身
            if _is_unit_title(text, rules):
                continue
            # 必须匹配 lesson_re
            if not rules['lesson_re'].match(text):
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
                if len(line_text) < 2 or len(line_text) > 60:
                    continue
                # 过滤纯页码行
                if re.fullmatch(r'[\-—\s]*\d{1,4}[\-—\s]*', line_text):
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

    # 跳过页检测
    skip_pages = _detect_skip_pages(page_lines, rules)

    # 正文字号 = 出现次数最多的字号
    body_font = float(max(font_count.items(), key=lambda x: x[1])[0])

    # 标题行 = 字号严格大于正文，不在跳过页，不是页眉页脚
    title_lines = [
        l for p, lines in page_lines.items()
        for l in lines
        if l['fontsize'] > body_font + 0.5
        and p not in skip_pages
        and not _is_running_header(text_pages, l['text'], total_pages)
    ]
    # 按页码、y 坐标排序（先按页，再按 y 从上到下，即降序）
    title_lines.sort(key=lambda l: (l['page'], -l['y']))

    # ★ 关键增强 1：先在正文中用学科正则找出所有单元标题（不依赖字号）
    # 解决"单元标题用粗体而非更大字号"导致单元漏识别的问题
    body_units = _find_units_in_body(page_lines, skip_pages, rules)

    # ★ 关键增强 2：在正文中用学科正则找出所有课文标题（不依赖字号）
    # 解决非语文学科"课文标题字号与正文一致"导致课文全部漏识别、
    # 最终 units 被过滤为空的问题（这是数学/英语/历史/道法提取效果差的核心原因）
    body_lessons = _find_lessons_in_body(page_lines, skip_pages, rules, body_units)

    units = []
    use_body_skeleton = bool(body_units) and bool(body_lessons)

    if use_body_skeleton:
        # 用正则找到的 (unit, lesson) 作为骨架，按页码切分填充 L3
        # 此分支适用于：单元/课文标题字号与正文一致（如历史/道法/数学的某些版本）
        for u_info in body_units:
            units.append({'title': u_info['text'], 'page': u_info['page'], 'lessons': []})

        # 给每个 unit 挂载 lessons（来自 body_lessons）
        # body_lessons 已按 unit_idx 分组、按页码顺序排列
        lesson_dict = {}   # unit_idx -> [lesson_info]
        for bl in body_lessons:
            lesson_dict.setdefault(bl['unit_idx'], []).append(bl)

        for u_idx, u in enumerate(units):
            cur_l2 = None
            for bl in lesson_dict.get(u_idx, []):
                text = bl['text']
                page = bl['page']
                is_group = any(kw in text for kw in rules['group_kws'])
                if is_group:
                    cur_l2 = None
                    u['lessons'].append({'title': text, 'type': 'group', 'page': page})
                else:
                    cur_l2 = {'title': text, 'type': 'lesson', 'startPage': page, 'children': []}
                    u['lessons'].append(cur_l2)

        # 再用 title_lines（字号大于正文的行）补充 L3 子篇目
        # 每个 L3 挂到其页码所属 lesson 的 children 里
        # 先建立 (unit_idx, lesson_idx) -> lesson 的索引
        lesson_index = []   # [(start_page, end_page, unit_idx, lesson_obj)]
        for u_idx, u in enumerate(units):
            for l in u['lessons']:
                if l['type'] == 'lesson':
                    lesson_index.append((l['startPage'], u_idx, l))

        for line in title_lines:
            text = line['text'].strip()
            page = line['page']

            # 跳过单元标题
            if _is_unit_title(text, rules):
                # 找到对应 unit 跳过其标题文本
                for u in units:
                    if u['title'] == text:
                        continue
                continue
            # 跳过已在 body_lessons 中的课文标题（避免重复）
            if rules['lesson_re'].match(text):
                continue
            # 跳过栏目（已在 body_lessons 里）
            if any(kw in text for kw in rules['group_kws']):
                continue

            # 找到该页所属的 unit
            cur_unit_idx = -1
            for i, u in enumerate(units):
                if u['page'] <= page:
                    cur_unit_idx = i
                else:
                    break
            if cur_unit_idx < 0:
                continue
            cur_unit = units[cur_unit_idx]

            # 找到该页所属的 lesson（最近的、startPage <= page 的 lesson）
            cur_l2 = None
            for l in cur_unit['lessons']:
                if l['type'] == 'lesson' and l['startPage'] <= page:
                    cur_l2 = l
                elif l['type'] == 'lesson' and l['startPage'] > page:
                    break

            if cur_l2 is not None:
                cur_l2['children'].append({'title': text, 'type': 'sublesson', 'startPage': page})

    elif body_units:
        # 有单元、但 body_lessons 为空 → 走字号+正则的混合路径（原逻辑）
        # 此分支适用于：单元用粗体而非更大字号，但课文标题字号大于正文
        for u_info in body_units:
            units.append({'title': u_info['text'], 'page': u_info['page'], 'lessons': []})

        cur_unit_idx = -1
        cur_l2 = None
        for line in title_lines:
            text = line['text'].strip()
            page = line['page']

            # 检查是否进入新单元（按页码切分）
            while cur_unit_idx + 1 < len(units) and page >= units[cur_unit_idx + 1]['page']:
                cur_unit_idx += 1
                cur_l2 = None

            if cur_unit_idx < 0:
                continue   # 第一个单元之前的内容，跳过

            cur_unit = units[cur_unit_idx]

            # 跳过单元标题本身（已经在 unit.title 里了）
            if _is_unit_title(text, rules) and text == cur_unit['title']:
                continue

            if _is_lesson_l2(text, rules):
                is_group = any(kw in text for kw in rules['group_kws'])
                if is_group:
                    cur_l2 = None
                    cur_unit['lessons'].append({'title': text, 'type': 'group', 'page': page})
                else:
                    cur_l2 = {'title': text, 'type': 'lesson', 'startPage': page, 'children': []}
                    cur_unit['lessons'].append(cur_l2)
            else:
                # L3 子篇目：必须有 L2 父
                if cur_l2 is not None:
                    cur_l2['children'].append({'title': text, 'type': 'sublesson', 'startPage': page})
    else:
        # 没有用正则找到单元 → 回退到字号 + 正则规则
        cur_unit = None
        cur_l2 = None
        for line in title_lines:
            text = line['text'].strip()
            page = line['page']
            if _is_unit_title(text, rules):
                cur_unit = {'title': text, 'page': page, 'lessons': []}
                units.append(cur_unit)
                cur_l2 = None
            elif _is_lesson_l2(text, rules):
                if cur_unit is None:
                    cur_unit = {'title': '未命名单元', 'page': page, 'lessons': []}
                    units.append(cur_unit)
                is_group = any(kw in text for kw in rules['group_kws'])
                if is_group:
                    cur_l2 = None
                    cur_unit['lessons'].append({'title': text, 'type': 'group', 'page': page})
                else:
                    cur_l2 = {'title': text, 'type': 'lesson', 'startPage': page, 'children': []}
                    cur_unit['lessons'].append(cur_l2)
            else:
                if cur_l2 is not None:
                    cur_l2['children'].append({'title': text, 'type': 'sublesson', 'startPage': page})

    _compute_endpages_v2(units, total_pages)
    units = [u for u in units if any(l['type'] == 'lesson' for l in u['lessons'])]

    return {
        'units': units,
        'pageOffset': 0,    # pymupdf 页码即真实 PDF 页码，无需偏移
        'totalPages': total_pages,
        'method': 'fontsize' if not use_body_skeleton else 'body_regex',
        'subject': subject_key,
        'subjectName': rules['name'],
        'bodyFont': body_font,
        'titleCount': len(title_lines),
        'bodyUnitsFound': len(body_units),
        'bodyLessonsFound': len(body_lessons)
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
        if content_length == 0:
            self.send_json({'error': 'No data received'})
            return

        body = self.rfile.read(content_length)

        try:
            result = extract_toc_with_fitz(body)
            print(f"[API] 提取完成: {len(result.get('units', []))} 个单元, 方法={result.get('method')}, 偏移={result.get('pageOffset')}, bodyUnits={result.get('bodyUnitsFound')}, bodyLessons={result.get('bodyLessonsFound')}")
            self.send_json(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f"[API] 提取失败: {e}")
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
