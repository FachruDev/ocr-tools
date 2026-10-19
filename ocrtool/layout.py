"""Menyusun kotak-kotak hasil OCR menjadi baris dan paragraf sesuai urutan baca.

Foto dari HP biasanya sedikit miring, jadi semua kotak "diluruskan" dulu memakai
kemiringan rata-rata teks, baru dikelompokkan per baris (atas ke bawah, kiri ke kanan).
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass, field

from .engine import TextBox

# Jarak antarbaris lebih dari (faktor x tinggi huruf) dianggap pergantian paragraf.
PARAGRAPH_GAP = 0.9


@dataclass
class _Item:
    box: TextBox
    x0: float
    x1: float
    y0: float
    y1: float

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2

    @property
    def height(self) -> float:
        return max(1.0, self.y1 - self.y0)


@dataclass
class Line:
    items: list[_Item] = field(default_factory=list)

    @property
    def y0(self) -> float:
        return min(i.y0 for i in self.items)

    @property
    def y1(self) -> float:
        return max(i.y1 for i in self.items)

    @property
    def cy(self) -> float:
        return statistics.fmean(i.cy for i in self.items)

    @property
    def height(self) -> float:
        return statistics.median(i.height for i in self.items)


def _angle(box: TextBox) -> float:
    (x0, y0), (x1, y1) = box.box[0], box.box[1]
    return math.atan2(y1 - y0, x1 - x0)


def group_lines(boxes: list[TextBox]) -> list[Line]:
    if not boxes:
        return []
    angle = statistics.median(_angle(b) for b in boxes)
    cos, sin = math.cos(-angle), math.sin(-angle)

    items = []
    for b in boxes:
        pts = [(x * cos - y * sin, x * sin + y * cos) for x, y in b.box]
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        items.append(_Item(b, min(xs), max(xs), min(ys), max(ys)))
    items.sort(key=lambda i: i.cy)

    lines: list[Line] = []
    for item in items:
        best, best_dist = None, None
        for line in lines[-3:]:  # cukup cek beberapa baris terakhir karena sudah urut vertikal
            dist = abs(item.cy - line.cy)
            if dist < 0.5 * min(item.height, line.height) and (best_dist is None or dist < best_dist):
                best, best_dist = line, dist
        if best is None:
            lines.append(Line([item]))
        else:
            best.items.append(item)

    for line in lines:
        line.items.sort(key=lambda i: i.x0)
    lines.sort(key=lambda ln: ln.cy)
    return lines


def ordered_boxes(lines: list[Line]) -> list[TextBox]:
    return [item.box for line in lines for item in line.items]


def _blank_lines_before(prev: Line | None, line: Line, unit: float, layout: bool) -> int:
    if prev is None:
        return 0
    gap = line.y0 - prev.y1
    if gap <= PARAGRAPH_GAP * unit:
        return 0
    if not layout:
        return 1
    return min(3, max(1, round(gap / (1.3 * unit))))


def to_plain_text(lines: list[Line]) -> str:
    """Teks saja: satu baris per baris gambar, paragraf dipisah baris kosong."""
    if not lines:
        return ""
    unit = statistics.median(i.height for ln in lines for i in ln.items)
    out: list[str] = []
    prev = None
    for line in lines:
        out.extend([""] * _blank_lines_before(prev, line, unit, layout=False))
        out.append(" ".join(i.box.text.strip() for i in line.items))
        prev = line
    return "\n".join(out)


def to_layout_text(lines: list[Line]) -> str:
    """Pertahankan tata letak: posisi kolom ditiru dengan spasi (cocok untuk tabel/faktur)."""
    if not lines:
        return ""
    all_items = [i for ln in lines for i in ln.items]
    unit = statistics.median(i.height for i in all_items)
    char_w = statistics.median((i.x1 - i.x0) / max(1, len(i.box.text)) for i in all_items)
    char_w = max(char_w, 1.0)
    left = min(i.x0 for i in all_items)

    out: list[str] = []
    prev = None
    for line in lines:
        out.extend([""] * _blank_lines_before(prev, line, unit, layout=True))
        row = ""
        for item in line.items:
            col = round((item.x0 - left) / char_w)
            if col <= 2:  # geser kecil akibat perspektif foto, bukan indentasi sungguhan
                col = 0
            if row:
                col = max(col, len(row) + 1)
            row = row.ljust(col) + item.box.text.strip()
        out.append(row.rstrip())
        prev = line
    return "\n".join(out)
