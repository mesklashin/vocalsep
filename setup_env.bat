python -m venv venv
.\venv\Scripts\activate
python -m pip install --upgrade pip
pip install -r requirements.txt
pip install -U yt-dlp
python scripts\download_ffmpeg.py
echo "Environment setup complete. Run run.bat to start the app."
