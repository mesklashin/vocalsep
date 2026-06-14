"""
download_lyrics.py — Auto-download French rap lyrics from Genius
Matches each mp3 in My_songs/ to its lyrics and saves as .txt

Usage:
    pip install lyricsgenius
    python download_lyrics.py
"""

import os
import re
from pathlib import Path

SONGS_DIR = Path(__file__).resolve().parent / "My_songs"
TOKEN = os.environ.get("GENIUS_API_TOKEN")

def clean_title(filename):
    name = Path(filename).stem
    name = re.sub(r'\(.*?\)', '', name)
    name = re.sub(r'\[.*?\]', '', name)
    name = re.sub(r'Official.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'Clip.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'MV.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'HQ.*', '', name, flags=re.IGNORECASE)
    name = re.sub(r'\d{4}', '', name)
    name = re.sub(r'[-_]+', ' ', name)
    name = name.strip()
    return name

def main():
    print("\n" + "="*60)
    print("  Lyrics Downloader for VocalSep Evaluation")
    print("="*60)

    if not TOKEN:
        print("\nERROR: Set the GENIUS_API_TOKEN environment variable with your Genius API token.")
        return

    try:
        import lyricsgenius
    except ImportError:
        print("\nlyricsgenius is not installed. Run: pip install lyricsgenius")
        return

    genius = lyricsgenius.Genius(
        TOKEN,
        skip_non_songs=True,
        excluded_terms=["(Remix)", "(Live)"],
        verbose=False,
        remove_section_headers=True,
    )

    songs = sorted(SONGS_DIR.glob("*.mp3"))
    print(f"\nFound {len(songs)} songs in My_songs/\n")

    found = 0
    skipped = 0
    failed = 0

    for song_path in songs:
        txt_path = song_path.with_suffix(".txt")

        if txt_path.exists():
            print(f"  SKIP (already have lyrics): {song_path.name}")
            skipped += 1
            continue

        title = clean_title(song_path.name)
        print(f"  Searching: {title[:60]}")

        try:
            song = genius.search_song(title)
            if song and song.lyrics:
                lyrics = song.lyrics
                lyrics = re.sub(r'\d+Embed$', '', lyrics).strip()
                lyrics = re.sub(r'You might also like', '', lyrics).strip()
                txt_path.write_text(lyrics, encoding="utf-8")
                print(f"    FOUND: {song.title} — {len(lyrics)} chars saved")
                found += 1
            else:
                print(f"    NOT FOUND on Genius")
                failed += 1
        except Exception as e:
            print(f"    ERROR: {e}")
            failed += 1

    print(f"\n{'='*60}")
    print(f"  Done! Found: {found} | Skipped: {skipped} | Failed: {failed}")
    print(f"  Lyrics saved as .txt files in My_songs/")
    print(f"  Now run: python evaluate.py")
    print("="*60)

if __name__ == "__main__":
    main()
