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

**You don't need to install ffmpeg yourself.** Running `setup_env.bat`
(Section 4) automatically downloads a self-contained copy into `bin/ffmpeg/`,
and the app adds it to its `PATH` automatically when it starts. No system-wide
install or PATH edit needed.

If you'd rather use a system-wide ffmpeg instead, install it with
`winget install Gyan.FFmpeg` and make sure `ffmpeg -version` works in a new
terminal — the bundled copy is only used if `bin/ffmpeg/bin/ffmpeg.exe` exists.

### 2.3 yt-dlp (required for the YouTube feature)

yt-dlp downloads audio from YouTube links. Without it, the YouTube box will fail.
File upload still works without yt-dlp, but the YouTube feature does not.

**You don't need to install this separately either** — `yt-dlp` is listed in
`requirements.txt` and gets installed into your virtual environment automatically
during Section 4. The app finds it there on its own.

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

From inside the project folder, run the setup script. This creates a virtual
environment, installs all required packages, and downloads the bundled ffmpeg:

```
setup_env.bat
```

This is the only setup step you need — it replaces creating/activating a venv
and running `pip install` manually. If you prefer to do it by hand instead:

```
python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
python scripts\download_ffmpeg.py
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

`run.bat` runs the app using the virtual environment created in Section 4
(`venv\Scripts\python.exe`), so it works out of the box after `setup_env.bat`.

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
A program the app needs could not be found. This almost always means
**ffmpeg** or **yt-dlp** is missing. Re-run `setup_env.bat` (Section 4) so the
bundled ffmpeg is downloaded into `bin/ffmpeg/` and `yt-dlp` is installed from
`requirements.txt`.

### `ModuleNotFoundError: No module named 'flask'`
You ran the app with the wrong Python — one that doesn't have the project's
packages. Run `setup_env.bat` (Section 4) to create the virtual environment and
install the requirements, and start the app with `run.bat` rather than calling
`python app/main.py` directly.

### `No module named pip`
The Python you're using has no pip. Either use your project's virtual environment
(Section 4), or bootstrap pip for that interpreter:
```
python -m ensurepip --upgrade
```

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
- [ ] Project cloned/downloaded
- [ ] `setup_env.bat` run successfully (creates venv, installs requirements,
      downloads bundled ffmpeg)
- [ ] App starts with `run.bat` and opens at `http://127.0.0.1:5000`
- [ ] (Optional) Spleeter set up in its own Python 3.8 environment
