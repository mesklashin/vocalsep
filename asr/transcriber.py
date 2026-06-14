import whisper
import torch
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

logger = logging.getLogger(__name__)

class WhisperTranscriber:
    def __init__(self, model_name="medium"):
        """
        Initializes the Whisper model.
        Detects CUDA for GPU acceleration.
        """
        self.device = "cuda" if torch.cuda.is_available() else "cpu"
        logger.info(f"Initializing Whisper '{model_name}' on {self.device}...")
        
        # Load model (this will download it on the first run)
        try:
            self.model = whisper.load_model(model_name, device=self.device)
        except Exception as e:
            logger.error(f"Failed to load Whisper model on GPU: {e}. Falling back to CPU.")
            self.model = whisper.load_model(model_name, device="cpu")

    def transcribe(self, audio_path):
        """
        Transcribes the given audio file.
        Returns a list of segments with timestamps.
        """
        audio_path = str(Path(audio_path).resolve())
        logger.info(f"Starting ASR for: {audio_path}")
        
        # task='transcribe' (not translate)
        result = self.model.transcribe(
            audio_path,
            language=config.WHISPER_LANGUAGE,
            task='transcribe',
            verbose=False,
            fp16=(self.device == "cuda")
        )
        
        segments = []
        for segment in result['segments']:
            segments.append({
                'start': segment['start'],
                'end': segment['end'],
                'text': segment['text'].strip()
            })
            
        logger.info(f"ASR Complete. Transcribed {len(segments)} segments.")
        return segments

if __name__ == "__main__":
    # Test script
    logging.basicConfig(level=logging.INFO)
    # Note: Replace with a real path if testing manually
    # transcriber = WhisperTranscriber()
    # print(transcriber.transcribe("sample_vocals.wav"))
