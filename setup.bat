@echo off
REM allmydox setup — Windows
REM Usage:  setup.bat [spacy-model]
REM Default model: de_core_news_sm  (German)
REM Other models:  en_core_web_sm  fr_core_news_sm  es_core_news_sm

setlocal

if "%~1"=="" (
    set SPACY_MODEL=de_core_news_sm
) else (
    set SPACY_MODEL=%~1
)
set SPACY_VERSION=3.8.0

echo === allmydox setup (Windows) ===

echo Installing Python dependencies...
python -m pip install --upgrade pip --quiet
python -m pip install --quiet ^
    "spacy>=3.7.0" ^
    "pymupdf>=1.23.0" ^
    "python-docx>=1.1.0" ^
    "PyQt6>=6.5.0" ^
    "openpyxl>=3.1.0" ^
    "xlrd>=2.0.0"

echo Installing spaCy model: %SPACY_MODEL% %SPACY_VERSION% ...
python -m pip install --quiet ^
    "https://github.com/explosion/spacy-models/releases/download/%SPACY_MODEL%-%SPACY_VERSION%/%SPACY_MODEL%-%SPACY_VERSION%-py3-none-any.whl"

echo Verifying installation...
python -c "import spacy, fitz, docx; from PyQt6.QtCore import PYQT_VERSION_STR; nlp = spacy.load('%SPACY_MODEL%'); print('  spacy       ', spacy.__version__); print('  pymupdf     ', fitz.__version__); print('  python-docx ', docx.__version__); print('  PyQt6       ', PYQT_VERSION_STR); print('  model        %SPACY_MODEL%  ok')"

echo.
echo Setup complete.
echo Start the GUI:        start.bat
echo Command-line usage:   python main.py process ^<directory^>
echo.
echo For a different language model, rerun: setup.bat en_core_web_sm

endlocal
