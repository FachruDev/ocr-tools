"""Jalankan OCR Tools sebagai aplikasi desktop (jendela sendiri, tanpa browser).

Memakai antarmuka yang sama dengan mode web, ditampilkan lewat pywebview (Edge WebView2 di Windows).
"""

import socket
import threading
import time
from pathlib import Path

import uvicorn
import webview

from ocrtool.server import ExportRequest, app, make_export


def _free_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class DesktopApi:
    """Fungsi Python yang bisa dipanggil dari JavaScript (window.pywebview.api.*)."""

    def save_export(self, payload: dict) -> dict:
        try:
            name, data, _ = make_export(ExportRequest(**payload))
        except Exception as exc:
            return {"error": str(exc.args[0] if exc.args else exc)}
        save_mode = getattr(getattr(webview, "FileDialog", None), "SAVE", None) or webview.SAVE_DIALOG
        path = webview.windows[0].create_file_dialog(save_mode, save_filename=name)
        if not path:
            return {"saved": False}
        if isinstance(path, (list, tuple)):
            path = path[0]
        Path(path).write_bytes(data)
        return {"saved": True, "path": str(path)}


def main() -> None:
    port = _free_port()
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, daemon=True).start()
    while not server.started:
        time.sleep(0.05)

    webview.create_window(
        "OCR Tools", f"http://127.0.0.1:{port}", js_api=DesktopApi(),
        width=1320, height=860, min_size=(820, 600),
    )
    # Folder data WebView tetap (bukan folder temp acak) agar tidak ada sisa/peringatan saat ditutup
    storage = Path.home() / ".ocr-tools" / "webview"
    storage.mkdir(parents=True, exist_ok=True)
    webview.start(private_mode=False, storage_path=str(storage))
    server.should_exit = True


if __name__ == "__main__":
    main()
