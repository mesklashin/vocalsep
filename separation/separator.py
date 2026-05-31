import os
import sys
import logging
from pathlib import Path
from abc import ABC, abstractmethod

sys.path.append(str(Path(__file__).resolve().parent.parent))
import config

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)


class BaseSeparator(ABC):
    def __init__(self, model: str):
        self.model = model

    @abstractmethod
    def separate(self, audio_path, bit_depth=16, stems_filter=None) -> dict:
        pass


def write_stem(path, data, sr, bit_depth):
    import soundfile as sf
    fmt = 'PCM_32' if bit_depth == 32 else 'PCM_16'
    sf.write(str(path), data, sr, subtype=fmt)


# ---------------------------------------------------------------------------
# Demucs
# ---------------------------------------------------------------------------

class DemucsSeparator(BaseSeparator):
    def __init__(self, model: str = config.DEFAULT_DEMUCS_MODEL):
        super().__init__(model)
        logger.info(f"[Demucs] Loading model '{model}' on device '{config.DEVICE}'")
        try:
            import torch
            from demucs.pretrained import get_model
            from demucs.apply import apply_model
        except ImportError:
            raise ImportError("Run: pip install demucs")

        self._torch = torch
        self._apply_model = apply_model
        self._demucs_model = get_model(model)
        self._demucs_model.to(config.DEVICE)
        self._demucs_model.eval()

    def separate(self, audio_path, bit_depth=16, stems_filter=None) -> dict:
        import torch
        import soundfile as sf
        import numpy as np

        audio_path = Path(audio_path)
        out_dir = config.SEPARATED_DATA_DIR / self.model / audio_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[Demucs] Separating: {audio_path.name} | {bit_depth}bit")

        waveform, sr = sf.read(str(audio_path), always_2d=True)
        waveform = waveform.T

        target_sr = self._demucs_model.samplerate
        if sr != target_sr:
            import librosa
            waveform = librosa.resample(waveform, orig_sr=sr, target_sr=target_sr)

        if waveform.shape[0] == 1:
            waveform = np.vstack([waveform, waveform])

        tensor = torch.tensor(waveform, dtype=torch.float32).unsqueeze(0).to(config.DEVICE)

        segment = getattr(config, "DEMUCS_SEGMENT_SIZE", 7)
        with torch.no_grad():
            sources = self._apply_model(
                self._demucs_model, tensor,
                device=config.DEVICE, split=True,
                segment=segment, overlap=0.25, progress=True,
            )[0]

        stem_names = self._demucs_model.sources
        results = {}
        for i, name in enumerate(stem_names):
            if stems_filter and name not in stems_filter:
                continue
            stem_np = sources[i].cpu().numpy().T
            out_file = out_dir / f"{name}.wav"
            write_stem(out_file, stem_np, target_sr, bit_depth)
            results[name] = str(out_file)
            logger.info(f"[Demucs] Saved '{name}' → {out_file}")

        return results


# ---------------------------------------------------------------------------
# Open-Unmix
# ---------------------------------------------------------------------------

class OpenUnmixSeparator(BaseSeparator):
    def __init__(self, model: str = config.DEFAULT_OPENUNMIX_MODEL):
        super().__init__(model)
        logger.info(f"[OpenUnmix] Loading model '{model}' on device '{config.DEVICE}'")
        try:
            import openunmix
        except ImportError:
            raise ImportError("Run: pip install openunmix")
        import torch
        self._torch = torch
        self._device = config.DEVICE

        if model == "umxl":
            self._model = openunmix.umxl(device=self._device)
        elif model == "umx":
            self._model = openunmix.umx(device=self._device)
        else:
            self._model = openunmix.umxhq(device=self._device)

        self._model.eval()

    def separate(self, audio_path, bit_depth=16, stems_filter=None) -> dict:
        import soundfile as sf
        import numpy as np
        import torch

        audio_path = Path(audio_path)
        out_dir = config.SEPARATED_DATA_DIR / self.model / audio_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[OpenUnmix] Separating: {audio_path.name} | {bit_depth}bit")

        waveform, sr = sf.read(str(audio_path), always_2d=True)
        waveform = waveform.T

        target_sr = 44100
        if sr != target_sr:
            import librosa
            waveform = librosa.resample(waveform, orig_sr=sr, target_sr=target_sr)

        if waveform.shape[0] == 1:
            waveform = np.vstack([waveform, waveform])

        audio_tensor = torch.tensor(waveform, dtype=torch.float32).unsqueeze(0).to(self._device)

        with torch.no_grad():
            estimates = self._model(audio_tensor)

        targets = ["vocals", "drums", "bass", "other"]
        results = {}
        for i, stem_name in enumerate(targets):
            if i >= estimates.shape[1]:
                break
            if stems_filter and stem_name not in stems_filter:
                continue
            stem_np = estimates[0, i].cpu().numpy().T
            out_file = out_dir / f"{stem_name}.wav"
            write_stem(out_file, stem_np, target_sr, bit_depth)
            results[stem_name] = str(out_file)
            logger.info(f"[OpenUnmix] Saved '{stem_name}' → {out_file}")

        return results


# ---------------------------------------------------------------------------
# Spleeter
# ---------------------------------------------------------------------------

class SpleeterSeparator(BaseSeparator):
    """
    Wraps Deezer Spleeter for vocal/instrumental separation.
    Requires Python 3.8 environment with spleeter installed.
    Config options: spleeter:2stems, spleeter:4stems, spleeter:5stems
    """

    def __init__(self, model: str = None):
        # Use config value if no model passed in
        stems_config = model or f"spleeter:{config.DEFAULT_SPLEETER_CONFIG}"
        super().__init__(stems_config)
        logger.info(f"[Spleeter] Loading model '{stems_config}'")
        try:
            from spleeter.separator import Separator
        except ImportError:
            raise ImportError(
                "Spleeter not found. Activate your spleeter-env7 environment "
                "and run: pip install spleeter"
            )
        # Spleeter downloads model weights on first use (~500 MB)
        self._separator = Separator(stems_config)
        logger.info(f"[Spleeter] Model ready.")

    def separate(self, audio_path, bit_depth=16, stems_filter=None) -> dict:
        import soundfile as sf
        import numpy as np

        audio_path = Path(audio_path)

        # Output directory mirrors the other separators
        out_dir = config.SEPARATED_DATA_DIR / "spleeter" / audio_path.stem
        out_dir.mkdir(parents=True, exist_ok=True)

        logger.info(f"[Spleeter] Separating: {audio_path.name} | model='{self.model}' | {bit_depth}bit")

        # Spleeter writes files itself into out_dir/song_name/
        self._separator.separate_to_file(
            str(audio_path),
            str(out_dir),
            filename_format="{instrument}.wav",   # e.g. vocals.wav, accompaniment.wav
            synchronous=True,
        )

        # Determine which stems this config produces
        stems_map = {
            "spleeter:2stems": ["vocals", "accompaniment"],
            "spleeter:4stems": ["vocals", "drums", "bass", "other"],
            "spleeter:5stems": ["vocals", "drums", "bass", "piano", "other"],
        }
        expected_stems = stems_map.get(self.model, ["vocals", "accompaniment"])

        # Collect paths and optionally re-write at requested bit depth
        results = {}
        for stem_name in expected_stems:
            if stems_filter and stem_name not in stems_filter:
                continue

            # Spleeter writes directly into out_dir (because of filename_format)
            out_file = out_dir / f"{stem_name}.wav"

            if not out_file.exists():
                logger.warning(f"[Spleeter] Expected file not found: {out_file}")
                continue

            # Re-write at correct bit depth if needed
            if bit_depth != 16:
                data, sr = sf.read(str(out_file), always_2d=True)
                write_stem(out_file, data, sr, bit_depth)

            results[stem_name] = str(out_file)
            logger.info(f"[Spleeter] Saved '{stem_name}' → {out_file}")

        return results


# ---------------------------------------------------------------------------
# Registry — add new engines here
# ---------------------------------------------------------------------------

ENGINES = {
    "demucs":     DemucsSeparator,
    "openunmix":  OpenUnmixSeparator,
    "spleeter":   SpleeterSeparator,
}

DEFAULT_MODELS = {
    "demucs":    config.DEFAULT_DEMUCS_MODEL,
    "openunmix": config.DEFAULT_OPENUNMIX_MODEL,
    "spleeter":  f"spleeter:{config.DEFAULT_SPLEETER_CONFIG}",
}


def get_separator(engine: str = "demucs", model: str = None):
    """
    Factory function — returns an initialised separator for the given engine.

    Usage:
        sep = get_separator("spleeter")
        results = sep.separate("song.mp3", bit_depth=16, stems_filter=["vocals"])
    """
    engine = engine.lower()
    if engine not in ENGINES:
        raise ValueError(
            f"Unknown engine '{engine}'. Available: {list(ENGINES.keys())}"
        )
    chosen_model = model or DEFAULT_MODELS[engine]
    return ENGINES[engine](model=chosen_model)