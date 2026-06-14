import os
import urllib.request
import zipfile
from pathlib import Path
import shutil
import sys
import time

# We use a shared build to get the .dll files required by torchcodec/torchaudio
FFMPEG_URL = "https://github.com/BtbN/FFmpeg-Builds/releases/download/latest/ffmpeg-master-latest-win64-gpl-shared.zip"

def download_ffmpeg():
    """
    Downloads and extracts FFmpeg Shared Build for Windows into the project root.

    On Linux/Mac this is a no-op - install ffmpeg via your system package
    manager instead (e.g. `sudo apt install ffmpeg` or `brew install ffmpeg`).
    """
    if os.name != "nt":
        print("[SKIP] Bundled ffmpeg download is Windows-only.")
        print("       Install ffmpeg via your system package manager, e.g.:")
        print("         sudo apt install ffmpeg   (Debian/Ubuntu)")
        print("         brew install ffmpeg       (macOS)")
        return

    project_root = Path(__file__).resolve().parent.parent
    bin_dir = project_root / "bin"
    ffmpeg_target = bin_dir / "ffmpeg"

    if (ffmpeg_target / "bin" / "ffmpeg.exe").exists():
        print("[OK] FFmpeg shared build already exists in bin/ffmpeg. Skipping.")
        return

    print("Starting FFmpeg Shared Build setup for Windows...")
    bin_dir.mkdir(exist_ok=True)
    temp_zip = bin_dir / "ffmpeg_shared.zip"
    
    try:
        # 1. Download
        def report(block_num, block_size, total_size):
            read_so_far = block_num * block_size
            if total_size > 0:
                percent = min(read_so_far * 100 / total_size, 100)
                if int(percent) % 10 == 0:
                    sys.stdout.write(f"\rDownloading: {percent:3.0f}%")
                    sys.stdout.flush()

        urllib.request.urlretrieve(FFMPEG_URL, temp_zip, reporthook=report)
        print("\n[OK] Download complete. Extracting files...")
        
        # 2. Extract
        with zipfile.ZipFile(temp_zip, 'r') as zip_ref:
            temp_extract = bin_dir / "temp_ffmpeg_extraction"
            if temp_extract.exists():
                shutil.rmtree(temp_extract)
            temp_extract.mkdir()
            
            zip_ref.extractall(temp_extract)
            
            extracted_folders = [f for f in temp_extract.iterdir() if f.is_dir()]
            if not extracted_folders:
                raise RuntimeError("Could not find extracted folder in ZIP.")
            
            inner_folder = extracted_folders[0]
            
            if ffmpeg_target.exists():
                shutil.rmtree(ffmpeg_target)
            shutil.move(str(inner_folder), str(ffmpeg_target))
            
            shutil.rmtree(temp_extract)
            
        # 3. Cleanup with retry logic for Windows file locks
        print("Cleaning up temporary files...")
        for i in range(5):
            try:
                if temp_zip.exists():
                    temp_zip.unlink()
                break
            except Exception:
                if i < 4:
                    time.sleep(1) # Wait for filesystem to release lock
            
        print(f"DONE: FFmpeg shared libraries successfully installed to: {ffmpeg_target}")
        
    except Exception as e:
        print(f"\nERROR during setup: {e}")
        # Try one last time to cleanup if it failed midway
        try:
            if temp_zip.exists():
                temp_zip.unlink()
        except:
            pass
        sys.exit(1)

if __name__ == "__main__":
    download_ffmpeg()
