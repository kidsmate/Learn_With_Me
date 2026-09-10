#!/usr/bin/env python3
"""测试 OCR 目录解析逻辑：模拟各种 OCR 输出格式，验证"春"等条目能否被正确提取。"""
import re
import sys

# 导入 server 的解析函数和规则
sys.path.insert(0, '/workspace/LearnWithMe-old')
from server import _parse_ocr_toc_lines, SUBJECT_RULES, _normalize_text

rules = SUBJECT_RULES['chinese']
TOTAL_PAGES = 200

# 模拟各种 OCR 输出格式
test_cases = [
    {
        'name': '标准格式（单行完整）',
        'lines': [
            '第一单元',
            '1 春/朱自清 2',
            '2 济南的冬天/老舍 5',
            '3* 雨的四季/刘湛秋 9',
            '写作 热爱生活，热爱写作 17',
            '第二单元',
            '5 秋天的怀念/史铁生 20',
        ]
    },
    {
        'name': '合并行（单元+课文在一行）',
        'lines': [
            '第一单元 阅读 1 春/朱自清 2',
            '2 济南的冬天/老舍 5',
            '3* 雨的四季/刘湛秋 9',
            '写作 热爱生活，热爱写作 17',
        ]
    },
    {
        'name': '编号和标题分行',
        'lines': [
            '第一单元',
            '1',
            '春/朱自清 2',
            '2',
            '济南的冬天/老舍 5',
        ]
    },
    {
        'name': 'OCR 噪声（缺空格、全角等）',
        'lines': [
            '第一单元',
            '1春/朱自清 2',
            '2济南的冬天/老舍 5',
        ]
    },
    {
        'name': '春无编号（OCR 漏读编号）',
        'lines': [
            '第一单元',
            '春/朱自清 2',
            '济南的冬天/老舍 5',
        ]
    },
    {
        'name': '页码和标题分行',
        'lines': [
            '第一单元',
            '1 春/朱自清',
            '2',
            '2 济南的冬天/老舍',
            '5',
        ]
    },
    {
        'name': '春只有单字无页码',
        'lines': [
            '第一单元',
            '春',
            '朱自清 2',
            '济南的冬天 5',
        ]
    },
]

print("=" * 70)
print("OCR 目录解析测试")
print("=" * 70)

for tc in test_cases:
    # 模拟 OCR 输出：(text, page_num) 元组列表
    ocr_lines = [(line, 4) for line in tc['lines']]
    ocr_lines = [(_normalize_text(t), p) for t, p in ocr_lines]

    print(f"\n{'='*60}")
    print(f"测试: {tc['name']}")
    print(f"输入行:")
    for i, (t, _) in enumerate(ocr_lines):
        print(f"  [{i}] '{t}'")
    print("-" * 40)

    units = _parse_ocr_toc_lines(ocr_lines, rules, TOTAL_PAGES)

    if not units:
        print("  ❌ 解析失败：无单元返回！")
        continue

    for u in units:
        print(f"  单元: '{u['title']}' (page={u.get('page')})")
        for l in u['lessons']:
            if l['type'] == 'lesson':
                print(f"    课文: '{l['title']}' (startPage={l.get('startPage')})")
                for sub in l.get('children', []):
                    print(f"      子篇: '{sub['title']}' (startPage={sub.get('startPage')})")
            elif l['type'] == 'group':
                print(f"    栏目: '{l['title']}' (page={l.get('page')})")

    # 检查"春"是否被提取
    all_titles = []
    for u in units:
        for l in u['lessons']:
            all_titles.append(l['title'])
            for sub in l.get('children', []):
                all_titles.append(sub['title'])

    has_chun = any('春' in t for t in all_titles)
    print(f"\n  {'✅ 春已提取' if has_chun else '❌ 春未提取！'}")
