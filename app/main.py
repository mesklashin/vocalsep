import os
import uuid
import threading
import logging
import zipfile
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

YTDLP = r"C:\Users\adaml\AppData\Local\Packages\PythonSoftwareFoundation.Python.3.12_qbz5n2kfra8p0\LocalCache\local-packages\Python312\Scripts\yt-dlp.exe"

# ---------------------------------------------------------------------------
# Model routing — maps model value → (engine, model_name)
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

    # Direct lookup first — handles all known models including spleeter:Xstems
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


def run_separation(task_id, input_path, chosen_model, bit_depth=16, stems_filter=None, engine_hint=None):
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

        lyrics = []
        if 'vocals' in stems and os.path.exists(stems['vocals']):
            logger.info(f"Task {task_id}: Starting ASR...")
            if transcriber is None:
                transcriber = WhisperTranscriber(model_name="small")
            raw = transcriber.transcribe(stems['vocals'])
            lyrics = [l.get('text', str(l)) if isinstance(l, dict) else str(l) for l in raw]

        tasks[task_id] = {
            'status':     'completed',
            'results':    result_links,
            'lyrics':     lyrics,
            'filename':   Path(input_path).name,
            'engine':     engine,
            'model':      separator.model,
            'audio_info': audio_info,
            'bit_depth':  bit_depth,
        }
        logger.info(f"Task {task_id} completed.")

    except Exception as e:
        logger.error(f"Task {task_id} failed: {e}", exc_info=True)
        tasks[task_id] = {'status': 'failed', 'error': str(e)}


def run_playlist(playlist_id, urls, chosen_model, bit_depth=16, engine_hint=None):
    total = len(urls)
    completed_songs = []

    for i, (title, url) in enumerate(urls):
        song_id = str(uuid.uuid4())
        filepath = app.config['UPLOAD_FOLDER'] / f"{song_id}.mp3"

        tasks[playlist_id]['current'] = i + 1
        tasks[playlist_id]['current_title'] = title
        tasks[playlist_id]['total'] = total

        try:
            logger.info(f"Playlist {playlist_id}: [{i+1}/{total}] {title}")
            cmd = [YTDLP, '-x', '--audio-format', 'mp3',
                   '-o', str(filepath.with_suffix('')), url]
            subprocess.run(cmd, check=True, capture_output=True)

            if not filepath.exists():
                raise FileNotFoundError(f"Download failed: {title}")

            engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
            separator = get_separator(engine=engine, model=model_name)
            stems = separator.separate(filepath, bit_depth=bit_depth)

            song_stems = {}
            for stem_name, abs_path_str in stems.items():
                rel = Path(abs_path_str).relative_to(config.SEPARATED_DATA_DIR)
                song_stems[stem_name] = str(rel).replace(os.sep, "/")

            completed_songs.append({'title': title, 'stems': song_stems})
            tasks[playlist_id]['completed_songs'] = completed_songs

        except Exception as e:
            logger.error(f"Playlist failed on '{title}': {e}")
            completed_songs.append({'title': title, 'error': str(e)})
            tasks[playlist_id]['completed_songs'] = completed_songs

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
        tasks[playlist_id]['zip'] = str(playlist_id) + '_stems.zip'
    except Exception as e:
        logger.error(f"Zip failed: {e}")

    tasks[playlist_id]['status'] = 'completed'


def run_batch(batch_id, saved_files, chosen_model, bit_depth=16, stems_filter=None, engine_hint=None):
    total = len(saved_files)
    completed_songs = []

    for i, (original_name, filepath) in enumerate(saved_files):
        tasks[batch_id]['current'] = i + 1
        tasks[batch_id]['current_title'] = original_name
        tasks[batch_id]['total'] = total

        try:
            logger.info(f"Batch {batch_id}: [{i+1}/{total}] {original_name}")

            engine, model_name = resolve_engine_and_model(chosen_model, engine_hint)
            separator = get_separator(engine=engine, model=model_name)
            stems = separator.separate(filepath, bit_depth=bit_depth, stems_filter=stems_filter)

            song_stems = {}
            for stem_name, abs_path_str in stems.items():
                rel = Path(abs_path_str).relative_to(config.SEPARATED_DATA_DIR)
                song_stems[stem_name] = str(rel).replace(os.sep, "/")

            completed_songs.append({
                'title': Path(original_name).stem,
                'stems': song_stems,
            })

        except Exception as e:
            logger.error(f"Batch failed on '{original_name}': {e}")
            completed_songs.append({
                'title': Path(original_name).stem,
                'error': str(e),
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
        tasks[batch_id]['zip'] = f"{batch_id}_stems.zip"
        logger.info(f"Batch {batch_id}: ZIP created.")
    except Exception as e:
        logger.error(f"Batch ZIP failed: {e}")

    tasks[batch_id]['status'] = 'completed'
    logger.info(f"Batch {batch_id}: All done! {len(completed_songs)}/{total} files.")


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
    engine_hint  = request.form.get('engine', None)   # ← NEW: read engine from frontend
    bit_depth    = int(request.form.get('bit_depth', 16))
    stems_filter = request.form.getlist('stems')
    if not stems_filter:
        stems_filter = None

    task_id  = str(uuid.uuid4())
    ext      = Path(file.filename).suffix
    filepath = app.config['UPLOAD_FOLDER'] / f"{task_id}{ext}"

    try:
        file.save(filepath)
        tasks[task_id] = {'status': 'processing'}
        threading.Thread(
            target=run_separation,
            args=(task_id, filepath, chosen_model, bit_depth, stems_filter, engine_hint),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id, 'status': 'processing'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/youtube', methods=['POST'])
def handle_youtube():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided.'}), 400

    url          = data['url']
    chosen_model = data.get('model', 'htdemucs_ft')
    engine_hint  = data.get('engine', None)            # ← NEW
    bit_depth    = int(data.get('bit_depth', 16))
    stems_filter = data.get('stems', None)
    task_id      = str(uuid.uuid4())
    filepath     = app.config['UPLOAD_FOLDER'] / f"{task_id}.mp3"

    try:
        tasks[task_id] = {'status': 'processing'}
        cmd = [YTDLP, '-x', '--audio-format', 'mp3',
               '-o', str(filepath.with_suffix('')), url]
        subprocess.run(cmd, check=True)
        if not filepath.exists():
            raise FileNotFoundError("Download failed.")
        threading.Thread(
            target=run_separation,
            args=(task_id, filepath, chosen_model, bit_depth, stems_filter, engine_hint),
            daemon=True
        ).start()
        return jsonify({'task_id': task_id, 'status': 'processing'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/playlist', methods=['POST'])
def handle_playlist():
    data = request.get_json()
    if not data or 'url' not in data:
        return jsonify({'error': 'No URL provided.'}), 400

    url          = data['url']
    chosen_model = data.get('model', 'htdemucs_ft')
    engine_hint  = data.get('engine', None)            # ← NEW
    bit_depth    = int(data.get('bit_depth', 16))
    playlist_id  = str(uuid.uuid4())

    try:
        result = subprocess.run(
            [YTDLP, '--flat-playlist', '--print', '%(title)s\t%(url)s', url],
            capture_output=True, text=True, check=True
        )
        urls = []
        for line in result.stdout.strip().split('\n'):
            if '\t' in line:
                title, video_url = line.split('\t', 1)
                urls.append((title.strip(), video_url.strip()))

        if not urls:
            return jsonify({'error': 'No songs found.'}), 400

        tasks[playlist_id] = {
            'status': 'processing', 'type': 'playlist',
            'total': len(urls), 'current': 0,
            'current_title': '', 'completed_songs': [], 'zip': None,
        }
        threading.Thread(
            target=run_playlist,
            args=(playlist_id, urls, chosen_model, bit_depth, engine_hint),
            daemon=True
        ).start()
        return jsonify({'task_id': playlist_id, 'status': 'processing', 'total': len(urls)})

    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/batch', methods=['POST'])
def handle_batch():
    if 'files' not in request.files:
        return jsonify({'error': 'No files found.'}), 400

    files = request.files.getlist('files')
    if not files:
        return jsonify({'error': 'No files selected.'}), 400

    chosen_model = request.form.get('model', 'htdemucs_ft')
    engine_hint  = request.form.get('engine', None)    # ← NEW
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


@app.route('/status/<task_id>')
def get_status(task_id):
    if task_id not in tasks:
        return jsonify({'error': 'Task not found.'}), 404
    return jsonify(tasks[task_id])


@app.route('/download/<path:filename>')
def download_stem(filename):
    safe = filename.replace("/", os.sep)
    full_path = config.SEPARATED_DATA_DIR / safe
    if not full_path.exists():
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
    app.run(debug=True, port=5000)