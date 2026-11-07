#!/usr/bin/env python3
"""
Clipvault - a modern YouTube downloader with a web interface.

Run:  python app.py
It installs anything it needs, starts a local server and opens your browser.
Options:  --port 8765   --no-browser
"""

import argparse
import json
import os
import socket
import subprocess
import sys
import threading
import time
import urllib.request
import webbrowser

APP_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, APP_DIR)

import bootstrap  # noqa: E402

TOOLS = bootstrap.ensure_all()

import logging  # noqa: E402

from flask import Flask, jsonify, request, send_from_directory  # noqa: E402
from werkzeug.exceptions import HTTPException  # noqa: E402

import downloader  # noqa: E402

downloader.setup_logging()
log = downloader.log

APP_NAME = "Clipvault"
APP_VERSION = "1.0.0"
DEFAULT_PORT = 8765

app = Flask(__name__, static_folder=os.path.join(APP_DIR, "static"), static_url_path="/static")
engine = downloader.Engine(TOOLS)
logging.getLogger("werkzeug").setLevel(logging.ERROR)
try:  # hide Flask's "development server" banner; this server is local-only
    import flask.cli
    flask.cli.show_server_banner = lambda *a, **k: None
except Exception:
    pass


def ok(data=None, **kw):
    out = {"ok": True}
    if data is not None:
        out["data"] = data
    out.update(kw)
    return jsonify(out)


def fail(message, code=400):
    return jsonify({"ok": False, "error": message}), code


def body():
    return request.get_json(silent=True) or {}


@app.errorhandler(Exception)
def unexpected_error(e):
    if isinstance(e, HTTPException):
        return e
    log.exception("Unhandled error on %s %s", request.method, request.path)
    return fail("Something went wrong. Details were written to data/clipvault.log.", 500)


# ---------------------------------------------------------------- pages
@app.get("/")
def index():
    resp = send_from_directory(app.static_folder, "index.html")
    resp.headers["Cache-Control"] = "no-store"
    return resp


# ---------------------------------------------------------------- api
@app.get("/api/health")
def health():
    return ok({
        "app": APP_NAME.lower(), "version": APP_VERSION,
        "engine": engine.engine_version,
        "ffmpeg": bool(TOOLS.get("ffmpeg")),
        "js_runtime": "deno" if TOOLS.get("deno") else ("node" if TOOLS.get("node") else None),
        "update": engine.update_state,
    })


@app.post("/api/info")
def info():
    url = (body().get("url") or "").strip()
    if not url:
        return fail("Paste a YouTube link first.")
    try:
        return ok(engine.fetch_info(url))
    except ValueError as e:
        return fail(str(e))
    except Exception as e:
        log.warning("Fetching info failed for %s: %s", url, e)
        return fail(str(e), 502)


@app.post("/api/download")
def download():
    b = body()
    kind = b.get("kind", "video")
    quality = b.get("quality", "best")
    items = b.get("items") or ([{"url": b.get("url")}] if b.get("url") else [])
    if kind not in ("video", "audio"):
        return fail("Unknown download type.")
    if kind == "audio" and quality not in ("mp3-320", "mp3-192", "m4a"):
        return fail("Unknown audio format.")
    if kind == "video" and quality != "best":
        try:
            quality = int(quality)
        except (TypeError, ValueError):
            return fail("Unknown video quality.")
    try:
        subtitles = downloader.parse_subtitles(b.get("subtitles")) if kind == "video" else None
    except ValueError as e:
        return fail(str(e))
    jobs = engine.add_jobs(items, kind, quality, subtitles, b.get("subtitles_label"))
    if not jobs:
        return fail("No valid YouTube links to download.")
    return ok(jobs)


@app.get("/api/jobs")
def jobs():
    return ok(engine.list_jobs(), update=engine.update_state)


@app.post("/api/jobs/<job_id>/cancel")
def cancel(job_id):
    return ok() if engine.cancel(job_id) else fail("Download not found.", 404)


@app.post("/api/jobs/<job_id>/retry")
def retry(job_id):
    return ok() if engine.retry(job_id) else fail("This download can't be retried right now.")


@app.delete("/api/jobs/<job_id>")
def remove(job_id):
    return ok() if engine.remove(job_id) else fail("Download not found.", 404)


@app.post("/api/jobs/clear")
def clear():
    engine.clear_finished()
    return ok()


@app.post("/api/open")
def open_path():
    b = body()
    job = engine.jobs.get(b.get("id")) if b.get("id") else None
    if job and job.filepath:
        done = downloader.open_in_file_manager(job.filepath, select=True)
    else:
        os.makedirs(engine.settings["output_dir"], exist_ok=True)
        done = downloader.open_in_file_manager(engine.settings["output_dir"])
    return ok() if done else fail("Couldn't find that file. It may have been moved or deleted.")


@app.route("/api/settings", methods=["GET", "POST"])
def settings():
    if request.method == "GET":
        return ok(engine.get_settings())
    try:
        return ok(engine.update_settings(body()))
    except Exception as e:
        log.warning("Saving settings failed: %s", e)
        return fail(f"Couldn't save settings: {e}")


@app.post("/api/pick-folder")
def pick_folder():
    path = downloader.pick_folder(engine.settings.get("output_dir"))
    if not path:
        return ok(None)
    return ok(engine.update_settings({"output_dir": path}))


@app.post("/api/update")
def update():
    threading.Thread(target=engine.update_engine, daemon=True).start()
    return ok({"status": "running"})


@app.post("/api/restart")
def restart():
    def _go():
        time.sleep(0.6)
        engine.save_history()
        env = dict(os.environ, CLIPVAULT_RESTARTED="1")
        args = [sys.executable, os.path.join(APP_DIR, "app.py"), "--port",
                str(app.config["PORT"]), "--no-browser"]
        subprocess.Popen(args, env=env, cwd=os.getcwd())
        os._exit(0)
    threading.Thread(target=_go, daemon=True).start()
    return ok()


# ---------------------------------------------------------------- startup
def port_free(port):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind(("127.0.0.1", port))
            return True
        except OSError:
            return False


def already_running(port):
    try:
        with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=1.5) as r:
            return json.load(r).get("data", {}).get("app") == "clipvault"
    except Exception:
        return False


def main():
    parser = argparse.ArgumentParser(description="Clipvault YouTube downloader")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()

    port = args.port
    url = f"http://127.0.0.1:{port}"

    if os.environ.get("CLIPVAULT_RESTARTED"):
        for _ in range(50):  # wait for the old process to release the port
            if port_free(port):
                break
            time.sleep(0.2)
    elif not port_free(port):
        if already_running(port):
            print(f"[clipvault] Already running at {url}")
            webbrowser.open(url)
            return
        for p in range(port + 1, port + 50):
            if port_free(p):
                port = p
                url = f"http://127.0.0.1:{port}"
                break

    app.config["PORT"] = port
    print()
    print(f"  {APP_NAME} is running at  {url}")
    print(f"  Downloads go to:          {engine.settings['output_dir']}")
    print("  Keep this window open while downloading. Press Ctrl+C to quit.")
    print()
    if not args.no_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    try:
        app.run(host="127.0.0.1", port=port, threaded=True, debug=False, use_reloader=False)
    except KeyboardInterrupt:
        pass
    finally:
        engine.save_history()


if __name__ == "__main__":
    main()
