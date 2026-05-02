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

This installs all dependencies and the default German spaCy model
(`de_core_news_sm`). For a different language:

```bash
bash setup.sh en_core_web_sm    # English
bash setup.sh fr_core_news_sm   # French
bash setup.sh es_core_news_sm   # Spanish
```

### Windows

Open a command prompt, navigate to the allmydox folder, and run:

```bat
setup.bat
```

For a different language:

```bat
setup.bat en_core_web_sm
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

![allmydox GUI](screenshot_gui.png)

### 1 — Select a source folder

Click **Browse…** next to *Source folder* and navigate to the folder that
contains your documents. Subfolders are included automatically. Supported
file types: **PDF**, **DOCX**, **TXT**.

You can also type the path directly into the text field.

### 2 — Select a target database

Click **Browse…** next to *Target database*.

- **Existing database**: select the `.db` file — new documents will be
  added; documents already in the database are skipped automatically.
- **New database**: type any path ending in `.db` (e.g.
  `C:\Users\you\mydocs.db`). The file is created on first use.

### 3 — Select the language model

Choose the spaCy model that matches the language of your documents from
the dropdown. You can also type any installed model name directly.

| Model | Language |
|---|---|
| `de_core_news_sm` | German |
| `en_core_web_sm` | English |
| `fr_core_news_sm` | French |
| `es_core_news_sm` | Spanish |
| `it_core_news_sm` | Italian |

To install an additional model run `setup.sh <model>` (Linux) or
`setup.bat <model>` (Windows) again.

### 4 — Start indexing

Click **Start indexing**. The progress bar and log show which document is
being processed. Each line reports one of:

| Status | Meaning |
|---|---|
| `… ✓  N page(s)` | document indexed successfully |
| `skipped (already indexed)` | document was already in the database |
| `ERROR: …` | file could not be read; processing continues with the next file |

Click **Stop** at any time to abort. Documents that were fully processed
before Stop was clicked remain in the database.

### 5 — Done

When the log shows *Finished. N new document(s) indexed.* the database is
ready. Open it with findethedox:

```bash
python3 /path/to/findethedox/main.py /path/to/your.db
```

---

## Adding more documents later

Simply start the GUI again, select the same (or a different) folder, and
select the **same database file**. Documents that are already in the
database are detected by folder path + filename and skipped. Only new
files are indexed.

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

**"Can't find model 'de_core_news_sm'"**  
The spaCy model was not installed. Run `bash setup.sh de_core_news_sm`.

**A PDF shows 0 pages or an error**  
The PDF may be image-only (scanned without OCR). allmydox extracts text
only; scanned pages without a text layer are skipped.

**The database grows very large**  
Large document collections produce large co-occurrence tables. A collection
of ~6,000 documents produces a database of roughly 2–3 GB, which is normal.

**Stop was clicked but the window froze briefly**  
The worker thread is stopped; the brief freeze is Python waiting for the
thread to finish its current document before exiting cleanly.
