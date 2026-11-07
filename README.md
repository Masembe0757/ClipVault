# Clipvault

A modern, local YouTube downloader with a clean web interface.
Download videos in up to 4K, or save music as high-quality MP3.

## Features

- **Paste and go.** Paste a link, or press Ctrl+V anywhere on the page, or drag a link onto it.
- **Video up to 4K.**
  - You see every available quality with its estimated size: 4K, 2K, 1080p, 720p and so on.
  - Videos are saved as `.mp4`.
- **Music mode.** Save audio as MP3 (320 or 192 kbps) or as the original M4A, with the cover art and tags embedded.
- **Subtitles.**
  - Pick a subtitle language before downloading a video. Uploaded subtitles are listed first, then YouTube's auto-generated captions.
  - Subtitles are embedded in the `.mp4`, and also saved as a separate `.srt` file unless you turn that off in Settings.
  - If a video has no subtitles in that language, it is still downloaded, with a note on the download.
- **Playlists.**
  - Paste a playlist link to see every video in it.
  - Pick the ones you want and download them all in one go.
- **Live progress.** Each download shows its percentage, speed, size and time left.
- **Queue.** Several downloads can run at once. You choose how many in Settings.
- **Retries.**
  - Network errors are retried with backoff, at both the connection and the fragment level.
  - Partial downloads resume where they stopped.
  - Each download gets up to 5 full attempts.
  - Errors that can't be fixed by retrying are detected and skipped: private, removed or region-blocked videos.
- **Self-updating engine.**
  - yt-dlp is updated when it gets old, or when YouTube changes break downloads.
  - You can also update it in one click from Settings.
- **History.** Your download list is kept between sessions.
- **Look.** Dark and light themes, and the layout works on small screens too.

## Requirements

You need **Python 3.9 or newer**. Everything else is installed automatically on first run:

| Package | What it's for |
|---|---|
| Flask | The local web interface |
| yt-dlp | The download engine |
| ffmpeg (via `imageio-ffmpeg`) | Merging HD video with audio, and converting to MP3 |
| Deno | The JavaScript runtime YouTube now requires |

The first run downloads roughly 100 MB of tools. After that, the app starts in seconds.

To install the dependencies yourself instead, run `python -m pip install -r requirements.txt`.

## How to run

**Windows:** double-click **`run.bat`**.

**Git Bash / MSYS2 / macOS / Linux:**

```bash
cd clipvault
bash run.sh
```

**Or directly with Python:**

```bash
python app.py
```

Clipvault opens in your browser at **http://127.0.0.1:8765**. Keep the terminal window open while you download, and press **Ctrl+C** in it to quit.

Options:

```
python app.py --port 9000      # use another port
python app.py --no-browser     # don't open the browser automatically
```

## Where files go

By default, files are saved to **`Downloads/Clipvault`** in your user folder. To change this, open **Settings** (the sliders icon), then use **Browse** or type a path and press Enter.

## Troubleshooting

| Problem | Fix |
|---|---|
| `python: command not found` | Use `run.bat`/`run.sh`, which find Python for you. Or call Python by its full path, e.g. `/c/Users/<you>/AppData/Local/Programs/Python/Python312/python.exe app.py` |
| Downloads suddenly fail | Settings → **Check for updates**, then **Restart now** |
| "Confirm you're not a bot" | YouTube is rate-limiting your network. Wait a few minutes, or try another network |
| Video won't play on TV/phone | Turn on **Maximum compatibility** in Settings (it's on by default) |
| Port already in use | Clipvault picks the next free port automatically, or use `--port` |
| Something else went wrong | Warnings and errors are written to `data/clipvault.log` |

## Project layout

```
clipvault/
├── app.py          # entry point: web server + API
├── downloader.py   # download engine: queue, progress, retries, history
├── bootstrap.py    # installs and updates dependencies
├── requirements.txt # supported dependency versions (for manual installs)
├── static/         # the interface (HTML, CSS, JS)
├── data/           # settings, history and clipvault.log (created at runtime)
├── run.bat         # Windows launcher
└── run.sh          # macOS / Linux / Git Bash launcher
```

## Note

Only download videos you own, that are Creative Commons licensed, or that you have permission to save. Respect YouTube's Terms of Service and creators' rights.
