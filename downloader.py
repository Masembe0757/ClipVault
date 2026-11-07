"""
Clipvault download engine: wraps yt-dlp with a job queue, live progress,
cancellation, retries with backoff, and persistent history.
"""

import glob
import json
import logging
import logging.handlers
import os
import random
import re
import subprocess
import sys
import threading
import time
import uuid
from importlib import metadata

import yt_dlp
from yt_dlp.utils import DownloadError

import bootstrap

APP_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(APP_DIR, "data")
HISTORY_FILE = os.path.join(DATA_DIR, "history.json")
SETTINGS_FILE = os.path.join(DATA_DIR, "settings.json")
LOG_FILE = os.path.join(DATA_DIR, "clipvault.log")
os.makedirs(DATA_DIR, exist_ok=True)

log = logging.getLogger("clipvault")


def setup_logging():
    """Write warnings and errors to data/clipvault.log (rotated at ~1 MB, 3 backups)."""
    if any(getattr(h, "_clipvault", False) for h in log.handlers):
        return LOG_FILE
    handler = logging.handlers.RotatingFileHandler(
        LOG_FILE, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s [%(threadName)s] %(message)s"))
    handler._clipvault = True
    log.addHandler(handler)
    log.setLevel(logging.INFO)
    log.propagate = False
    return LOG_FILE

MAX_ATTEMPTS = 5
BASE_DELAY = 3  # seconds, doubled each attempt

YOUTUBE_RE = re.compile(
    r"^(https?://)?([\w-]+\.)?(youtube\.com|youtu\.be|youtube-nocookie\.com)/", re.I)

# Subtitle choice sent by the UI:
#   "<lang>"       uploaded subtitles in that language (e.g. "en", "pt-BR")
#   "auto:<lang>"  YouTube's automatic captions with that key (e.g. "en-orig")
#   "any:<lang>"   uploaded subtitles, falling back to automatic captions (playlists)
#   "orig"         automatic captions in the video's spoken language (playlists)
SUBS_RE = re.compile(r"^(?:(auto|any):)?([A-Za-z]{2,3}(?:-[A-Za-z0-9]{2,8}){0,2})$")

# Errors that retrying cannot fix
PERMANENT_ERRORS = (
    "private video", "video unavailable", "has been removed", "account associated",
    "copyright", "members-only", "join this channel", "sign in to confirm your age",
    "unsupported url", "not a valid url", "this live event will begin", "premieres in",
    "is not available in your country", "does not exist",
)
# Errors that usually mean yt-dlp is out of date
OUTDATED_HINTS = ("signature", "nsig", "unable to extract", "player", "http error 403",
                  "requested format is not available", "n challenge")


def _default_download_dir():
    home = os.path.expanduser("~")
    for name in ("Downloads", "downloads"):
        d = os.path.join(home, name)
        if os.path.isdir(d):
            return os.path.join(d, "Clipvault")
    return os.path.join(os.getcwd(), "downloads")


DEFAULT_SETTINGS = {
    "output_dir": _default_download_dir(),
    "max_concurrent": 2,
    "prefer_h264": True,        # plays on every device/player
    "embed_thumbnail": True,    # cover art in mp3/mp4
    "add_metadata": True,       # title/artist tags
    "keep_subtitle_file": True, # save subtitles as a .srt next to the video too
    "theme": "dark",
}


def _read_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


_WRITE_LOCK = threading.Lock()


def _write_json(path, data):
    """Atomic write. Serialized so jobs finishing at the same moment don't race on
    the temp file, and retried because Windows refuses to replace a file that
    another program (antivirus, indexer) has open for a moment."""
    tmp = f"{path}.{os.getpid()}.{threading.get_ident()}.tmp"
    with _WRITE_LOCK:
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            for attempt in range(5):
                try:
                    os.replace(tmp, path)
                    return
                except PermissionError:
                    if attempt == 4:
                        raise
                    time.sleep(0.05 * (attempt + 1))
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass


def is_youtube_url(url):
    return bool(YOUTUBE_RE.match((url or "").strip()))


def parse_subtitles(choice):
    """Validate a subtitle choice from the UI. Returns the normalized choice,
    None for "no subtitles", or raises ValueError."""
    choice = (choice or "").strip()
    if not choice or choice == "none":
        return None
    if choice == "orig" or SUBS_RE.match(choice):
        return choice
    raise ValueError("Unknown subtitle language.")


def subtitle_opts(choice):
    """yt-dlp options for a validated subtitle choice."""
    if choice == "orig":
        return {"writeautomaticsub": True, "subtitleslangs": [r".*-orig"]}
    mode, lang = SUBS_RE.match(choice).groups()
    lang_re = re.escape(lang)
    if mode == "auto":
        return {"writeautomaticsub": True, "subtitleslangs": [lang_re]}
    if mode == "any":
        # Uploaded subtitles win; automatic captions only fill missing languages.
        return {"writesubtitles": True, "writeautomaticsub": True,
                "subtitleslangs": [lang_re, lang_re + "-orig"]}
    return {"writesubtitles": True, "subtitleslangs": [lang_re]}


class Cancelled(Exception):
    pass


class _QuietLogger:
    """Collects yt-dlp messages instead of printing them."""

    def __init__(self, job=None):
        self.job = job

    def debug(self, msg):
        pass

    def info(self, msg):
        pass

    def warning(self, msg):
        if self.job is not None:
            self.job.add_log("warning: " + msg)

    def error(self, msg):
        if self.job is not None:
            self.job.add_log(msg)


# --------------------------------------------------------------------------- #
class Job:
    LIVE = ("queued", "starting", "downloading", "processing", "waiting")
    FIELDS = ("id", "url", "video_id", "title", "uploader", "thumbnail", "duration",
              "kind", "quality", "quality_label", "status", "stage", "progress",
              "downloaded_bytes", "total_bytes", "speed", "eta", "attempt", "max_attempts",
              "error", "filepath", "created_at", "finished_at", "retry_at",
              "subtitles", "subtitles_label", "notice")

    def __init__(self, url, kind, quality, meta=None, subtitles=None, subtitles_label=None):
        meta = meta or {}
        self.id = uuid.uuid4().hex[:12]
        self.url = url
        self.video_id = meta.get("id")
        self.title = meta.get("title") or "Fetching details..."
        self.uploader = meta.get("uploader")
        self.thumbnail = meta.get("thumbnail")
        self.duration = meta.get("duration")
        self.kind = kind            # "video" | "audio"
        self.quality = quality      # height int / "best" | "mp3-320" / "mp3-192" / "m4a"
        self.quality_label = quality_label(kind, quality)
        self.status = "queued"
        self.stage = "Waiting in queue"
        self.progress = 0.0
        self.downloaded_bytes = 0
        self.total_bytes = 0
        self.speed = None
        self.eta = None
        self.attempt = 0
        self.max_attempts = MAX_ATTEMPTS
        self.error = None
        self.filepath = None
        self.created_at = time.time()
        self.finished_at = None
        self.retry_at = None
        self.subtitles = subtitles if kind == "video" else None
        self.subtitles_label = (str(subtitles_label)[:40] or None) if self.subtitles and subtitles_label else None
        self.notice = None          # non-fatal problem shown on a finished job
        self.log = []
        self.cancel_event = threading.Event()
        # internal progress bookkeeping
        self._streams = 1
        self._stream_idx = 0
        self._stream_bytes_done = 0
        self._prefix = None

    def add_log(self, msg):
        self.log.append(msg)
        self.log = self.log[-30:]

    def to_dict(self):
        d = {k: getattr(self, k) for k in self.FIELDS}
        d["log"] = self.log[-5:]
        return d

    @classmethod
    def from_dict(cls, d):
        job = cls(d.get("url"), d.get("kind", "video"), d.get("quality", "best"))
        for k in cls.FIELDS:
            if k in d:
                setattr(job, k, d[k])
        if job.status in cls.LIVE:  # app closed mid-download
            job.status = "error"
            job.stage = "Interrupted"
            job.error = "Clipvault was closed during this download. Click retry to resume."
        return job


def quality_label(kind, quality):
    if kind == "audio":
        return {"mp3-320": "MP3 · 320 kbps", "mp3-192": "MP3 · 192 kbps",
                "m4a": "M4A · Original"}.get(quality, "Audio")
    if quality == "best":
        return "Best available"
    try:
        h = int(quality)
    except (TypeError, ValueError):
        return str(quality)
    tag = {2160: "4K", 1440: "2K", 1080: "Full HD", 720: "HD"}.get(h)
    return f"{h}p · {tag}" if tag else f"{h}p"


# --------------------------------------------------------------------------- #
class Engine:
    def __init__(self, tools):
        self.tools = tools  # paths found by bootstrap: ffmpeg, deno, node
        self.lock = threading.RLock()
        self.wake = threading.Condition(self.lock)  # signalled when the queue may need attention
        self.jobs = {}
        self.order = []
        self.settings = dict(DEFAULT_SETTINGS)
        self.settings.update(_read_json(SETTINGS_FILE, {}))
        self.engine_version = yt_dlp.version.__version__
        self.update_state = {"status": "idle", "installed": None, "message": ""}
        self._load_history()
        threading.Thread(target=self._scheduler, daemon=True).start()

    # ---------------- settings & persistence ----------------
    def get_settings(self):
        return dict(self.settings)

    def update_settings(self, changes):
        allowed = set(DEFAULT_SETTINGS)
        for k, v in (changes or {}).items():
            if k not in allowed:
                continue
            if k == "max_concurrent":
                v = max(1, min(5, int(v)))
            if k == "output_dir":
                v = os.path.abspath(os.path.expanduser(str(v).strip()))
                os.makedirs(v, exist_ok=True)
            if k in ("prefer_h264", "embed_thumbnail", "add_metadata", "keep_subtitle_file"):
                v = bool(v)
            self.settings[k] = v
        _write_json(SETTINGS_FILE, self.settings)
        self._wake_scheduler()  # max_concurrent may have changed
        return self.get_settings()

    def _load_history(self):
        for d in _read_json(HISTORY_FILE, []):
            try:
                job = Job.from_dict(d)
                self.jobs[job.id] = job
                self.order.append(job.id)
            except Exception:
                log.exception("Skipping unreadable history entry")
                continue

    def save_history(self):
        with self.lock:
            data = [self.jobs[i].to_dict() for i in self.order[-300:]]
        try:
            _write_json(HISTORY_FILE, data)
        except Exception:
            log.exception("Could not save download history")

    # ---------------- yt-dlp options ----------------
    def _base_opts(self, job=None):
        runtimes = {}
        if self.tools.get("deno"):
            runtimes["deno"] = {"path": self.tools["deno"]}
        if self.tools.get("node"):
            runtimes["node"] = {"path": self.tools["node"]}
        opts = {
            "quiet": True,
            "no_warnings": True,
            "noprogress": True,
            "logger": _QuietLogger(job),
            "noplaylist": True,
            "socket_timeout": 30,
            "retries": 10,
            "fragment_retries": 10,
            "extractor_retries": 5,
            "file_access_retries": 5,
            "retry_sleep_functions": {
                "http": lambda n: min(2 ** n, 30),
                "fragment": lambda n: min(2 ** n, 30),
                "extractor": lambda n: min(2 ** n, 30),
            },
            "continuedl": True,
            "windowsfilenames": True,
            "remote_components": ["ejs:github"],
        }
        if runtimes:
            opts["js_runtimes"] = runtimes
        if self.tools.get("ffmpeg"):
            opts["ffmpeg_location"] = self.tools["ffmpeg"]
        return opts

    def _download_opts(self, job, outdir, embed_thumbnail, subtitles=None):
        s = self.settings
        opts = self._base_opts(job)
        name = "%(title).150B [%(id)s].%(ext)s"
        if job.kind == "audio":
            # Download the audio source into a private working folder, so an
            # existing .mp4 of the same video is never reused and then deleted
            # by the audio conversion.
            name = os.path.join(".clipvault-audio", name)
        opts.update({
            "outtmpl": os.path.join(outdir, name),
            "progress_hooks": [lambda d: self._progress_hook(job, d)],
            "postprocessor_hooks": [lambda d: self._pp_hook(job, d)],
            "post_hooks": [lambda path: setattr(job, "filepath", path)],
        })
        pps = []
        if job.kind == "audio":
            if job.quality == "m4a":
                opts["format"] = "ba[ext=m4a]/ba/b"
                pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "m4a"})
            else:
                kbps = "320" if job.quality == "mp3-320" else "192"
                opts["format"] = "ba/b"
                pps.append({"key": "FFmpegExtractAudio", "preferredcodec": "mp3",
                            "preferredquality": kbps})
        else:
            h = None if job.quality == "best" else int(job.quality)
            if h:
                opts["format"] = f"bv*[height<={h}]+ba/b[height<={h}]/bv*+ba/b"
            else:
                opts["format"] = "bv*+ba/b"
            sort = [f"res:{h}" if h else "res", "fps"]
            if s.get("prefer_h264"):
                sort.append("vcodec:h264")
            sort.append("ext:mp4:m4a")
            opts["format_sort"] = sort
            opts["merge_output_format"] = "mp4"
            if subtitles:
                opts.update(subtitle_opts(subtitles))
                opts["subtitlesformat"] = "srt/vtt/best"
                # Convert to .srt before download, then embed into the mp4.
                # Same order as yt-dlp's own command line.
                pps.append({"key": "FFmpegSubtitlesConvertor", "format": "srt", "when": "before_dl"})
                pps.append({"key": "FFmpegEmbedSubtitle",
                            "already_have_subtitle": bool(s.get("keep_subtitle_file"))})
        if s.get("add_metadata"):
            pps.append({"key": "FFmpegMetadata", "add_metadata": True, "add_chapters": True})
        if embed_thumbnail:
            opts["writethumbnail"] = True
            pps.append({"key": "EmbedThumbnail", "already_have_thumbnail": False})
        opts["postprocessors"] = pps
        return opts

    # ---------------- info / preview ----------------
    def fetch_info(self, url):
        url = url.strip()
        if not is_youtube_url(url):
            raise ValueError("That doesn't look like a YouTube link.")
        opts = self._base_opts()
        # Keep previews snappy: fewer inner retries, the outer loop covers blips
        opts.update({"skip_download": True, "extract_flat": "in_playlist",
                     "extractor_retries": 2, "socket_timeout": 20})
        last = None
        for attempt in range(1, 4):
            try:
                with yt_dlp.YoutubeDL(opts) as ydl:
                    info = ydl.extract_info(url, download=False)
                return self._summarize(info, url)
            except DownloadError as e:
                last = e
                if _is_permanent(str(e)):
                    break
            except Exception as e:
                last = e
            time.sleep(1.5 * attempt)
        raise RuntimeError(_clean_error(last))

    def _summarize(self, info, url):
        if info.get("_type") == "playlist" or info.get("entries") is not None:
            entries = []
            for e in info.get("entries") or []:
                if not e:
                    continue
                vid = e.get("id")
                entries.append({
                    "id": vid,
                    "url": e.get("url") if str(e.get("url", "")).startswith("http")
                    else f"https://www.youtube.com/watch?v={vid}",
                    "title": e.get("title") or "Untitled",
                    "duration": e.get("duration"),
                    "uploader": e.get("uploader") or e.get("channel"),
                    "thumbnail": f"https://i.ytimg.com/vi/{vid}/mqdefault.jpg" if vid else None,
                })
            return {"type": "playlist", "url": url, "title": info.get("title") or "Playlist",
                    "uploader": info.get("uploader") or info.get("channel"),
                    "count": len(entries), "entries": entries,
                    "thumbnail": entries[0]["thumbnail"] if entries else None,
                    "subtitles": [
                        {"value": "any:en", "label": "English", "auto": False},
                        {"value": "orig", "label": "Original language (auto-generated)", "auto": True},
                    ]}

        formats = info.get("formats") or []
        audio_size = 0
        for f in formats:
            if f.get("vcodec") == "none" and f.get("acodec") not in (None, "none"):
                audio_size = max(audio_size, f.get("filesize") or f.get("filesize_approx") or 0)
        by_h = {}
        for f in formats:
            h = f.get("height")
            if not h or f.get("vcodec") in (None, "none"):
                continue
            size = f.get("filesize") or f.get("filesize_approx") or 0
            cur = by_h.setdefault(h, {"height": h, "fps": 0, "size": 0})
            cur["fps"] = max(cur["fps"], int(f.get("fps") or 0))
            cur["size"] = max(cur["size"], size)
        qualities = []
        for h in sorted(by_h, reverse=True):
            q = by_h[h]
            if h < 144:
                continue
            qualities.append({
                "value": h,
                "label": quality_label("video", h),
                "fps": q["fps"],
                "size": (q["size"] + audio_size) if q["size"] else None,
            })
        duration = info.get("duration") or 0
        thumb = info.get("thumbnail")
        return {
            "type": "video", "url": info.get("webpage_url") or url, "id": info.get("id"),
            "title": info.get("title"), "uploader": info.get("uploader") or info.get("channel"),
            "duration": duration, "view_count": info.get("view_count"),
            "upload_date": info.get("upload_date"), "thumbnail": thumb,
            "is_live": bool(info.get("is_live")),
            "qualities": qualities,
            "subtitles": _subtitle_choices(info),
            "audio": [
                {"value": "mp3-320", "label": "MP3 · 320 kbps", "size": int(duration * 40000) or None},
                {"value": "mp3-192", "label": "MP3 · 192 kbps", "size": int(duration * 24000) or None},
                {"value": "m4a", "label": "M4A · Original", "size": audio_size or None},
            ],
        }

    # ---------------- queue ----------------
    def add_jobs(self, items, kind, quality, subtitles=None, subtitles_label=None):
        created = []
        with self.lock:
            for it in items:
                url = (it.get("url") or "").strip()
                if not is_youtube_url(url):
                    continue
                q = quality
                if kind == "video" and q != "best":
                    q = int(q)
                job = Job(url, kind, q, it, subtitles, subtitles_label)
                self.jobs[job.id] = job
                self.order.append(job.id)
                created.append(job.to_dict())
            self._wake_scheduler()
        self.save_history()
        return created

    def list_jobs(self):
        with self.lock:
            return [self.jobs[i].to_dict() for i in reversed(self.order)]

    def cancel(self, job_id):
        job = self.jobs.get(job_id)
        if not job:
            return False
        job.cancel_event.set()
        if job.status in ("queued", "waiting"):
            self._finish(job, "cancelled", "Cancelled")
        return True

    def retry(self, job_id):
        job = self.jobs.get(job_id)
        if not job or job.status in Job.LIVE:
            return False
        with self.lock:
            job.cancel_event = threading.Event()
            job.status, job.stage = "queued", "Waiting in queue"
            job.error, job.attempt, job.progress, job.finished_at = None, 0, 0.0, None
            job.speed = job.eta = job.notice = None
            self._wake_scheduler()
        self.save_history()
        return True

    def remove(self, job_id):
        with self.lock:
            job = self.jobs.get(job_id)
            if not job:
                return False
            if job.status in Job.LIVE:
                job.cancel_event.set()
            self.jobs.pop(job_id, None)
            self.order = [i for i in self.order if i != job_id]
        self.save_history()
        return True

    def clear_finished(self):
        with self.lock:
            keep = [i for i in self.order if self.jobs[i].status in Job.LIVE]
            for i in self.order:
                if i not in keep:
                    self.jobs.pop(i, None)
            self.order = keep
        self.save_history()

    def _wake_scheduler(self):
        with self.wake:
            self.wake.notify_all()

    def _scheduler(self):
        """Start queued jobs while there are free slots. Sleeps until something
        changes (job added, finished, retried, or settings saved) instead of polling.
        The timeout is only a safety net."""
        while True:
            with self.wake:
                try:
                    active = sum(1 for j in self.jobs.values()
                                 if j.status in ("starting", "downloading", "processing", "waiting"))
                    limit = int(self.settings.get("max_concurrent", 2))
                    free = max(0, limit - active)
                    if free:
                        for i in self.order:
                            job = self.jobs[i]
                            if job.status != "queued":
                                continue
                            job.status, job.stage = "starting", "Starting..."
                            threading.Thread(target=self._run_job, args=(job,), daemon=True,
                                             name=f"job-{job.id}").start()
                            free -= 1
                            if not free:
                                break
                except Exception:
                    log.exception("Scheduler error")
                self.wake.wait(timeout=30)

    # ---------------- running a job ----------------
    def _run_job(self, job):
        outdir = self.settings["output_dir"]
        os.makedirs(outdir, exist_ok=True)
        embed_thumb = bool(self.settings.get("embed_thumbnail"))
        subtitles = job.subtitles
        last_error = None

        while job.attempt < job.max_attempts:
            job.attempt += 1
            job.retry_at = None
            job.status = "starting"
            job.stage = "Connecting to YouTube..." if job.attempt == 1 else \
                f"Retrying (attempt {job.attempt}/{job.max_attempts})..."
            try:
                if job.cancel_event.is_set():
                    raise Cancelled()
                self._download_once(job, outdir, embed_thumb, subtitles)
                job.progress = 100.0
                self._finish(job, "done", "Completed")
                return
            except Cancelled:
                self._cleanup_partials(job)
                self._finish(job, "cancelled", "Cancelled")
                return
            except Exception as e:
                if job.cancel_event.is_set():
                    self._cleanup_partials(job)
                    self._finish(job, "cancelled", "Cancelled")
                    return
                last_error = e
                msg = str(e).lower()
                job.add_log(_clean_error(e))
                log.warning("Job %s attempt %d/%d failed: %s", job.id, job.attempt,
                            job.max_attempts, _clean_error(e))
                if _is_permanent(msg):
                    break
                # A thumbnail problem shouldn't cost the whole download
                if "thumbnail" in msg and embed_thumb:
                    embed_thumb = False
                # Neither should a subtitle problem: retry without them and say so
                if "subtitle" in msg and subtitles:
                    subtitles = None
                    job.notice = "Subtitles couldn't be downloaded, so the video was saved without them."
                if any(h in msg for h in OUTDATED_HINTS) and self.update_state["status"] == "idle":
                    threading.Thread(target=self.update_engine, daemon=True).start()

            if job.attempt < job.max_attempts:
                wait = BASE_DELAY * 2 ** (job.attempt - 1) + random.uniform(0, 1)
                job.status = "waiting"
                job.retry_at = time.time() + wait
                job.stage = f"Failed, retrying in {int(wait)}s"
                job.error = _clean_error(last_error)
                if job.cancel_event.wait(wait):
                    self._cleanup_partials(job)
                    self._finish(job, "cancelled", "Cancelled")
                    return

        job.error = _clean_error(last_error)
        log.error("Job %s failed: %s (%s)", job.id, job.error, job.url)
        self._finish(job, "error", "Failed")

    def _download_once(self, job, outdir, embed_thumb, subtitles=None):
        opts = self._download_opts(job, outdir, embed_thumb, subtitles)
        with yt_dlp.YoutubeDL(opts) as ydl:
            info = ydl.extract_info(job.url, download=False)
            if job.cancel_event.is_set():
                raise Cancelled()
            if info.get("_type") == "playlist":
                raise DownloadError("This link is a playlist; add it from the playlist view.")
            job.video_id = info.get("id")
            job.title = info.get("title") or job.title
            job.uploader = info.get("uploader") or info.get("channel") or job.uploader
            job.thumbnail = info.get("thumbnail") or job.thumbnail
            job.duration = info.get("duration") or job.duration
            req = info.get("requested_formats") or [info]
            job._streams = max(1, len(req))
            job._stream_idx = 0
            job._stream_bytes_done = 0
            job.total_bytes = sum((f.get("filesize") or f.get("filesize_approx") or 0) for f in req)
            job._prefix = os.path.splitext(ydl.prepare_filename(info))[0]
            if subtitles and not info.get("requested_subtitles"):
                job.notice = "No subtitles in that language for this video, so it was saved without them."
            job.status, job.stage = "downloading", "Downloading..."
            result = ydl.process_ie_result(info, download=True)
        try:
            path = (result or {}).get("requested_downloads", [{}])[0].get("filepath")
            if path:
                job.filepath = path
        except Exception:
            pass
        if job.kind == "audio" and job.filepath and os.path.isfile(job.filepath):
            workdir = os.path.dirname(job.filepath)
            final = os.path.join(outdir, os.path.basename(job.filepath))
            os.replace(job.filepath, final)
            job.filepath = final
            try:
                os.rmdir(workdir)  # only succeeds when empty
            except OSError:
                pass

    def _progress_hook(self, job, d):
        if job.cancel_event.is_set():
            raise Cancelled()
        st = d.get("status")
        info = d.get("info_dict") or {}
        is_audio_stream = info.get("vcodec") == "none"
        label = "audio" if (is_audio_stream or job.kind == "audio") else "video"
        part = f" ({job._stream_idx + 1}/{job._streams})" if job._streams > 1 else ""
        if st == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate") or 0
            done = d.get("downloaded_bytes") or 0
            if total:
                frac = done / total
            elif d.get("fragment_count"):
                frac = (d.get("fragment_index") or 0) / d["fragment_count"]
            else:
                frac = 0
            overall = (job._stream_idx + min(frac, 1.0)) / job._streams
            job.status = "downloading"
            job.stage = f"Downloading {label}{part}"
            job.progress = round(min(overall * 100, 99.5), 1)
            job.speed = d.get("speed")
            job.eta = d.get("eta")
            job.downloaded_bytes = job._stream_bytes_done + done
            if total:
                job.total_bytes = max(job.total_bytes or 0, job._stream_bytes_done + total)
        elif st == "finished":
            job._stream_bytes_done += d.get("total_bytes") or d.get("downloaded_bytes") or 0
            job._stream_idx = min(job._stream_idx + 1, job._streams)
            job.progress = round(min(job._stream_idx / job._streams * 100, 99.5), 1)
            job.speed = job.eta = None

    def _pp_hook(self, job, d):
        if d.get("status") != "started":
            return
        names = {
            "Merger": "Merging video and audio",
            "FFmpegMerger": "Merging video and audio",
            "ExtractAudio": "Converting audio",
            "FFmpegExtractAudio": "Converting audio",
            "Metadata": "Writing tags",
            "FFmpegMetadata": "Writing tags",
            "EmbedThumbnail": "Embedding cover art",
            "FFmpegEmbedSubtitle": "Embedding subtitles",
            "EmbedSubtitle": "Embedding subtitles",
        }
        pp = d.get("postprocessor") or ""
        if pp in names or pp.startswith("FFmpeg"):
            job.status = "processing"
            job.stage = names.get(pp, "Finishing up")
            job.speed = job.eta = None

    def _cleanup_partials(self, job):
        if not job._prefix:
            return
        pattern = glob.escape(job._prefix)
        for p in glob.glob(pattern + "*"):
            if p.endswith((".part", ".ytdl", ".temp")) or ".part-Frag" in p or \
                    re.search(r"\.f\d+\.\w+(\.part)?$", p):
                try:
                    os.remove(p)
                except OSError:
                    pass

    def _finish(self, job, status, stage):
        job.status, job.stage = status, stage
        job.speed = job.eta = job.retry_at = None
        job.finished_at = time.time()
        if status == "done":
            job.error = None
        self._wake_scheduler()  # a slot may have opened up
        self.save_history()

    # ---------------- engine updates ----------------
    def update_engine(self):
        if self.update_state["status"] == "running":
            return self.update_state
        self.update_state = {"status": "running", "installed": None, "message": "Updating yt-dlp..."}
        ok = bootstrap.pip_install(bootstrap.spec("yt-dlp"), upgrade=True, required=False)
        try:
            new = metadata.version("yt-dlp")
        except Exception:
            new = None
        if not ok:
            self.update_state = {"status": "idle", "installed": None,
                                 "message": "Update failed. Check your internet connection."}
        elif new and new != self.engine_version:
            self.update_state = {"status": "restart", "installed": new,
                                 "message": f"yt-dlp {new} installed. Restart to use it."}
        else:
            self.update_state = {"status": "idle", "installed": new,
                                 "message": "Already up to date."}
        return self.update_state


# --------------------------------------------------------------------------- #
def _subtitle_choices(info):
    """Subtitle options for one video: uploaded subtitles first (the video's own
    language, then English, then A-Z), then automatic captions in the spoken
    language when there are no uploaded ones in that language."""
    def name_of(formats, code):
        for f in formats or []:
            if f.get("name"):
                return f["name"]
        return code

    spoken = (info.get("language") or "").split("-")[0].lower()
    manual = []
    for code, formats in (info.get("subtitles") or {}).items():
        if code == "live_chat" or not SUBS_RE.match(code):
            continue
        manual.append({"value": code, "label": name_of(formats, code), "auto": False})

    def rank(c):
        base = c["value"].split("-")[0].lower()
        return (base != spoken if spoken else True, base != "en", c["label"].lower())
    manual.sort(key=rank)

    have = {c["value"].split("-")[0].lower() for c in manual}
    auto = []
    for code, formats in (info.get("automatic_captions") or {}).items():
        if not code.endswith("-orig") or not SUBS_RE.match(code):
            continue
        if code[:-5].split("-")[0].lower() in have:
            continue
        label = name_of(formats, code).replace(" (Original)", "")
        auto.append({"value": f"auto:{code}", "label": f"{label} (auto-generated)", "auto": True})
    return manual + auto


def _is_permanent(msg):
    msg = (msg or "").lower()
    return any(p in msg for p in PERMANENT_ERRORS)


def _clean_error(e):
    if e is None:
        return "Unknown error"
    msg = str(e)
    msg = re.sub(r"\x1b\[[0-9;]*m", "", msg)
    msg = msg.replace("ERROR: ", "")
    msg = re.split(r";\s*please report this issue", msg, flags=re.I)[0]
    msg = re.sub(r"\s*\(caused by .*\)$", "", msg)
    msg = re.sub(r"^\[[\w:]+\]\s*[\w-]+:\s*", "", msg)
    if "Sign in to confirm you" in msg and "bot" in msg:
        return ("YouTube is asking to confirm you're not a bot. Wait a few minutes and retry, "
                "or try a different network.")
    if len(msg) > 300:
        msg = msg[:300] + "..."
    return msg.strip() or e.__class__.__name__


# --------------------------------------------------------------------------- #
def open_in_file_manager(path, select=False):
    path = os.path.abspath(path)
    if not os.path.exists(path):
        path = os.path.dirname(path)
        select = False
    if not os.path.exists(path):
        return False
    if sys.platform.startswith("win"):
        if select:
            subprocess.Popen(["explorer", "/select,", path])
        else:
            os.startfile(path)  # noqa
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path] if select else ["open", path])
    else:
        subprocess.Popen(["xdg-open", os.path.dirname(path) if select else path])
    return True


def pick_folder(initial):
    """Open a native folder picker in a separate process (safe from any thread)."""
    code = (
        "import tkinter as tk, sys\n"
        "from tkinter import filedialog\n"
        "r = tk.Tk(); r.withdraw(); r.attributes('-topmost', True)\n"
        "p = filedialog.askdirectory(initialdir=sys.argv[1], title='Choose download folder')\n"
        "print(p or '')\n"
    )
    try:
        out = subprocess.run([sys.executable, "-c", code, initial or os.path.expanduser("~")],
                             capture_output=True, text=True, timeout=600)
        return out.stdout.strip() or None
    except Exception:
        return None
