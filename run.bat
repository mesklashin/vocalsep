@echo off
set PYTHONPATH=.
if exist "%USERPROFILE%\spleeter-env7\Scripts\python.exe" (
    "%USERPROFILE%\spleeter-env7\Scripts\python.exe" app/main.py
) else (
    venv\Scripts\python.exe app/main.py
)
