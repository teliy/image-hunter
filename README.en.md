# Image Hunter

**English** | [中文](README.zh.md) | [Русский](README.md)
> **Project page:** https://teliy.github.io/image-hunter/ · [Releases](https://github.com/teliy/image-hunter/releases) · [Changelog](CHANGELOG.md) · [Discussions](https://github.com/teliy/image-hunter/discussions)


Local image browser **+ image search in search engines + bulk saving by links** — all in one window, on four tabs (the fourth is “📜 Log”: a chronicle of everything the app does). For Windows and Linux.

Written in Python + PySide6 (Qt6): heavy operations (rendering, network, image decoding) are done by native Qt, so the interface is fast and responsive.

> **⚡ Special focus — fast work over the network and with network drives** (SMB/NAS, mounted shares): a folder is read in one request, thumbnails are built only for the visible part of the list, ready previews are cached on disk. A network folder with thousands of photos opens without lags — neither in the app nor on the network. Details in [“Fast work over the network and with network drives”](#fast-work-over-the-network-and-with-network-drives).

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


## Upscale quality and resolution — the Real-ESRGAN module (v0.8.24)

The wish: “давай добавим модуль улучшения качества изображения (и разрешения картинки) так-же как и другие, чтобы он качался с github и мог быть установлен/обновлен и полностью удален” (add an image quality and resolution enhancement module, just like the others — downloaded from GitHub, installable/updatable and fully removable). The third plug-in module, next to “🪄 Remove Background” and “🧽 Remove Watermarks”. The engine is **Real-ESRGAN** (`xinntao/Real-ESRGAN`, GitHub): instead of stretching the image, the model rebuilds it — object edges get crisper, faces neater, noise and compression artifacts smoothed out. Everything runs locally, no cloud and no keys.

**How to use.** The **“✨ Upscale”** button on the “My Pictures” image tools panel (after “🧽”) or the same right-click item on the ribbon — works on the selected files, like the neighbouring modules. The result is a separate **“name_x4.ext”**/“name_x2.ext” file next to the original (originals are never overwritten); after a batch the familiar “Keep / Revert to originals” dialog appears: while it is open you can inspect the results in the ribbon, “Revert” removes only this batch’s result files.

**Three models** (submenu in the “Modules” menu, the choice is remembered): **x4plus** — universal ×4 (~64 MB), **x4 anime 6B** — for anime and drawn art ×4, four times fewer blocks — noticeably faster (~17 MB), **x2plus** — moderate ×2, safer for photos with fine detail (~64 MB).

**Downloaded from GitHub, installed and removed without a terminal.** A click with the module not installed offers the installation: the only pip dependency is torch (if the watermark module already installed it, nothing is downloaded twice — the module is ready right away). The model weights are downloaded from GitHub on first use — from the immutable releases of the Real-ESRGAN repository (x4plus — v0.1.0, anime 6B — v0.2.2.4, x2plus — v0.2.1), with progress in the status bar; the downloaded file’s size is verified against the release, a broken download is discarded. “Modules menu → Update module” checks the selected model’s weights against the release and re-downloads a changed file (torch is never replaced — it is shared with the watermark module). “Uninstall module” (with a confirmation showing the space freed) cleans everything: the package and the weights cache `~/.cache/ImageHunter/real-esrgan` — but torch stays if the watermark module still needs it.

**Details worth knowing.** Large images are processed in 256×256 tiles with a 10 px overlap (as in the stock Real-ESRGAN pipeline): memory does not depend on the image size, tile progress is visible in the status bar (“tile 17/28”). Transparency is preserved: the model upscales RGB, the mask uses Lanczos ×scale (PNG/WebP keep alpha; RGBA → JPEG is flattened onto white); the EXIF rotation matches the display. GIFs, extensionless files and existing results (“X_x4.jpg”) are skipped; a result above 50 megapixels is an honest refusal.

— 94 checks on a real tiny RRDBNet (real torch): result names, the stock pipeline (×4, alpha, white background under JPEG, 28 tiles, the 50 MP guard), UpscaleTask (batch, refusal without weights), downloading from a local HTTP server (signals, “.part” cleanup, wrong size), Install/Uninstall/Update/Revert, an e2e run through the button with the choice dialog, the “Modules” menu in both states; adjacent suites green (test_watermark 215, test_modules_menu 85). Note (v0.8.25): official Real-ESRGAN checkpoints come wrapped by the trainer (`{"params_ema": …}`) — loading unwraps them (EMA weights, as the stock `inference_realesrgan.py` does); a bare state dict still loads. Note (v0.8.26): key tiles of upscaling are logged (“✨ name: tile 5/20”), results are saved via a “.part” temp file with an atomic replace — no more zero-byte results on network drives.

## The window remembers its size and position (v0.8.23)

The wish: “окно программы не запоминает свои последние размеры и местоположение на экране” (the app window does not remember its last size and screen position). On close the window now stores its geometry (size, position and maximized state), and on the next launch it opens exactly where it was closed: docked to a second monitor — it opens there; closed maximized — it opens maximized. The first run still starts with the default 1280×820, the window manager picks the position. A window left outside the monitors (the screen was unplugged) is moved onto the nearest working screen by Qt itself; a corrupted settings entry is skipped — the window starts with the usual size and the app does not crash. Together with the already-remembered settings (last folder, search query, ribbon cell size, splitter, tab order) the window opens “the way you left it”.

Tests: `scripts/test_window_geometry.py` — 20 checks: first run 1280×820, the `window/geometry` key is written on close (bytes), the restore is applied, the maximized state is restored, an exact size-and-position round-trip, corrupted string and garbage bytes are skipped without a crash; adjacent suites green.

## Erase watermarks inside a selection on the image (v0.8.22)

The wish: “сделай возможность удалять ватермарки из выделения на картинке” (make it possible to remove watermarks from a selection on the image). Florence-2 auto-detection is good, but not all-powerful — when the watermark is known and visible, it is easier to outline it with the mouse. The **“✂ Crop”** mode gained an **“🧽 Erase Selection”** button (between “🪣 Fill” and “✂▶ Next”): outline the mark with the same frame — eight amber handles, moving, thirds grid, zoom works — and LaMa fills exactly that area, rebuilding the background from the surroundings. Detection is unnecessary and is not loaded: Florence-2 never enters memory, a selection run is noticeably faster than a batch. The mask is exactly the frame, no dilation: what you outlined is what gets filled. The result is a separate “name_nowm.ext” next to the original (originals are never overwritten); cleaning leftovers of an already-made result takes the next free “name_nowm-1.ext”, “-2”… The selection lives in image coordinates and matches the shown picture (both apply the EXIF rotation). When done, the result opens itself in the viewer with the frame armed — leftovers are cleaned without re-clicking. If the module is not installed, the click offers the installation and continues the same selection afterwards. A selection covering more than 60% of the frame is an honest refusal: filling everything is not “removing a mark” but destroying the image. The progress is in the status-bar module widget (same as a batch), the outcome is in the “Log”.

Tests: `scripts/test_watermark.py` — 198 checks (+46): sel_result_path (free names, “_nowm” input → “-1”), the task with sel (detection is not loaded, mask exactly the selection, phases without detection, coverage), a viewer scenario with honest mouse delivery (frame → click → result opens with the mode armed → re-cleaning gives “-1”), install-continuation from the selection click; adjacent suites green. Note (v0.8.26): +17 checks — the hub pin from iopaint metadata and pipeline self-repair (restore `huggingface-hub` to the pin and reload without a restart), the hub pin in the single-package update; 219 total. Note (v0.8.27): the repair rebuilds the WHOLE pipeline dependency set (the same requirements as install step 2) — restoring only the hub is not enough once transformers has drifted to 5.x; the repair progress is visible in the log and the status bar. Note (v0.8.28): a tiled watermark (the same mark repeated in a grid across the photo) is now removed in one pass — in crop mode select ONE instance and press the new All-repeats button; auto mode adds the repeats to the mask on its own; 227 checks in total.

## Watermark removal — the Florence-2 + LaMa module (v0.8.11)

The wish: “let's add the best watermark remover from GitHub as a module (that can be installed and uninstalled)”. The best of GitHub is wired into one fully local pipeline of two open-source tools — the approach of D-Ogi/WatermarkRemover-AI: **Florence-2** (microsoft, via transformers) runs `<CAPTION_TO_PHRASE_GROUNDING>` with the phrase “watermark” to find watermark captions, and **LaMa from IOPaint** (Sanster/IOPaint) — the most alive inpainting project on GitHub — paints those areas over, rebuilding the background from the surroundings. Everything runs locally, no clouds, no keys.

**Install and uninstall — no terminal.** The “🧽 Remove Watermarks” button on the “My Pictures” image tools panel (and the same item in the strip’s right-click menu): if the module is not installed yet, the app honestly warns about the size (iopaint + transformers + timm — gigabytes with PyTorch) and installs everything with pip in a hidden window, then immediately continues processing. The “Modules” menu holds one-item install/uninstall (uninstall asks for confirmation, shows how much space will be freed and wipes the model caches — big-lama in torch-hub and Florence-2 in the Hugging Face cache; foreign caches and libraries shared with the app/rembg are left alone) and a detector submenu: Florence-2-base — fast (~0.5 GB), Florence-2-large — better (~1.6 GB). The models (LaMa ~0.2 GB and Florence-2) download on the first removal run.

**The install is fixed on modern Pythons (v0.8.12–v0.8.13).** First (v0.8.12): IOPaint pins exactly Pillow==9.5.0 — that version has no prebuilt wheels for Python 3.12/3.13, so the first install died with “KeyError: '__version__'” while building the old Pillow source. The install runs in two steps: iopaint itself without dependencies, then its dependencies taken from iopaint’s own metadata. Next (v0.8.13): on Python 3.13+ the install was killed by the `numpy~=1.0` pin from gradio 4.21.0 (iopaint’s web UI, not used by the pipeline) — numpy 1.x has no wheels for 3.13+, so pip tried to build numpy from source (“note: This is an issue with the package mentioned above, not pip”); gradio is now excluded from the install. Along with the dependencies, `standard-imghdr` and `setuptools` shims are installed — iopaint and the pinned diffusers import modules that were removed from the standard library of newer Pythons (imghdr, distutils). “Remove module” cleans iopaint’s direct dependencies (gradio, diffusers, peft, fastapi…) but keeps numpy/Pillow and the shims. The pipeline was verified live on Python 3.13: big-lama is downloaded before ModelManager (otherwise “Unsupported model: lama”), LaMa inpaints, Florence-2 finds the marks.

**Detection rewritten (v0.8.14): tiled watermarks no longer turn a photo into mush.** The report “the marks were not removed, some nonsense came out” exposed this: on a watermark tiled across the whole frame the “watermark” grounding returns 3–4 giant boxes (measured: 100%, 39%, 28% and 18% of the frame), the mask covered all 100% — and LaMa “rebuilt” the entire picture (182 seconds of gray mush). Now the mark is found by Florence-2 OCR (`<OCR_WITH_REGION>`): precise rotated quadrangles of every caption, in two passes — the original plus an autocontrast copy (faint instances no longer slip away and no longer lure LaMa into painting ghosts). The median HSV saturation inside a quad separates the gray semi-transparent mark (0–25) from the colored product-label text (~180) — the label is not painted over. A logo watermark without text is still caught by grounding, but giant boxes (>25% of the frame) are discarded, and if the final mask covered more than 60% of the frame, the file is honestly marked as failed instead of being ruined. A live run on the report’s picture: the mark is gone even from the red box and the corners, the label is intact, LaMa took 9 seconds instead of 182.

**The module updates from inside the app (v0.8.15).** If Florence-2, LaMa or IOPaint get a new release upstream, the module no longer stays old: the Modules menu gains an “Update the watermark removal module…” item. Packages iopaint/transformers/timm are checked against PyPI and updated with the same safe pipeline as the install (no Pillow/gradio, with shims; the app’s own numpy/Pillow are untouched); the Florence-2 revision in the Hugging Face cache is checked against the hub API — only changed files are fetched; big-lama is compared with the release by size and re-fetched by the stock iopaint loader with md5 verification. If pypi.org is unreachable — an honest refusal: no blind updates; a failed model check is not fatal and is reported in the summary. The outcome lands in the status bar, the log and a dialog; after package updates the app asks to restart so the new pipeline versions are picked up. No manual restart is needed anymore: the Modules menu has “🔄 Restart Image Hunter” (v0.8.17), and pip success is verified in fact — a stuck package is caught up by a lone pip run, and if it still stays old, the summary says so honestly.

**How it works.** Selected tiles (or the opened picture) are processed in one session in the background: models are loaded into memory once per batch, and on network drives the interface does not freeze. The result is “name_nowm.ext” next to the original, the format is preserved (AVIF → PNG), the original is never modified, existing files are never overwritten; already-results and GIF files are skipped. The paint area is the polygons of the found captions, widened by a 15 px maximum filter; files with no detected watermarks are honestly counted as “clean” (no result file, no error), and a giant mask is an honest failure with no result. Progress goes to the status line, the summary to the status line and the Log.

Tests: new `scripts/test_watermark.py` — 140 checks; a section in `scripts/test_modules_menu.py`.

## Search results rebuilt after deletion (v0.8.10)

When a name search is active, deleting images (Delete or the context menu) now reruns the search — the same principle as moving files to tree folders (v0.8.5): deleted files are no longer listed as found, the “found: N” counter is honest, and results trimmed by the 5000 limit are refilled with the next matching files. The selection lands on the first tile of the new results, and the status shows both the deletion summary and the rebuild progress. Without an active search the behavior is unchanged — the film strip simply shrinks by the deleted tiles.

Tests: `scripts/test_delete_restore.py` — a new section with 7 rebuild checks.

## Image tools panel (v0.8.9)

The editing tools — **“⇲ Resize”** (with “💾 Save”), **“✂ Crop”** (with its mode buttons “💾 Save”, “💾 As…”, “🪣 Fill”, “✂▶ Save & next”), **“💧 Eyedropper”** (with the color swatch and HEX) and all related elements — moved from the top toolbar to a **dedicated panel right below it** (“Image tools:”) with its own caption, a light background and separators between groups. The top toolbar is now about navigation only — folders, the film strip, zoom, the checkerboard, search (since v0.8.18 it is shorter still — “🪄 Remove Background” and “🧽 Remove Watermarks” moved to the image tools panel too, see below); the image tools live on their own always-visible row and no longer mix with navigation. Button behavior is unchanged: mode buttons still appear only in their modes — but now in this panel, next to their group.

Tests: viewer checks in `scripts/test_image_resize.py` — 73, `scripts/test_image_crop.py` — 74, `scripts/test_image_fill.py` — 67 all green after the move, no semantic changes.

## “Remove Background” and “Remove Watermarks” move to the image tools panel (v0.8.18)

Request: “move background removal and watermarks to the panel below — they get in the way of the search display”. The **“🪄 Remove Background”** (rembg, v0.7.12) and **“🧽 Remove Watermarks”** (Florence-2 + LaMa, v0.8.11) buttons moved from the top toolbar to the image tools panel — to the end of the row, after “💧 Eyedropper”, behind a separator. The top toolbar became noticeably shorter: between “Open folder” and the search field only navigation, zoom and the checkerboard remain, and the search field breathes freely — on a narrow window it no longer squeezes into a slit. Both buttons still work on the files selected in the strip (the picture on screen is not required), so unlike “Resize”, “Crop” and “Eyedropper” they stay enabled at all times — even with nothing open. The strip’s right-click menu and the “Modules” menu are unchanged.

Tests: `scripts/test_rembg.py` — 156 (+3) and `scripts/test_watermark.py` — 152 (+3): the button lives on the image tools panel (parent — QFrame#toolsPanel), it is gone from the top bar (exactly one button with this text in the viewer), the order in the panel — after “💧 Eyedropper” and “🪄”; neighboring suites green; smokes — version 0.8.18.

## Color picker and filling the selected area (v0.8.8)

The **“💧 Picker”** button on the “My Pictures” toolbar turns on color-reading mode: hovering shows the color of the pixel under the cursor right in the status line (“💧 #e02020 · 50,25”), a click picks the color — it is copied to the clipboard as “#rrggbb”, and a sample (color square + HEX) appears on the panel. A shortcut without any mode: **right-click the picture to pick its color in any mode** — including right inside crop mode, without leaving it and without losing the selection. The **“🪣 Fill”** button (in “✂ Crop” mode, next to “💾 As…”) fills the selected rectangle with the picked color: the result is visible immediately, writing to a separate “name_fill.ext” file runs in the background next to the original — the original stays untouched, existing files are never overwritten (a free “-1” suffix is picked), and if writing fails the preview honestly reverts to the original. The fill is opaque — exactly the color the sample shows; the result format follows the original’s extension (AVIF → PNG, transparency in JPEG/BMP lands on a white background). GIF and empty view — buttons are disabled; Esc leaves the mode; the result is reported in the status line and the Log.

Tests: new `scripts/test_image_fill.py` — 67 checks.

## Cropping an image with the mouse, like in XnView (v0.8.7)

The **“✂ Crop”** button on the “My Pictures” toolbar turns on crop mode: drag a rectangle right over the picture, adjust it with the eight amber handles (corners and edges) or drag the whole rectangle by its inner area; a rule-of-thirds grid is drawn inside the rectangle, the picture outside is dimmed, a badge at the corner shows the selection size and the status line shows “✂ 409×275 of 1920×1080”. A click without movement clears the selection, an accidental click does not create a rectangle. Like in XnView, three actions: **“💾 Save”** writes the selected area as a separate “name_crop.ext” file next to the original, **“💾 As…”** — via the standard dialog with a name and folder of your choice, **“✂▶ Save & next”** — saves and opens the next picture of the folder with a fresh rectangle on its own: a whole folder can be cropped in one flow, and the series honestly ends at the last picture. The selection is stored in image coordinates — zoom and “◱ Fit” work in this mode and the rectangle stays in place. The original is never modified, existing files are never overwritten (a free “-1” suffix is picked), cutting and writing run in a background thread (the window does not freeze even on a network drive), and the result is shown in the status line and the Log. GIF animations cannot be cropped (the button is disabled), AVIF is saved as PNG, and transparency in JPEG/BMP lands on a white background. Esc leaves the mode; the “⇲ Resize” and “✂ Crop” modes are mutually exclusive.

Tests: new `scripts/test_image_crop.py` — 74 checks.

## Resizing an image with the mouse (v0.8.6)

The **“⇲ Resize”** button on the “My Pictures” toolbar turns on a mode where the image size is set with the mouse right in the preview: the image gets a frame with three amber handles — drag the corner (keeps proportions) or the right/bottom edge (one side). The display matches the future file one to one: what you see is what gets written; a badge near the corner shows the current size, the status line shows “✂ 400×300 of 800×600”. The **“💾 Save”** button writes the result as a separate “name_WxH.ext” file next to the original: the original stays untouched, existing files are never overwritten (on a conflict a free “-1” suffix is picked), scaling and writing run in a background thread (the window does not freeze even on a network drive), and after saving the strip refreshes and opens the new file right away. GIF animations are not resizable (the button is disabled), AVIF is saved as PNG (Qt cannot write AVIF), and transparency in JPEG/BMP lands on a white background. Esc or “◱ Fit” leaves the mode.

Tests: new `scripts/test_image_resize.py` — 73 checks.

## Dragging selected files onto tree folders (v0.8.5)

Select images in the “My Pictures” strip (Ctrl/Shift, like in Explorer) and drop them onto a folder or a drive in the tree on the left — the files are moved there. The folder under the cursor is highlighted with a translucent selection color; a collapsed folder expands by itself when you hold a file over it (like in Explorer). The move never overwrites anything: files already in the target folder are skipped, and on a name conflict the file gets a free name (“cat-1.png”). The move runs as a background task (the window does not freeze even on a network drive); the result and errors are visible in the status line and the Log.

Tests: new `scripts/test_tree_drop.py`.

## Image resolution in the tile caption (v0.8.4)

Under the file name on every tile of the “My Pictures” strip the app now shows the image’s original resolution — the same “1920×1080” format the full-screen viewer uses; the font is one step smaller and gray, so it does not compete with the name. The resolution is read from the file header in a background thread, together with the thumbnail (EXIF rotation respected), and is stored right inside the cached thumbnail — reopening a folder stays instant and does not read files again. The tile text remains the plain file name: renaming and name search work exactly as before.

Tests: new `scripts/test_thumb_caption.py`.

## Web search from your phone: new engines, the app bridge and server logging (v0.8.3)

**Five engines instead of two.** The “Web” mode header now offers: **Openverse** — the official JSON API of the open-image aggregator (Flickr, Wikimedia, NASA and hundreds more sources: no key, no scraping, ready-made previews), **Wikimedia** — the official Commons API, **DuckDuckGo** and **Bing** — server-side scraping where it still works (Bing increasingly serves an empty JS shell — now that is an honest error suggesting another engine, not a silent “nothing found”), and **“From program”** — a bridge from the app’s “Image search” tab: the app searches with a real browser that network blocks, captchas and changed result formats cannot scare, and automatically hands the phone the cleaned-up, lightweight tiles — only the original URL, preview, title and source page. The engine choice is remembered; requests time out after 60 s — the endless “Searching…” is gone.

**Web server and API activity in the app’s Log.** Opening the web UI (with the client address), phone searches (engine, query, result count, errors), renames, deletions, background-removal starts, downloads to a folder or to the device, view-only denials — all of it lands both in the app’s log and in the phone’s log. Thumbnails and listings are not logged, so the log stays clean.

Tests: the web-search section of `scripts/test_server.py` — mocks for Openverse/Wikimedia/Bing (the m= and data-m= formats, the empty shell), the “app → phone” bridge, log events (search/rename/denial), UI elements.

## Modules menu: install, removal and settings (v0.8.2)

The **Modules** item in the menu bar (next to Help) gathers the management of all pluggable modules in one place. The menu is rebuilt every time it opens, so its items and checkmarks always show the current state.

- **Background removal (rembg):** install or remove the module with one item (removal asks for confirmation and shows how much space the downloaded models take), update the installed module (v0.8.15 — a fresh package version from PyPI; pooch pulls updated models by hash on its own), the “rembg model” submenu with a checkmark on the chosen model (u2netp / u2net / isnet-general-use). The section header shows whether the module is installed. These items are gone from the “My pictures” strip context menu — only the “🪄 Remove background” action remains there.
- **Watermark removal (Florence-2 + LaMa, v0.8.11):** install or remove the module with one item (with confirmation, the freed space and the model-cache cleanup), update the installed module (v0.8.15 — packages from PyPI, Florence-2 by the Hugging Face cache revision, big-lama by the release size), the “Florence-2 detection model” submenu with a checkmark on the chosen detector (base — fast / large — better). Only the “🧽 Remove watermarks” action remains in the strip context menu.
- **Web server:** “▶ Start” / “⏹ Stop” right in the menu, the “Start with the app” checkbox and the “🌐 Web server panel…” item (port, token, QR code, “view only”). The section header shows the state: “Server is running — port N” or “stopped”.

## Modules menu: module versions and “Restart Image Hunter” (v0.8.17)

Wishes: “Add a ‘Restart’ item to the menu with the same function. And the ‘modules’ menu should show module version info”, plus the report “the module does not update — after the message appeared I closed and reopened the app, but the module is not updated”.

**Versions — right in the menu.** An installed module shows disabled info lines under its state header: rembg — the package version; watermarks — the whole pipeline (“Versions: iopaint …, transformers …, timm …”) and the models (“Models:” — the Florence-2 revision in the Hugging Face cache as a short commit tail, and the big-lama size in MB; “not downloaded” is stated honestly). This is exactly what “Update the module” checks against PyPI and Hugging Face — now visible without leaving the menu.

**“🔄 Restart Image Hunter”** — at the bottom of the Modules menu. The new instance starts with a one-second delay (settings are saved before the start), the current one closes by itself: the hint after “Update the module” no longer asks to close the app manually. While pip installs or updates a module the item is disabled — a restart would cut the installation short. If a new instance could not be started, an honest warning appears and the app stays open.

**Module updates became honest (the report above).** pip can report success yet silently leave a package old: in one combined command the resolver rolled it back under someone else’s requirement, “only-if-needed” kept an already-satisfying one, and the newest release might not support this Python. Now pip success is not taken on faith: every target is verified in fact, a stuck one is caught up with a single `pip install --upgrade` (with no neighbours, the resolver has nobody to backtrack to), and if it still did not move, the summary says honestly “still on X — the update did not take”; the restart hint appears only when versions really changed. The same for rembg.

## Web server: control the app from your phone (v0.8.0)

The **“🌐 Web server panel…”** item in the Modules menu opens the window of a small web server — a pluggable, fully removable module (`app/server/`): a phone on the same network opens the address from the QR code and gets almost the whole app in a mobile-friendly interface. The server can also be started right from the Modules menu.

**Available from the phone:** folder feed with thumbnails (the same disk cache the app uses), name search (deep into subfolders, “ignore dash”), full-screen viewing with swipes, renaming, delete to recycle bin or permanently, rembg background removal with progress, drives and favorite folders, the log.

**Security:** access by token (part of the address, generated automatically; a cookie remembers it after the first visit), a “view only” mode blocks remote changes, and root restriction is available for headless runs. The server lives while the app is open and dies with it; autostart is optional. Nothing is listening until you press “Start”.

**Standalone process** (headless, for a folder without a GUI): `python -m app.server --port 8477 --token MY-TOKEN` — the same API without the GUI.

Tests: `scripts/test_server.py` — real HTTP requests on a random port: token (header/link/cookie), the UI page, the folder feed, thumbnail cache (including reuse of the app’s cache), Range/206, downloads, rename rules, deletion, view-only, root restriction, search with limits and dash handling, rembg routes, settings manager, CLI process.

## Web image search from your phone (v0.8.1)

The **🔎** button switches the web interface to “Web” mode: the query goes to a search engine (**DuckDuckGo** or **Bing** — pick it in the header) and the result tiles open in the same feed as your files. From there: view the original full-screen (via the server — hotlink-protected sites do not serve images to foreign pages), save the original to the device itself, or save it to a folder on the computer — the one opened in Files mode (remembered between visits). Tiles are marked with a “+” (like the checkboxes in the desktop app); the floating “⬇ N” button downloads all marked images as one background job with progress and log entries. Downloading follows the desktop downloader rules: the Referer attempt ladder, Cloudflare `/cdn-cgi/image/` unwrapping, collision-free names (“name-1.ext”), a 100 MB per-file cap. Search works in view-only mode too — it changes nothing on the computer; saving to a folder does not. The engines work without an embedded browser: the server fetches clean-data endpoints (DuckDuckGo JSON results, Bing server-rendered HTML) — see the new `app/server/websearch.py` module.

Tests: the web-search section of `scripts/test_server.py` — a local mock server pretends to be DuckDuckGo/Bing and an image host (no network needed): tile parsing, dedupe, offset, proxy with attachment, background downloads with name rules, view-only, root restriction.

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

## Module messages are no longer duplicated (v0.8.21)

Report “messages in the status are duplicated”: module activity texts (“Preparing the models…”, “Downloading the model: N of M”, “Removing watermarks: 3/12”) were written both to the viewer caption on the left and to the module widget on the right — two identical lines side by side. The live process now lives ONLY in the permanent widget (progress bar, phases, seconds tick), while the viewer caption receives only the finals — “Watermarks removed: 10”, “The model is downloaded”, module install/uninstall/update results: a final appears when the widget has already cleared its activity, so every line in the status bar is visible exactly once.

## Module progress — in the status bar (v0.8.20)

Module activity (especially watermark removal) is visible at the bottom of the window, in a permanent spot of the status bar next to the "My pictures" label: a progress bar and the current phase. The widget is hidden while modules are idle; its activity is never overwritten by viewer events (opening a folder, search), and if updates stop coming for a while it ticks " · N s" — you can see the process is alive and how long it has been running.

The watermark pipeline is transparent phase by phase: "Removing watermarks: 3/12 — photo.webp: inpainting · 14 s" — Florence-2 detection, "watermarks found: N", LaMa inpainting, saving; the bar moves inside each file. rembg works the same: file N of M, model preparation and download with megabytes and percent. Install/uninstall/update of modules (pip, gigabytes of PyTorch) also live on the widget — a seconds counter instead of a frozen line.

The first run of the watermark module downloads models with progress: big-lama (~200 MB) via our own streaming downloader with md5 verification (falling back to the stock path), Florence-2 (~0.5 GB) via a watchdog watching the Hugging Face downloader: the hub cache is untouched, the size of the "*.incomplete" files in blobs/ is the honest progress.

## Linux: network hang, davfs2 and file permissions (v0.8.19)

The reports "hangs in Linux when touching the network" (with a py-spy dump) and "something with permissions, e.g. I can't delete files" (with a log from a cloud.mail.ru davfs2 mount) exposed a whole layer of Linux problems — all fixed:

**1. Concurrent decoding of broken data deadlocked the process (Qt mutex ↔ GIL).** The threads were not stuck on the network (reading network files releases the GIL) but inside `QImageReader`: several worker threads decoded images at the same time, and on broken/truncated data (plenty of that when a WebDAV drive is hanging) one thread held an internal QtGui mutex and waited for the GIL through a shiboken callback, while threads waiting for that same mutex were waiting for the GIL — the whole process froze. Qt decoding is now serialized with a single mutex (`imgload._QT_DECODE_LOCK`): the section is short (milliseconds), network reads never enter it, Pillow (AVIF) decodes in parallel without the lock, and thumbnail-cache reads go through the same lock. A repro with 6 parallel decodes of broken PNGs used to hang deterministically — now there are zero hangs and decode errors are returned honestly.

**2. Linux network mounts are recognized via `/proc/self/mounts`.** `_is_remote_path` used to know Windows only (DRIVE_REMOTE), so files on davfs2/sshfs/rclone drives went to the regular pool: a hanging WebDAV occupied all 4 threads and the strip stopped completely. Now the file system type of the mount point is recognized (in `app/core/netfs.py`: davfs2, rclone, sshfs, CIFS/SMB, NFS, 9p/drvfs — WSL, GVFS paths `/run/user/<uid>/gvfs/`, and for unknown fuse.* a heuristic on the daemon name plus an explicit list of definitely-local ones like unionfs/encfs), and network files go through the narrow v0.7.2 pool. `/proc/self/mounts` is generated by the kernel and reads instantly even when the mounts themselves are stuck.

**3. davfs2 and other WebDAV mounts are served like Windows mapped drives.** Every operation (thumbnails, viewing, folder scans, the tree, delete, move, rename) goes through a narrow two-thread pool — exactly how the Windows version has treated mapped drives since v0.7.2. davfs2 cannot handle parallel requests: its slots run out, operations stall for ~30 s and fail with "[Errno 11] Resource temporarily unavailable" (EAGAIN) — the narrow pool plus automatic EAGAIN retries remove that.

**4. Deletion no longer damages permissions; the trash behavior is honest.**

- There is no trash on a network mount (the freedesktop trash lives in a hidden folder on the same disk, which WebDAV cannot provide), so the app immediately offers permanent deletion — instead of a guaranteed-failed trash attempt and a second dialog. Local folders keep the usual trash behavior.
- File permissions are no longer damaged: after a failed deletion the file keeps its original permissions (older Linux builds set "write-only", leaving the file unreadable after a failure).
- Permission failures are explained: if the mount is owned by another user (for example, mounted via sudo without uid/gid), the log shows a hint to check `uid`/`gid`/`file_mode` in `/etc/davfs2/davfs2.conf` or fstab — by default davfs2 shows files with the permissions of whoever mounted it.

**5. Honest write errors.** Saving images from the internet to a network drive writes files via Python I/O with retries: instead of a bare "ValueError" the log shows the real system error with errno and path.
## Checkboxes on Google and Mail.ru work again (v0.7.3)

Neither case is "broken outright" — both search engines changed their markup, so the checkbox injection stopped reaching the tiles:

**1. Mail.ru unified its search portal.** The address `go.mail.ru/search_images` now redirects to `mail.ru/search?...&type=images`, and the image results themselves open in a nested `yandex.ru/images` frame inside. The old gate "inject only if the main page IS a results page" cut Mail.ru off for good: the wrapper address is not a results page. Now SERP frames are looked up regardless of the wrapper address: injection and the checked-counter work on any page that has a results frame inside, and the Mail.ru engine entry opens the final address `mail.ru/search?text=…&type=images` directly (no extra redirect).

**2. Google changed its tile markup again.** Google's hashed class names change from release to release, and any single-class selector stops matching sooner or later. Instead of playing the class-name lottery, the checkbox now "climbs" by quality: if the container does not look like a tile and the best candidate is just a thumbnail, the scan walks up the parents and takes the minimal wrapper that knows the true original (the `/imgres?imgurl=…` anchor) — but never a wrapper that swallows neighboring tiles. One checkbox per tile, and the "best" is still the original.

**3. Diagnostics in the Journal.** After the injection the log gets a line "Image SERP: tiles with checkboxes: N (frames: M)"; if no tiles were recognized — "Image SERP found, but no checkbox tiles were recognized… please send this log to the developer": the next "checkboxes gone" report immediately tells whether the injection arrived and how many tiles were recognized.

Additionally, `udm=2` counts as a results page on any national Google domain (google.de, google.co.uk, …) — Google moves between them on its own; the checkbox scan is isolated per tile (one broken tile no longer wrecks the whole scan).

## The name filter survives downloads (v0.7.5)

Scenario: a name search is active in My Pictures, a batch of images is saved into the same folder from the Image Search tab — and back in the tab the strip was shown unfiltered while the query was still in the field; Enter had to be pressed again. The cause: saving calls `refresh()` on the current folder, and it re-read the folder with a plain scan, ignoring the active query. Now `refresh()` behaves like a tree click: with an active search it re-runs the search from the same folder — the new files join the same result set, nothing to retype. Without a query the behavior is unchanged — the folder is re-read as before.

## Double-click on the name — the rename zone follows the drawn tile (v0.8.16)

A request: “file renaming has to work from a double click on the file name”. Double-click on the name arrived in v0.7.17, but the boundary of the click zone was a constant (icon size + 2 px), while where the style actually draws the caption is up to the style: Windows styles use their own spacing, Fusion uses another. A click on the visible name could land outside the zone — and instead of the rename editor the file opened. Now the zone is computed by the style itself, with the very same calls the delegate uses to draw the tile: the zone runs from the bottom edge of the thumbnail to the bottom of the tile, so the editor opens for clicks on the name itself, on the resolution line, and on the gap under the picture; a click on the picture itself still opens it in the system viewer. If the tile has no thumbnail yet and the style returns no rectangle, the previous formula applies. Measured: the style's caption rectangle matches the drawn one pixel for pixel.

Tests: `scripts/test_rename.py` — 62 checks (+5): the zone starts at the thumbnail's bottom edge, it covers the drawn caption, a click at the center of the painted name, a click in the gap under the thumbnail, the fallback formula without the helper delegate; version smoke.

## Renaming files — F2, double-click on the name, and a menu item (v0.7.17)

A request: “add the ability to rename files, both via the mouse menu and by double-clicking on the file name”.

Image names can now be edited right in the My Pictures strip without leaving the program: a “✏️ Rename” item in the right-click menu on a tile, the **F2** key, or a double-click on the **file name** below the thumbnail. The editor opens with the base name (without extension) selected, like in Explorer — Enter or clicking away applies the change, Esc cancels. Double-clicking the picture itself still opens it in the system viewer. Among selected tiles, the file under the cursor is renamed, as in Explorer. The rename itself runs in a worker thread (the window does not freeze on network drives), and the strip and the status of the opened image update immediately. The new name is checked in advance: empty names, names ending with a dot or space, or containing characters forbidden in Windows (`\ / : * ? " < > |`) are rejected, and a clash with an existing file restores the old name with an explanation in the status line. Every outcome is recorded in the “Journal” (renamed / error with cause).

Tests: `scripts/test_rename.py` — tile label geometry, double-click routing (name → editor, picture → open), the full rename cycle (file on disk, `_paths`, tile, status), the F2 shortcut, the menu item, rejection of empty and forbidden names, clash with an existing file, case-only rename, opened-image status update, version smoke.

## Checkerboard background for transparent images, slider-sized (v0.7.16)

A request from work: “let the background for transparent formats be a grid of gray and white squares, adjustable in size by a slider”.

Behind transparent images (PNG, GIF, WebP, “*_nobg.png” results…) the viewer now draws the classic checkerboard — white and gray squares, like the transparent canvas in graphics editors. You can instantly see where the image is transparent and where it is painted white; before, both blended into the dark backdrop. The square size is adjusted with a slider on the toolbar (a small checker icon hints at what it controls), and the choice is remembered between runs. The checkerboard appears only for images with an alpha channel: JPEG and other opaque formats keep the plain dark backdrop. The squares scroll together with the image (painted from the image widget origin, like a canvas) and stay crisp on HiDPI screens; no squares under text messages (“Open a folder…”, read errors). The preview in the choice dialog after background removal (v0.7.15) now uses the same colors and cell size as the viewer.

Tests: `scripts/test_checker.py` — tile colors and geometry (white/gray diagonal, HiDPI), painting over QLabel (a transparent pixel shows a square), on for a PNG with alpha and off for a JPEG, the slider (limits, settings persistence, tile rebuild), text without squares, the choice preview following the configured cell.

## Background removal results can be reverted; the module narrates itself in the status bar (v0.7.15)

Two requests: “make it so there is a choice — keep the file after the background change or revert to the original”, and “let the status bar show what the background removal module is doing — whether the model is downloading, the download status”.

**Choice after background removal.** When a batch is done, the app no longer just leaves the “*_nobg.png” files next to the originals — a window opens at the bottom asking “Keep the result or revert to the originals?”. It shows a preview of the first result on a checkerboard (transparency is visible immediately) and the file name; with several results — “…and N more”. The window is intentionally non-modal: while it is open the thumbnail strip keeps working, so every “*_nobg.png” result can be opened full-size and inspected. “💾 Keep Result” leaves the files; “↩ Revert to Originals” removes the results of **this batch only** — originals were never touched, so reverting is safe (results were created seconds ago and are removed bypassing the recycle bin, without cluttering it). Closing with X or Esc also means “Keep”: the result is lost only on an explicit click. Starting a new batch without answering closes the old question as “Keep”. Every choice is logged (kept/reverted/per-file errors), and the strip refreshes right after a revert.

**The status bar narrates the module.** Previously the model was downloaded by pooch, whose progress lives in a console the app does not have — users stared at silence while 5–176 MB were downloading (and on pythonw builds tqdm even crashed until v0.7.14 stubbed it out). Now the app intercepts the download: the model is fetched by the app itself via requests, and the status bar shows the whole story — “Preparing the u2netp model…” → “Downloading the u2netp model: 1.2 MB of 4.7 MB (26 %)” → “The u2netp model is downloaded (4.7 MB)” → “The u2netp model is ready” → “Removing background: 2/5 — cat.jpg…”. The downloaded file is still verified by pooch (hash); on a network break the unfinished “.part” is cleaned up and pooch retries the download — quieter progress, but the model arrives. The download summary (size, time) goes to the log; percent ticks stay in the status bar only, without cluttering the log.

Tests: `scripts/test_rembg.py` — 134 checks, including an end-to-end run with real rembg (empty model cache → download signals → result file → choice), a unit test of the streaming download with a network break, the pooch wrapper and the revert flow.

## Background removal works without a console; startup no longer freezes on a network drive (v0.7.14)

Two field reports fixed: “🪄 Failed to remove the background — 'NoneType' object has no attribute 'write'” (background removal did not work at all) and “⚠ UI not responding ≈1742 ms” at startup.

**Background removal on Windows without a console.** The app runs via pythonw — no console, so Python's `sys.stdout`/`sys.stderr` are `None`. The rembg model download goes through pooch with a tqdm progress bar, and tqdm writes to `sys.stderr` and crashed with “'NoneType' object has no attribute 'write'”: the model was never saved, and every attempt repeated the error (the first spent a minute on a slow GitHub connection, the second failed instantly). Dummy streams writing to nowhere are installed before processing (`_ensure_stdio`); a real console is untouched, the call is idempotent.

**Drive tree is read in the background.** The drive list was built with `QStorageInfo` right in the GUI thread: the first request to a not-yet-connected network drive establishes an SMB session — the window froze for a couple of seconds (that “≈1742 ms” report). Volumes are now enumerated by a worker thread (_DrivesTask): the tree appears immediately, the drive section is filled in when the list arrives; on rebuilds (language change, ⟳) drives are restored from the cache instantly. If the set of drives is unchanged the section is left alone (expanded branches stay expanded); only the size tooltip is refreshed. The current-folder highlight after a rebuild is now the asynchronous walk (v0.7.6 principle), and the synchronous highlight can re-read a node whose background load hasn't landed yet (a token cancels the late result).

Tests: `scripts/test_rembg.py` — 63 checks, including the exact scenario (empty model cache, stdio = None → the model downloads, the result file is created); test_tree — instant cache restore of drives, background enumeration, virtual volumes hidden; test_folder_search — waits rebuilt for the async tree.

## The current task is visible at the bottom, in the status bar (v0.7.13)

The log collects the whole chronicle of the app's work, but the tab has to be opened first. Now every log line (events, warnings, errors) is mirrored into the left part of the status bar at the bottom of the window: whatever the app is doing — searching, downloading, removing backgrounds, installing or uninstalling the rembg module, syncing the drive tree — the current task is visible without switching tabs.

Events from worker threads (search, downloads, thumbnails) reach the status bar through the Qt signal queue — the line changes in real time while the UI stays responsive. The display rules are simple: DEBUG lines are not shown (technical noise), multi-line records such as error tracebacks are shown by their first line, and overly long lines are trimmed to 220 characters. The message stays until the next event replaces it: the app “narrates” what it is busy with and does not fade away five seconds into a long module installation.

The other status-bar elements (the My Pictures status on the right, the language picker and the update button) are untouched. Tests: `scripts/test_status_log.py` — 12 checks, including an event from a worker thread and the startup “Ready” message not being overwritten.

## Background removal right in the app: rembg as a module (v0.7.12)

Marketplace and search images often need their background removed. Image Hunter now integrates **rembg** (github.com/danielgatis/rembg) — the most alive open-source background removal project: MIT code, everything runs locally via ONNX Runtime, no cloud, no keys.

**Install without a terminal.** The “🪄 Remove Background” button on the My Pictures image tools panel and the same item in the strip’s right-click menu: if the module is not installed yet, the app offers to install `rembg[cpu]` via pip (hidden window, same trick as the v0.7.6 updater) and then **immediately continues removing the background** for the image you clicked. An “Install the background removal module…” item also lives in the right-click menu itself.

**Uninstalling the module — also from the app.** In the same menu: “Uninstall the rembg module and models…” — pip removes the package and ONNX Runtime, then the downloaded-model cache is wiped (`~/.rembg`, or `~/.u2net` for older versions); before removal the app shows how much space will be freed. Nothing is left on disk.

**How it works.** The result is saved next to the original as `name_nobg.png` and appears in the strip right away; re-processing a result is blocked (“this is already a no-background image”). Works on the selection too — several tiles at once. Processing runs in a worker thread (one rembg session for the whole batch — the model is loaded into memory once); on network drives the files are read by the narrow pool, so the UI never freezes. Progress goes to the status bar, per-file results and errors to the log. Model choice is in the “Model” submenu: `u2netp` (~5 MB, fast, the default), `u2net` (~176 MB), `isnet-general-use` (~170 MB, cleanest edges); the model downloads automatically on first use and is remembered between sessions.

Tests: `scripts/test_rembg.py` — 60 checks, including a full run with real rembg (pip install → model download → result file → cache cleanup).

## Stability and speed: results of a full code audit (v0.7.11)

The whole codebase was re-reviewed for freezes, races and slow spots. Eight narrow places were found and fixed:

**1. GIFs are no longer read on the UI thread.** Full-size pictures have been decoded in the background since v0.7.2, but GIFs slipped through: `QMovie` opens the file right in the GUI thread, and on a stalled network drive even reading the header froze the window for the network timeout. The GIF file is now read in a worker thread (the same GIL-releasing Python I/O) and the animation is built from memory over a `QBuffer` — the last file read in the GUI thread is gone.

**2. Parallel downloads no longer overwrite each other.** The file name comes from the link, and six parallel downloads often share one (`image.jpg`): the classic “does it exist → create” check cannot see races, so one file silently replaced another. The file is now created atomically by the OS (`O_CREAT|O_EXCL`): the losing thread honestly takes the next free number (`image-1.jpg`, `image-2.jpg`…), nothing is lost.

**3. Connection reuse.** Every request opened a new TCP/TLS connection: a batch of a hundred images from one CDN paid a handshake for each. Each worker thread now has its own `requests` session — connections are reused, batches download noticeably faster, and sockets no longer pile up in `TIME_WAIT`. Failed responses are closed immediately instead of waiting for the garbage collector.

**4. “Open folder…” highlight — without freezes.** Picking a folder via the dialog highlighted it in the tree synchronously: on a network drive every level of the path paid a scan in the GUI thread. The highlight now uses the asynchronous walk (the same one used at startup since v0.7.6) — including when a batch is saved into a new folder.

**5. Resizing the window with a large photo no longer stutters.** Dragging the window edge rescaled the picture on every pixel, and smooth scaling of a large photo costs tens of milliseconds — the delays added up into visible sluggishness. The rescale now happens once, when the window stops changing.

**6. “Update” without duplicates.** Double-clicking the update button ran two network checks and showed two dialogs in a row. While a check is in progress, repeated clicks do nothing.

**7. The recycle bin is queried once per drive.** Before deleting, the app checks whether the drive has a recycle bin; with a hundred files selected the query went to the shell once per file. The result is now cached per drive root.

**8. The delete report is now honest.** Permanent deletion on a drive without a recycle bin was counted in the status and the log as “moved to trash”: the count followed the deletion phase number, not the actual mode. “Permanently deleted: N” and the `delete_perm` log event are now reported correctly.

**9. The network caches already in place** (v0.7.2–v0.7.10): drive remoteness, recycle-bin presence, lazy thumbnails, background scans and batched search — the audit confirmed these mechanisms work as designed.

## The folder filter searches inside the highlighted folder or drive (v0.7.10)

**1. The scope is the focus.** Typing in the “🔍 Filter folders…” box used to crawl every branch of the tree at once — Home, favorites and all drives, including network ones: on WebDAV/SMB the search dragged on for long seconds, and the results flashed “foreign” folders from other drives. Now the search goes deep into whatever is highlighted in the tree: select drive Z: — the filter searches that whole drive; select the “Автозапчасти” folder — only its subfolders. Foreign branches are hidden entirely and never traversed — that is the whole saving on a network drive. With nothing selected, all drives are searched, as before. The counter above the tree shows where the search ran: “Folders found: 2 — in “Z:/Автозапчасти””.

**2. Changing the focus re-scopes the filter.** Clicking another folder or drive with an active filter immediately re-applies it to the new scope (before, with the same text the filter simply did not re-run). Enter opens only matches inside the scope — it will not drag you into a foreign drive.

## Favorite folders — always at the top of the tree (v0.7.9)

**1. Two ways to add a folder to favorites.** The “☆” button in the tree header adds (and “★” removes) the folder currently open in the tab; right-clicking any folder in the “Drives and folders” tree offers “⭐ Add to favorites” / “Remove from favorites” — handy for nested folders the currently open path does not reach. Adding and removing is written to the Log.

**2. Favorites sit at the top of the tree.** Favorite folders with a gold star come first in the tree — before “Home” and the drive list — on every launch; the list is stored in the settings. Otherwise they behave like ordinary folders: lazy expansion, a click opens them, the folder filter finds them too. Removing from favorites never touches the folders themselves.

## The log now names the engine behind each event (v0.7.8)

**1. Log lines carry the engine name.** “Find everywhere” opens a tab per engine, and the log used to make it impossible to tell who was who: eight identical “Image SERP found, but no checkbox tiles were recognized…” lines in a row meant eight different engines, with no way to know which one changed its markup. Now every tab event is tagged with the engine’s short name in square brackets: “[Startpage] Page did not load within 45 s…”, “[Google] Image SERP: tiles with checkboxes: 2…”, “[Mail.ru] SAVE ERROR…”, “[Yandex] Saving finished: 3 saved…”, “[Google] Links collected…” — and the render-process crash is tagged too. For a bug report, just send the log: it is immediately clear which engine failed and how.

## Search status moved down to the status bar (v0.7.7)

**1. Search info lives in the status bar.** The name-search result (“Search “96985730”: 0 files”) used to be drawn in the same top bar as the search field: long texts bloated the bar, and your eyes had to wander around the window for the result. Now this status is shown at the bottom of the window, in the status bar — the same place where service messages appear and the language is switched: the text sits right to the left of the language selector and the update button. The other “My Pictures” statuses moved there too — “reading folder…”, “copied N”, “deleted N”, details of the picture on screen; the top bar now keeps only the buttons, the search field and “ignore dash”.

## Windowless updates and a tree that shows where you are (v0.7.6)

**1. In-app update — zero terminal windows.** The installer used to run in a visible console window (before v0.7.4 — two or three of them), and the windows stayed on screen after the update. Now cmd is launched with the CREATE_NO_WINDOW flag: no terminals during the update or after it. The installer output goes to the `%TEMP%\ImageHunter_update.log` journal; on failure a normal dialog shows the error and the log path instead of a console. Also, install paths are no longer written into the batch file — they are passed via environment variables, so the update no longer breaks when the install folder or the user name contains non-ASCII characters. The app tells you what to expect: after confirming the update a dialog explains that the update runs in the background and the app will close and relaunch itself in 1–2 minutes.

**2. The folder tree expands to the current folder.** If the last folder and the name filter were restored at startup, it used to be unclear where the shown pictures lived — the tree stayed collapsed. The cause: the tree highlight was tied to the result of the background folder scan, and the restored search outran the scan and dropped it together with the highlight. Now the tree expands to the current folder right away, level by level, in the background (on a network drive — without freezing the UI); if the folder is unreachable, the nearest existing node gets highlighted; manual selection and dialog-open override the walk, not the other way around.

## Features

**📁 My Pictures** — local viewer:
- **drive and folder tree on the left**: mounted drives and devices (free space in the tooltip), favorite
  folders ⭐ — always at the top, quick links “Home” and “Pictures”; folders expand lazily, a click on a folder
  shows its images right away; the panel width is adjusted with the mouse; the “⟳” button refreshes the drive
  list (after plugging in a USB stick);
- **folder filter**: the “🔍 Filter folders…” box above the tree — as you type, the tree keeps only folders whose
  names contain those letters: the rest are hidden, branches to the matches expand, and a counter above the tree
  shows how many folders matched and where the search ran; it searches deep inside the highlighted folder or drive
  (whatever is selected in the tree is what gets searched; with nothing selected — all drives);
  it is instant and does not rescan the disk — the tree just loads more levels within a budget
  (300 folders or 1.5 s at a time), so even a huge or network disk cannot freeze the window;
  case-insensitive, a click opens the folder, Enter opens the first match, Esc resets; hidden folders are not shown;
- **lazy thumbnails** (see the network section above) and the “🖼 Thumbnails” on/off toggle;
  the tile caption shows the file name plus the image resolution (“1920×1080”);
- **multi-select and drag'n'drop**: select images in the strip (Ctrl/Shift, like in Explorer) and drag them into Explorer, e-mail or any other application — or drop them onto a folder or a drive in the tree on the left to move them there (v0.8.5); the original files are passed on (`text/uri-list`); the drag start is backed by three independent paths (event filter, own mouse-move tracking, built-in Qt mechanics) and every step is written to the Log; **if dragging does not work — a no-drag fallback:** `Ctrl+C` (or right-click → “Copy selected files”), then paste them wherever needed — `Ctrl+V` into Explorer or a browser;
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
