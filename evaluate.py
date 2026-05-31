import os, sys, time, csv, shutil, tempfile, subprocess
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent
sys.path.append(str(PROJECT_ROOT))
import config
from separation.separator import get_separator

SONGS_DIR   = PROJECT_ROOT / "My_songs"
RESULTS_CSV = PROJECT_ROOT / "evaluation_results.csv"
SONGS       = sorted(SONGS_DIR.glob("*.mp3"))

# Run Demucs and OpenUnmix in main process, Spleeter in subprocess
ENGINES = [
    ("demucs",    "htdemucs_ft"),
    ("demucs",    "htdemucs"),
    ("openunmix", "umxhq"),
    ("spleeter",  "spleeter:2stems"),
]

CSV_HEADER = ["song","engine","model","processing_time_sec","vocals_path","transcription","wer"]

def save_row(row):
    file_exists = RESULTS_CSV.exists()
    with open(RESULTS_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        if not file_exists:
            writer.writerow(CSV_HEADER)
        writer.writerow(row)

def already_done(song_name, engine, model):
    if not RESULTS_CSV.exists():
        return False
    with open(RESULTS_CSV, "r", encoding="utf-8") as f:
        reader = csv.reader(f)
        for row in reader:
            if len(row) >= 3 and row[0] == song_name and row[1] == engine and row[2] == model:
                return True
    return False

_whisper_model = None
def get_whisper():
    global _whisper_model
    if _whisper_model is None:
        import whisper
        print("     Loading Whisper model...")
        _whisper_model = whisper.load_model("medium")
    return _whisper_model

def transcribe(vocal_path):
    tmp_path = None
    try:
        model = get_whisper()
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
            tmp_path = tmp.name
        shutil.copy2(str(vocal_path), tmp_path)
        result = model.transcribe(tmp_path, language="fr")
        return result["text"].strip()
    except Exception as e:
        return f"[Whisper error: {e}]"
    finally:
        if tmp_path and os.path.exists(tmp_path):
            try: os.remove(tmp_path)
            except: pass

def compute_wer(reference, hypothesis):
    try:
        from jiwer import wer
        return round(wer(reference, hypothesis), 4)
    except:
        return -1.0

def separate_with_spleeter(song_path, model):
    """Run Spleeter in a completely separate subprocess to avoid TensorFlow graph issues."""
    script = f"""
import sys
sys.path.insert(0, r'{PROJECT_ROOT}')
import config
from separation.separator import get_separator
from pathlib import Path
sep = get_separator(engine='spleeter', model='{model}')
stems = sep.separate(Path(r'{song_path}'), bit_depth=16, stems_filter=['vocals'])
vocals = stems.get('vocals') or stems.get('accompaniment') or ''
print(vocals)
"""
    try:
        result = subprocess.run(
            [sys.executable, "-c", script],
            capture_output=True, text=True, timeout=300
        )
        # Get last non-empty line as vocals path
        lines = [l.strip() for l in result.stdout.strip().split('\n') if l.strip()]
        if lines:
            vocals_path = lines[-1]
            if Path(vocals_path).exists():
                return vocals_path
        return None
    except Exception as e:
        print(f"     Spleeter subprocess error: {e}")
        return None

def main():
    print("\n" + "="*70)
    print("  VocalSep - Automated Evaluation Script (with Spleeter fix)")
    print(f"  Songs found : {len(SONGS)}")
    print(f"  Results CSV : {RESULTS_CSV}")
    print("  Saves after EACH result - safe to restart!")
    print("="*70 + "\n")

    if not SONGS:
        print("No mp3 files found in My_songs/")
        return

    total_combos = len(SONGS) * len(ENGINES)
    done_count = 0

    for song_path in SONGS:
        print(f"\n{'─'*70}")
        print(f"Song: {song_path.name}")
        print(f"{'─'*70}")

        lyrics_file = song_path.with_suffix(".txt")
        reference_lyrics = None
        if lyrics_file.exists():
            reference_lyrics = lyrics_file.read_text(encoding="utf-8").strip()
            print(f"  Lyrics: found")
        else:
            print(f"  Lyrics: not found - WER skipped")

        for engine, model in ENGINES:
            done_count += 1
            progress = f"[{done_count}/{total_combos}]"

            if already_done(song_path.name, engine, model):
                print(f"\n  {progress} SKIP: {engine} | {model}")
                continue

            print(f"\n  {progress} Engine: {engine} | Model: {model}")
            try:
                start_time = time.time()

                if engine == "spleeter":
                    # Run Spleeter in subprocess to avoid TensorFlow crash
                    print("     Running Spleeter in isolated process...")
                    vocals_path = separate_with_spleeter(song_path, model)
                else:
                    separator = get_separator(engine=engine, model=model)
                    stems = separator.separate(song_path, bit_depth=16, stems_filter=["vocals"])
                    vocals_path = stems.get("vocals") or stems.get("accompaniment")

                elapsed = round(time.time() - start_time, 2)
                print(f"     Time: {elapsed}s")

                if not vocals_path:
                    save_row([song_path.name, engine, model, elapsed, "N/A", "N/A", "N/A"])
                    continue

                print(f"     Transcribing...")
                transcription = transcribe(Path(vocals_path))
                print(f"     Text: {transcription[:80]}...")

                wer_score = "N/A"
                if reference_lyrics:
                    wer_score = compute_wer(reference_lyrics, transcription)
                    if isinstance(wer_score, float) and wer_score >= 0:
                        print(f"     WER: {wer_score:.1%}")

                save_row([song_path.name, engine, model, elapsed, vocals_path, transcription, wer_score])
                print(f"     Saved!")

            except Exception as e:
                print(f"     FAILED: {e}")
                save_row([song_path.name, engine, model, "FAILED", "N/A", str(e), "N/A"])

    print(f"\n\n{'='*70}")
    print(f"  ALL DONE! Open evaluation_results.csv in Excel!")
    print("="*70)

if __name__ == "__main__":
    main()