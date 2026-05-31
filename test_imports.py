import sys

def test_imports():
    modules = [
        "demucs",
        "whisper",
        "flask",
        "mir_eval",
        "librosa",
        "soundfile",
        "numpy",
        "pandas",
        "matplotlib",
        "jiwer"
    ]
    
    print(f"Python version: {sys.version}")
    print("-" * 20)
    
    for module in modules:
        try:
            __import__(module)
            print(f"[OK] {module} imported successfully.")
        except ImportError as e:
            print(f"[FAIL] {module} failed to import: {e}")

if __name__ == "__main__":
    test_imports()
