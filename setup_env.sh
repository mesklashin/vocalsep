#!/usr/bin/env bash
set -e

python3 -m venv venv
source venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
python scripts/download_ffmpeg.py

echo "Environment setup complete. Run ./run.sh to start the app."
