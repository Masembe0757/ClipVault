/* Clipvault front-end */
(() => {
  "use strict";

  // ------------------------------------------------------------ helpers
  const $ = (s, el = document) => el.querySelector(s);
  const $$ = (s, el = document) => [...el.querySelectorAll(s)];
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
    ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const YT_RE = /^(https?:\/\/)?([\w-]+\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)\//i;

  const ICON = {
    film: '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M7 4v16M17 4v16M3 9h4M3 15h4M17 9h4M17 15h4"/></svg>',
    music: '<svg viewBox="0 0 24 24"><path d="M9 18V5l11-2v13"/><circle cx="6" cy="18" r="3"/><circle cx="17" cy="16" r="3"/></svg>',
    download: '<svg viewBox="0 0 24 24"><path d="M12 4v11m0 0-4-4m4 4 4-4M5 20h14"/></svg>',
    folder: '<svg viewBox="0 0 24 24"><path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"/></svg>',
    x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6 6 18"/></svg>',
    retry: '<svg viewBox="0 0 24 24"><path d="M3 12a9 9 0 0 1 15.5-6.3L21 8M21 3v5h-5M21 12a9 9 0 0 1-15.5 6.3L3 16M3 21v-5h5"/></svg>',
    trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 13h10l1-13M9 7V4h6v3"/></svg>',
    check: '<svg viewBox="0 0 24 24"><path d="M5 12.5 10 17 19 7"/></svg>',
    alert: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 8v5M12 16.5v.01"/></svg>',
    info: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 11v5M12 7.5v.01"/></svg>',
    user: '<svg viewBox="0 0 24 24"><circle cx="12" cy="8" r="4"/><path d="M4 21a8 8 0 0 1 16 0"/></svg>',
    eye: '<svg viewBox="0 0 24 24"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z"/><circle cx="12" cy="12" r="3"/></svg>',
    cal: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M3 10h18M8 3v4M16 3v4"/></svg>',
    list: '<svg viewBox="0 0 24 24"><path d="M8 6h13M8 12h13M8 18h13M3 6h.01M3 12h.01M3 18h.01"/></svg>',
    cc: '<svg viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M10.5 10.2a2.2 2.2 0 1 0 0 3.6M17 10.2a2.2 2.2 0 1 0 0 3.6"/></svg>',
  };

  const fmtBytes = (n) => {
    if (!n || n <= 0) return null;
    const u = ["B", "KB", "MB", "GB", "TB"];
    let i = 0;
    while (n >= 1024 && i < u.length - 1) { n /= 1024; i++; }
    return `${n >= 100 || i === 0 ? n.toFixed(0) : n.toFixed(1)} ${u[i]}`;
  };
  const fmtDur = (s) => {
    if (!s && s !== 0) return "";
    s = Math.round(s);
    const h = Math.floor(s / 3600), m = Math.floor((s % 3600) / 60), x = s % 60;
    return h ? `${h}:${String(m).padStart(2, "0")}:${String(x).padStart(2, "0")}` : `${m}:${String(x).padStart(2, "0")}`;
  };
  const fmtEta = (s) => {
    if (s == null) return null;
    if (s < 60) return `${Math.max(1, Math.round(s))}s left`;
    if (s < 3600) return `${Math.floor(s / 60)}m ${Math.round(s % 60)}s left`;
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m left`;
  };
  const fmtViews = (n) => {
    if (!n) return null;
    if (n >= 1e9) return (n / 1e9).toFixed(1).replace(/\.0$/, "") + "B views";
    if (n >= 1e6) return (n / 1e6).toFixed(1).replace(/\.0$/, "") + "M views";
    if (n >= 1e3) return (n / 1e3).toFixed(1).replace(/\.0$/, "") + "K views";
    return n + " views";
  };
  const fmtDate = (d) => {
    if (!d || d.length !== 8) return null;
    const dt = new Date(+d.slice(0, 4), +d.slice(4, 6) - 1, +d.slice(6, 8));
    return dt.toLocaleDateString(undefined, { year: "numeric", month: "short", day: "numeric" });
  };
  const fmtAgo = (t) => {
    if (!t) return "";
    const s = Date.now() / 1000 - t;
    if (s < 60) return "just now";
    if (s < 3600) return `${Math.floor(s / 60)} min ago`;
    if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
    return new Date(t * 1000).toLocaleDateString();
  };
  const thumbFallback = (id) => id ? `https://i.ytimg.com/vi/${id}/mqdefault.jpg` : "";

  async function api(path, opts = {}) {
    const res = await fetch(path, {
      method: opts.method || (opts.body ? "POST" : "GET"),
      headers: opts.body ? { "Content-Type": "application/json" } : {},
      body: opts.body ? JSON.stringify(opts.body) : undefined,
    });
    let data;
    try { data = await res.json(); } catch { throw new Error("The server returned an unexpected response."); }
    if (!data.ok) throw new Error(data.error || "Something went wrong.");
    return data;
  }

  function toast(msg, type = "info", ms = 3800) {
    const el = document.createElement("div");
    el.className = `toast ${type}`;
    el.innerHTML = `${type === "ok" ? ICON.check : type === "err" ? ICON.alert : ICON.info}<div>${esc(msg)}</div>`;
    $("#toasts").appendChild(el);
    setTimeout(() => { el.classList.add("out"); setTimeout(() => el.remove(), 300); }, ms);
  }

  const store = {
    get(k) { try { return localStorage.getItem(k); } catch { return null; } },
    set(k, v) { try { localStorage.setItem(k, v); } catch { /* ignore */ } },
  };

  // Hide broken thumbnails (offline, removed videos) instead of showing an icon
  document.addEventListener("error", (e) => {
    const img = e.target;
    if (img && img.tagName === "IMG" && !img.onerror) img.classList.add("broken");
  }, true);
  document.addEventListener("load", (e) => {
    if (e.target && e.target.tagName === "IMG") e.target.classList.remove("broken");
  }, true);

  // ------------------------------------------------------------ state
  const state = {
    info: null,
    kind: "video",
    quality: null,
    subs: "",
    selected: new Set(),
    jobs: [],
    filter: "all",
    settings: null,
    online: true,
    restarting: false,
  };

  // ------------------------------------------------------------ theme
  function applyTheme(t) {
    document.documentElement.dataset.theme = t === "light" ? "light" : "dark";
  }
  applyTheme(store.get("cv-theme") || "dark");
  $("#themeBtn").addEventListener("click", () => {
    const t = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    applyTheme(t);
    store.set("cv-theme", t);
    api("/api/settings", { body: { theme: t } }).catch(() => {});
  });

  // ------------------------------------------------------------ fetch / preview
  const urlInput = $("#urlInput");
  const urlForm = $("#urlForm");
  const fetchBtn = $("#fetchBtn");
  const preview = $("#preview");

  function setFetching(on) {
    fetchBtn.disabled = on;
    fetchBtn.innerHTML = on
      ? '<span class="spinner"></span><span class="btn-label">Fetching</span>'
      : '<span class="btn-label">Fetch</span><svg viewBox="0 0 24 24"><path d="M5 12h14m-6-6 6 6-6 6"/></svg>';
  }

  function shake() {
    urlForm.classList.remove("shake");
    void urlForm.offsetWidth;
    urlForm.classList.add("shake");
  }

  async function fetchInfo(url) {
    url = (url || "").trim();
    if (!url) { shake(); urlInput.focus(); return; }
    if (!YT_RE.test(url)) { shake(); toast("That doesn't look like a YouTube link.", "err"); return; }
    setFetching(true);
    showSkeleton();
    try {
      const { data } = await api("/api/info", { body: { url } });
      state.info = data;
      state.subs = "";
      if (data.type === "playlist") renderPlaylist(data);
      else renderVideo(data);
    } catch (e) {
      preview.classList.add("hidden");
      toast(e.message, "err", 6000);
    } finally {
      setFetching(false);
    }
  }

  function showSkeleton() {
    preview.classList.remove("hidden");
    preview.innerHTML = `
      <div class="card preview-card skeleton">
        <div class="sk" style="aspect-ratio:16/9"></div>
        <div>
          <div class="sk" style="height:24px;width:85%;margin-bottom:10px"></div>
          <div class="sk" style="height:24px;width:55%;margin-bottom:22px"></div>
          <div class="sk" style="height:14px;width:40%;margin-bottom:26px"></div>
          <div class="sk" style="height:40px;width:210px;margin-bottom:16px"></div>
          <div style="display:grid;grid-template-columns:repeat(3,1fr);gap:10px">
            <div class="sk" style="height:58px"></div><div class="sk" style="height:58px"></div><div class="sk" style="height:58px"></div>
          </div>
        </div>
      </div>`;
  }

  function kindToggle() {
    return `
      <div class="segmented" id="kindSeg">
        <button data-kind="video" class="${state.kind === "video" ? "active" : ""}">${ICON.film} Video</button>
        <button data-kind="audio" class="${state.kind === "audio" ? "active" : ""}">${ICON.music} Audio only</button>
      </div>`;
  }

  function qualityOptions(info) {
    if (state.kind === "audio") {
      const opts = info.audio || [
        { value: "mp3-320", label: "MP3 · 320 kbps" },
        { value: "mp3-192", label: "MP3 · 192 kbps" },
        { value: "m4a", label: "M4A · Original" },
      ];
      return opts.map((o) => ({
        value: o.value,
        main: o.label.split(" · ")[0],
        sub: [o.label.split(" · ")[1], o.size ? "~" + fmtBytes(o.size) : null].filter(Boolean).join(" · "),
        tag: o.value === "mp3-320" ? "BEST" : null,
      }));
    }
    const qs = info.qualities && info.qualities.length ? info.qualities : [
      { value: 2160, label: "2160p · 4K" }, { value: 1440, label: "1440p · 2K" },
      { value: 1080, label: "1080p · Full HD" }, { value: 720, label: "720p · HD" },
      { value: 480, label: "480p" }, { value: 360, label: "360p" },
    ];
    const out = qs.map((q) => {
      const [res, tag] = q.label.split(" · ");
      return {
        value: q.value,
        main: res + (q.fps >= 50 ? `<small style="font-weight:600;color:var(--text-3)">${q.fps}</small>` : ""),
        sub: [tag, q.size ? "~" + fmtBytes(q.size) : null].filter(Boolean).join(" · ") || "Standard",
        tag: q.value >= 2160 ? "4K" : q.value >= 1080 ? "HD" : null,
      };
    });
    if (info.type === "playlist") out.unshift({ value: "best", main: "Best", sub: "Highest available", tag: null });
    return out;
  }

  function defaultQuality(info) {
    if (state.kind === "audio") return "mp3-320";
    if (info.type === "playlist") return 1080;
    const qs = (info.qualities || []).map((q) => q.value);
    if (!qs.length) return "best";
    return qs.includes(1080) ? 1080 : qs.find((h) => h <= 1080) || qs[0];
  }

  function qualityGrid(info) {
    const opts = qualityOptions(info);
    if (!opts.some((o) => String(o.value) === String(state.quality))) state.quality = defaultQuality(info);
    return `<div class="q-grid" id="qGrid">${opts.map((o) => `
      <button class="q-opt ${String(o.value) === String(state.quality) ? "active" : ""}" data-q="${esc(o.value)}">
        <div class="q-main">${o.main} ${o.tag ? `<span class="tag">${o.tag}</span>` : ""}</div>
        <div class="q-sub">${esc(o.sub)}</div>
      </button>`).join("")}</div>`;
  }

  function subtitlePicker(info) {
    if (state.kind !== "video" || !(info.subtitles || []).length) return "";
    const opts = info.subtitles;
    if (!opts.some((o) => o.value === state.subs)) state.subs = "";
    const manual = opts.filter((o) => !o.auto), auto = opts.filter((o) => o.auto);
    const option = (o) => `<option value="${esc(o.value)}" ${o.value === state.subs ? "selected" : ""}>${esc(o.label)}</option>`;
    const keep = state.settings ? state.settings.keep_subtitle_file : true;
    return `
      <div class="sub-pick">
        <label for="subSel">${ICON.cc}<span>Subtitles</span></label>
        <select id="subSel">
          <option value="">None</option>
          ${manual.length ? `<optgroup label="Subtitles">${manual.map(option).join("")}</optgroup>` : ""}
          ${auto.length ? `<optgroup label="Auto-generated">${auto.map(option).join("")}</optgroup>` : ""}
        </select>
      </div>
      <p class="hint sub-hint ${state.subs ? "" : "hidden"}" id="subHint">
        Embedded in the video${keep ? " and saved as a separate .srt file" : ""}.
        ${info.type === "playlist" ? "Videos without them are saved without subtitles." : ""}
      </p>`;
  }

  function bindPreviewControls(info, rerender) {
    const subSel = $("#subSel", preview);
    if (subSel) subSel.addEventListener("change", () => {
      state.subs = subSel.value;
      $("#subHint", preview).classList.toggle("hidden", !state.subs);
    });
    $$("#kindSeg button", preview).forEach((b) => b.addEventListener("click", () => {
      if (state.kind === b.dataset.kind) return;
      state.kind = b.dataset.kind;
      state.quality = defaultQuality(info);
      rerender(info);
    }));
    $$("#qGrid .q-opt", preview).forEach((b) => b.addEventListener("click", () => {
      state.quality = b.dataset.q;
      $$("#qGrid .q-opt", preview).forEach((x) => x.classList.toggle("active", x === b));
    }));
  }

  function renderVideo(info) {
    if (state.quality == null) state.quality = defaultQuality(info);
    const meta = [
      info.uploader && `<span>${ICON.user}${esc(info.uploader)}</span>`,
      fmtViews(info.view_count) && `<span>${ICON.eye}${fmtViews(info.view_count)}</span>`,
      fmtDate(info.upload_date) && `<span>${ICON.cal}${fmtDate(info.upload_date)}</span>`,
    ].filter(Boolean).join("");
    preview.classList.remove("hidden");
    preview.innerHTML = `
      <div class="card preview-card">
        <div class="thumb">
          <img src="${esc(info.thumbnail || thumbFallback(info.id))}" alt="" referrerpolicy="no-referrer"
               onerror="this.onerror=null;this.src='${thumbFallback(info.id)}'">
          ${info.duration ? `<span class="badge-time">${fmtDur(info.duration)}</span>` : ""}
        </div>
        <div>
          <div class="preview-title">${esc(info.title)}</div>
          <div class="preview-meta">${meta}</div>
          ${info.is_live ? `<p class="hint" style="color:var(--warn);margin:-8px 0 14px">This is a live stream. It will download from the current point.</p>` : ""}
          ${kindToggle()}
          ${qualityGrid(info)}
          ${subtitlePicker(info)}
          <button class="btn btn-primary btn-block" id="dlBtn">${ICON.download}<span>Download</span></button>
        </div>
      </div>`;
    bindPreviewControls(info, renderVideo);
    $("#dlBtn").addEventListener("click", () => startDownload([{
      url: info.url, id: info.id, title: info.title, uploader: info.uploader,
      thumbnail: info.thumbnail, duration: info.duration,
    }]));
  }

  function renderPlaylist(info, keepSelection) {
    if (!keepSelection) state.selected = new Set(info.entries.map((e) => e.id));
    if (state.quality == null || (state.kind === "video" && typeof state.quality === "string" && state.quality.startsWith("mp")))
      state.quality = defaultQuality(info);
    preview.classList.remove("hidden");
    preview.innerHTML = `
      <div class="card">
        <div class="pl-head">
          <div class="thumb"><img src="${esc(info.thumbnail || "")}" alt="" referrerpolicy="no-referrer"></div>
          <div>
            <div class="hint" style="margin:0 0 4px;display:flex;gap:6px;align-items:center">${ICON.list} PLAYLIST · ${info.count} videos</div>
            <div class="preview-title" style="margin:0">${esc(info.title)}</div>
            ${info.uploader ? `<div class="preview-meta" style="margin:6px 0 0"><span>${ICON.user}${esc(info.uploader)}</span></div>` : ""}
          </div>
        </div>
        <div class="pl-body">
          <div class="pl-tools">
            <span class="hint" id="selCount" style="margin:0"></span>
            <div style="display:flex;gap:14px">
              <button class="link-btn" id="selAll">Select all</button>
              <button class="link-btn" id="selNone">Select none</button>
            </div>
          </div>
          <div class="pl-list">${info.entries.map((e, i) => `
            <label class="pl-row">
              <input type="checkbox" class="check" data-id="${esc(e.id)}" ${state.selected.has(e.id) ? "checked" : ""}>
              <span class="num">${i + 1}</span>
              <img src="${esc(e.thumbnail || "")}" alt="" loading="lazy" referrerpolicy="no-referrer">
              <span class="t">${esc(e.title)}</span>
              <span class="d">${fmtDur(e.duration)}</span>
            </label>`).join("")}
          </div>
          ${kindToggle()}
          ${qualityGrid(info)}
          ${subtitlePicker(info)}
          <button class="btn btn-primary btn-block" id="dlBtn">${ICON.download}<span id="dlLabel">Download</span></button>
        </div>
      </div>`;
    const sync = () => {
      const n = state.selected.size;
      $("#selCount").textContent = `${n} of ${info.count} selected`;
      $("#dlLabel").textContent = n ? `Download ${n} ${n === 1 ? "video" : "videos"}` : "Select videos to download";
      $("#dlBtn").disabled = !n;
    };
    $$(".pl-list .check", preview).forEach((c) => c.addEventListener("change", () => {
      c.checked ? state.selected.add(c.dataset.id) : state.selected.delete(c.dataset.id);
      sync();
    }));
    $("#selAll").addEventListener("click", () => { state.selected = new Set(info.entries.map((e) => e.id)); renderPlaylist(info, true); });
    $("#selNone").addEventListener("click", () => { state.selected.clear(); renderPlaylist(info, true); });
    bindPreviewControls(info, (i) => renderPlaylist(i, true));
    $("#dlBtn").addEventListener("click", () => startDownload(
      info.entries.filter((e) => state.selected.has(e.id))
    ));
    sync();
  }

  async function startDownload(items) {
    const btn = $("#dlBtn");
    if (btn) { btn.disabled = true; btn.innerHTML = '<span class="spinner"></span><span>Adding…</span>'; }
    try {
      const body = { items, kind: state.kind, quality: state.quality };
      if (state.kind === "video" && state.subs) {
        const opt = (state.info?.subtitles || []).find((o) => o.value === state.subs);
        body.subtitles = state.subs;
        body.subtitles_label = opt ? opt.label : state.subs;
      }
      const { data } = await api("/api/download", { body });
      toast(data.length === 1 ? "Added to downloads" : `${data.length} videos added to downloads`, "ok");
      preview.classList.add("hidden");
      preview.innerHTML = "";
      state.info = null;
      urlInput.value = "";
      setFilter("all");
      poll(true);
      setTimeout(() => $(".downloads").scrollIntoView({ behavior: "smooth", block: "start" }), 100);
    } catch (e) {
      toast(e.message, "err");
      if (btn) { btn.disabled = false; btn.innerHTML = `${ICON.download}<span>Download</span>`; }
    }
  }

  urlForm.addEventListener("submit", (e) => { e.preventDefault(); state.quality = null; fetchInfo(urlInput.value); });

  $("#pasteBtn").addEventListener("click", async () => {
    try {
      const t = (await navigator.clipboard.readText()).trim();
      if (!t) return toast("Your clipboard is empty.", "info");
      urlInput.value = t;
      state.quality = null;
      fetchInfo(t);
    } catch {
      urlInput.focus();
      toast("Press Ctrl+V to paste the link.", "info");
    }
  });

  // Paste anywhere -> fetch
  document.addEventListener("paste", (e) => {
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" && e.target !== urlInput) return;
    const t = (e.clipboardData?.getData("text") || "").trim();
    if (!YT_RE.test(t)) return;
    e.preventDefault();
    urlInput.value = t;
    state.quality = null;
    fetchInfo(t);
  });

  // Drag & drop a link
  ["dragenter", "dragover"].forEach((ev) => document.addEventListener(ev, (e) => {
    e.preventDefault(); urlForm.classList.add("drag");
  }));
  ["dragleave", "drop"].forEach((ev) => document.addEventListener(ev, () => urlForm.classList.remove("drag")));
  document.addEventListener("drop", (e) => {
    e.preventDefault();
    const t = (e.dataTransfer.getData("text/uri-list") || e.dataTransfer.getData("text") || "").split("\n")[0].trim();
    if (t) { urlInput.value = t; state.quality = null; fetchInfo(t); }
  });

  // ------------------------------------------------------------ jobs
  const jobList = $("#jobList");
  const LIVE = ["queued", "starting", "downloading", "processing", "waiting"];
  const STATUS_LABEL = {
    queued: "Queued", starting: "Starting", downloading: "Downloading", processing: "Processing",
    waiting: "Retrying", done: "Completed", error: "Failed", cancelled: "Cancelled",
  };
  const els = new Map();

  function matches(job) {
    switch (state.filter) {
      case "active": return LIVE.includes(job.status);
      case "done": return job.status === "done";
      case "failed": return job.status === "error" || job.status === "cancelled";
      default: return true;
    }
  }

  function setFilter(f) {
    state.filter = f;
    $$("#tabs .tab").forEach((t) => t.classList.toggle("active", t.dataset.filter === f));
    renderJobs();
  }
  $$("#tabs .tab").forEach((t) => t.addEventListener("click", () => setFilter(t.dataset.filter)));

  function jobSkeleton(job) {
    const el = document.createElement("div");
    el.className = "card job";
    el.dataset.id = job.id;
    el.innerHTML = `
      <div class="thumb"><img alt="" referrerpolicy="no-referrer"><span class="kind"></span></div>
      <div class="job-main">
        <div class="job-title"></div>
        <div class="job-tags"><span class="pill"></span><span class="q"></span><span class="who muted"></span></div>
        <div class="bar"><i></i></div>
        <div class="job-stats"><span class="stage"></span><span class="nums"></span></div>
        <div class="job-error hidden"></div>
        <div class="job-notice hidden"></div>
      </div>
      <div class="job-actions"></div>`;
    el.addEventListener("click", (e) => {
      const b = e.target.closest("[data-act]");
      if (b) jobAction(job.id, b.dataset.act);
    });
    return el;
  }

  function updateJob(el, job) {
    const img = $(".thumb img", el);
    const src = job.thumbnail || thumbFallback(job.video_id);
    if (src && img.dataset.src !== src) {
      img.dataset.src = src;
      img.src = src;
      img.onerror = () => {
        const fb = thumbFallback(job.video_id);
        if (fb && img.src !== fb) img.src = fb;
        else img.classList.add("broken");
      };
    }
    $(".thumb .kind", el).innerHTML = job.kind === "audio" ? ICON.music : ICON.film;
    $(".job-title", el).textContent = job.title || job.url;
    $(".job-title", el).title = job.title || job.url;
    const pill = $(".pill", el);
    pill.className = `pill s-${job.status}`;
    pill.textContent = STATUS_LABEL[job.status] || job.status;
    $(".q", el).textContent = [job.quality_label, job.subtitles_label && `CC ${job.subtitles_label}`]
      .filter(Boolean).join(" · ");
    $(".who", el).textContent = job.status === "done" ? fmtAgo(job.finished_at) : (job.uploader || "");

    const bar = $(".bar", el);
    const live = ["downloading"].includes(job.status);
    const indet = ["starting", "processing"].includes(job.status) || (job.status === "downloading" && !job.progress);
    bar.className = "bar" + (live ? " live" : "") + (indet ? " indeterminate" : "") +
      (job.status === "done" ? " done" : "") + (job.status === "error" ? " error" : "") +
      (job.status === "cancelled" ? " cancelled" : "");
    $(".bar > i", el).style.width = (job.status === "done" ? 100 : (job.progress || 0)) + "%";

    let stage = job.stage || "";
    if (job.status === "waiting" && job.retry_at) {
      const s = Math.max(0, Math.round(job.retry_at - Date.now() / 1000));
      stage = `Retrying in ${s}s · attempt ${job.attempt + 1}/${job.max_attempts}`;
    }
    $(".stage", el).textContent = stage;

    const parts = [];
    if (job.status === "downloading") {
      if (job.progress) parts.push(`${job.progress.toFixed(0)}%`);
      const d = fmtBytes(job.downloaded_bytes), t = fmtBytes(job.total_bytes);
      if (d && t) parts.push(`${d} / ${t}`);
      if (job.speed) parts.push(`${fmtBytes(job.speed)}/s`);
      if (fmtEta(job.eta)) parts.push(fmtEta(job.eta));
    } else if (job.status === "done") {
      const t = fmtBytes(job.total_bytes);
      if (t) parts.push(t);
      if (job.duration) parts.push(fmtDur(job.duration));
    }
    $(".nums", el).textContent = parts.join("  ·  ");

    const err = $(".job-error", el);
    const showErr = job.error && (job.status === "error" || job.status === "waiting");
    err.classList.toggle("hidden", !showErr);
    if (showErr) err.textContent = job.error;

    const notice = $(".job-notice", el);
    const showNotice = job.notice && job.status === "done";
    notice.classList.toggle("hidden", !showNotice);
    if (showNotice) notice.textContent = job.notice;

    const actions = [];
    if (job.status === "done") {
      actions.push(`<button class="icon-btn go" data-act="open" title="Show in folder">${ICON.folder}</button>`);
    }
    if (job.status === "error" || job.status === "cancelled") {
      actions.push(`<button class="icon-btn" data-act="retry" title="Retry">${ICON.retry}</button>`);
    }
    if (LIVE.includes(job.status)) {
      actions.push(`<button class="icon-btn danger" data-act="cancel" title="Cancel">${ICON.x}</button>`);
    } else {
      actions.push(`<button class="icon-btn danger" data-act="remove" title="Remove from list">${ICON.trash}</button>`);
    }
    const html = actions.join("");
    const box = $(".job-actions", el);
    if (box.dataset.html !== html) { box.innerHTML = html; box.dataset.html = html; }
  }

  function renderJobs() {
    const visible = state.jobs.filter(matches);
    const ids = new Set(visible.map((j) => j.id));
    for (const [id, el] of els) {
      if (!ids.has(id)) { el.remove(); els.delete(id); }
    }
    visible.forEach((job, i) => {
      let el = els.get(job.id);
      if (!el) { el = jobSkeleton(job); els.set(job.id, el); }
      updateJob(el, job);
      if (jobList.children[i] !== el) jobList.insertBefore(el, jobList.children[i] || null);
    });
    $("#emptyState").classList.toggle("hidden", visible.length > 0);
    if (!visible.length && state.jobs.length) {
      $("#emptyState h3").textContent = "Nothing here";
      $("#emptyState p").textContent = "No downloads match this filter.";
    } else {
      $("#emptyState h3").textContent = "No downloads yet";
      $("#emptyState p").textContent = "Paste a YouTube link above to get started.";
    }
    const c = {
      all: state.jobs.length,
      active: state.jobs.filter((j) => LIVE.includes(j.status)).length,
      done: state.jobs.filter((j) => j.status === "done").length,
      failed: state.jobs.filter((j) => j.status === "error" || j.status === "cancelled").length,
    };
    Object.entries(c).forEach(([k, v]) => { $(`[data-c="${k}"]`).textContent = v; });
    const active = c.active;
    document.title = active ? `(${active}) Clipvault` : "Clipvault";
  }

  const prevStatus = new Map();
  function notifyTransitions(jobs) {
    for (const j of jobs) {
      const before = prevStatus.get(j.id);
      if (before && before !== j.status) {
        if (j.status === "done") toast(`Downloaded: ${j.title}`, "ok");
        if (j.status === "error") toast(`Failed: ${j.title}`, "err", 6000);
      }
      prevStatus.set(j.id, j.status);
    }
  }

  async function jobAction(id, act) {
    try {
      if (act === "cancel") await api(`/api/jobs/${id}/cancel`, { method: "POST" });
      if (act === "retry") await api(`/api/jobs/${id}/retry`, { method: "POST" });
      if (act === "remove") await api(`/api/jobs/${id}`, { method: "DELETE" });
      if (act === "open") await api("/api/open", { body: { id } });
      poll(true);
    } catch (e) {
      toast(e.message, "err");
    }
  }

  $("#clearBtn").addEventListener("click", async () => {
    try { await api("/api/jobs/clear", { method: "POST" }); poll(true); } catch (e) { toast(e.message, "err"); }
  });
  $("#openFolderBtn").addEventListener("click", () =>
    api("/api/open", { body: {} }).catch((e) => toast(e.message, "err")));

  // ------------------------------------------------------------ polling
  let pollTimer = null;
  async function poll(immediate) {
    clearTimeout(pollTimer);
    if (immediate === true) { /* fall through now */ }
    try {
      const res = await api("/api/jobs");
      state.jobs = res.data;
      notifyTransitions(res.data);
      renderJobs();
      handleUpdateState(res.update);
      setOnline(true);
    } catch {
      setOnline(false);
    }
    const busy = state.jobs.some((j) => LIVE.includes(j.status));
    pollTimer = setTimeout(poll, !state.online ? 3000 : busy ? 700 : 2500);
  }

  function setOnline(on) {
    if (state.restarting) return;
    state.online = on;
    const pill = $("#statusPill");
    if (!on) {
      pill.className = "status-pill bad";
      $("#statusText").textContent = "Offline · start Clipvault";
    } else if (state.health) {
      const h = state.health;
      const good = h.ffmpeg;
      pill.className = `status-pill ${good ? "ok" : "bad"}`;
      $("#statusText").textContent = good ? `Ready · yt-dlp ${h.engine}` : "ffmpeg missing";
    }
  }

  async function loadHealth() {
    try {
      const { data } = await api("/api/health");
      state.health = data;
      $("#engVer").textContent = data.engine;
      $("#engFf").textContent = data.ffmpeg ? "Ready" : "Missing";
      $("#engJs").textContent = data.js_runtime || "None";
      setOnline(true);
      handleUpdateState(data.update);
    } catch {
      setOnline(false);
    }
  }

  function handleUpdateState(u) {
    if (!u) return;
    const banner = $("#updateBanner");
    if (u.status === "restart") {
      banner.classList.remove("hidden");
      $("#updateBannerText").textContent = u.message;
    }
    const btn = $("#updateBtn");
    if (u.status === "running") {
      btn.disabled = true; btn.innerHTML = '<span class="spinner" style="border-color:var(--border-strong);border-top-color:var(--text)"></span> Updating';
    } else {
      btn.disabled = false; btn.textContent = "Check for updates";
    }
    if (u.message) $("#updateMsg").textContent = u.message;
  }

  // ------------------------------------------------------------ settings
  const drawer = $("#drawer"), scrim = $("#scrim");
  function openDrawer(open) {
    drawer.classList.toggle("open", open);
    scrim.classList.toggle("hidden", !open);
    drawer.setAttribute("aria-hidden", String(!open));
    if (open) loadHealth();
  }
  $("#settingsBtn").addEventListener("click", () => openDrawer(true));
  $("#closeDrawer").addEventListener("click", () => openDrawer(false));
  scrim.addEventListener("click", () => openDrawer(false));
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") openDrawer(false); });

  function fillSettings(s) {
    state.settings = s;
    $("#outDir").value = s.output_dir;
    $("#concVal").textContent = s.max_concurrent;
    $("#optH264").checked = !!s.prefer_h264;
    $("#optThumb").checked = !!s.embed_thumbnail;
    $("#optMeta").checked = !!s.add_metadata;
    $("#optSubFile").checked = !!s.keep_subtitle_file;
    if (s.theme && !store.get("cv-theme")) applyTheme(s.theme);
  }

  async function saveSettings(changes, msg) {
    try {
      const { data } = await api("/api/settings", { body: changes });
      fillSettings(data);
      if (msg) toast(msg, "ok", 2200);
    } catch (e) {
      toast(e.message, "err");
      if (state.settings) fillSettings(state.settings);
    }
  }

  $("#outDir").addEventListener("keydown", (e) => {
    if (e.key === "Enter") { e.preventDefault(); saveSettings({ output_dir: e.target.value }, "Download folder updated"); }
  });
  $("#outDir").addEventListener("blur", (e) => {
    if (state.settings && e.target.value.trim() && e.target.value !== state.settings.output_dir)
      saveSettings({ output_dir: e.target.value }, "Download folder updated");
  });
  $("#browseBtn").addEventListener("click", async () => {
    const b = $("#browseBtn");
    b.disabled = true; b.textContent = "Choosing…";
    try {
      const { data } = await api("/api/pick-folder", { method: "POST" });
      if (data) { fillSettings(data); toast("Download folder updated", "ok", 2200); }
    } catch (e) { toast(e.message, "err"); }
    b.disabled = false; b.textContent = "Browse";
  });
  $("#concMinus").addEventListener("click", () => saveSettings({ max_concurrent: (state.settings?.max_concurrent || 2) - 1 }));
  $("#concPlus").addEventListener("click", () => saveSettings({ max_concurrent: (state.settings?.max_concurrent || 2) + 1 }));
  $("#optH264").addEventListener("change", (e) => saveSettings({ prefer_h264: e.target.checked }));
  $("#optThumb").addEventListener("change", (e) => saveSettings({ embed_thumbnail: e.target.checked }));
  $("#optMeta").addEventListener("change", (e) => saveSettings({ add_metadata: e.target.checked }));
  $("#optSubFile").addEventListener("change", (e) => saveSettings({ keep_subtitle_file: e.target.checked }));

  $("#updateBtn").addEventListener("click", async () => {
    try {
      await api("/api/update", { method: "POST" });
      handleUpdateState({ status: "running", message: "Updating yt-dlp… this can take a minute." });
      const wait = async () => {
        const { data } = await api("/api/health");
        handleUpdateState(data.update);
        if (data.update.status === "running") setTimeout(wait, 1500);
        else toast(data.update.message || "Done", data.update.status === "restart" ? "ok" : "info");
      };
      setTimeout(wait, 1500);
    } catch (e) { toast(e.message, "err"); }
  });

  $("#restartBtn").addEventListener("click", async () => {
    try {
      state.restarting = true;
      $("#statusText").textContent = "Restarting…";
      $("#restartBtn").disabled = true;
      await api("/api/restart", { method: "POST" });
      const back = async () => {
        try { await api("/api/health"); location.reload(); }
        catch { setTimeout(back, 800); }
      };
      setTimeout(back, 1500);
    } catch (e) {
      state.restarting = false;
      toast(e.message, "err");
    }
  });

  // ------------------------------------------------------------ init
  (async function init() {
    await loadHealth();
    try { const { data } = await api("/api/settings"); fillSettings(data); } catch { /* offline */ }
    poll(true);
    urlInput.focus();
  })();
})();

// Footer copyright year
{
  const yearEl = document.getElementById("copyYear");
  if (yearEl) yearEl.textContent = String(new Date().getFullYear());
}
