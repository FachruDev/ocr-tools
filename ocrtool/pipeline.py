"""Alur lengkap satu gambar: buka -> siapkan -> OCR -> susun baris."""

from __future__ import annotations

import io
import time
import uuid
from dataclasses import dataclass

from . import layout, preprocess
from .engine import TextBox, get_engine


@dataclass
class PageResult:
    id: str
    name: str
    width: int
    height: int
    image_jpeg: bytes  # gambar yang dipakai OCR (sudah diputar & diubah ukuran); koordinat kotak mengacu ke sini
    boxes: list[TextBox]  # urut sesuai urutan baca
    text: str
    layout_text: str
    seconds: float

    @property
    def score(self) -> float:
        if not self.boxes:
            return 0.0
        return sum(b.score for b in self.boxes) / len(self.boxes)

    def get_text(self, keep_layout: bool) -> str:
        return self.layout_text if keep_layout else self.text

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "width": self.width,
            "height": self.height,
            "text": self.text,
            "layout_text": self.layout_text,
            "score": round(self.score, 4),
            "seconds": round(self.seconds, 2),
            "boxes": [b.to_dict() for b in self.boxes],
        }


def _digit_weight(boxes: list[TextBox]) -> float:
    return sum(b.score * sum(ch.isdigit() for ch in b.text) for b in boxes)


def _read_seven_segment(bgr) -> list[TextBox]:
    """Coba semua varian preprocessing seven segment, ambil yang menghasilkan angka paling meyakinkan."""
    engine = get_engine()
    best: list[TextBox] = []
    for variant in preprocess.seven_segment_variants(bgr):
        boxes = engine.recognize(variant, use_cls=False)
        if _digit_weight(boxes) > _digit_weight(best):
            best = boxes
        # Sudah ada angka (min. 2 digit) yang sangat meyakinkan: varian lain tidak perlu dicoba
        if any(b.score >= 0.95 and sum(ch.isdigit() for ch in b.text) >= 2 for b in best):
            break
    return best


def process_image(data: bytes, name: str, enhance: bool = False, seven_segment: bool = False) -> PageResult:
    started = time.perf_counter()
    img = preprocess.normalize_size(preprocess.load_image(data))
    bgr = preprocess.to_bgr(img)
    if enhance:
        bgr = preprocess.enhance_contrast(bgr)

    boxes = _read_seven_segment(bgr) if seven_segment else get_engine().recognize(bgr)
    lines = layout.group_lines(boxes)

    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=88)
    return PageResult(
        id=uuid.uuid4().hex[:10],
        name=name,
        width=img.width,
        height=img.height,
        image_jpeg=buf.getvalue(),
        boxes=layout.ordered_boxes(lines),
        text=layout.to_plain_text(lines),
        layout_text=layout.to_layout_text(lines),
        seconds=time.perf_counter() - started,
    )
