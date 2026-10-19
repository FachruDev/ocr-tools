"""Jalankan OCR Tools sebagai aplikasi web.

    python run_web.py                     # hanya bisa dibuka dari laptop ini
    python run_web.py --host 0.0.0.0      # bisa dibuka dari komputer lain di jaringan (mode server)
"""

import argparse
import threading
import webbrowser

import uvicorn


def main() -> None:
    parser = argparse.ArgumentParser(description="OCR Tools - mode web")
    parser.add_argument("--host", default="127.0.0.1", help="alamat (0.0.0.0 = semua jaringan)")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--no-browser", action="store_true", help="jangan buka browser otomatis")
    args = parser.parse_args()

    url = f"http://{'127.0.0.1' if args.host == '0.0.0.0' else args.host}:{args.port}"
    print(f"OCR Tools berjalan di {url}  (tekan Ctrl+C untuk berhenti)")
    if not args.no_browser:
        threading.Timer(1.5, webbrowser.open, [url]).start()
    uvicorn.run("ocrtool.server:app", host=args.host, port=args.port, log_level="warning")


if __name__ == "__main__":
    main()
