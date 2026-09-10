#!/usr/bin/env python3
"""创建模拟语文教材 PDF，测试 OCR 目录提取端到端流程。"""
try:
    import pymupdf as fitz
except ImportError:
    import fitz

doc = fitz.open()

# 第1-3页：封面、扉页、版权（空白页模拟）
for _ in range(3):
    doc.new_page()

# 第4页：目录页
toc_page = doc.new_page()
y = 80
line_h = 28

toc_entries = [
    ("目录", True),
    ("", False),
    ("第一单元", True),
    ("1 春/朱自清 ........... 2", False),
    ("2 济南的冬天/老舍 ..... 5", False),
    ("3* 雨的四季/刘湛秋 ... 9", False),
    ("写作 热爱生活，热爱写作 17", False),
    ("", False),
    ("第二单元", True),
    ("5 秋天的怀念/史铁生 . 20", False),
    ("6 散步/莫怀戚 ......... 24", False),
    ("写作 学会记事 ......... 28", False),
]

for text, is_title in toc_entries:
    if not text:
        y += line_h
        continue
    fs = 18 if is_title else 12
    toc_page.insert_text(fitz.Point(80, y), text, fontname="china-s", fontsize=fs)
    y += line_h

# 第5-14页：正文（每页有标题模拟正文）
lesson_titles = [
    "春",           # 第5页 = 印刷页2
    "朱自清",
    "济南的冬天",
    "老舍",
    "雨的四季",
    "刘湛秋",
    "秋天的怀念",
    "史铁生",
    "散步",
    "莫怀戚",
]
for title in lesson_titles:
    page = doc.new_page()
    page.insert_text(fitz.Point(100, 100), title, fontname="china-s", fontsize=24)

output = "/workspace/LearnWithMe-old/test_textbook.pdf"
doc.save(output)
doc.close()
print(f"✅ 测试 PDF 已创建: {output}")
