"""Persiapan gambar sebelum OCR: rotasi EXIF, ukuran, dan peningkatan kontras."""

from __future__ import annotations

import io

import cv2
import numpy as np
from PIL import Image, ImageOps

try:  # Foto iPhone (.heic) - opsional, hanya jika pillow-heif terpasang
    from pillow_heif import register_heif_opener

    register_heif_opener()
except ImportError:
    pass

IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".heic", ".heif"}

# Gambar lebih besar dari ini diperkecil (lebih cepat, akurasi tetap),
# gambar lebih kecil dari MIN_SIDE diperbesar (huruf kecil di screenshot jadi terbaca).
MAX_SIDE = 3000
MIN_SIDE = 1000


def load_image(data: bytes) -> Image.Image:
    """Buka gambar dari bytes, perbaiki orientasi foto HP, dan jadikan RGB."""
    img = Image.open(io.BytesIO(data))
    img = ImageOps.exif_transpose(img)  # foto HP sering tersimpan miring + tag EXIF
    if img.mode in ("RGBA", "LA") or (img.mode == "P" and "transparency" in img.info):
        rgba = img.convert("RGBA")
        background = Image.new("RGB", rgba.size, "white")
        background.paste(rgba, mask=rgba.getchannel("A"))
        return background
    return img.convert("RGB")


def normalize_size(img: Image.Image) -> Image.Image:
    longest = max(img.size)
    if longest > MAX_SIDE:
        scale = MAX_SIDE / longest
    elif longest < MIN_SIDE:
        scale = min(2.0, MIN_SIDE / longest)
    else:
        return img
    size = (max(1, round(img.width * scale)), max(1, round(img.height * scale)))
    return img.resize(size, Image.LANCZOS)


def to_bgr(img: Image.Image) -> np.ndarray:
    return cv2.cvtColor(np.asarray(img), cv2.COLOR_RGB2BGR)


def seven_segment_variants(bgr: np.ndarray) -> list[np.ndarray]:
    """Versi gambar untuk display digital (seven segment), hitam di atas putih.

    Segmen yang menyala dipisahkan dari segmen mati (yang sering tetap terlihat samar),
    lalu celah antar segmen ditutup agar angka tampak seperti huruf cetak utuh.
    Dibuat beberapa varian (LED terang / LCD gelap, dua ukuran penyambung) karena
    tiap display berbeda; pipeline memilih hasil yang paling meyakinkan.
    """
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    value = bgr.max(axis=2)  # kanal terang HSV: LED merah/hijau tetap terang di sini
    base = max(3, round(min(bgr.shape[:2]) / 60))
    variants = []
    for source in (value, 255 - gray):  # LED (segmen terang) lalu LCD (segmen gelap)
        _, segments = cv2.threshold(source, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        for size in (base, round(base * 1.7)):
            kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (size, size))
            joined = cv2.morphologyEx(segments, cv2.MORPH_CLOSE, kernel)
            variants.append(cv2.cvtColor(255 - joined, cv2.COLOR_GRAY2BGR))
    return variants


def enhance_contrast(bgr: np.ndarray) -> np.ndarray:
    """CLAHE pada kanal terang: membantu foto gelap, pudar, atau kena bayangan."""
    lab = cv2.cvtColor(bgr, cv2.COLOR_BGR2LAB)
    lightness, a, b = cv2.split(lab)
    lightness = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(lightness)
    return cv2.cvtColor(cv2.merge((lightness, a, b)), cv2.COLOR_LAB2BGR)
