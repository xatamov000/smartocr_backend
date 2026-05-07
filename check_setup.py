"""
SmartOCR Setup Checker
Ishlatish: python check_setup.py

Barcha kerakli narsalar o'rnatilganligini tekshiradi.
"""

import sys
import subprocess
import socket

print("=" * 50)
print("  SmartOCR Setup Checker")
print("=" * 50)

errors = []
warnings = []

# 1. Python versiyasi
print(f"\n[1] Python: {sys.version.split()[0]}", end=" ")
major, minor = sys.version_info[:2]
if major == 3 and minor >= 9:
    print("✓")
else:
    print("✗ (3.9+ kerak)")
    errors.append("Python 3.9+ o'rnating")

# 2. Tesseract
print("[2] Tesseract:", end=" ")
try:
    result = subprocess.run(
        ["tesseract", "--version"],
        capture_output=True, text=True, timeout=5
    )
    version = result.stdout.split('\n')[0] if result.stdout else result.stderr.split('\n')[0]
    print(f"✓ ({version.strip()})")
except FileNotFoundError:
    print("✗ (topilmadi)")
    errors.append("Tesseract o'rnatilmagan")

# 3. Tesseract til fayllari
print("[3] Tesseract tillar:", end=" ")
try:
    result = subprocess.run(
        ["tesseract", "--list-langs"],
        capture_output=True, text=True, timeout=5
    )
    output = result.stdout + result.stderr
    langs = [l.strip() for l in output.split('\n') if l.strip() and 'List' not in l]
    
    needed = ["eng", "uzb", "uzb_cyrl", "rus"]
    found = [l for l in needed if l in langs]
    missing = [l for l in needed if l not in langs]
    
    if missing:
        print(f"⚠ (topilmadi: {', '.join(missing)})")
        warnings.append(f"Til fayllari kerak: {', '.join(missing)}")
    else:
        print(f"✓ ({', '.join(found)})")
except Exception as e:
    print(f"✗ ({e})")

# 4. Python kutubxonalar
packages = {
    "fastapi": "fastapi",
    "uvicorn": "uvicorn",
    "cv2": "opencv-python-headless",
    "pytesseract": "pytesseract",
    "docx": "python-docx",
    "numpy": "numpy",
    "PIL": "Pillow",
}

print("[4] Python kutubxonalar:")
for module, package in packages.items():
    try:
        __import__(module)
        print(f"     {package}: ✓")
    except ImportError:
        print(f"     {package}: ✗")
        errors.append(f"pip install {package}")

# 5. IP manzil
print("[5] Kompyuter IP manzili:", end=" ")
try:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.connect(("8.8.8.8", 80))
    ip = s.getsockname()[0]
    s.close()
    print(f"\n     >>> http://{ip}:8000 <<<")
    print(f"     (Bu manzilni Flutter ilovasida ishlating)")
except Exception:
    print("? (aniqlab bo'lmadi)")

# Natija
print("\n" + "=" * 50)
if errors:
    print("XATOLAR (hal qilish kerak):")
    for e in errors:
        print(f"  ✗ {e}")
if warnings:
    print("OGOHLANTIRISHLAR:")
    for w in warnings:
        print(f"  ⚠ {w}")
if not errors:
    print("✓ Barcha asosiy komponentlar tayyor!")
    print("  Server ishga tushirish: start_server.bat")
print("=" * 50)