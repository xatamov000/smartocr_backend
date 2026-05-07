import fitz  # PyMuPDF
import os
import tempfile
from PIL import Image


class CompressionLevel:
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


def compress_pdf(input_path: str, output_path: str, level: str):
    """
    Deterministic PDF compression engine.
    Har sahifani raster qilib qayta JPEG encode qiladi.
    """

    if not os.path.exists(input_path):
        raise FileNotFoundError("Input file topilmadi")

    original_size = os.path.getsize(input_path)

    # Level parametrlar
    if level == CompressionLevel.LOW:
        dpi = 200
        quality = 80
    elif level == CompressionLevel.MEDIUM:
        dpi = 150
        quality = 60
    elif level == CompressionLevel.HIGH:
        dpi = 100
        quality = 40
    else:
        raise ValueError("Invalid compression level")

    try:
        doc = fitz.open(input_path)
        new_doc = fitz.open()

        for page in doc:
            zoom = dpi / 72
            mat = fitz.Matrix(zoom, zoom)

            # Alpha o‘chirildi (stability uchun)
            pix = page.get_pixmap(matrix=mat, alpha=False)

            # Rang formatini aniqlash
            if pix.n == 1:
                mode = "L"
            elif pix.n == 3:
                mode = "RGB"
            elif pix.n == 4:
                mode = "RGBA"
            else:
                mode = "RGB"

            img = Image.frombytes(mode, [pix.width, pix.height], pix.samples)

            # JPEG faqat RGB yoki L qabul qiladi
            if img.mode not in ("RGB", "L"):
                img = img.convert("RGB")

            # Temp image fayl
            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                img.save(tmp_img.name, "JPEG", quality=quality, optimize=True)
                img_path = tmp_img.name

            # Yangi PDF sahifa
            rect = fitz.Rect(0, 0, pix.width, pix.height)
            pdf_page = new_doc.new_page(width=pix.width, height=pix.height)
            pdf_page.insert_image(rect, filename=img_path)

            os.unlink(img_path)

        new_doc.save(output_path, deflate=True)
        new_doc.close()
        doc.close()

    except Exception as e:
        raise Exception(f"Compression engine error: {str(e)}")

    # Hajm nazorati
    new_size = os.path.getsize(output_path)

    # Agar siqish foyda bermasa originalni qaytarish
    if new_size >= original_size:
        with open(input_path, "rb") as f_in:
            with open(output_path, "wb") as f_out:
                f_out.write(f_in.read())