"""Server web (FastAPI). Dipakai untuk mode browser maupun mode desktop (pywebview)."""

from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from contextlib import asynccontextmanager
from pathlib import Path
from urllib.parse import quote

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from PIL import UnidentifiedImageError
from pydantic import BaseModel

from .engine import engine_info, get_engine
from .exporters import FORMATS, build_export
from .pipeline import PageResult, process_image

STATIC_DIR = Path(__file__).parent / "static"
MAX_UPLOAD_MB = 30
MAX_JOBS = 20  # sesi lama dibuang otomatis agar memori tidak terus bertambah


class JobStore:
    """Menyimpan hasil OCR di memori, dikelompokkan per sesi (job) pengguna."""

    def __init__(self) -> None:
        self._jobs: OrderedDict[str, dict[str, PageResult]] = OrderedDict()
        self._lock = threading.Lock()

    def add(self, job_id: str | None, page: PageResult) -> str:
        with self._lock:
            if not job_id or job_id not in self._jobs:
                job_id = uuid.uuid4().hex
                self._jobs[job_id] = {}
            self._jobs[job_id][page.id] = page
            self._jobs.move_to_end(job_id)
            while len(self._jobs) > MAX_JOBS:
                self._jobs.popitem(last=False)
            return job_id

    def get(self, job_id: str, page_id: str) -> PageResult | None:
        with self._lock:
            return self._jobs.get(job_id, {}).get(page_id)

    def pages(self, job_id: str, page_ids: list[str]) -> list[PageResult]:
        with self._lock:
            job = self._jobs.get(job_id, {})
            missing = [pid for pid in page_ids if pid not in job]
            if missing:
                raise KeyError("Sebagian hasil sudah tidak ada di server (sesi kedaluwarsa). Unggah ulang gambarnya.")
            return [job[pid] for pid in page_ids]


store = JobStore()


class ExportRequest(BaseModel):
    job_id: str
    page_ids: list[str]
    format: str = "txt"
    layout: bool = False
    combine: bool = True
    texts: dict[str, str] = {}


def make_export(req: ExportRequest) -> tuple[str, bytes, str]:
    pages = store.pages(req.job_id, req.page_ids)
    texts = [req.texts.get(p.id) for p in pages]
    return build_export(pages, req.format, keep_layout=req.layout, combine=req.combine, texts=texts)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    # Muat model di belakang layar supaya gambar pertama tidak menunggu lama
    threading.Thread(target=get_engine, daemon=True).start()
    yield


app = FastAPI(title="OCR Tools", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.middleware("http")
async def no_cache_static(request, call_next):
    # Selalu cek ulang file UI agar pembaruan langsung terlihat tanpa hard refresh
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "no-cache"
    return response


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html", headers={"Cache-Control": "no-store"})


@app.get("/api/status")
def status() -> dict:
    info = engine_info()
    info["formats"] = {code: label for code, (label, _, _) in FORMATS.items()}
    return info


@app.post("/api/ocr")
def ocr(
    file: UploadFile = File(...),
    enhance: bool = Form(False),
    seven_segment: bool = Form(False),
    job_id: str | None = Form(None),
) -> dict:
    data = file.file.read(MAX_UPLOAD_MB * 1024 * 1024 + 1)
    if len(data) > MAX_UPLOAD_MB * 1024 * 1024:
        raise HTTPException(413, f"File terlalu besar (maks {MAX_UPLOAD_MB} MB).")
    try:
        page = process_image(data, file.filename or "gambar.png", enhance=enhance, seven_segment=seven_segment)
    except UnidentifiedImageError:
        raise HTTPException(400, "File bukan gambar atau formatnya tidak didukung.")
    job_id = store.add(job_id, page)
    return {"job_id": job_id, "page": page.to_dict()}


@app.get("/api/image/{job_id}/{page_id}", include_in_schema=False)
def image(job_id: str, page_id: str) -> Response:
    page = store.get(job_id, page_id)
    if page is None:
        raise HTTPException(404, "Gambar tidak ditemukan.")
    return Response(page.image_jpeg, media_type="image/jpeg")


@app.post("/api/export")
def export(req: ExportRequest) -> Response:
    try:
        name, data, mime = make_export(req)
    except KeyError as exc:
        raise HTTPException(410, str(exc.args[0]))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    disposition = f"attachment; filename=\"{name.encode('ascii', 'replace').decode()}\"; filename*=UTF-8''{quote(name)}"
    return Response(data, media_type=mime, headers={"Content-Disposition": disposition})
