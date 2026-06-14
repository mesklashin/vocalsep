import os
import uuid
import json
import shutil
import threading
import datetime
import logging
import zipfile
import concurrent.futures
from flask import Flask, request, jsonify, render_template, send_file
from flask_cors import CORS
from pathlib import Path
import sys
import subprocess

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.append(str(PROJECT_ROOT))

import config
from separation.separator import get_separator
from asr.transcriber import WhisperTranscriber

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

transcriber = None

app = Flask(__name__)
CORS(app)
app.config['SECRET_KEY'] = config.SECRET_KEY
app.config['UPLOAD_FOLDER'] = config.UPLOAD_FOLDER
app.config['MAX_CONTENT_LENGTH'] = 500 * 1024 * 1024  # 500MB for batch uploads

tasks = {}


def friendly_error(e):
    """
    Turn a raw exception into a short, user-facing message.

    Long technical messages (CUDA tracebacks, ffmpeg errors, etc.) are
    confusing in a browser alert, so common cases are mapped to plain
    explanations. Anything unrecognized falls back to a trimmed version of
    the original message.
    """
    msg = str(e)

    if "out of memory" in msg.lower() or "CUDA error" in msg:
        return ("Your GPU ran out of memory while processing this audio. "
                "Try a shorter file, a lower bit depth, or restart the app "
                "to free up GPU memory.")
    if "ffmpeg" in msg.lower() and ("not found" in msg.lower() or "No such file" in msg):
        return "ffmpeg could not be found. Please check your installation (see README)."
    if isinstance(e, FileNotFoundError):
        return "A required file could not be found or downloaded."

    # Trim very long technical messages so the alert stays readable
    first_line = msg.strip().splitlines()[0] if msg.strip() else "An unexpected error occurred."
    if len(first_line) > 200:
        first_line = first_line[:200] + "..."
    return first_line


# ---------------------------------------------------------------------------
# Separation history (saved to disk so it survives "New Track" clicks AND
# restarts). Everything here is wrapped in try/except so that a problem with
# the history can never break separation, playback, or the rest of the app.
# ---------------------------------------------------------------------------
HISTORY_FILE = config.RESULTS_DIR / "history.json"
HISTORY_MAX  = 200
_history_lock = threading.Lock()


def load_history():
    """Return the list of saved jobs (most recent first). Never raises."""
    try:
        if HISTORY_FILE.exists():
            with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read history: {e}")
    return []


def save_history(record):
    """Append one completed job to the history file. Never raises."""
    try:
        with _history_lock:
            history = []
            if HISTORY_FILE.exists():
                try:
                    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
                        history = json.load(f)
                except Exception:
                    history = []
            history.append(record)
            history = history[-HISTORY_MAX:]  # keep only the most recent
            with open(HISTORY_FILE, "w", encoding="utf-8") as f:
                json.dump(history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logger.warning(f"Could not save history (separation still succeeded): {e}")


def _delete_rel_file(rel_path, base_dir):
    """Delete a file given a path relative to base_dir, never raising."""
    try:
        full_path = (base_dir / rel_path.replace("/", os.sep)).resolve()
        if base_dir.resolve() in full_path.parents and full_path.exists():
            full_path.unlink()
    except Exception as e:
        logger.warning(f"Could not delete '{rel_path}': {e}")


def delete_history_entry(record_id):
    """
    Remove a history record and delete the audio files it references
    (separated stems, original upload, zip). Returns True if a matching
    record was found and removed.
    """
    with _history_lock:
        history = load_history()
        record = next((r for r in history if r.get('id') == record_id), None)
        if record is None:
            return False
        history = [r for r in history if r.get('id') != record_id]
        with open(HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, ensure_ascii=False, indent=2)

    if record.get('type') == 'single':
        for rel in record.get('results', {}).values():
            _delete_rel_file(rel, config.SEPARATED_DATA_DIR)
        original = record.get('original') or ''
        if original.startswith('/static/'):
            _delete_rel_file(original[len('/static/'):], config.STATIC_DIR)
    else:
        for song in record.get('completed_songs', []):
            for rel in song.get('stems', {}).values():
                _delete_rel_file(rel, config.SEPARATED_DATA_DIR)
        zip_name = record.get('zip')
        if zip_name:
            _delete_rel_file(zip_name, config.UPLOAD_FOLDER)

    return True


# Find yt-dlp. YouTube changes its playlist API often, so newer yt-dlp
# releases matter - but the newest releases dropped Python 3.8 support
# (needed for Spleeter), so an app running under Python 3.8 would otherwise
# be stuck on an old, possibly-broken yt-dlp. Prefer the project's own
# `venv` (which can run a modern Python and stay up to date via
# `pip install -U yt-dlp`), then the copy next to this interpreter, then PATH.
_yt_dlp_name = "yt-dlp.exe" if os.name == "nt" else "yt-dlp"
_yt_dlp_in_repo_venv = config.BASE_DIR / "venv" / ("Scripts" if os.name == "nt" else "bin") / _yt_dlp_name
_yt_dlp_in_venv = Path(sys.executable).parent / _yt_dlp_name
if _yt_dlp_in_repo_venv.exists():
    YTDLP = str(_yt_dlp_in_repo_venv)
elif _yt_dlp_in_venv.exists():
    YTDLP = str(_yt_dlp_in_venv)
else:
    YTDLP = shutil.which("yt-dlp") or "yt-dlp"

# ---------------------------------------------------------------------------
# Model routing - maps model value -> (engine, model_name)
# ---------------------------------------------------------------------------
MODEL_ROUTING = {
    # Demucs models
    "htdemucs":        ("demucs",    "htdemucs"),
    "htdemucs_ft":     ("demucs",    "htdemucs_ft"),
    "htdemucs_6s":     ("demucs",    "htdemucs_6s"),
    "mdx":             ("demucs",    "mdx"),
    "mdx_extra":       ("demucs",    "mdx_extra"),
    "mdx_extra_q":     ("demucs",    "mdx_extra_q"),
    # Open-Unmix models
    "umx":             ("openunmix", "umx"),
    "umxhq":           ("openunmix", "umxhq"),
    "umxl":            ("openunmix", "umxl"),
    # Spleeter configs
    "spleeter:2stems": ("spleeter",  "spleeter:2stems"),
    "spleeter:4stems": ("spleeter",  "spleeter:4stems"),
    "spleeter:5stems": ("spleeter",  "spleeter:5stems"),
}


def resolve_engine_and_model(chosen_model: str, engine_hint: str = None):
    """
    Resolve the engine and model name from the chosen_model string.
    engine_hint is the 'engine' field sent from the frontend (demucs/openunmix/spleeter).
    """
    chosen_model = chosen_model.strip()

    # Direct lookup first - handles all known models including spleeter:Xstems
    if chosen_model in MODEL_ROUTING:
        return MODEL_ROUTING[chosen_model]

    # If frontend sent an explicit engine, trust it
    if engine_hint:
        engine_hint = engine_hint.lower().strip()
        if engine_hint == "spleeter":
            # Default to 2stems if no valid spleeter config given
            model = chosen_model if chosen_model.startswith("spleeter:") else "spleeter:2stems"
            return ("spleeter", model)
        if engine_hint == "openunmix" or "umx" in chosen_model.lower():
            return ("openunmix", chosen_model)
        if engine_hint == "demucs":
            return ("demucs", chosen_model)

    # Fallback heuristics
    if chosen_model.startswith("spleeter:"):
        return ("spleeter", chosen_model)
    if "umx" in chosen_model.lower():
        return ("openunmix", chosen_model)

    # Default to demucs
    return ("demucs", chosen_model)


def analyze_audio(audio_path) -> dict:
    try:
        import librosa
        import soundfile as sf
        import numpy as np

        info = sf.info(str(audio_path))
        y, sr = librosa.load(str(audio_path), mono=True, sr=None)

        tempo, _ = librosa.beat.beat_track(y=y, sr=sr)
        bpm = round(float(tempo), 1)

        chroma = librosa.feature.chroma_cqt(y=y, sr=sr)
        chroma_mean = chroma.mean(axis=1)
        keys = ['C','C#','D','D#','E','F','F#','G','G#','A','A#','B']
        key = keys[int(np.argmax(chroma_mean))]

        duration_sec = info.duration
        mins = int(duration_sec // 60)
        secs = int(duration_sec % 60)
        duration_str = f"{mins}:{secs:02d}"

        return {
            'bpm': bpm,
            'key': key,
            'duration': duration_str,
            'sample_rate': f"{info.samplerate} Hz",
            'channels': info.channels,
            'format': info.format,
            'bit_depth': str(info.subtype),
        }
    except Exception as e:
        logger.warning(f"Audio analysis failed: {e}")
        return {}


def get_audio_duration(audio_path):
    """Return 'm:ss' for an audio file, or None on failure. Cheap - no decoding."""
    try:
        import soundfile as sf
        duration_sec = sf.info(str(audio_path)).duration
        mins = int(duration_sec // 60)
        secs = int(duration_sec % 60)
        return f"{mins}:{secs:02d}"
    except Exception as e:
        logger.warning(f"Could not read duration for '{audio_path}': {e}")
        return None


def run_separation(task_id, input_path, chosen_model, bit_depth=16, stems_filter=None, engine_hint=None, original_name=None):
    global transcriber
    try:
        engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
        logger.info(f"Task {task_id}: engine='{engine}' model='{model_name}' bit={bit_depth} stems={stems_filter}")

        audio_info = analyze_audio(input_path)

        separator = get_separator(engine=engine, model=model_name)
        stems = separator.separate(input_path, bit_depth=bit_depth, stems_filter=stems_filter)

        result_links = {}
        for stem_name, abs_path_str in stems.items():
            rel = Path(abs_path_str).relative_to(config.SEPARATED_DATA_DIR)
            result_links[stem_name] = str(rel).replace(os.sep, "/")

        # URL of the ORIGINAL uploaded/downloaded track, so the UI can play it
        # with the "Play Song" button. The upload folder lives under static/.
        original_url = None
        try:
            rel_orig = Path(input_path).resolve().relative_to(config.STATIC_DIR)
            original_url = "/static/" + str(rel_orig).replace(os.sep, "/")
        except Exception as e:
            logger.warning(f"Could not build original audio URL: {e}")

        lyrics = []
        if 'vocals' in stems and os.path.exists(stems['vocals']):
            logger.info(f"Task {task_id}: Starting ASR...")
            if transcriber is None:
                transcriber = WhisperTranscriber(model_name=config.WHISPER_MODEL_SIZE)
            raw = transcriber.transcribe(stems['vocals'])
            # Keep the timestamps so the frontend can sync lyrics to playback.
            lyrics = [
                {
                    'start': l.get('start', 0),
                    'end':   l.get('end', 0),
                    'text':  l.get('text', ''),
                }
                if isinstance(l, dict)
                else {'start': 0, 'end': 0, 'text': str(l)}
                for l in raw
            ]

        tasks[task_id] = {
            'status':     'completed',
            'results':    result_links,
            'original':   original_url,
            'lyrics':     lyrics,
            'filename':   Path(input_path).name,
            'engine':     engine,
            'model':      separator.model,
            'audio_info': audio_info,
            'bit_depth':  bit_depth,
        }
        logger.info(f"Task {task_id} completed.")

        # Save to history (safe: never breaks the completed result)
        save_history({
            'id':         task_id,
            'type':       'single',
            'time':       datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
            'title':      original_name or Path(input_path).name,
            'engine':     engine,
            'model':      separator.model,
            'bit_depth':  bit_depth,
            'results':    result_links,
            'original':   original_url,
            'lyrics':     lyrics,
            'audio_info': audio_info,
        })

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        tasks[task_id] = {'status': 'failed', 'error': friendly_error(e)}


def _download_song(url, song_id):
    """
    Download one song's audio as mp3 into UPLOAD_FOLDER/<song_id>.mp3.
    Returns the resulting Path, or raises on failure.
    """
    out_template = str(app.config['UPLOAD_FOLDER'] / song_id) + ".%(ext)s"
    filepath = app.config['UPLOAD_FOLDER'] / f"{song_id}.mp3"

    cmd = [YTDLP, '-x', '--audio-format', 'mp3',
           '--no-playlist',           # treat the URL as a single video
           '-o', out_template, url]
    result = subprocess.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        logger.error(f"yt-dlp failed for {url}:\n{result.stderr}")
        err_line = next(
            (line for line in result.stderr.splitlines() if line.startswith("ERROR:")),
            result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "yt-dlp failed."
        )
        raise RuntimeError(err_line)

    if not filepath.exists():
        raise FileNotFoundError("Download failed.")

    return filepath


def run_playlist(playlist_id, urls, chosen_model, bit_depth=16, engine_hint=None):
    global transcriber
    total = len(urls)
    completed_songs = []
    song_ids = [str(uuid.uuid4()) for _ in urls]

    # Download the next song's audio in the background while the current
    # song is being separated/transcribed (GPU-bound), so the slow CPU-bound
    # download doesn't add to the total time.
    executor = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    download_futures = {0: executor.submit(_download_song, urls[0][1], song_ids[0])} if urls else {}

    try:
        for i, (title, url) in enumerate(urls):
            if tasks[playlist_id].get('cancel_requested'):
                logger.info(f"Playlist {playlist_id}: cancelled by user.")
                break

            # Kick off the next song's download while we process this one
            if i + 1 < total and (i + 1) not in download_futures:
                download_futures[i + 1] = executor.submit(_download_song, urls[i + 1][1], song_ids[i + 1])

            tasks[playlist_id]['current'] = i + 1
            tasks[playlist_id]['current_title'] = title
            tasks[playlist_id]['total'] = total

            try:
                logger.info(f"Playlist {playlist_id}: [{i+1}/{total}] {title}")
                filepath = download_futures.pop(i).result()

                engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
                separator = get_separator(engine=engine, model=model_name)
                duration = get_audio_duration(filepath)
                stems = separator.separate(filepath, bit_depth=bit_depth)

                # The downloaded source file isn't needed once separation is
                # done (playlist results only link to the separated stems).
                try:
                    filepath.unlink()
                except OSError as e:
                    logger.warning(f"Could not remove downloaded file '{filepath}': {e}")

                song_stems = {}
                for stem_name, abs_path_str in stems.items():
                    rel = Path(abs_path_str).relative_to(config.SEPARATED_DATA_DIR)
                    song_stems[stem_name] = str(rel).replace(os.sep, "/")

                # Transcribe the vocal stem so each song gets a lyrics sheet,
                # exactly like the file-upload batch path does.
                lyrics_text = ""
                if 'vocals' in stems and os.path.exists(stems['vocals']):
                    try:
                        if transcriber is None:
                            transcriber = WhisperTranscriber(model_name=config.WHISPER_MODEL_SIZE)
                        raw = transcriber.transcribe(stems['vocals'])
                        lyrics_text = "\n".join(
                            (seg.get('text', '').strip() if isinstance(seg, dict) else str(seg))
                            for seg in raw
                        )
                    except Exception as e:
                        logger.warning(f"Playlist lyrics failed for '{title}': {e}")

                completed_songs.append({
                    'title':    title,
                    'stems':    song_stems,
                    'lyrics':   lyrics_text,
                    'duration': duration,
                })
                tasks[playlist_id]['completed_songs'] = completed_songs

            except Exception as e:
                logger.error(f"Playlist failed on '{title}': {e}")
                completed_songs.append({'title': title, 'error': friendly_error(e)})
                tasks[playlist_id]['completed_songs'] = completed_songs
    finally:
        executor.shutdown(wait=False)

    try:
        zip_path = app.config['UPLOAD_FOLDER'] / f"{playlist_id}_stems.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for song in completed_songs:
                if 'stems' not in song:
                    continue
                folder = song['title'][:50].replace('/', '_').replace('\\', '_')
                for stem_name, rel_path in song['stems'].items():
                    abs_path = config.SEPARATED_DATA_DIR / rel_path.replace("/", os.sep)
                    if abs_path.exists():
                        zf.write(abs_path, f"{folder}/{stem_name}.wav")
                # Add a lyrics sheet for this song, if we have one
                if song.get('lyrics'):
                    zf.writestr(f"{folder}/lyrics.txt", song['lyrics'])
        tasks[playlist_id]['zip'] = str(playlist_id) + '_stems.zip'
    except Exception as e:
        logger.error(f"Zip failed: {e}")

    tasks[playlist_id]['status'] = 'completed'
    tasks[playlist_id]['cancelled'] = tasks[playlist_id].get('cancel_requested', False)

    engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
    save_history({
        'id':              playlist_id,
        'type':            'playlist',
        'time':            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        'title':           f"Playlist ({len(completed_songs)} songs)",
        'engine':          engine,
        'model':           model_name,
        'bit_depth':       bit_depth,
        'completed_songs': completed_songs,
        'zip':             tasks[playlist_id].get('zip'),
    })


def run_batch(batch_id, saved_files, chosen_model, bit_depth=16, stems_filter=None, engine_hint=None):
    global transcriber
    total = len(saved_files)
    completed_songs = []

    for i, (original_name, filepath) in enumerate(saved_files):
        if tasks[batch_id].get('cancel_requested'):
            logger.info(f"Batch {batch_id}: cancelled by user.")
            break

        tasks[batch_id]['current'] = i + 1
        tasks[batch_id]['current_title'] = original_name
        tasks[batch_id]['total'] = total

        try:
            logger.info(f"Batch {batch_id}: [{i+1}/{total}] {original_name}")

            engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
            separator = get_separator(engine=engine, model=model_name)
            duration = get_audio_duration(filepath)
            stems = separator.separate(filepath, bit_depth=bit_depth, stems_filter=stems_filter)

            # The uploaded source file isn't needed once separation is done
            # (batch results only link to the separated stems).
            try:
                filepath.unlink()
            except OSError as e:
                logger.warning(f"Could not remove uploaded file '{filepath}': {e}")

            song_stems = {}
            for stem_name, abs_path_str in stems.items():
                rel = Path(abs_path_str).relative_to(config.SEPARATED_DATA_DIR)
                song_stems[stem_name] = str(rel).replace(os.sep, "/")

            # Transcribe the vocal stem so each song gets a lyrics sheet
            lyrics_text = ""
            if 'vocals' in stems and os.path.exists(stems['vocals']):
                try:
                    if transcriber is None:
                        transcriber = WhisperTranscriber(model_name=config.WHISPER_MODEL_SIZE)
                    raw = transcriber.transcribe(stems['vocals'])
                    lyrics_text = "\n".join(
                        (seg.get('text', '').strip() if isinstance(seg, dict) else str(seg))
                        for seg in raw
                    )
                except Exception as e:
                    logger.warning(f"Batch lyrics failed for '{original_name}': {e}")

            completed_songs.append({
                'title':    Path(original_name).stem,
                'stems':    song_stems,
                'lyrics':   lyrics_text,
                'duration': duration,
            })

        except Exception as e:
            logger.error(f"Batch failed on '{original_name}': {e}")
            completed_songs.append({
                'title': Path(original_name).stem,
                'error': friendly_error(e),
            })

        tasks[batch_id]['completed_songs'] = completed_songs

    try:
        zip_path = app.config['UPLOAD_FOLDER'] / f"{batch_id}_stems.zip"
        with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zf:
            for song in completed_songs:
                if 'stems' not in song:
                    continue
                folder = song['title'][:50].replace('/', '_').replace('\\', '_')
                for stem_name, rel_path in song['stems'].items():
                    abs_path = config.SEPARATED_DATA_DIR / rel_path.replace("/", os.sep)
                    if abs_path.exists():
                        zf.write(abs_path, f"{folder}/{stem_name}.wav")
                # Add a lyrics sheet for this song, if we have one
                if song.get('lyrics'):
                    zf.writestr(f"{folder}/lyrics.txt", song['lyrics'])
        tasks[batch_id]['zip'] = f"{batch_id}_stems.zip"
        logger.info(f"Batch {batch_id}: ZIP created.")
    except Exception as e:
        logger.error(f"Batch ZIP failed: {e}")

    tasks[batch_id]['status'] = 'completed'
    tasks[batch_id]['cancelled'] = tasks[batch_id].get('cancel_requested', False)
    logger.info(f"Batch {batch_id}: All done! {len(completed_songs)}/{total} files.")

    engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
    save_history({
        'id':              batch_id,
        'type':            'batch',
        'time':            datetime.datetime.now().strftime("%Y-%m-%d %H:%M"),
        'title':           f"Batch ({len(completed_songs)} files)",
        'engine':          engine,
        'model':           model_name,
        'bit_depth':       bit_depth,
        'completed_songs': completed_songs,
        'zip':             tasks[batch_id].get('zip'),
    })


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/upload', methods=['POST'])
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file found.'}), 400
    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'No file selected.'}), 400

    chosen_model = request.form.get('model', 'htdemucs_ft')
    engine_hint  = request.form.get('engine', None)   # read engine from frontend
    bit_depth    = int(request.form.get('bit_depth', 16))
    stems_filter = request.form.getlist('stems')
    if not stems_filter:
        stems_filter = None

    task_id  = str(uuid.uuid4())
    ext      = Path(file.filename).suffix
    original_name = file.filename
    filepath = app.config['UPLOAD_FOLDER'] / f"{task_id}{ext}"

    try:
        file.save(filepath)
        tasks[task_id] = {'status': 'processing'}
        threading.Thread(
            target=run_separation,
            args=(task_id, filepath, chosen_model, bit_depth, stems_filter, engine_hint, original_name),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id, 'status': 'processing'})
    except Exception as e:
        return jsonify({'error': friendly_error(e)}), 500


@app.route('/youtube', methods=['POST'])
def handle_youtube():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided.'}), 400

    url          = data['url']
    chosen_model = data.get('model', 'htdemucs_ft')
    engine_hint  = data.get('engine', None)
    bit_depth    = int(data.get('bit_depth', 16))
    stems_filter = data.get('stems', None)
    task_id      = str(uuid.uuid4())
    filepath     = app.config['UPLOAD_FOLDER'] / f"{task_id}.mp3"

    try:
        tasks[task_id] = {'status': 'processing'}
        out_template = str(app.config['UPLOAD_FOLDER'] / task_id) + ".%(ext)s"
        cmd = [YTDLP, '-x', '--audio-format', 'mp3',
               '--no-playlist',            # if a playlist URL is pasted here,
                                           # just take the single video
               '-o', out_template, url]
        result = subprocess.run(cmd, capture_output=True, text=True)
        if result.returncode != 0:
            logger.error(f"yt-dlp failed for {url}:\n{result.stderr}")
            err_line = next(
                (line for line in result.stderr.splitlines() if line.startswith("ERROR:")),
                result.stderr.strip().splitlines()[-1] if result.stderr.strip() else "yt-dlp failed."
            )
            raise RuntimeError(err_line)
        if not filepath.exists():
            raise FileNotFoundError("Download failed.")
        threading.Thread(
            target=run_separation,
            args=(task_id, filepath, chosen_model, bit_depth, stems_filter, engine_hint),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id, 'status': 'processing'})
    except Exception as e:
        return jsonify({'error': friendly_error(e)}), 500


def expand_links(raw_text):
    """
    Take whatever the user pasted - any mix of single videos and playlist
    links, one per line (or separated by spaces) - and expand it into one
    flat list of (title, video_url) entries.

    A single video resolves to one entry; a playlist resolves to all of its
    videos. Everything is concatenated into a single master list, so you can
    paste 1 video + 2 playlists + another video and they all get processed
    one after another.
    """
    # Split on newlines AND whitespace, so pasting links on one line still works
    candidates = []
    for line in raw_text.replace('\r', '\n').split('\n'):
        for piece in line.split():
            piece = piece.strip()
            if piece:
                candidates.append(piece)

    songs = []
    errors = []
    seen_urls = set()
    for link in candidates:
        try:
            result = subprocess.run(
                [YTDLP, '--flat-playlist', '--yes-playlist',
                 '--print', '%(title)s\t%(url)s', link],
                capture_output=True, text=True, check=True
            )
            for out_line in result.stdout.strip().split('\n'):
                if '\t' in out_line:
                    title, video_url = out_line.split('\t', 1)
                    title = title.strip()
                    video_url = video_url.strip()
                    if video_url and video_url not in seen_urls:
                        seen_urls.add(video_url)
                        songs.append((title, video_url))
        except subprocess.CalledProcessError as e:
            # One bad link shouldn't sink the whole list - skip it, but
            # remember why so we can tell the user if nothing came through.
            stderr = (e.stderr or '').strip()
            err_line = next(
                (l for l in stderr.splitlines() if l.startswith("ERROR:")),
                stderr.splitlines()[-1] if stderr else str(e)
            )
            logger.warning(f"Could not read link '{link}': {err_line}")
            errors.append(f"{link}: {err_line}")
            continue
    return songs, errors


@app.route('/playlist', methods=['POST'])
def handle_playlist():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'No data provided.'}), 400

    # Accept either 'urls' (preferred, the new multi-line box) or 'url'
    # (kept for backwards compatibility with the old single-link box).
    raw_text = data.get('urls') or data.get('url') or ''
    raw_text = raw_text.strip()
    if not raw_text:
        return jsonify({'error': 'No links provided.'}), 400

    chosen_model = data.get('model', 'htdemucs_ft')
    engine_hint  = data.get('engine', None)
    bit_depth    = int(data.get('bit_depth', 16))
    playlist_id  = str(uuid.uuid4())

    try:
        songs, link_errors = expand_links(raw_text)
        if not songs:
            if link_errors:
                return jsonify({'error': 'No songs found. ' + ' | '.join(link_errors)}), 400
            return jsonify({'error': 'No songs found in those links.'}), 400

        tasks[playlist_id] = {
            'status': 'processing', 'type': 'playlist',
            'total': len(songs), 'current': 0,
            'current_title': '', 'completed_songs': [], 'zip': None,
        }
        threading.Thread(
            target=run_playlist,
            args=(playlist_id, songs, chosen_model, bit_depth, engine_hint),
            daemon=True
        ).start()
        return jsonify({'task_id': playlist_id, 'status': 'processing', 'total': len(songs)})

    except Exception as e:
        return jsonify({'error': friendly_error(e)}), 500


@app.route('/batch', methods=['POST'])
def handle_batch():
    if 'files' not in request.files:
        return jsonify({'error': 'No files found.'}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files selected.'}), 400

    chosen_model = request.form.get('model', 'htdemucs_ft')
    engine_hint  = request.form.get('engine', None)
    bit_depth    = int(request.form.get('bit_depth', 16))
    stems_filter = request.form.getlist('stems')
    if not stems_filter:
        stems_filter = None

    batch_id = str(uuid.uuid4())

    saved_files = []
    for file in files:
        if file.filename == '':
            continue
        ext      = Path(file.filename).suffix
        filename = f"{uuid.uuid4()}{ext}"
        filepath = app.config['UPLOAD_FOLDER'] / filename
        file.save(filepath)
        saved_files.append((file.filename, filepath))

    if not saved_files:
        return jsonify({'error': 'No valid files uploaded.'}), 400

    tasks[batch_id] = {
        'status':          'processing',
        'type':            'batch',
        'total':           len(saved_files),
        'current':         0,
        'current_title':   '',
        'completed_songs': [],
        'zip':             None,
    }

    threading.Thread(
        target=run_batch,
        args=(batch_id, saved_files, chosen_model, bit_depth, stems_filter, engine_hint),
        daemon=True
    ).start()

    return jsonify({
        'task_id': batch_id,
        'status':  'processing',
        'total':   len(saved_files),
    })


# ---------------------------------------------------------------------------
# Sequential batch (upload one file at a time, then process). This is the
# robust path for large albums: no single huge upload, so 50+ songs work.
# ---------------------------------------------------------------------------

@app.route('/batch/start', methods=['POST'])
def batch_start():
    data = request.get_json(silent=True) or {}
    batch_id = str(uuid.uuid4())
    tasks[batch_id] = {
        'status':          'uploading',
        'type':            'batch',
        'total':           int(data.get('total', 0)),
        'current':         0,
        'current_title':   '',
        'completed_songs': [],
        'zip':             None,
        'engine':          data.get('engine'),
        'model':           data.get('model', 'htdemucs_ft'),
        'bit_depth':       int(data.get('bit_depth', 16)),
        'stems':           data.get('stems') or None,
        '_pending':        [],   # list of (original_name, filepath)
    }
    return jsonify({'batch_id': batch_id})


@app.route('/batch/file', methods=['POST'])
def batch_file():
    batch_id = request.form.get('batch_id')
    if not batch_id or batch_id not in tasks:
        return jsonify({'error': 'Unknown batch session.'}), 400
    if 'file' not in request.files:
        return jsonify({'error': 'No file in request.'}), 400

    file = request.files['file']
    if file.filename == '':
        return jsonify({'error': 'Empty filename.'}), 400

    try:
        ext      = Path(file.filename).suffix
        filename = f"{uuid.uuid4()}{ext}"
        filepath = app.config['UPLOAD_FOLDER'] / filename
        file.save(filepath)
        tasks[batch_id]['_pending'].append((file.filename, filepath))
        return jsonify({'received': len(tasks[batch_id]['_pending'])})
    except Exception as e:
        logger.error(f"Batch file save failed: {e}")
        return jsonify({'error': friendly_error(e)}), 500


@app.route('/batch/finish', methods=['POST'])
def batch_finish():
    data = request.get_json(silent=True) or {}
    batch_id = data.get('batch_id')
    if not batch_id or batch_id not in tasks:
        return jsonify({'error': 'Unknown batch session.'}), 400

    t = tasks[batch_id]
    saved_files = t.get('_pending', [])
    if not saved_files:
        return jsonify({'error': 'No files were uploaded.'}), 400

    t['status'] = 'processing'
    t['total']  = len(saved_files)

    threading.Thread(
        target=run_batch,
        args=(batch_id, saved_files, t.get('model', 'htdemucs_ft'),
              t.get('bit_depth', 16), t.get('stems'), t.get('engine')),
        daemon=True
    ).start()

    return jsonify({'task_id': batch_id, 'status': 'processing', 'total': len(saved_files)})


@app.route('/cancel/<task_id>', methods=['POST'])
def cancel_task(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found.'}), 404
    tasks[task_id]['cancel_requested'] = True
    return jsonify({'status': 'cancelling'})


@app.route('/status/<task_id>')
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found.'}), 404
    # Don't expose internal keys (e.g. _pending holds non-serialisable paths)
    public = {k: v for k, v in tasks[task_id].items() if not k.startswith('_')}
    return jsonify(public)


@app.route('/history')
def get_history():
    """Return saved separations, most recent first. Never errors out."""
    history = load_history()
    return jsonify(list(reversed(history)))


@app.route('/history/<record_id>', methods=['DELETE'])
def delete_history(record_id):
    try:
        if not delete_history_entry(record_id):
            return jsonify({'error': 'History entry not found.'}), 404
        return jsonify({'status': 'deleted'})
    except Exception as e:
        return jsonify({'error': friendly_error(e)}), 500


@app.route('/download/<path:filename>')
def download_stem(filename):
    safe = filename.replace("/", os.sep)
    full_path = (config.SEPARATED_DATA_DIR / safe).resolve()
    if not full_path.is_relative_to(config.SEPARATED_DATA_DIR) or not full_path.exists():
        return jsonify({"error": "File not found"}), 404
    return send_file(full_path, mimetype='audio/wav', as_attachment=False)


@app.route('/download-zip/<playlist_id>')
def download_zip(playlist_id):
    zip_path = app.config['UPLOAD_FOLDER'] / f"{playlist_id}_stems.zip"
    if not zip_path.exists():
        return jsonify({"error": "Zip not ready"}), 404
    return send_file(zip_path, mimetype='application/zip',
                     as_attachment=True, download_name='stems.zip')


@app.route('/download-batch-zip/<batch_id>')
def download_batch_zip(batch_id):
    zip_path = app.config['UPLOAD_FOLDER'] / f"{batch_id}_stems.zip"
    if not zip_path.exists():
        return jsonify({"error": "Zip not ready"}), 404
    return send_file(zip_path, mimetype='application/zip',
                     as_attachment=True, download_name='batch_stems.zip')


if __name__ == '__main__':
    logger.info("Starting VocalSep server...")
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(debug=debug_mode, port=5000)