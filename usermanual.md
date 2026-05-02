# allmydox — User Manual

allmydox scans folders of documents (PDF, DOCX, TXT), extracts nouns, names,
and verbs using NLP, and stores everything — including sentence and paragraph
co-occurrence relationships — into a SQLite database. The database can then
be explored visually with [findethedox](https://github.com/cndrbrbr/findethedox).

---

## Requirements

- Python 3.9 or newer
- Internet connection for the one-time setup

---

## Installation

### Linux

Open a terminal, navigate to the allmydox folder, and run:

```bash
bash setup.sh
```

This installs all Python dependencies (spaCy, PyQt6, pymupdf, python-docx) and
downloads the default German spaCy model (`de_core_news_sm`).

### Windows

Open a command prompt, navigate to the allmydox folder, and run:

```bat
setup.bat
```

For a different language during setup:

```bash
bash setup.sh en_core_web_sm    # Linux — English model
setup.bat en_core_web_sm        # Windows — English model
```

---

## Starting the GUI

### Linux

```bash
bash start.sh
```

### Windows

```bat
start.bat
```

Or double-click `start.bat` in Explorer.

---

## Using the GUI

### 1 — Select a source folder

Click **Browse…** next to *Source folder* and navigate to the folder that
contains your documents. Subfolders are scanned automatically. Supported
file types: **PDF**, **DOCX**, **TXT**.

### 2 — Select a target database

Click **Browse…** next to *Target database*.

- **Existing database**: select the `.db` file — new documents will be added
  and documents already in the database are skipped automatically.
- **New database**: type any path ending in `.db`
  (e.g. `C:\Users\you\mydocs.db`). The file is created on first use.

### 3 — Select a language model

#### Models folder

The *Models folder* field points to the directory where spaCy language models
are stored. The default is `~/.allmydox_models` (created automatically on
first download).

Click **Browse…** to choose a different location — useful if you want to keep
models on a shared drive or a specific disk.

#### Available models list

The list below the models folder shows all models that are ready to use:

- **[models folder]** — installed in the models folder you selected
- **[system]** — installed system-wide in the Python environment (shown in grey)

Click a model in the list to select it. The selected model is used when
indexing starts.

Click **Refresh** to re-scan after manually adding or removing models.

#### Downloading a new model

1. Select a model from the *Download model* dropdown.
2. Click **Download**.
3. The model is downloaded from GitHub and installed into the models folder.
   The list updates automatically when the download finishes.

Available models:

| Model | Language | Size |
|---|---|---|
| `de_core_news_sm` | German | small |
| `de_core_news_md` | German | medium |
| `de_core_news_lg` | German | large |
| `en_core_web_sm` | English | small |
| `en_core_web_md` | English | medium |
| `en_core_web_lg` | English | large |
| `fr_core_news_sm` | French | small |
| `fr_core_news_md` | French | medium |
| `es_core_news_sm` | Spanish | small |
| `it_core_news_sm` | Italian | small |
| `nl_core_news_sm` | Dutch | small |
| `pt_core_news_sm` | Portuguese | small |
| `pl_core_news_sm` | Polish | small |

*Small* models are faster and use less memory. *Medium* and *large* models
produce more accurate NLP results at the cost of speed.

### 4 — Start indexing

Click **Start indexing**. The progress bar and log show which document is
being processed. Each line reports one of:

| Status | Meaning |
|---|---|
| `ok  N page(s)` | document indexed successfully |
| `skipped (already indexed)` | document was already in the database |
| `ERROR: …` | file could not be read; processing continues |

Click **Stop** at any time to abort. Documents fully processed before Stop
was clicked remain in the database.

### 5 — Done

When the log shows *Finished. N new document(s) indexed.* the database is
ready. Open it with findethedox:

```bash
python3 /path/to/findethedox/main.py /path/to/your.db
```

The GUI saves your last-used paths and model selection and restores them on
the next launch.

---

## Adding more documents later

Start the GUI again, select the same (or a different) source folder, and
select the **same database file**. Documents already in the database are
detected by folder path + filename and skipped. Only new files are indexed.

---

## Command-line usage

The GUI is a front-end for `main.py`, which can also be used directly:

```bash
# Index a folder
python3 main.py --db /path/to/allmydox.db process /path/to/documents

# Show row counts
python3 main.py --db /path/to/allmydox.db stats

# Use a specific language model
python3 main.py --db allmydox.db process /docs --model de_core_news_sm
```

---

## Troubleshooting

**"No module named spacy" / "No module named PyQt6"**  
Run `setup.sh` (Linux) or `setup.bat` (Windows) again.

**Model list is empty**  
No models are installed yet. Use the *Download model* section in the GUI,
or run `bash setup.sh <model>` in a terminal.

**"Can't find model 'de_core_news_sm'"**  
The model is in the list but could not be loaded. Make sure the correct
*Models folder* is selected and click **Refresh**.

**A PDF shows 0 pages or an error**  
The PDF may be image-only (scanned without OCR). allmydox extracts text
only; scanned pages without a text layer are skipped.

**The database grows very large**  
Large document collections produce large co-occurrence tables. A collection
of ~6,000 documents produces a database of roughly 2–3 GB, which is normal.

**Stop was clicked but the window froze briefly**  
The worker thread is stopped; the brief freeze is Python waiting for the
current document to finish before exiting cleanly.
