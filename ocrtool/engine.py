"""Engine OCR. Saat ini memakai RapidOCR (model PaddleOCR via ONNX Runtime, berjalan offline)."""

from __future__ import annotations

import os
import threading
from dataclasses import dataclass

import numpy as np


def default_threads() -> int:
    """Jumlah thread CPU untuk ONNX Runtime.

    Memakai semua thread justru lambat & tidak stabil di CPU hybrid (core P + E, mis. Intel gen 12+),
    jadi dibatasi 4. Bisa diubah lewat env OCR_THREADS (mis. di server dengan banyak core).
    """
    env = os.environ.get("OCR_THREADS", "").strip()
    if env.isdigit() and int(env) > 0:
        return int(env)
    return max(1, min(4, (os.cpu_count() or 2) // 2))


@dataclass
class TextBox:
    text: str
    score: float
    # 4 titik [x, y] dalam piksel: kiri-atas, kanan-atas, kanan-bawah, kiri-bawah
    box: list[list[float]]

    def to_dict(self) -> dict:
        return {"text": self.text, "score": round(self.score, 4), "box": self.box}


class RapidOCREngine:
    name = "RapidOCR (PP-OCR, ONNX Runtime)"

    def __init__(self, text_score: float = 0.5):
        from rapidocr import RapidOCR

        self._ocr = RapidOCR(params={
            "Global.log_level": "error",
            "Global.text_score": text_score,
            "EngineConfig.onnxruntime.intra_op_num_threads": default_threads(),
        })
        self._text_score = text_score
        # Satu sesi ONNX dipakai bersama; kunci agar aman dipanggil dari banyak thread (server web).
        self._lock = threading.Lock()
        self._warm_up()

    def _warm_up(self) -> None:
        """Inferensi pertama ONNX jauh lebih lambat; lakukan sekali di awal dengan gambar kecil."""
        import cv2

        dummy = np.full((160, 640, 3), 255, dtype=np.uint8)
        cv2.putText(dummy, "Warm up 123", (20, 100), cv2.FONT_HERSHEY_SIMPLEX, 2, (0, 0, 0), 3)
        self._ocr(dummy)

    def recognize(self, bgr: np.ndarray, use_cls: bool = True, min_score: float | None = None) -> list[TextBox]:
        """use_cls=False mematikan deteksi teks terbalik (perlu untuk seven segment: 1999 bisa terbaca 6661).
        min_score mengganti batas skor minimum."""
        # Selalu kirim semua opsi: RapidOCR menyimpan opsi per panggilan untuk panggilan berikutnya
        score = self._text_score if min_score is None else max(min_score, 1e-3)
        with self._lock:
            out = self._ocr(bgr, use_det=True, use_cls=use_cls, use_rec=True, text_score=score)
        if out.boxes is None or out.txts is None:
            return []
        return [
            TextBox(str(text), float(score), np.asarray(box, dtype=float).round(1).tolist())
            for box, text, score in zip(out.boxes, out.txts, out.scores)
            if str(text).strip()
        ]

    def detect(self, bgr: np.ndarray, box_thresh: float = 0.5) -> list[list[list[float]]]:
        """Hanya cari lokasi teks (tanpa membaca). Mengembalikan daftar kotak 4 titik.
        box_thresh lebih rendah = lebih banyak kotak (berguna untuk segmen yang putus-putus)."""
        with self._lock:
            out = self._ocr(bgr, use_det=True, use_cls=False, use_rec=False, box_thresh=box_thresh)
            self._ocr(np.full((32, 32, 3), 255, np.uint8), use_det=False, use_cls=False, use_rec=True,
                      box_thresh=0.5)  # kembalikan box_thresh default (opsi per panggilan "menempel")
        if out.boxes is None:
            return []
        return [np.asarray(box, dtype=float).round(1).tolist() for box in out.boxes]

    def recognize_line(self, bgr: np.ndarray) -> tuple[str, float]:
        """Baca satu potongan berisi satu baris teks (tanpa tahap deteksi; cepat)."""
        with self._lock:
            out = self._ocr(bgr, use_det=False, use_cls=False, use_rec=True, text_score=1e-3)
        if not out.txts:
            return "", 0.0
        return str(out.txts[0]).strip(), float(out.scores[0])


_engine: RapidOCREngine | None = None
_engine_lock = threading.Lock()


def get_engine() -> RapidOCREngine:
    """Engine dibuat sekali (memuat model butuh beberapa detik) lalu dipakai ulang."""
    global _engine
    if _engine is None:
        with _engine_lock:
            if _engine is None:
                _engine = RapidOCREngine()
    return _engine


def engine_ready() -> bool:
    return _engine is not None


def engine_info() -> dict:
    import onnxruntime

    providers = [p.replace("ExecutionProvider", "") for p in onnxruntime.get_available_providers()]
    return {"engine": RapidOCREngine.name, "providers": providers, "ready": engine_ready()}
