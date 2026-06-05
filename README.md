# Installation Manual

**Voice and Music Separation Tool for Speech Transcription Support**

This guide explains how to install and run the application from scratch.

> **Tested platform:** Windows 10/11. The tool was developed and tested only on
> Windows. It may work on Linux or macOS with adjusted commands, but those have
> not been tested.

---

## 1. Overview

The application is a local web app (Flask) that separates the vocals and the
instrumental from a song, and can transcribe the separated vocals into text.
It runs entirely on your own computer and opens in your web browser at
`http://127.0.0.1:5000`.

It can take audio in three ways: a file you upload, a YouTube link, or a whole
folder/album at once. Separation is done by one of several engines (Demucs,
Open-Unmix, and optionally Spleeter), and transcription is done by Whisper.

---

## 2. Prerequisites

You must install these **before** the app will run. Three of them are external
programs that the app calls, and the app can only find them if they are on your
system **PATH**. Getting these onto PATH is the single most common cause of the
app "not working", so follow this section carefully.

### 2.1 Python

Install **Python 3.10** (recommended) from <https://www.python.org/downloads/>.

During installation, tick **"Add Python to PATH"** on the first screen.

Verify in a new terminal:

```
python --version
```

> **Note on environments:** This project uses a Python virtual environment so
> its packages don't clash with the rest of your system. The optional Spleeter
> engine needs its **own separate Python 3.8 environment** — see Section 6. If
> you only want Demucs and Open-Unmix (recommended), you can ignore Spleeter
> entirely.

### 2.2 ffmpeg (required)

ffmpeg is used by every separation engine and by the YouTube downloader. The app
**will not work without it.**

1. Install it. The easiest way on Windows is winget:
   ```
   winget install Gyan.FFmpeg
   ```
2. Find where it was installed:
   ```
   where ffmpeg
   ```
   This prints a full path ending in `...\bin\ffmpeg.exe`.
3. Confirm it works in a **new** terminal:
   ```
   ffmpeg -version
   ```
   If you see version information, ffmpeg is on your PATH and ready.

If `ffmpeg -version` says *"not recognized"*, the folder containing
`ffmpeg.exe` is not on your PATH — add it using the steps in Section 2.4.

### 2.3 yt-dlp (required for the YouTube feature)

yt-dlp downloads audio from YouTube links. Without it, the YouTube box will fail
with `[WinError 2] The system cannot find the file specified`. File upload still
works without yt-dlp, but the YouTube feature does not.

The simplest, most reliable method is the standalone executable (no Python
needed):

1. Download `yt-dlp.exe` from the official releases page:
   <https://github.com/yt-dlp/yt-dlp/releases/latest> (the file named
   **`yt-dlp.exe`**).
2. Create a folder for your tools, for example `C:\tools`.
3. Move `yt-dlp.exe` into `C:\tools`.
4. Add `C:\tools` to your PATH (see Section 2.4).
5. Confirm in a **new** terminal:
   ```
   yt-dlp --version
   ```
   It should print a version like `2026.03.17`.

### 2.4 How to add a folder to PATH (Windows)

You will need this for any tool that says *"not recognized"*.

1. Press **Start**, type **environment variables**, and open
   **"Edit the system environment variables."**
2. Click **Environment Variables…**
3. In the **top** box ("User variables"), select **Path**, then click **Edit…**
4. Click **New**, type the folder path (for example `C:\tools`), and press Enter.
5. Click **OK** on all three windows to save.
6. **Open a brand-new terminal.** (Existing terminals — and editors like VS Code —
   keep the old PATH until fully restarted.)

---

## 3. Get the code

Either clone the repository:

```
git clone <YOUR_REPOSITORY_URL>
cd <PROJECT_FOLDER>
```

or download the ZIP from the repository page and extract it, then open a terminal
in the extracted folder.

---

## 4. Install the Python packages

From inside the project folder, create and activate a virtual environment, then
install the requirements.

Create the environment:

```
python -m venv venv
```

Activate it (Windows):

- **PowerShell:**
  ```
  .\venv\Scripts\Activate.ps1
  ```
  If PowerShell blocks the script, first run:
  ```
  Set-ExecutionPolicy -Scope Process -ExecutionPolicy RemoteSigned
  ```
- **Command Prompt (cmd):**
  ```
  venv\Scripts\activate.bat
  ```

You should now see `(venv)` at the start of your prompt. Install the packages:

```
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

> The first run may download model files (for Demucs and Whisper). This is
> normal and only happens once.

---

## 5. Start the application

With everything installed, start the app:

```
run.bat
```

Then open your browser at:

```
http://127.0.0.1:5000
```

> **About `run.bat`:** the included file points at a specific Python on the
> developer's machine. If it does not start on your computer, edit `run.bat` so
> it points at the Python in your own environment. A portable version looks like
> this:
> ```bat
> @echo off
> set PYTHONPATH=.
> venv\Scripts\python.exe app/main.py
> ```
> (Replace `venv\Scripts\python.exe` with your Spleeter environment's Python if
> you set Spleeter up as in Section 6.)

To stop the app, press **Ctrl+C** in the terminal where it is running.

---

## 6. Optional: enable Spleeter

**Spleeter is optional.** The app runs fine with Demucs and Open-Unmix without
it. Only set this up if you specifically want the Spleeter engine for comparison.

Spleeter requires **Python 3.8** and TensorFlow, which conflict with the newer
packages used by the rest of the app. For that reason it must live in its **own
separate environment**.

1. Install Python 3.8 (separately from your main Python).
2. Create a dedicated environment for Spleeter, for example:
   ```
   C:\Users\<you>\spleeter-env
   ```
   using Python 3.8.
3. Install Spleeter into that environment:
   ```
   <path-to-spleeter-env>\Scripts\python.exe -m pip install spleeter
   ```
4. The app detects Spleeter when it is available. If Spleeter is not installed,
   choosing it simply reports that the engine is unavailable — it does not crash
   the rest of the app.

---

## 7. Troubleshooting

These are the most common problems and their fixes.

### `[WinError 2] The system cannot find the file specified`
A program the app needs is not on your PATH. This almost always means **yt-dlp**
(for YouTube links) or **ffmpeg** is missing. Install the missing tool
(Sections 2.2 / 2.3) and add its folder to PATH (Section 2.4). Open a new
terminal afterwards.

### `ModuleNotFoundError: No module named 'flask'`
You ran the app with the wrong Python — one that doesn't have the project's
packages. Make sure your virtual environment is activated (you should see
`(venv)`), that you ran `pip install -r requirements.txt`, and start the app with
`run.bat` rather than calling `python app/main.py` directly.

### `No module named pip`
The Python you're using has no pip. Either use your project's virtual environment
(Section 4), or bootstrap pip for that interpreter:
```
python -m ensurepip --upgrade
```

### `'ffmpeg' is not recognized` / `'yt-dlp' is not recognized`
The tool is installed but not on PATH, **or** you're using a terminal opened
before you changed PATH. Add the folder (Section 2.4) and open a brand-new
terminal. In editors like VS Code, fully restart the editor — new terminal tabs
alone keep the old PATH.

### PowerShell won't run a program in the current folder
PowerShell requires a `.\` prefix for local paths, e.g.:
```
.\venv\Scripts\Activate.ps1
```

### `CUDA out of memory` / `CUDA error: out of memory`
Your GPU ran out of video memory, usually on long tracks or after processing
many songs in a row. Options:
- Process fewer/shorter files at once.
- Reduce the Demucs segment size in `config.py` (lower `DEMUCS_SEGMENT_SIZE`).
- Restart the app between large batches to free GPU memory.
- If your GPU has limited VRAM (e.g. 4–8 GB), prefer lighter settings or run on
  CPU (slower but no VRAM limit).

### The app starts but the browser page doesn't load
Make sure the terminal still shows the app running, and open exactly
`http://127.0.0.1:5000`. If a previous run is still using the port, close that
terminal first.

---

## 8. Quick checklist

- [ ] Python installed and on PATH (`python --version`)
- [ ] ffmpeg installed and on PATH (`ffmpeg -version`)
- [ ] yt-dlp installed and on PATH (`yt-dlp --version`) — for YouTube
- [ ] Project downloaded, virtual environment created and activated
- [ ] `pip install -r requirements.txt` completed
- [ ] App starts with `run.bat` and opens at `http://127.0.0.1:5000`
- [ ] (Optional) Spleeter set up in its own Python 3.8 environment
