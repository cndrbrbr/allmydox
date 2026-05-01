#!/usr/bin/env bash
set -euo pipefail

SPACY_MODEL="${1:-en_core_web_sm}"
SPACY_VERSION="3.8.0"

echo "=== allmydox setup ==="

# Bootstrap pip if not present
if ! python3 -m pip --version &>/dev/null; then
    echo "Installing pip..."
    TMP_PIP="$(mktemp)"
    curl -sSf https://bootstrap.pypa.io/get-pip.py -o "$TMP_PIP"
    python3 "$TMP_PIP" --user --break-system-packages
    rm "$TMP_PIP"
fi

PIP="$(python3 -c 'import site; print(site.getuserbase())')/bin/pip"

echo "Installing Python dependencies..."
"$PIP" install --break-system-packages -q \
    "spacy>=3.7.0" \
    "pymupdf>=1.23.0" \
    "python-docx>=1.1.0"

echo "Installing spaCy model: $SPACY_MODEL $SPACY_VERSION..."
"$PIP" install --break-system-packages -q \
    "https://github.com/explosion/spacy-models/releases/download/${SPACY_MODEL}-${SPACY_VERSION}/${SPACY_MODEL}-${SPACY_VERSION}-py3-none-any.whl"

echo "Verifying installation..."
python3 - <<'EOF'
import spacy, fitz, docx
nlp = spacy.load("en_core_web_sm")
doc = nlp("Setup complete.")
print(f"  spacy        {spacy.__version__}")
print(f"  pymupdf      {fitz.__version__}")
print(f"  python-docx  {docx.__version__}")
print(f"  model        en_core_web_sm  ok")
EOF

echo ""
echo "Setup complete. Run with:"
echo "  python3 main.py process <directory>"
echo "  python3 main.py stats"
echo ""
echo "For a different language model, rerun: bash setup.sh de_core_news_sm"
