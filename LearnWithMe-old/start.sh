#!/bin/bash
# LearnWithMe 服务启动脚本
# 确保所有依赖已安装，然后启动 HTTP server

set -e
cd "$(dirname "$0")"

# 检查并安装核心依赖
python3 -c "import pymupdf, pdfplumber, pypdfium2, pytesseract, PIL" 2>/dev/null || {
  echo "[startup] 安装缺失的 Python 依赖..."
  pip3 install pymupdf pdfplumber pypdfium2 pytesseract Pillow 2>&1 | tail -3
}

# 检查 tesseract 二进制
if ! command -v tesseract &>/dev/null; then
  echo "[startup] ⚠️ tesseract 未安装，OCR 兜底方案不可用"
  echo "[startup]   安装: apt-get install tesseract-ocr tesseract-ocr-chi-sim"
fi

echo "[startup] 依赖检查通过，启动 server.py..."
exec python3 server.py
