"""Mode command line, cocok untuk memproses banyak gambar / satu folder sekaligus.

Contoh:
    python -m ocrtool foto.jpg
    python -m ocrtool folder_foto/ -f txt docx pdf -o hasil/
    python -m ocrtool folder_foto/ -f docx --layout --gabung
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .exporters import FORMATS, build_export
from .preprocess import IMAGE_EXTENSIONS


def collect_images(inputs: list[str], recursive: bool) -> list[Path]:
    files: list[Path] = []
    for raw in inputs:
        path = Path(raw)
        if path.is_dir():
            pattern = "**/*" if recursive else "*"
            files.extend(sorted(p for p in path.glob(pattern) if p.suffix.lower() in IMAGE_EXTENSIONS))
        elif path.is_file():
            files.append(path)
        else:
            print(f"  ! tidak ditemukan: {raw}", file=sys.stderr)
    return files


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="ocrtool", description="Baca teks dari gambar (offline).")
    parser.add_argument("input", nargs="+", help="file gambar atau folder")
    parser.add_argument("-f", "--format", nargs="+", default=["txt"], choices=list(FORMATS),
                        help="format output (boleh lebih dari satu). Default: txt")
    parser.add_argument("-o", "--output", default="hasil_ocr", help="folder output. Default: hasil_ocr")
    parser.add_argument("--layout", action="store_true", help="pertahankan tata letak (kolom/tabel)")
    parser.add_argument("--gabung", "--combine", dest="combine", action="store_true",
                        help="gabungkan semua gambar jadi satu file per format")
    parser.add_argument("--kontras", "--enhance", dest="enhance", action="store_true",
                        help="tingkatkan kontras (foto gelap/pudar)")
    parser.add_argument("-r", "--recursive", action="store_true", help="ikut proses subfolder")
    args = parser.parse_args(argv)

    files = collect_images(args.input, args.recursive)
    if not files:
        print("Tidak ada file gambar untuk diproses.", file=sys.stderr)
        return 1

    from .pipeline import process_image

    print(f"Memuat engine OCR & memproses {len(files)} gambar...")
    pages = []
    for index, path in enumerate(files, 1):
        try:
            page = process_image(path.read_bytes(), path.name, enhance=args.enhance)
        except Exception as exc:  # satu file rusak tidak menghentikan yang lain
            print(f"  [{index}/{len(files)}] {path.name}: GAGAL - {exc}", file=sys.stderr)
            continue
        pages.append(page)
        print(f"  [{index}/{len(files)}] {path.name}: {len(page.boxes)} teks, "
              f"keyakinan {page.score:.0%}, {page.seconds:.1f} dtk")

    if not pages:
        return 1

    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)
    for fmt in args.format:
        if args.combine:
            groups = [pages]
        else:
            groups = [[p] for p in pages]
        for group in groups:
            name, data, _ = build_export(group, fmt, keep_layout=args.layout, combine=True)
            target = out_dir / name
            if fmt == "pdf_text":  # beda nama dengan PDF searchable agar tidak saling menimpa
                target = target.with_name(target.stem + "_teks.pdf")
            target.write_bytes(data)
            print(f"  -> {target}")
    print("Selesai.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
