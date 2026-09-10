#!/usr/bin/env python3
"""测试不同 OCR PSM 模式和 DPI 对中文识别质量的影响。"""
try:
    import pymupdf as fitz
except ImportError:
    import fitz
import pytesseract
from PIL import Image
import io

doc = fitz.open("/workspace/LearnWithMe-old/test_textbook.pdf")
page = doc[3]  # 第4页 = 目录页

# 测试不同 DPI 和 PSM 组合
configs = [
    (300, '--psm 6 -l chi_sim+eng'),
    (300, '--psm 3 -l chi_sim+eng'),
    (300, '--psm 4 -l chi_sim+eng'),
    (400, '--psm 6 -l chi_sim+eng'),
    (400, '--psm 3 -l chi_sim+eng'),
    (300, '--psm 6 -l chi_sim'),
    (400, '--psm 6 -l chi_sim'),
]

for dpi, config in configs:
    mat = fitz.Matrix(dpi/72, dpi/72)
    pix = page.get_pixmap(matrix=mat)
    img = Image.open(io.BytesIO(pix.tobytes("png")))
    text = pytesseract.image_to_string(img, config=config)
    # 统计识别质量
    has_chun = '春' in text
    has_diyi = '第一单元' in text or '第一' in text
    has_jinan = '济南' in text
    has_sandan = '散步' in text
    score = sum([has_chun, has_diyi, has_jinan, has_sandan])
    print(f"\n{'='*60}")
    print(f"DPI={dpi}, config='{config}'")
    print(f"识别质量: 春={has_chun} 第一={has_diyi} 济南={has_jinan} 散步={has_sandan} ({score}/4)")
    print(f"文本前300字: {text[:300]}")

doc.close()
