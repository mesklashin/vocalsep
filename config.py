import os
from pathlib import Path
import torch

# Base Paths
BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = (BASE_DIR / "data").resolve()
RAW_DATA_DIR = (DATA_DIR / "raw").resolve()
SEPARATED_DATA_DIR = (DATA_DIR / "separated").resolve()
RESULTS_DIR = (DATA_DIR / "results").resolve()

# App Components
APP_DIR = (BASE_DIR / "app").resolve()
TEMPLATE_DIR = (APP_DIR / "templates").resolve()
STATIC_DIR = (APP_DIR / "static").resolve()
UPLOAD_FOLDER = (STATIC_DIR / "uploads").resolve()
WEB_RESULTS_DIR = (STATIC_DIR / "results").resolve()

ALLOWED_EXTENSIONS = {'mp3', 'wav', 'flac'}

# If a bundled ffmpeg was downloaded via scripts/download_ffmpeg.py, make it
# available on PATH so subprocess calls (yt-dlp, librosa, etc.) find it
# without requiring a system-wide ffmpeg install.
_BUNDLED_FFMPEG_BIN = BASE_DIR / "bin" / "ffmpeg" / "bin"
if _BUNDLED_FFMPEG_BIN.exists():
    os.environ["PATH"] = str(_BUNDLED_FFMPEG_BIN) + os.pathsep + os.environ.get("PATH", "")

# Hardware
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# GPU performance tuning. TF32 matmul is safe for audio separation (no
# audible quality loss) and gives a speedup on Ampere+ NVIDIA cards.
# Note: cudnn.benchmark is intentionally NOT enabled — Demucs splits audio
# into segments where the last chunk has a different size, so cudnn would
# re-run its algorithm search for every shape change, making things much
# slower overall.
if DEVICE == "cuda":
    torch.backends.cuda.matmul.allow_tf32 = True
    torch.backends.cudnn.allow_tf32 = True

# ---------------------------------------------------------------------------
# Demucs
# ---------------------------------------------------------------------------
# models: htdemucs, htdemucs_ft, htdemucs_6s, mdx_extra, mdx_extra_q
DEMUCS_MODELS = ["htdemucs", "htdemucs_ft", "mdx_extra"]
DEFAULT_DEMUCS_MODEL = "htdemucs_ft"


def _auto_demucs_segment():
    """
    Pick a safe Demucs segment size based on available GPU memory.

    Bigger segments process more audio per pass (faster) but use more VRAM;
    too big causes out-of-memory crashes. Auto-detecting keeps the tool fast
    on capable GPUs while staying safe on small ones, with no manual config.
    HTDemucs is trained at a max segment of ~7.8 s, so we never exceed that.
    """
    if DEVICE != "cuda":
        return 7  # CPU: segment size barely matters; keep it modest
    try:
        vram_gb = torch.cuda.get_device_properties(0).total_memory / (1024 ** 3)
    except Exception:
        return 7
    if vram_gb >= 6:
        return 7.8   # full HTDemucs segment — best speed on 6 GB+ cards
    if vram_gb >= 4:
        return 7
    return 5         # tight on memory: smaller chunks avoid OOM


DEMUCS_SEGMENT_SIZE = _auto_demucs_segment()

# ---------------------------------------------------------------------------
# Spleeter
# ---------------------------------------------------------------------------
# configs: 2stems, 4stems, 5stems
DEFAULT_SPLEETER_CONFIG = "4stems"   # vocals, drums, bass, other

# ---------------------------------------------------------------------------
# Open-Unmix
# ---------------------------------------------------------------------------
# models: umxl (best), umxhq, umx
DEFAULT_OPENUNMIX_MODEL = "umxhq"    # vocals, drums, bass, other

# ---------------------------------------------------------------------------
# Whisper ASR
# ---------------------------------------------------------------------------
WHISPER_MODEL_SIZE = "small"
WHISPER_LANGUAGE = "fr"

# ---------------------------------------------------------------------------
# Flask
# ---------------------------------------------------------------------------
SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-key-123")

# Create directories
for folder in [RAW_DATA_DIR, SEPARATED_DATA_DIR, RESULTS_DIR,
               UPLOAD_FOLDER, WEB_RESULTS_DIR, TEMPLATE_DIR]:
    folder.mkdir(parents=True, exist_ok=True)
