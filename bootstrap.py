"""
Dependency bootstrap: makes sure everything Clipvault needs is installed
before the rest of the app is imported. Uses only the standard library.
"""

import importlib
import os
import shutil
import subprocess
import sys
import sysconfig
import time

PIP_RETRIES = 3

# Version ranges Clipvault is tested with. Keep requirements.txt in sync.
# Each entry: (pip spec, distribution name, minimum version, first unsupported major).
# yt-dlp has no upper bound on purpose: YouTube changes often, so it must stay current.
REQUIREMENTS = {
    "flask": ("flask>=3.0,<4", "flask", (3, 0), 4),
    "yt-dlp": ("yt-dlp[default]>=2025.11.12", "yt-dlp", (2025, 11, 12), None),
    "imageio-ffmpeg": ("imageio-ffmpeg>=0.5,<1", "imageio-ffmpeg", (0, 5), 1),
    "deno": ("deno>=2,<3", "deno", (2,), 3),
}


def log(msg):
    print(f"[clipvault] {msg}", flush=True)


def _add_scripts_dirs_to_path():
    """pip puts executables (deno, yt-dlp) in a Scripts folder that is often
    not on PATH (common on Windows). Add those folders for this process."""
    dirs = [sysconfig.get_path("scripts")]
    try:
        scheme = sysconfig.get_preferred_scheme("user")
        dirs.append(sysconfig.get_path("scripts", scheme=scheme))
    except Exception:
        pass
    current = os.environ.get("PATH", "").split(os.pathsep)
    for d in dirs:
        if d and os.path.isdir(d) and d not in current:
            os.environ["PATH"] = d + os.pathsep + os.environ.get("PATH", "")


def ensure_pip():
    try:
        import pip  # noqa: F401
    except ImportError:
        log("pip not found, bootstrapping it...")
        subprocess.run([sys.executable, "-m", "ensurepip", "--upgrade"], check=False)


def pip_install(package, upgrade=False, required=True):
    """Install a package, retrying and falling back to --user and
    --break-system-packages for locked-down or externally managed Pythons."""
    base = [sys.executable, "-m", "pip", "install", "--quiet",
            "--disable-pip-version-check", "--no-warn-script-location"]
    if upgrade:
        base.append("--upgrade")
    variants = [[], ["--user"], ["--break-system-packages"], ["--user", "--break-system-packages"]]
    last = None
    for attempt in range(1, PIP_RETRIES + 1):
        for extra in variants:
            last = subprocess.run(base + extra + [package], capture_output=True, text=True)
            if last.returncode == 0:
                importlib.invalidate_caches()
                _add_scripts_dirs_to_path()
                return True
        wait = 3 * attempt
        log(f"Installing {package} failed (attempt {attempt}/{PIP_RETRIES}), retrying in {wait}s...")
        time.sleep(wait)
    if required:
        log(f"Could not install {package}.\n{(last.stderr or '').strip()}")
        log("Check your internet connection and try again.")
        sys.exit(1)
    return False


def _has(module):
    try:
        importlib.import_module(module)
        return True
    except ImportError:
        return False


def _version_tuple(text):
    parts = []
    for piece in str(text).split("."):
        digits = ""
        for ch in piece:  # leading digits only: "0rc1" -> 0
            if not ch.isdigit():
                break
            digits += ch
        if not digits:
            break
        parts.append(int(digits))
        if len(digits) < len(piece):  # pre-release suffix ends the numeric part
            break
    return tuple(parts)


def _satisfies(name):
    """True when the installed distribution is inside the supported range."""
    _spec, dist, minimum, max_major = REQUIREMENTS[name]
    try:
        from importlib import metadata
        installed = _version_tuple(metadata.version(dist))
    except Exception:
        return False
    if installed < minimum:
        return False
    return max_major is None or (installed and installed[0] < max_major)


def spec(name):
    return REQUIREMENTS[name][0]


def _engine_is_stale(max_age_days=21):
    """yt-dlp versions are dates (e.g. 2026.10.26). Treat old ones as stale."""
    try:
        from importlib import metadata
        from datetime import date
        y, m, d = (int(x) for x in metadata.version("yt-dlp").split(".")[:3])
        return (date.today() - date(y, m, d)).days > max_age_days
    except Exception:
        return False


def find_ffmpeg():
    path = shutil.which("ffmpeg")
    if path:
        return path
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception:
        return None


def find_deno():
    path = shutil.which("deno")
    if path:
        return path
    try:
        import deno
        return deno.find_deno_bin()
    except Exception:
        return None


def ensure_all():
    _add_scripts_dirs_to_path()
    ensure_pip()

    if not _has("flask") or not _satisfies("flask"):
        log("Installing Flask (web interface)...")
        pip_install(spec("flask"))

    if not _has("yt_dlp") or not _satisfies("yt-dlp"):
        log("Installing yt-dlp (download engine)...")
        pip_install(spec("yt-dlp"), upgrade=True)
    elif _engine_is_stale():
        # YouTube changes often; an old yt-dlp is the #1 cause of failed downloads.
        log("Updating yt-dlp to the latest version...")
        pip_install(spec("yt-dlp"), upgrade=True, required=False)

    if not find_ffmpeg():
        log("Installing ffmpeg (needed for HD video and MP3)...")
        pip_install(spec("imageio-ffmpeg"))

    # YouTube needs a JavaScript runtime for reliable extraction.
    if not find_deno() and not shutil.which("node"):
        log("Installing Deno (JavaScript runtime for YouTube)... this is a one-time ~40 MB download")
        pip_install(spec("deno"), required=False)

    return {"ffmpeg": find_ffmpeg(), "deno": find_deno(), "node": shutil.which("node")}
