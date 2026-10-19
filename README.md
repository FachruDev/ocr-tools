# OCR Tools

Membaca teks dari gambar (foto HP, scan, screenshot) lalu menyimpannya ke **Word, PDF, TXT, Markdown, atau JSON**.
Gratis, **berjalan offline**, tanpa API key. Mendukung bahasa Indonesia, Inggris, dan angka.

- Engine: [RapidOCR](https://github.com/RapidAI/RapidOCR) (model PP-OCR dari PaddleOCR, dijalankan dengan ONNX Runtime).
  Modelnya sudah ikut di dalam paket, jadi setelah instalasi tidak perlu internet lagi.
- Ada 3 cara pakai: **aplikasi desktop**, **web** (browser / server), dan **command line** (untuk banyak file).

## Instalasi (sekali saja)

Butuh Python 3.10 atau lebih baru. Klik dua kali `setup.bat`, atau jalankan:

```bash
python -m venv .venv
```

```bash
.venv\Scripts\python -m pip install -r requirements.txt
```

## Cara pakai

### 1. Desktop
Klik dua kali **`jalankan_desktop.bat`**. Aplikasi terbuka di jendelanya sendiri, dan tombol Download memunculkan dialog *Save As*.

### 2. Web
Klik dua kali **`jalankan_web.bat`**, lalu browser akan terbuka di `http://127.0.0.1:8000`.

Agar bisa dibuka dari komputer lain di jaringan kantor (mode server):

```bash
.venv\Scripts\python run_web.py --host 0.0.0.0 --port 8000
```

Setelah itu buka `http://<ip-server>:8000` dari komputer lain.
> Belum ada login atau password. Jangan buka port ini ke internet publik tanpa reverse proxy + autentikasi.

Langkah di aplikasi:
1. Seret foto ke halaman (bisa banyak sekaligus), klik untuk memilih, atau **Ctrl+V** untuk menempel screenshot.
2. Pilih tampilan **Teks saja** atau **Tata letak**. Tata letak menjaga posisi kolom, cocok untuk tabel, nota, dan faktur.
3. Perbaiki teks langsung di kotak teks bila ada salah baca.
   Kotak deteksi di gambar diberi warna sesuai keyakinan: hijau = yakin, oranye = ragu, merah = kemungkinan salah.
4. Pilih format, lalu klik **Download**. Opsi "Gabungkan" membuat satu file untuk semua gambar; kalau tidak dicentang, hasilnya berupa ZIP berisi satu file per gambar.

### 3. Command line (banyak file / satu folder)

```bash
.venv\Scripts\python -m ocrtool folder_foto -f docx pdf txt -o hasil
```

| Opsi | Arti |
|---|---|
| `-f txt docx pdf pdf_text md json` | format output (boleh lebih dari satu) |
| `-o hasil` | folder output |
| `--layout` | pertahankan tata letak kolom/tabel |
| `--gabung` | gabungkan semua gambar jadi satu file |
| `--kontras` | tingkatkan kontras untuk foto gelap/pudar |
| `--7seg` | mode display digital / seven segment |
| `-r` | ikut memproses subfolder |

## Format output

| Format | Isi |
|---|---|
| Word (.docx) | Teks yang bisa diedit. Mode tata letak memakai font Consolas agar kolom tetap lurus |
| PDF searchable | Gambar asli + lapisan teks tak terlihat, sehingga bisa dicari (Ctrl+F) dan disalin. Cocok untuk arsip |
| PDF teks | Hanya teks hasil OCR (termasuk hasil edit) |
| TXT / Markdown | Teks polos |
| JSON | Teks, skor keyakinan, dan koordinat setiap kotak (untuk developer) |

## Display digital (seven segment)

Angka di panel meter, timbangan, atau termometer digital tersusun dari batang-batang terpisah,
sehingga mode biasa sering tidak mendeteksinya sama sekali. Centang **Display digital** (CLI: `--7seg`).
Teks biasa di sekitarnya (label tombol, merek) tetap ikut terbaca. Kode: [ocrtool/sevenseg.py](ocrtool/sevenseg.py).

Cara kerjanya bertahap:

1. OCR biasa. Angka yang skornya meragukan dibaca ulang.
2. Deteksi ulang dengan ambang lebih rendah, untuk angka yang segmennya putus-putus.
3. Pencarian klasik bentuk "batang" (calon segmen) yang dikelompokkan menjadi area angka,
   untuk angka LCD tipis yang sama sekali tidak terlihat oleh detektor (contoh: suhu di remote AC).
4. Pencarian kaca/panel display (persegi panjang) yang dibinarisasi secara lokal,
   untuk angka berongga atau berkontras rendah.

Setiap pembacaan ulang membuang segmen mati yang tampak samar, menyambung celah antar segmen,
dan mematikan deteksi teks terbalik (tanpa ini, "1999" bisa terbaca "6661").

**Hasil uji** pada 18 foto (14 foto display dari Wikimedia Commons, 2 foto dari pengguna, 2 gambar buatan):
mode Display digital membaca **77%** angka dengan benar, sedangkan mode biasa 50%. Waktunya ±3–17 detik per foto.

Kasus yang masih gagal:
- display yang sedang mati (semua segmen tampak "8" samar),
- angka yang menempel jadi satu kotak (contoh: "2.59 23.5" terbaca "2.5923.5"),
- jam LCD dengan banyak angka kecil di sekitarnya.

Tips: foto display dari depan, hindari pantulan cahaya di kaca, dan bila perlu potong (crop) foto di sekitar display.

## Tips agar hasil OCR akurat

- Foto tegak lurus dari atas dokumen, cahaya merata, tanpa bayangan tangan atau HP.
- Pastikan fokus tajam. Lebih baik dekatkan kamera daripada memotret dari jauh lalu di-zoom.
- Untuk foto gelap atau pudar, centang **Tingkatkan kontras**.
- Tulisan tangan belum didukung dengan baik (keterbatasan engine gratis).

## Performa

Di laptop uji (Intel i3-1215U, hanya CPU): ±4–5 detik untuk satu foto dokumen penuh, ±2 detik untuk gambar kecil.
Saat aplikasi pertama dibuka, model dimuat dan "dipanaskan" dulu beberapa detik (status di pojok kanan atas: *Memuat engine…* → *Siap*).

- Jumlah thread CPU dibatasi 4 karena memakai semua core justru lambat di CPU Intel hybrid.
  Di server dengan banyak core, ubah lewat environment variable, contoh: `set OCR_THREADS=8`.
- **Server dengan GPU NVIDIA**: `pip uninstall onnxruntime`, lalu `pip install onnxruntime-gpu`,
  dan aktifkan `"EngineConfig.onnxruntime.use_cuda": True` di [ocrtool/engine.py](ocrtool/engine.py).
- GPU bawaan Intel tidak memberi percepatan berarti untuk kasus ini. OpenVINO sudah diuji dan malah 2x lebih lambat,
  karena ukuran setiap foto berbeda-beda sehingga model terus dikompilasi ulang.

## Struktur kode

```
ocrtool/
  preprocess.py   buka gambar, perbaiki rotasi EXIF foto HP, atur ukuran, tingkatkan kontras
  engine.py       pembungkus RapidOCR (bisa ditambah engine lain, mis. Tesseract)
  layout.py       luruskan kemiringan, susun kotak teks menjadi baris/paragraf/kolom
  sevenseg.py     pembaca display digital (seven segment)
  pipeline.py     alur lengkap satu gambar -> PageResult
  exporters.py    txt / docx / pdf searchable / pdf teks / md / json (+ ZIP)
  server.py       API FastAPI + menyajikan UI
  cli.py          mode command line
  static/         antarmuka (HTML/CSS/JS), dipakai bersama oleh mode web & desktop
run_web.py        jalankan mode web
run_desktop.py    jalankan mode desktop (pywebview / Edge WebView2)
```
