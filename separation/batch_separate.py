import os
import sys
from pathlib import Path
import logging

# Add project root to path for imports
sys.path.append(str(Path(__file__).resolve().parent.parent))
import config
from separation.separator import DemucsSeparator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

def run_batch_separation():
    """
    Iterates through all audio files in the raw data directory
    and runs separation using multiple Demucs models.
    """
    raw_dir = Path(config.RAW_DATA_DIR)
    models = config.DEMUCS_MODELS
    
    # 1. Gather all music files
    audio_files = []
    for ext in config.ALLOWED_EXTENSIONS:
        audio_files.extend(list(raw_dir.glob(f"*.{ext}")))
    
    if not audio_files:
        logger.warning(f"No audio files found in {raw_dir}. Please place MP3/WAV files there.")
        return

    logger.info(f"Batch separation initialized. Found {len(audio_files)} files to process.")
    logger.info(f"Models to evaluate: {models}")

    # 2. Process each model
    for model_name in models:
        logger.info(f"--- Switching to model: {model_name} ---")
        separator = DemucsSeparator(model=model_name)
        
        for audio_path in audio_files:
            logger.info(f"Processing: {audio_path.name}")
            try:
                # We save output to data/separated/<model>/<song_name>
                # separator.py already handles the subfolder structure
                results = separator.separate(audio_path)
                logger.info(f"Successfully separated {audio_path.name}")
            except Exception as e:
                logger.error(f"Failed to process {audio_path.name} with {model_name}: {e}")

    logger.info("Batch separation process finished.")

if __name__ == "__main__":
    run_batch_separation()
