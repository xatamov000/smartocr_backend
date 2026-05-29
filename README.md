# SmartArchive OCR — Patch v3

Sizning loyihangizdagi mavjud fayllar uchun to'liq almashtiruvchi
(drop-in replacement) versiyalar.

## Qanday qo'llash

### Backend (`smartocr_backend`)

Quyidagi fayllarni mavjud fayllar ustiga **to'liq almashtirish** orqali ko'chiring:

| Yangi fayl                                     | Loyihangizda joylashuv                  | Holat        |
|------------------------------------------------|-----------------------------------------|--------------|
| `backend/app/main.py`                          | `app/main.py`                           | Almashtirish |
| `backend/app/services/ocr_engine.py`           | `app/services/ocr_engine.py`            | Almashtirish |
| `backend/app/services/ocr_pipeline.py`         | `app/services/ocr_pipeline.py`          | Almashtirish |
| `backend/app/services/text_normalize.py`       | `app/services/text_normalize.py`        | **YANGI**    |
| `backend/app/utils/preprocess_image.py`        | `app/utils/preprocess_image.py`         | Almashtirish |
| `backend/tests/test_homoglyph.py`              | `tests/test_homoglyph.py`               | **YANGI**    |
| `backend/tests/test_normalize.py`              | `tests/test_normalize.py`               | **YANGI**    |

> **Eslatma:** loyihangizdagi `app/services/__init__.py`, `app/services/layout_engine.py`,
> `app/export/word_export.py`, `app/docx_text_service.py` va boshqa fayllarga
> hech qanday o'zgartirish kerak emas — ular avvalgidek ishlaydi.

### Flutter (`arxive` / `smartarxiv_flutter`)

| Yangi fayl                                                | Loyihangizda joylashuv                          | Holat        |
|-----------------------------------------------------------|-------------------------------------------------|--------------|
| `flutter_app/lib/services/image_compress_service.dart`    | `lib/services/image_compress_service.dart`      | Almashtirish |
| `flutter_app/lib/pages/scan_page.dart`                    | `lib/pages/scan_page.dart`                      | Almashtirish |

> Boshqa Flutter fayllariga (api_service.dart, ocr_api_service.dart, va h.k.)
> tegmaslik kerak.

## Asosiy o'zgarishlar — qisqacha

### Backend

1. **`ocr_engine.py`**:
   - `lang='latin'` → `lang='en'` (aniqlik uchun)
   - `lang='ru'` → `lang='cyrillic'` (Kirill recognizer'i to'g'ri chaqirilishi uchun)
   - Token-darajadagi homoglyph aniqlash (`Pyrkoscxaa` → garble deb tutiladi)
   - `_should_try_cyrillic`: yuqori ishonch bilan ham garble bo'lsa CYR'ni sinaydi
   - G'olib tanlash: garble bayrog'i ishonchdan ustun
   - `det_limit_side_len`: 4096 → 1920 (≈2× tezroq, sifatda farq yo'q)
   - `det_db_box_thresh`: 0.6 → 0.3 (oqsh matn yo'qolmaydi)
   - `drop_score`: default 0.5 → 0.3

2. **`preprocess_image.py`**:
   - **YANGI**: telefon UI bandlarini kesish (`_crop_phone_chrome`)
   - "Tools / Mobile View / Share / Edit on PC / School Tools" qatorlari
     OCR'ga endi kirmaydi
   - Ehtiyotkor: kesish faqat 50%+ tasvirni saqlaganda

3. **`text_normalize.py`** (yangi):
   - `o'` → `oʻ`, `g'` → `gʻ` (modifier letter ʻ U+02BB)
   - Glottal stop: `ma'lum` → `maʼlum` (ʼ U+02BC)
   - Aralash token Kirill/Lotin homoglif tuzatish
   - NFC normalizatsiya (DOCX'da to'g'ri renderlash)
   - Idempotent: ikki marta chaqirish bir xil natija beradi

4. **`ocr_pipeline.py`**:
   - Geometriyaga asoslangan paragraf birlashtirish (vertikal bo'shliqdan
     foydalanish, faqat uzunlik emas)
   - `_blocks_to_text`: paragraflar orasida bo'sh qator chiqarish
   - Sarlavhalar: ≥70% katta harf talab qilish (false positive kamaytirish)
   - Yangi shovqin patternlari: `Scan_20260507_*`, `1 ta qurilma`,
     `Tools|Mobile View|Share`...
   - `text_normalize.normalize()` chaqiriladi

5. **`main.py`**:
   - FastAPI lifespan startup: ikkala PaddleOCR modelini oldindan yuklash
   - Birinchi mijoz endi 30-60s kutmaydi

### Flutter

1. **`image_compress_service.dart`**:
   - **Screenshot'lar (PNG, uzun aspect)**: hech qachon JPEG'ga qayta kodlanmaydi
   - JPEG sifati: 80 → 92 (OCR-xavfsiz, matn chetlarida ringing yo'q)
   - Faqat uzun chet > 3500px bo'lsagina kichraytirish
   - 1080-1440px screenshot'lar bayt-aniq native sifatda yetib boradi

2. **`scan_page.dart`**:
   - `pickImage(..., imageQuality: 90)` → `imageQuality` parametri olib tashlandi
   - `pickMultiImage(imageQuality: 85)` → `imageQuality` parametri olib tashlandi
   - Endi qayta kodlash bir marta (compress'da q=92), ikki marta emas

## Sinov

```bash
# Backend testlar (paddleocr o'rnatilgan bo'lishi shart emas — testlar
# soft mock'lar bilan ishlaydi)
cd backend
python -m pytest tests/ -v
```

Tabiiy ravishda har bir test alohida ham qo'lda chaqirilishi mumkin —
ular `paddleocr` ni import qilmaydi, faqat sof Python helperlarni sinashadi.

## Qo'llash tartibi (tavsiya etiladi)

1. **Avval backend'ni yangilang** (eng katta ta'sirli o'zgarish):
   ```
   backend/app/services/ocr_engine.py
   backend/app/services/text_normalize.py     # yangi
   backend/app/services/ocr_pipeline.py
   backend/app/utils/preprocess_image.py
   backend/app/main.py
   backend/tests/                              # yangi
   ```
   Server'ni qayta ishga tushiring.

2. **Flutter'ni yangilang**:
   ```
   flutter_app/lib/services/image_compress_service.dart
   flutter_app/lib/pages/scan_page.dart
   ```
   Ilovani qayta build qiling.

3. **Test qiling**: avval kompyuteringizdan Image 5 (Kirill OCR muammosi)
   ni server'ga yuboring va `Pyrkoscxaa` o'rniga `Рутковская` chiqishini
   tekshiring. Bu eng katta o'zgarishni isbotlaydi.

## Muvaffaqiyat ko'rsatkichlari (kutilgan)

- **Image 5 (Kirill matn)**: OCR natijasi tushunarsizdan ≥95% to'g'ri
  belgilarga
- **Image 1 (Uzbek-Latin screenshot)**: telefon UI matni natijaga kirmaydi,
  apostroflar to'g'ri (`oʻzbek`, `boʻladi`)
- **Image 2 (English screenshot)**: avvalgidek mukammal, sarlavhalar
  ajratilgan, paragraflar to'g'ri
- **Birinchi so'rov kechikishi**: 30-60s → ~3s
- **Server ishlash vaqti har bir sahifa**: ~2× tezroq
  (det_limit_side_len 4096 → 1920)