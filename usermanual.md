# allmydox — User Manual

allmydox scans folders of documents (PDF, DOC, DOCX, XLS, XLSX, TXT, HTML, HTM),
extracts nouns, names, and verbs using NLP, and stores everything — including
sentence and paragraph co-occurrence relationships — into a SQLite database.
The database can then be explored visually with
[findethedox](https://github.com/cndrbrbr/findethedox).

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

This installs all Python dependencies (spaCy, PyQt6, pymupdf, python-docx,
openpyxl, xlrd) and downloads the default German spaCy model (`de_core_news_sm`).

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
file types: **PDF**, **DOC**, **DOCX**, **XLS**, **XLSX**, **TXT**, **HTML**, **HTM**.

> **Note on DOC files:** `.doc` files require [LibreOffice](https://www.libreoffice.org)
> to be installed. If LibreOffice is not found, the file is skipped with an
> error message in the log.
>
> **Note on HTML files:** only the visible text is extracted — tags, scripts,
> and stylesheets are ignored.

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

### 4 — Options

Three options appear below the model list:

**Re-index changed files** (checkbox, on by default)  
When ticked, a file that is already in the database is re-indexed if its
modification time has changed since the last run. Untick this if you want
to index only brand-new files and leave existing entries untouched even when
the source files have changed.

**Parallel workers** (radio buttons: Auto / 1 / 2 / 4)  
Controls how many CPU cores are used for the slow NLP step. Each worker
process analyses a different document simultaneously; the database is still
written one file at a time in the background.

- **Auto** — uses up to 4 workers, limited by the number of available CPU
  cores. Best choice for most systems with small or medium models.
- **1** — sequential processing, lowest memory use. Recommended when RAM
  is limited or when using a large model on a modest machine.
- **2 / 4** — fixed worker count. Choose based on your available RAM:

  | Model size | RAM per worker | 2 workers | 4 workers |
  |---|---|---|---|
  | small (`*_sm`) | ~100 MB | ~350 MB | ~550 MB |
  | medium (`*_md`) | ~300 MB | ~750 MB | ~1.4 GB |
  | large (`*_lg`) | ~800 MB | ~1.75 GB | ~3.4 GB |

  Figures include the main process (~150 MB). If your machine has less free
  RAM than shown, choose fewer workers or use a smaller model.

**Sequential threshold** (spinbox, default 50 MB)  
Files at or above this size are never sent to the parallel pool. Instead they
are processed one at a time in their own isolated worker process. This
prevents large scanned PDFs (which can load hundreds of megabytes of image
data into RAM) from crashing a worker and disrupting the rest of the batch.

- Lower the threshold (e.g. 20 MB) if your machine has limited RAM or you
  often see out-of-memory errors.
- Raise it (e.g. 200 MB) if your large files are mostly text-based and you
  want them to benefit from the parallel pool.

All three settings are saved and restored on the next launch.

### 5 — Start indexing

Click **Start indexing**. The progress bar and log show which documents are
being processed. Because multiple workers run in parallel, log lines may
appear out of numerical order — this is normal. Each line reports one of:

| Status | Meaning |
|---|---|
| `ok  N page(s)  [new]` | document indexed for the first time |
| `ok  N page(s)  [changed, re-indexed]` | document updated since last run |
| `ok  N page(s)  [new]  (X MB, sequential)` | large file, processed outside the parallel pool |
| `ok  N page(s)  [new]  [retried]` | processed successfully after its first worker crashed |
| `skipped (unchanged)` | modification time matches the database — skipped |
| `skipped (already indexed)` | already in the database; re-index option is off |
| `— worker crashed, will retry …` | worker killed (e.g. OOM); file queued for isolated retry |
| `ERROR: …` | file could not be read or processed; indexing continues with other files |

Click **Stop** at any time to abort. Documents whose analysis was already
complete before Stop was clicked remain in the database.

### 6 — Done

When the log shows *Finished. N new, M updated.* the database is ready.
Open it with findethedox:

```bash
python3 /path/to/findethedox/main.py /path/to/your.db
```

The GUI saves your last-used paths, model selection, worker count, and
sequential threshold and restores them on the next launch.

---

## Adding more documents later

Start the GUI (or keep it open), select the same (or a different) source
folder, and select the **same database file**. Documents already in the
database are detected by folder path + filename and skipped. Only new files
are indexed.

You can also switch to a **different database** in the same session without
restarting — just change the target database path and click Start indexing
again. The vocabulary caches are reset automatically for each run.

---

## How indexing works

When you click **Start indexing**, allmydox runs four passes:

**Pass 1 — Scan** *(fast, sequential)*  
Every file is checked against the database by modification time. Unchanged
files are skipped immediately. New or changed files are sorted into two
queues: files *smaller* than the sequential threshold go to the parallel
queue; files *at or above* the threshold go to the sequential queue.

**Pass 2 — Parallel NLP** *(concurrent)*  
Small files are distributed across the configured number of worker processes.
Each worker independently extracts text from its file and runs the spaCy NLP
analysis, returning a result object. As workers finish, the main thread
receives results and writes them to the database one file at a time. Because
multiple workers run at once, log entries appear out of order — this is normal.

**Pass 3 — Sequential NLP for large files** *(isolated, one at a time)*  
Large files are processed here, each in its own fresh worker process with a
5-minute timeout. Isolating each file means that if a large PDF crashes the
worker (for example by exhausting available RAM), only that one file is logged
as an error and the next file continues unaffected.

**Pass 4 — Retry** *(isolated, one at a time)*  
If a worker in Pass 2 was killed mid-run (e.g. by the OS out-of-memory
killer), all files that were waiting in that pool also received an error
through no fault of their own. Pass 4 retries those files, again one at a
time in isolated fresh workers, so innocent files get a second chance.

The database is always written by the main thread, one file at a time, so
there is no risk of data corruption even if worker processes crash.

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

**"FOREIGN KEY constraint failed" errors in the log**  
This could happen in v1.6 when indexing a second database in the same GUI
session — the vocabulary caches retained IDs from the first database. Fixed
in v1.6.1: the caches are now cleared at the start of every indexing run.
If you see this error on a current version, try clicking Start indexing again;
if it persists, please report it as a bug.

**Processing seems slower with more workers / system becomes unresponsive**  
Each worker loads its own copy of the spaCy model into RAM. With a large
model and 4 workers this can require 3–4 GB of free RAM. If the system
starts swapping to disk, reduce the worker count to 1 or 2, or switch to a
smaller model.

**Many files show "worker crashed, will retry …" in the log**  
A worker process was killed by the operating system, most likely because a
large scanned PDF loaded too much image data into RAM (OOM). The files marked
"will retry" are innocent bystanders — they will be retried automatically in
Pass 4. The file that actually caused the crash will either succeed in the
retry or be logged as an error.

To prevent this in future runs, lower the *Sequential threshold* so that
large PDFs bypass the parallel pool entirely and are processed one at a time
in Pass 3.

**Stop was clicked but the window froze briefly**  
The worker processes are stopped after completing their current file; the
brief freeze is Python waiting for them to exit cleanly before the GUI
returns to idle.
