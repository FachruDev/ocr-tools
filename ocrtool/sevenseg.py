"""Pembaca display digital (seven segment).

Model OCR biasa dilatih untuk huruf cetak utuh, sedangkan angka seven segment tersusun dari
batang-batang terpisah. Akibatnya angka sering (a) tidak terdeteksi sama sekali, atau
(b) terdeteksi tapi salah/gagal dibaca. Modul ini menangani keduanya, bertahap:

1. OCR biasa; angka yang skornya meragukan dibaca ulang.
2. Deteksi ulang dengan ambang rendah untuk kotak yang terlewat (segmen putus-putus).
3. Pencarian klasik: komponen berbentuk batang (calon segmen) dikelompokkan jadi area angka.
   Ini menemukan angka LCD tipis yang sama sekali tidak terlihat oleh detektor.
4. Panel display (kaca LCD/LED persegi panjang) dibinarisasi secara lokal lalu dibaca.

"Dibaca ulang" = potongan dibuat beberapa versi hitam-putih (segmen mati dibuang,
celah antar segmen ditutup), lalu dipilih hasil yang paling meyakinkan.
"""

from __future__ import annotations

import re

import cv2
import numpy as np

from .engine import TextBox, get_engine

CROP_HEIGHT = 96  # tinggi potongan setelah diskalakan sebelum dibaca ulang
PANEL_HEIGHT = 240  # tinggi panel display setelah diluruskan
DET_MIN_SIDE = 736  # detektor RapidOCR memperbesar gambar sampai sisi terpendek sebesar ini
_NOT_DIGIT = re.compile(r"[^0-9]")
# Model bawaan bilingual Mandarin-Inggris; huruf Mandarin di display = salah baca
_CJK = re.compile(r"[　-鿿豈-﫿]")


def _digits(text: str) -> int:
    return len(_NOT_DIGIT.sub("", text))


def _rect(box: list[list[float]]) -> tuple[int, int, int, int]:
    xs, ys = [p[0] for p in box], [p[1] for p in box]
    return int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys))


def _overlap(a, b) -> float:
    """Bagian dari kotak a yang tertutup kotak b (0..1)."""
    ix = max(0, min(a[2], b[2]) - max(a[0], b[0]))
    iy = max(0, min(a[3], b[3]) - max(a[1], b[1]))
    area = max(1, (a[2] - a[0]) * (a[3] - a[1]))
    return ix * iy / area


# --------------------------------------------------------------- cari area angka


def find_segment_regions(gray: np.ndarray) -> list[tuple[int, int, int, int]]:
    """Cari area yang berisi kumpulan batang (segmen) - kandidat angka seven segment."""
    height, width = gray.shape
    short_side = min(height, width)
    block = max(31, short_side // 12) | 1
    regions = []
    for invert in (True, False):  # segmen gelap (LCD) lalu segmen terang (LED)
        mode = cv2.THRESH_BINARY_INV if invert else cv2.THRESH_BINARY
        binary = cv2.adaptiveThreshold(gray, 255, cv2.ADAPTIVE_THRESH_MEAN_C, mode, block, 12)
        count, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
        segments = []
        for x, y, w, h, area in stats[1:count]:
            long_side, thin_side = max(w, h), max(1, min(w, h))
            if not (short_side * 0.02 <= long_side <= short_side * 0.45):
                continue
            if long_side / thin_side < 2.2 or area / (w * h) < 0.35:
                continue  # bukan batang memanjang yang padat
            segments.append((x, y, w, h))
        if len(segments) < 2:
            continue

        # Gabungkan batang-batang yang berdekatan menjadi satu area angka.
        # Angka berderet ke samping, jadi penggabungan horizontal dibuat lebih jauh.
        canvas = np.zeros((height, width), np.uint8)
        for x, y, w, h in segments:
            seg_len = max(w, h)
            gx, gy = int(seg_len * 0.7), int(seg_len * 0.35)
            cv2.rectangle(canvas, (x - gx, y - gy), (x + w + gx, y + h + gy), 255, -1)
        count, labels, stats, _ = cv2.connectedComponentsWithStats(canvas, connectivity=8)
        for x, y, w, h, _ in stats[1:count]:
            members = [s for s in segments if x <= s[0] and s[0] + s[2] <= x + w and y <= s[1] and s[1] + s[3] <= y + h]
            if len(members) < 2:
                continue
            seg_len = np.median([max(s[2], s[3]) for s in members])
            if h < seg_len * 1.2:  # angka seven segment tingginya ~2 segmen
                continue
            if w * h > 0.5 * width * height:
                continue
            regions.append((x, y, x + w, y + h))
    return regions


def _order_quad(pts: np.ndarray) -> list[list[float]]:
    """Urutkan 4 titik menjadi kiri-atas, kanan-atas, kanan-bawah, kiri-bawah."""
    pts = pts.reshape(4, 2).astype(float)
    s, d = pts.sum(axis=1), np.diff(pts, axis=1).ravel()
    return [pts[np.argmin(s)].tolist(), pts[np.argmin(d)].tolist(),
            pts[np.argmax(s)].tolist(), pts[np.argmax(d)].tolist()]


def find_display_panels(gray: np.ndarray, max_panels: int = 3) -> list[list[list[float]]]:
    """Cari kaca/panel display: bidang persegi panjang (boleh agak miring) berukuran sedang."""
    height, width = gray.shape
    edges = cv2.Canny(cv2.GaussianBlur(gray, (5, 5), 0), 40, 120)
    edges = cv2.dilate(edges, np.ones((3, 3), np.uint8))
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    found: list[tuple[float, tuple[int, int, int, int], list[list[float]]]] = []
    for contour in contours:
        approx = cv2.approxPolyDP(contour, 0.03 * cv2.arcLength(contour, True), True)
        if len(approx) != 4 or not cv2.isContourConvex(approx):
            continue
        area = cv2.contourArea(approx)
        x, y, w, h = cv2.boundingRect(approx)
        if not (0.004 * width * height <= area <= 0.6 * width * height):
            continue
        if not (1.1 <= w / h <= 8) or area < 0.7 * w * h:
            continue
        found.append((area, (x, y, x + w, y + h), _order_quad(approx)))

    panels: list[tuple[tuple[int, int, int, int], list[list[float]]]] = []
    for _, rect, quad in sorted(found, key=lambda f: -f[0]):
        if any(_overlap(rect, r) > 0.8 and _overlap(r, rect) > 0.8 for r, _ in panels):
            continue  # hampir sama dengan panel yang sudah ada (garis tepi dalam/luar)
        panels.append((rect, quad))
    # Panel kecil yang berada di dalam panel besar biasanya kaca display-nya: dahulukan
    panels.sort(key=lambda p: (p[0][2] - p[0][0]) * (p[0][3] - p[0][1]))
    return [quad for _, quad in panels[:max_panels]]


def _panel_variants(panel: np.ndarray) -> list[np.ndarray]:
    """Binarisasi di dalam satu panel display (ambang Otsu lokal) + penyambung segmen."""
    height = panel.shape[0]
    _, otsu = cv2.threshold(panel, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    dark_text = np.count_nonzero(otsu == 0) < otsu.size / 2
    text = (otsu == 0) if dark_text else (otsu == 255)
    masks = [text]
    values = panel[text]
    if values.size > 50:
        t2, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        masks.append(((panel < t2) if dark_text else (panel > t2)) & text)
    out = []
    for mask in masks:
        segments = mask.astype(np.uint8) * 255
        for frac in (0.035, 0.06):
            k = max(3, round(height * frac))
            joined = cv2.morphologyEx(segments, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
            # Detektor memperbesar gambar sampai sisi terpendek >= 736 px; panel yang pendek & lebar
            # jadi sangat besar dan lambat. Tambah margin putih (kanan/bawah) agar tidak perlu diperbesar.
            pad_h, pad_w = max(0, DET_MIN_SIDE - joined.shape[0]), max(0, DET_MIN_SIDE - joined.shape[1])
            canvas = cv2.copyMakeBorder(255 - joined, 0, pad_h, 0, pad_w, cv2.BORDER_CONSTANT, value=255)
            out.append(cv2.cvtColor(canvas, cv2.COLOR_GRAY2BGR))
    return out


def read_panel(gray: np.ndarray, quad: list[list[float]]) -> list[TextBox]:
    """Baca angka di dalam satu panel display; koordinat dikembalikan ke gambar asli."""
    pts = np.float32(quad)
    width = max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[3] - pts[2]))
    height = max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2]))
    scale = PANEL_HEIGHT / max(height, 1)  # samakan ukuran panel
    out_w, out_h = max(8, int(width * scale)), PANEL_HEIGHT
    dst = np.float32([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]])
    matrix = cv2.getPerspectiveTransform(pts, dst)
    panel = cv2.warpPerspective(gray, matrix, (out_w, out_h), flags=cv2.INTER_CUBIC)
    inverse = np.linalg.inv(matrix)

    engine = get_engine()
    best: list[TextBox] = []
    for variant in _panel_variants(panel):
        boxes = [b for b in engine.recognize(variant, use_cls=False) if _digits(b.text)]
        if _digit_weight(boxes) > _digit_weight(best):
            best = boxes
        if any(b.score >= 0.95 and _digits(b.text) >= 2 for b in best):
            break
    mapped = []
    for b in best:
        back = cv2.perspectiveTransform(np.float32(b.box).reshape(-1, 1, 2), inverse).reshape(-1, 2)
        mapped.append(TextBox(b.text, b.score, back.round(1).tolist()))
    return mapped


def _digit_weight(boxes: list[TextBox]) -> float:
    return sum(b.score * _digits(b.text) for b in boxes)


# --------------------------------------------------------------- baca ulang potongan


def _binarize_variants(crop: np.ndarray) -> list[np.ndarray]:
    """Beberapa versi hitam-di-atas-putih dari potongan display."""
    _, otsu = cv2.threshold(crop, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    # Teks/segmen adalah kelas yang lebih sedikit pikselnya
    dark_text = np.count_nonzero(otsu == 0) < otsu.size / 2
    text = (otsu == 0) if dark_text else (otsu == 255)

    masks = [text]
    # Ambang kedua di dalam kelas "teks": membuang segmen mati yang tampak samar
    values = crop[text]
    if values.size > 50:
        t2, _ = cv2.threshold(values.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
        strict = (crop < t2) if dark_text else (crop > t2)
        masks.append(strict & text)

    out = []
    for mask in masks:
        segments = mask.astype(np.uint8) * 255
        for frac in (0.0, 0.07, 0.13):
            joined = segments
            if frac:
                k = max(3, round(CROP_HEIGHT * frac))
                joined = cv2.morphologyEx(segments, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_RECT, (k, k)))
            out.append(255 - joined)
    return out


def _quality(text: str, score: float) -> float:
    core = re.sub(r"[\s.:,\-°]", "", text)
    if not core:
        return 0.0
    digit_frac = _digits(core) / len(core)
    return score * (0.6 + 0.4 * digit_frac)


def _crop_quad(gray: np.ndarray, quad: list[list[float]], pad_frac: float = 0.15) -> np.ndarray | None:
    """Potong kotak 4 titik (boleh miring) menjadi persegi panjang lurus, diberi sedikit margin."""
    pts = np.float32(quad)
    width = max(np.linalg.norm(pts[0] - pts[1]), np.linalg.norm(pts[3] - pts[2]))
    height = max(np.linalg.norm(pts[0] - pts[3]), np.linalg.norm(pts[1] - pts[2]))
    if width < 6 or height < 6:
        return None
    ux = (pts[1] - pts[0]) / max(1e-6, np.linalg.norm(pts[1] - pts[0]))
    uy = (pts[3] - pts[0]) / max(1e-6, np.linalg.norm(pts[3] - pts[0]))
    pad = height * pad_frac + 2
    src = np.float32([pts[0] - (ux + uy) * pad, pts[1] + (ux - uy) * pad,
                      pts[2] + (ux + uy) * pad, pts[3] + (uy - ux) * pad])
    out_w, out_h = int(width + 2 * pad), int(height + 2 * pad)
    dst = np.float32([[0, 0], [out_w, 0], [out_w, out_h], [0, out_h]])
    crop = cv2.warpPerspective(gray, cv2.getPerspectiveTransform(src, dst), (out_w, out_h),
                               flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE)
    scale = CROP_HEIGHT / crop.shape[0]
    return cv2.resize(crop, None, fx=scale, fy=scale, interpolation=cv2.INTER_CUBIC)


def read_region(gray: np.ndarray, quad: list[list[float]]) -> tuple[str, float]:
    crop = _crop_quad(gray, quad)
    if crop is None:
        return "", 0.0
    engine = get_engine()
    text, score = engine.recognize_line(cv2.cvtColor(crop, cv2.COLOR_GRAY2BGR))
    if _digits(text) == 0 and score >= 0.75:
        return text, score  # teks biasa yang sudah terbaca jelas (label, merek): biarkan

    best_text, best_score, best_quality = text, score, _quality(text, score)
    for variant in _binarize_variants(crop):
        v_text, v_score = engine.recognize_line(cv2.cvtColor(variant, cv2.COLOR_GRAY2BGR))
        quality = _quality(v_text, v_score)
        if _digits(v_text) and quality > best_quality:
            best_text, best_score, best_quality = v_text, v_score, quality
    return best_text, best_score


# --------------------------------------------------------------- alur lengkap


def recognize(bgr: np.ndarray, min_score: float = 0.5) -> list[TextBox]:
    gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
    engine = get_engine()

    # 1) OCR biasa (potongan bawaan RapidOCR paling bagus untuk teks biasa)
    results: list[TextBox] = []
    for box in engine.recognize(bgr, use_cls=False):
        if _digits(box.text) and box.score < 0.95:  # angka yang masih meragukan: coba baca ulang
            text, score = read_region(gray, box.box)
            if _digits(text) and _quality(text, score) > _quality(box.text, box.score):
                box = TextBox(text, score, box.box)
        results.append(box)
    known = [_rect(b.box) for b in results]

    def is_new(rect) -> bool:
        return not any(_overlap(rect, k) > 0.5 or _overlap(k, rect) > 0.5 for k in known)

    # 2) Kotak yang terdeteksi lemah (segmen putus-putus) tapi tidak terbaca di langkah 1
    for quad in engine.detect(bgr, box_thresh=0.3):
        rect = _rect(quad)
        if not is_new(rect):
            continue
        text, score = read_region(gray, quad)
        if _digits(text) and score >= min_score:
            results.append(TextBox(text, score, quad))
            known.append(rect)

    # 3) Area angka yang sama sekali tidak terdeteksi oleh detektor teks
    for rect in find_segment_regions(gray):
        if not is_new(rect):
            continue
        x0, y0, x1, y1 = rect
        quad = [[x0, y0], [x1, y0], [x1, y1], [x0, y1]]
        text, score = read_region(gray, quad)
        # Satu batang lepas (tepi benda, garis) mudah terbaca "1": abaikan hasil sependek itu
        if len(re.sub(r"[\s.:,\-]", "", text)) < 2:
            continue
        if _digits(text) and score >= min_score:
            results.append(TextBox(text, score, [[float(v) for v in p] for p in quad]))
            known.append(rect)

    # 4) Panel display: binarisasi lokal di dalam kaca display (angka berongga/kontras rendah).
    #    Dilewati bila di dalam panel sudah ada angka yang terbaca meyakinkan (hemat waktu).
    for quad in find_display_panels(gray):
        panel_rect = _rect(quad)
        if any(_digits(b.text) >= 2 and b.score >= 0.9 and _overlap(_rect(b.box), panel_rect) > 0.8 for b in results):
            continue
        panel_boxes = read_panel(gray, quad)
        for box in panel_boxes:
            rect = _rect(box.box)
            clashes = [b for b in results if _overlap(rect, _rect(b.box)) > 0.3 or _overlap(_rect(b.box), rect) > 0.3]
            # Ganti hasil lama di area yang sama hanya jika hasil panel lebih lengkap & meyakinkan
            if all(_digits(c.text) and _digit_weight([box]) > _digit_weight([c]) for c in clashes):
                results = [b for b in results if b not in clashes] + [box]
        if any(_digits(b.text) >= 2 and b.score >= 0.9 for b in panel_boxes):
            break  # display utama sudah terbaca; panel lain tidak perlu

    return [b for b in results if b.score >= min_score and not _CJK.search(b.text)]
