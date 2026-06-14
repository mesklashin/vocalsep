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

# ---------------------------------------------------------------------------
# Demucs
# ---------------------------------------------------------------------------
# models: htdemucs, htdemucs_ft, htdemucs_6s, mdx_extra, mdx_extra_q
DEMUCS_MODELS = ["htdemucs", "htdemucs_ft", "mdx_extra"]
DEFAULT_DEMUCS_MODEL = "htdemucs_ft"
# Lower segment size to avoid OOM on 4 GB VRAM (HTDemucs max is 7.8 s)
DEMUCS_SEGMENT_SIZE = 7

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
