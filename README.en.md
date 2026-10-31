# Image Hunter

**English** | [中文](README.zh.md) | [Русский](README.md)

Local image browser **+ image search in search engines + bulk saving by links** — all in one window, on four tabs (the fourth is “📜 Log”: a chronicle of everything the app does). For Windows and Linux.

Written in Python + PySide6 (Qt6): heavy operations (rendering, network, image decoding) are done by native Qt, so the interface is fast and responsive.

> **⚡ Special focus — fast work over the network and with network drives** (SMB/NAS, mounted shares): a folder is read in one request, thumbnails are built only for the visible part of the list, ready previews are cached on disk. A network folder with thousands of photos opens without lags — neither in the app nor on the network. Details in [“Fast work over the network and with network drives”](#fast-work-over-the-network-and-with-network-drives).

## Fast work over the network and with network drives

Image Hunter was written from day one for the scenario “photos live on a network drive (NAS, Windows share, mounted folder) and the pipe is not infinite”. Ordinary viewers die in this scenario: a list of 10 000 files means 10 000 stat calls over the network, and bulk thumbnail loading clogs the pipe. Below is what exactly is done and why it works.

**1. A folder is read in one pass — no stat per file.** The classic `os.listdir()` + `os.stat()` per file approach becomes two network operations per file over SMB. Image Hunter uses `os.scandir()`: file type, size and modification time arrive together with the listing — opening a folder is one network operation no matter how many files it holds. Hidden files and images are filtered from the same data, without a single extra request.

**2. Lazy thumbnails: only what is visible is loaded.** Bulk preview loading is fully disabled. Thumbnails are built only for the visible part of the list (plus a screen-height margin); scrolling loads the next portion, scrolling back re-reads nothing. You open a network folder — the app requests exactly the files that fit on the screen (six out of a thousand in a typical window). The “🖼 Thumbnails” toggle disables previews entirely — the state is remembered between runs.

**3. Disk thumbnail cache — reopening is instant.** Every ready thumbnail is written to `%LOCALAPPDATA%\ImageHunter\thumbs` (Linux: `~/.cache/ImageHunter/thumbs`). The key is SHA-1 of “path + size + mtime”: if a file changes, its cache entry goes stale by itself. Reopening the same network folder renders from the local cache and makes zero network requests for the pictures. Cache limit is 256 MB, writes are atomic (via a temp file) — a connection drop leaves no broken thumbnails.

**4. Task generations: leave the folder — stale work is silently dropped.** Every scan gets a generation number. Thumbnails and search results from the previous folder that arrive late are discarded: the task queue does not grow, the network does not carry work nobody needs.

**5. Subfolder search — in the background, without blocking the window.** Name search runs in a background thread with the same one-pass scandir and delivers results as it goes: the window stays responsive, the network is loaded evenly, thumbnails are not read during the search.

**6. The interface — set it once.** The width of the folder tree and the thumbnail strip is remembered between runs; icons are handed to the list in batches — hundreds of new rows do not cause a repaint storm.

**7. Network in downloads — fast but polite.** Downloads run up to 6 files in parallel in a QThreadPool, streamed to disk in 64 KB chunks (the file is never held in memory), 10/60 s timeouts, 100 MB per-file limit. Saving runs in 3 threads — gentle to the source sites.

**8. Updates bypass the CDN cache.** The installer and the update check fetch code via `codeload.github.com`, which generates the archive on the fly: a new version is available right after the push, without the 5-minute cache of `raw.githubusercontent.com`.

## Instant startup and freeze protection (v0.7.0)

The main source of weight and freezes in Image Hunter is the embedded browser of the search tabs: every QWebEngineView is a whole Chromium process. Since v0.7.0 the architecture is modular and lazy — heavy things start only when they are actually needed:

**1. Zero Chromium at app startup.** Previously every search tab created its browser immediately at startup and opened the start page: restoring 11 tabs meant 11 Chromium processes and 11 simultaneous page loads — on a weak machine or a slow network this looked like a freeze. Now a tab at startup is only its toolbar (a few kilobytes of UI). The tab's browser is created the first time the tab is shown (`showEvent`). Until you open the "Image search" tab, Chromium does not start at all — the window appears instantly.

**2. "Search everywhere" without a load storm.** Searching in all engines at once no longer fires a dozen loads simultaneously: tabs without a browser only remember the request (pending) and run it when you open the tab. Network, memory and CPU are spent exactly on what you are looking at; a tab you never open has not cost a single megabyte.

**3. All WebEngine configuration in one module.** `app/core/webengine.py` is the single place: platform-plugin warning capture (broken Wayland), `--disable-gpu` (auto-detected, IH_GPU), `--disable-dev-shm-usage` (on systems with a tiny /dev/shm tabs silently crashed and restarted in a loop), `--disable-breakpad`, and `--no-sandbox` — only when the kernel forbids user namespaces (otherwise tabs crash in a loop and look frozen; the switch is visible in the Log, bring the sandbox back with `IH_NO_SANDBOX=0`).

**4. Watchdog for "eternal" loads.** A page that has not opened within 45 seconds (dead network, hanging redirect) is stopped automatically — a tab never spins an endless load, and the Log shows which URL failed.

**5. Search engine data in a separate module.** The engine list, URL templates and SERP recognition moved to `app/core/engines.py` — pure data without UI: reusable anywhere and testable without Qt.

## Network drives and huge folders: freezes eliminated (v0.7.2)

The Log diagnostics (⏱ lines and "⚠ The UI did not respond") showed that on a WebDAV drive (Z:) thumbnails and folder opening froze the whole process for the network timeout (~60 s). Since v0.7.2 no network operation ever touches the GUI thread or Qt file reading:

**1. Images are read with Python I/O and decoded from memory.** `app/core/imgload.py` reads the whole file with a plain `open().read()` first — CPython releases the GIL during the read, so a file stuck on the network blocks only its worker thread while the UI and all other threads keep running. Decoding happens from memory (QImageReader over QBuffer, AVIF via Pillow); the file is also traversed once instead of two-three times like path-based QImageReader (size() + read() + AVIF sniff) — three times fewer round-trips on a network drive.

**2. Folder opening is asynchronous.** The folder scan (os.scandir over the network) runs in a worker thread: clicking a folder or "Open Folder…" instantly clears the strip, shows "Reading folder…", and files appear when ready. You can switch folders while scanning — the stale result is dropped. The auto-shown last folder at startup scans in the background too, so startup stays instant even on a network drive.

**3. The folder tree loads in the background.** Clicking and expanding a node no longer wait for scandir: subfolders appear once read (until then the node still looks expandable). Synchronous reading remains only where the result is needed immediately — the folder filter and highlighting the current folder.

**4. Network thumbnails use a dedicated narrow pool.** Files on mapped drives (Windows, DRIVE_REMOTE — WebDAV/SMB) load through a 2-thread pool: when the server hangs, one or two tasks wait while local thumbnails keep loading. Full-size viewing follows the same scheme.

**5. Deletion runs in the background.** Recycle Bin and permanent deletion are done by a worker thread (dialogs stay in the GUI): deleting many files over the network no longer stops the window. Recycle Bin failures still ask about permanent deletion, as before.

**6. Honest wording in the Log.** Slow operations from worker threads are marked "⏱ SLOW (in background, UI stays alive)", while "…this blocks the UI" remains only for operations that actually stalled the GUI thread — the log shows at a glance where the freeze was.

## Checkboxes on Google and Mail.ru work again (v0.7.3)

Neither case is "broken outright" — both search engines changed their markup, so the checkbox injection stopped reaching the tiles:

**1. Mail.ru unified its search portal.** The address `go.mail.ru/search_images` now redirects to `mail.ru/search?...&type=images`, and the image results themselves open in a nested `yandex.ru/images` frame inside. The old gate "inject only if the main page IS a results page" cut Mail.ru off for good: the wrapper address is not a results page. Now SERP frames are looked up regardless of the wrapper address: injection and the checked-counter work on any page that has a results frame inside, and the Mail.ru engine entry opens the final address `mail.ru/search?text=…&type=images` directly (no extra redirect).

**2. Google changed its tile markup again.** Google's hashed class names change from release to release, and any single-class selector stops matching sooner or later. Instead of playing the class-name lottery, the checkbox now "climbs" by quality: if the container does not look like a tile and the best candidate is just a thumbnail, the scan walks up the parents and takes the minimal wrapper that knows the true original (the `/imgres?imgurl=…` anchor) — but never a wrapper that swallows neighboring tiles. One checkbox per tile, and the "best" is still the original.

**3. Diagnostics in the Journal.** After the injection the log gets a line "Image SERP: tiles with checkboxes: N (frames: M)"; if no tiles were recognized — "Image SERP found, but no checkbox tiles were recognized… please send this log to the developer": the next "checkboxes gone" report immediately tells whether the injection arrived and how many tiles were recognized.

Additionally, `udm=2` counts as a results page on any national Google domain (google.de, google.co.uk, …) — Google moves between them on its own; the checkbox scan is isolated per tile (one broken tile no longer wrecks the whole scan).

## Features

**📁 My Pictures** — local viewer:
- **drive and folder tree on the left**: mounted drives and devices (free space in the tooltip), quick links “Home” and “Pictures”; folders expand lazily, a click on a folder shows its images right away; the panel width is adjusted with the mouse; the “⟳” button refreshes the drive list (after plugging in a USB stick);
- **folder filter**: the “🔍 Filter folders…” box above the tree — as you type, the tree keeps only folders whose
  names contain those letters: the rest are hidden, branches to the matches expand, and a counter above the tree
  shows how many folders matched; it is instant and does not rescan the disk — the tree just loads more levels
  within a budget (300 folders or 1.5 s at a time), so even a huge or network disk cannot freeze the window;
  case-insensitive, a click opens the folder, Enter opens the first match, Esc resets; hidden folders are not shown;
- **lazy thumbnails** (see the network section above) and the “🖼 Thumbnails” on/off toggle;
- **multi-select and drag'n'drop**: select images in the strip (Ctrl/Shift, like in Explorer) and drag them into Explorer, e-mail or any other application — the original files are passed on (`text/uri-list`); the drag start is backed by three independent paths (event filter, own mouse-move tracking, built-in Qt mechanics) and every step is written to the Log; **if dragging does not work — a no-drag fallback:** `Ctrl+C` (or right-click → “Copy selected files”), then paste them wherever needed — `Ctrl+V` into Explorer or a browser;
- **search by file name**: type part of the name — all images in the current folder and all subfolders are found; no masks or stars, case-insensitive, results appear as the scan goes; the **“ignore hyphens”** checkbox matches without hyphens — the query “23542-23523” finds “2354223523” and “23542-23523” alike (part numbers are written with the hyphen elsewhere or not at all); the checkbox state is remembered;
- **deleting files**: press `Delete` or right-click → “🗑 Delete” — the selected images are moved to the Recycle Bin (restorable from Explorer); a confirmation shows the number of files, every failure is logged with its reason. On drives without a Recycle Bin (network drives, some removable ones) ImageHunter offers to delete files permanently — after a separate confirmation;
- the last folder reopens automatically on start (if it holds up to 2000 images), and the last search query is restored exactly as it was before closing;
- full-screen view, zoom (`+` / `−` / `Ctrl+wheel`), “fit to window”, “100%”;
- navigation with ←/→, human-friendly sorting (file2 < file10);
- **AVIF support**: `.avif` files show up in the strip with thumbnails and full-screen view, and AVIF images downloaded by links (marketplaces serve AVIF even under a `.jpg` name) can be re-saved into any of the formats; the decoder is Pillow + pillow-avif-plugin (installed automatically);
- the selected image loads in a background thread — picking a file on a network drive (or a heavy AVIF) no longer freezes the window (“Not Responding”);
- animated GIF, JPG/PNG/WEBP/BMP/GIF/AVIF support;
- double-click a thumbnail — open with the system viewer; “Show in Explorer” button;
- the thumbnail strip is resized with the mouse via the splitter (panel widths are remembered between runs), the search field sits on the toolbar.

**🌐 Image Search** — built-in Chromium browser:
- **browser-like multiple tabs**: “＋”/Ctrl+T opens another search tab, each with its own engine and browser; right-click a tab to duplicate / close / close others / close to the right; the × closes a tab (closing the last one spawns a fresh one), tabs are draggable; the tab title is the selected engine and the colored dot is its brand color (Yandex — red, DuckDuckGo — orange, Google — blue, Bing — green); open tabs are restored on the next start;
- **one box — all engines**: a shared query bar above the tabs; press Enter or
  **“🔎 Search everywhere”** and the query opens in all 11 search engines at once,
  each in its own tab (tabs that are already open reload with the new results);
- engines (11): Yandex Images, Google, Bing, DuckDuckGo (safe mode),
  Brave, Startpage, Mojeek, Baidu, Sogou, Naver, Mail.ru;
- Yandex captcha can be entered right in the built-in browser;
- **checkboxes on result tiles**: mark the images you need with orange ticks — a counter appears on the button, and “Download checked” downloads the full-size originals (for Yandex the `origUrl` is taken — the same file that opens when you click the preview, e.g. `avatars.mds.yandex.net/get-mpic/…/orig`; for other engines — the original from the tile link parameters);
- checkboxes work with the current DuckDuckGo markup (2025): tiles without familiar class names, and “originals” from the Bing cache that have no file extension are recognized and marked;
- checkboxes also work with the current Google Images markup (udm=2): extension-less `encrypted-tbn0.gstatic.com`/`googleusercontent` thumbnails are recognized, lazy tiles whose picture loads after rendering get their tick, and continuous page re-rendering no longer delays the checkboxes;
- checkboxes also work with the current Brave markup (extension-less `imgs.search.brave.com` proxy thumbnails — the true original is unwrapped from the base64 in the URL path), Sogou (tile classes and the `drag-img` attribute) and Mail.ru (results live in a nested frame — checkboxes and collection work inside frames too). Mail.ru has unified its search portal: go.mail.ru/search_images now redirects to mail.ru/search?type=images — that address is recognized as a results page as well, and the injection is no longer tied to the wrapper page URL;
- when a search engine changes its tile markup (Google rotates hashed class names regularly), the checkbox "climbs" from the thumbnail to the nearest wrapper that knows the true original — ticks and originals are not lost;
- the Journal shows checkbox diagnostics: how many tiles got ticks on the results page (or "none recognized" — please send the log to the developer);
- checkboxes pick up tiles loaded while scrolling the endless feed;
- **“✕ Clear checks”** — removes all orange ticks with one click (enabled when there is at least one);
- **“💾 Save to folder”** — checked tiles are converted to the selected format (WebP, PNG, JPEG, BMP, TIFF — the picker sits next to the button and is remembered) and saved to the folder open on the “My Pictures” tab: the first file is `name.ext`, then `name-1.ext`, `name-2.ext`… **Existing files are never overwritten:** occupied names are skipped and the name is re-checked right before writing — if `name.webp` and `name-2.webp` already exist, the new files become `name-1.webp` and `name-3.webp`. Transparency is flattened onto white for JPEG/BMP, EXIF rotation is respected. The name is asked on save (default — the search query); if no folder is open, the app offers to pick one; saved files appear in the viewer immediately.
- **“📋 Collect links”** — as before: every image on the open results page (thumbnails, originals from the DuckDuckGo proxy, from Yandex `data-bem`/`data-state` JSON) in one batch to the downloads.

**⬇️ Downloads** — the saving manager:
- bulk download by direct links (up to 6 files in parallel);
- manual paste of links (one per line);
- session link de-duplication, no file overwriting (`-1`, `-2`… suffixes);
- file names come from the URL, the extension is refined by `Content-Type`;
- when a CDN refuses (401/403/429), the downloader retries with fallbacks: no Referer, the image site's own Referer, and for Cloudflare `/cdn-cgi/image/…` wrappers — the direct original URL;
- download folder picker (default `Pictures\ImageHunter`), 100 MB per-file limit.

**📜 Log** — the activity chronicle (tab added on the right):
- which folders were opened, what the search found, which files were dragged and how the drag ended, how much was downloaded/saved, which errors happened; if a specific file failed to download or save, the log shows both the link and the reason (e.g. “not an image (text/html)”, timeout, “file too large”);
- errors are highlighted red, warnings orange; the log keeps the last 5000 lines;
- “🧹 Clear” and “📋 Copy all” buttons — easy to attach the log to a bug report; uncaught exceptions land in the log too;
- the main-window tabs can be dragged with the mouse and rearranged in any order.

The app icon (“a photo with a magnifier”) is drawn programmatically and embedded into the window; a multi-size `app_icon.ico` for Windows ships with the app.

## Interface languages

Russian, English and Chinese (simplified). The picker sits in the status bar; the translation applies on the fly, without restarting, and the choice is remembered.

## Installation

### One-line install (recommended)

The installer asks for the installation folder, creates a virtual environment, downloads dependencies and creates shortcuts.

**Windows** (PowerShell — copy the whole line):

```powershell
irm https://codeload.github.com/teliy/image-hunter/zip/refs/heads/main -OutFile "$env:TEMP\ih.zip"; Expand-Archive "$env:TEMP\ih.zip" "$env:TEMP\ih-src" -Force; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-src\image-hunter-main\install.ps1"
```

**Linux** (bash):

```bash
curl -fsSL https://raw.githubusercontent.com/teliy/image-hunter/main/install.sh | bash
```

The installer checks Python 3.10–3.14 (offers to install it if missing), asks where to install, downloads the code (no git needed), creates `.venv`, installs dependencies and creates a Start-menu shortcut (Windows) or a `.desktop` entry and the `image-hunter` command (Linux).

> **Alpine Linux (musl):** the installer understands `apk` and accepts Python 3.10–3.14 (3.12 in stable, 3.14 in edge). PySide6 ships no musl wheels, so the installer adds `gcompat` and lets pip pick glibc wheels — usually enough, but QtWebEngine may still fail to start on musl; the reliable option is Docker or a glibc-based distro (Debian, Ubuntu, Fedora).

**Update and uninstall:**

| Action | Windows | Linux |
|---|---|---|
| Update | `ImageHunter.bat update`, or right from the app: “Help → Check for updates” / the “🔄 Update” button (Ctrl+U) | `image-hunter update` |
| Uninstall | `ImageHunter.bat uninstall` | `image-hunter uninstall` |
| Version | `ImageHunter.bat version` | `image-hunter --version` |

### Installing from a private repository (with a token)

GitHub does not serve `raw.githubusercontent.com` files of a **private** repository without authorization — the usual one-liner returns `404: Not Found`. Download the installer with an `Authorization` header and run it locally.

**Windows** (PowerShell, one line — put your token in):

```powershell
$t="ghp_YOUR_TOKEN"; iwr https://raw.githubusercontent.com/teliy/image-hunter/main/install.ps1 -Headers @{Authorization="token $t"} -UseBasicParsing -OutFile "$env:TEMP\ih-install.ps1"; $env:IH_GH_TOKEN=$t; powershell -NoProfile -ExecutionPolicy Bypass -File "$env:TEMP\ih-install.ps1"
```

**Linux** (bash):

```bash
export IH_GH_TOKEN=ghp_YOUR_TOKEN
curl -fsSL -H "Authorization: token $IH_GH_TOKEN" https://raw.githubusercontent.com/teliy/image-hunter/main/install.sh | bash
```

The token needs read access to the repository: classic — the `repo` scope, fine-grained — “Contents: Read-only”. The installer stores the token in `.gh_token` inside the installation folder for future auto-updates; delete the file if that is not wanted.
Variables for non-interactive runs: `IH_ASSUME_YES=1`, `IH_DIR=<path>`, `IH_PYTHON=/path/to/python` (set the interpreter manually if the auto-detection does not fit).

### Manual installation

Requires Windows 10/11 and Python 3.10–3.14 (64-bit).

```bat
git clone https://github.com/teliy/image-hunter.git
cd image-hunter
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python main.py
```

## How to use

1. **Find images:** “Image Search” tab → type the query → pick the engine → “Search”.
   Or type it into the shared bar above the tabs — “🔎 Search everywhere” opens it in all engines at once.
2. **Collect links:** wait for the results page (you can scroll down) → “📋 Collect links”. The list goes to the “Downloads” tab automatically and the download starts right away.
3. **Save manually:** “Downloads” tab → paste direct links → “⬇ Download links”.
4. **See what you got:** the “Open” button opens the download folder; the same folder can be opened on the “My Pictures” tab.

## Project structure

```
image-hunter/
├── install.sh                 # Linux installer (curl | bash)
├── install.ps1                # Windows installer (irm | iex)
├── main.py                    # entry point
├── requirements.txt
└── app/
    ├── __init__.py
    ├── core/
    │   ├── extractor.py       # JS link collection from the results page
    │   ├── downloader.py      # multi-threaded downloader
    │   ├── updates.py         # update check, in-app installer launch
    │   ├── image_saver.py     # conversion to WebP/PNG/JPEG/BMP/TIFF without overwriting
    │   └── i18n.py            # mini-i18n: ru/en/zh strings, live retranslation
    └── ui/
        ├── main_window.py     # main window, tabs
        ├── local_viewer.py    # local image viewer
        ├── web_search.py      # built-in search-engine browser
        └── downloads.py       # downloads table
```

## How link collection works

A JS script (`app/core/extractor.py`) runs on the results page and collects `img[src]`, `srcset`, lazy-load data attributes; unwraps originals from the `external-content.duckduckgo.com/iu/?u=…` proxy; parses the JSON in Yandex `data-bem` attributes; scans the raw HTML (unwrapping `\u002F` and `\/`) for direct file links. Up to 500 links per pass. The page is not “hacked” — only what the browser has already downloaded and shown is used.

## Notes

- Yandex Images is captcha-protected under active scrolling — enter it right in the built-in browser.
- Respect copyright: download images for personal use only or with the owners’ permission.
- Possible improvements (roadmap): auto-collecting links while scrolling, image size filter (HEAD requests), a pausable queue, link list export, .exe build via PyInstaller.

## Troubleshooting

**The app freezes on Linux (Wayland session).** When the wayland plugin fails
to load (the terminal shows `Could not load the Qt platform plugin "wayland"`),
the app keeps running through XWayland, and the combination of the built-in
browser with the graphics driver is known to hard-freeze. Since v0.6.4 Image
Hunter detects this at startup and disables GPU for the built-in browser —
pages render in software (search and download speed are unaffected) and a note
is added to the Log. Manual control:

- `IH_GPU=0 image-hunter` — disable GPU unconditionally;
- `IH_GPU=1 image-hunter` — keep GPU enabled, skip auto-detection;
- `QTWEBENGINE_CHROMIUM_FLAGS="--disable-gpu" image-hunter` — the same via the
  standard Chromium flag (list your own flags space-separated).

If search tabs stay blank (Alpine/musl and other systems where the Chromium
sandbox cannot start), add `--no-sandbox`:

    QTWEBENGINE_CHROMIUM_FLAGS="--no-sandbox --disable-gpu" image-hunter

**A search tab is grey and the terminal mentions a render process** — the app
now restarts a crashed tab renderer on its own (two attempts); the event is
visible in the Log.

**A page loads forever and the tab does not respond** — since v0.7.0 the load
is stopped automatically after 45 seconds and the Log shows the URL. If it
happens on every site, check your network/proxy.

**A Log entry mentions the sandbox** — your Linux kernel forbids user
namespaces; without them the Chromium sandbox cannot start and tabs crash in
a loop (which looks like a freeze). The app has started the browser without
the sandbox on its own. To bring it back: `IH_NO_SANDBOX=0 image-hunter`.

**Terminal errors like `handshake failed … net_error -202`** — not an app
freeze but a certificate trust failure: check the system clock, any
HTTPS-intercepting antivirus/proxy and the presence of system root
certificates (`ca-certificates`). After `net_error -100` (connection closed)
check network availability.

**It is an old version that freezes** — if the terminal shows
`js: Uncaught TypeError … appendChild`, you are running something older than
v0.6.4: please update (`ImageHunter.bat update` on Windows, `image-hunter
update` on Linux).

## License

MIT — see [LICENSE](LICENSE).
