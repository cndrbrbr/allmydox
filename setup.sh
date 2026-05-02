#!/usr/bin/env bash
# allmydox setup — Linux
# Usage:  bash setup.sh [spacy-model]
# Default model: de_core_news_sm  (German)
# Other models:  en_core_web_sm  fr_core_news_sm  es_core_news_sm
set -euo pipefail

SPACY_MODEL="${1:-de_core_news_sm}"
SPACY_VERSION="3.8.0"

echo "=== allmydox setup (Linux) ==="

# Bootstrap pip if not present
if ! python3 -m pip --version &>/dev/null; then
    echo "Installing pip..."
    TMP_PIP="$(mktemp)"
    curl -sSf https://bootstrap.pypa.io/get-pip.py -o "$TMP_PIP"
    python3 "$TMP_PIP" --user --break-system-packages
    rm "$TMP_PIP"
fi

echo "Installing Python dependencies..."
python3 -m pip install --break-system-packages -q \
    "spacy>=3.7.0" \
    "pymupdf>=1.23.0" \
    "python-docx>=1.1.0" \
    "PyQt6>=6.5.0" \
    "openpyxl>=3.1.0" \
    "xlrd>=2.0.0"

echo "Installing spaCy model: $SPACY_MODEL $SPACY_VERSION ..."
python3 -m pip install --break-system-packages -q \
    "https://github.com/explosion/spacy-models/releases/download/${SPACY_MODEL}-${SPACY_VERSION}/${SPACY_MODEL}-${SPACY_VERSION}-py3-none-any.whl"

echo "Verifying installation..."
python3 - <<EOF
import spacy, fitz, docx
from PyQt6.QtCore import PYQT_VERSION_STR
nlp = spacy.load("$SPACY_MODEL")
print(f"  spacy        {spacy.__version__}")
print(f"  pymupdf      {fitz.__version__}")
print(f"  python-docx  {docx.__version__}")
print(f"  PyQt6        {PYQT_VERSION_STR}")
print(f"  model        $SPACY_MODEL  ok")
EOF

echo ""
echo "Setup complete."
echo "Start the GUI:        bash start.sh"
echo "Command-line usage:   python3 main.py process <directory>"
echo ""
echo "For a different language model, rerun: bash setup.sh en_core_web_sm"
