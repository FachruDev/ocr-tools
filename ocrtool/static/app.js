"use strict";

const $ = (sel) => document.querySelector(sel);

const state = {
  jobId: null,
  pages: [],        // {id, name, width, height, text, layout_text, score, seconds, boxes, edited:{plain,layout}, el}
  queue: [],
  busy: false,
  done: 0,
  total: 0,
  mode: "plain",
};

const FORMAT_HINTS = {
  docx: "Bisa langsung diedit di Microsoft Word / LibreOffice.",
  txt: "Teks polos, paling ringan.",
  pdf: "Gambar asli + lapisan teks tersembunyi: bisa dicari (Ctrl+F) & disalin. Hasil edit teks tidak dipakai.",
  pdf_text: "PDF berisi teks hasil OCR (termasuk hasil edit Anda).",
  md: "Untuk catatan / dokumentasi (Obsidian, GitHub, dll).",
  json: "Untuk developer: teks, skor keyakinan, dan koordinat tiap kotak.",
};

// ------------------------------------------------------------------ util

let toastTimer;
function toast(message, isError = false) {
  const el = $("#toast");
  el.textContent = message;
  el.classList.toggle("error", isError);
  el.classList.add("show");
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => el.classList.remove("show"), isError ? 5000 : 2500);
}

async function copyText(text) {
  try {
    await navigator.clipboard.writeText(text);
  } catch {
    const ta = Object.assign(document.createElement("textarea"), { value: text });
    document.body.append(ta);
    ta.select();
    document.execCommand("copy");
    ta.remove();
  }
  toast("Teks disalin ke clipboard.");
}

function currentText(page) {
  return page.edited[state.mode];
}

function refreshButtons() {
  const has = state.pages.length > 0;
  $("#btnExport").disabled = !has;
  $("#btnCopyAll").disabled = !has;
  $("#btnClear").disabled = !has;
  $("#empty").hidden = has || state.busy;
}

// ------------------------------------------------------------------ status engine

async function pollStatus() {
  try {
    const res = await fetch("/api/status");
    const info = await res.json();
    const el = $("#engineStatus");
    const device = info.providers.includes("CUDA") ? "GPU" : info.providers.includes("Dml") ? "DirectML" : "CPU";
    el.classList.toggle("ready", info.ready);
    el.lastElementChild.textContent = info.ready ? `Siap · ${device}` : "Memuat engine…";
    if (!info.ready) setTimeout(pollStatus, 1000);
  } catch {
    setTimeout(pollStatus, 2000);
  }
}

// ------------------------------------------------------------------ upload & OCR

const IMAGE_RE = /\.(jpe?g|png|bmp|tiff?|webp|heic|heif)$/i;

function addFiles(fileList) {
  const files = [...fileList].filter((f) => f.type.startsWith("image/") || IMAGE_RE.test(f.name));
  if (!files.length) {
    toast("Tidak ada file gambar yang bisa diproses.", true);
    return;
  }
  const enhance = $("#optEnhance").checked;
  const sevenSegment = $("#optSevenSeg").checked;
  for (const file of files) state.queue.push({ file, enhance, sevenSegment });
  state.total += files.length;
  processQueue();
}

function updateProgress() {
  const box = $("#progress");
  box.hidden = !state.busy;
  const pct = state.total ? (state.done / state.total) * 100 : 0;
  $("#progressBar").style.width = `${pct}%`;
  $("#progressText").textContent = `Memproses ${Math.min(state.done + 1, state.total)} dari ${state.total}…`;
}

async function processQueue() {
  if (state.busy) return;
  state.busy = true;
  refreshButtons();
  while (state.queue.length) {
    updateProgress();
    const item = state.queue.shift();
    try {
      addCard(await ocrFile(item));
    } catch (err) {
      toast(`${item.file.name}: ${err.message}`, true);
    }
    state.done += 1;
  }
  state.busy = false;
  state.done = state.total = 0;
  updateProgress();
  refreshButtons();
}

async function ocrFile({ file, enhance, sevenSegment }) {
  const form = new FormData();
  const name = file.name && file.name !== "image.png" ? file.name : `tempel_${Date.now()}.png`;
  form.append("file", file, name);
  form.append("enhance", enhance ? "true" : "false");
  form.append("seven_segment", sevenSegment ? "true" : "false");
  if (state.jobId) form.append("job_id", state.jobId);
  const res = await fetch("/api/ocr", { method: "POST", body: form });
  const data = await res.json().catch(() => ({}));
  if (!res.ok) throw new Error(data.detail || `Gagal (${res.status})`);
  state.jobId = data.job_id;
  return data.page;
}

// ------------------------------------------------------------------ kartu hasil

const SVG_NS = "http://www.w3.org/2000/svg";

function addCard(page) {
  page.edited = { plain: page.text, layout: page.layout_text };
  const el = $("#cardTpl").content.firstElementChild.cloneNode(true);
  page.el = el;

  el.querySelector(".name").textContent = page.name;
  const pct = Math.round(page.score * 100);
  const meta = el.querySelector(".meta");
  meta.innerHTML = "";
  meta.append(`${page.boxes.length} potongan teks · `);
  const conf = document.createElement("span");
  conf.textContent = `keyakinan ${pct}%`;
  if (page.boxes.length && pct < 85) conf.className = "low";
  meta.append(conf, ` · ${page.seconds.toFixed(1)} dtk`);

  const img = el.querySelector("img");
  img.src = `/api/image/${state.jobId}/${page.id}`;
  img.alt = page.name;

  const svg = el.querySelector("svg.boxes");
  svg.setAttribute("viewBox", `0 0 ${page.width} ${page.height}`);
  for (const b of page.boxes) {
    const poly = document.createElementNS(SVG_NS, "polygon");
    poly.setAttribute("points", b.box.map((p) => p.join(",")).join(" "));
    poly.setAttribute("class", b.score >= 0.9 ? "good" : b.score >= 0.7 ? "warn" : "bad");
    const title = document.createElementNS(SVG_NS, "title");
    title.textContent = `${b.text}  (${Math.round(b.score * 100)}%)`;
    poly.append(title);
    svg.append(poly);
  }

  const ta = el.querySelector("textarea");
  ta.value = currentText(page);
  ta.wrap = state.mode === "layout" ? "off" : "soft";
  ta.addEventListener("input", () => { page.edited[state.mode] = ta.value; });
  if (!page.boxes.length) ta.placeholder = "Tidak ada teks yang terdeteksi pada gambar ini.";

  el.querySelector(".btn-copy").addEventListener("click", () => copyText(currentText(page)));
  el.querySelector(".btn-remove").addEventListener("click", () => {
    state.pages = state.pages.filter((p) => p !== page);
    el.remove();
    refreshButtons();
  });

  state.pages.push(page);
  $("#results").append(el);
  refreshButtons();
}

function setMode(mode) {
  state.mode = mode;
  $("#results").classList.toggle("layout-mode", mode === "layout");
  for (const page of state.pages) {
    const ta = page.el.querySelector("textarea");
    ta.value = currentText(page);
    ta.wrap = mode === "layout" ? "off" : "soft";
  }
}

// ------------------------------------------------------------------ export

function filenameFrom(res, fallback) {
  const header = res.headers.get("Content-Disposition") || "";
  const star = header.match(/filename\*=UTF-8''([^;]+)/i);
  if (star) return decodeURIComponent(star[1]);
  const plain = header.match(/filename="([^"]+)"/i);
  return plain ? plain[1] : fallback;
}

async function doExport() {
  if (!state.pages.length) return;
  const payload = {
    job_id: state.jobId,
    page_ids: state.pages.map((p) => p.id),
    format: $("#format").value,
    layout: state.mode === "layout",
    combine: $("#optCombine").checked,
    texts: Object.fromEntries(state.pages.map((p) => [p.id, currentText(p)])),
  };
  const btn = $("#btnExport");
  btn.disabled = true;
  btn.textContent = "Menyiapkan…";
  try {
    // Mode desktop: simpan lewat dialog "Save As" milik Windows
    if (window.pywebview && window.pywebview.api && window.pywebview.api.save_export) {
      const r = await window.pywebview.api.save_export(payload);
      if (r && r.error) throw new Error(r.error);
      if (r && r.saved) toast(`Tersimpan: ${r.path}`);
      return;
    }
    const res = await fetch("/api/export", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    if (!res.ok) {
      const data = await res.json().catch(() => ({}));
      throw new Error(data.detail || `Gagal (${res.status})`);
    }
    const blob = await res.blob();
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = filenameFrom(res, "hasil_ocr");
    document.body.append(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(a.href), 10000);
  } catch (err) {
    toast(err.message || String(err), true);
  } finally {
    btn.disabled = false;
    btn.textContent = "Download";
  }
}

// ------------------------------------------------------------------ event

function init() {
  const drop = $("#dropzone");
  $("#fileInput").addEventListener("change", (e) => {
    addFiles(e.target.files);
    e.target.value = "";
  });

  // Gambar boleh dijatuhkan di mana saja di halaman
  let depth = 0;
  window.addEventListener("dragenter", (e) => { e.preventDefault(); depth++; drop.classList.add("drag"); });
  window.addEventListener("dragleave", () => { if (--depth <= 0) { depth = 0; drop.classList.remove("drag"); } });
  window.addEventListener("dragover", (e) => e.preventDefault());
  window.addEventListener("drop", (e) => {
    e.preventDefault();
    depth = 0;
    drop.classList.remove("drag");
    if (e.dataTransfer && e.dataTransfer.files.length) addFiles(e.dataTransfer.files);
  });

  document.addEventListener("paste", (e) => {
    if (e.target instanceof HTMLTextAreaElement) return; // biarkan tempel teks biasa di kotak teks
    const files = [...(e.clipboardData?.items || [])]
      .filter((i) => i.kind === "file")
      .map((i) => i.getAsFile())
      .filter(Boolean);
    if (files.length) addFiles(files);
  });

  for (const radio of document.querySelectorAll("input[name=mode]")) {
    radio.addEventListener("change", () => setMode(radio.value));
  }
  $("#optBoxes").addEventListener("change", (e) => $("#results").classList.toggle("no-boxes", !e.target.checked));

  const format = $("#format");
  const showHint = () => { $("#formatHint").textContent = FORMAT_HINTS[format.value] || ""; };
  format.addEventListener("change", showHint);
  showHint();

  $("#btnExport").addEventListener("click", doExport);
  $("#btnCopyAll").addEventListener("click", () => {
    const parts = state.pages.map((p) => (state.pages.length > 1 ? `===== ${p.name} =====\n` : "") + currentText(p));
    copyText(parts.join("\n\n"));
  });
  $("#btnClear").addEventListener("click", () => {
    if (!confirm("Hapus semua hasil dari daftar?")) return;
    for (const p of state.pages) p.el.remove();
    state.pages = [];
    refreshButtons();
  });

  refreshButtons();
  pollStatus();
}

init();
