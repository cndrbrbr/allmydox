# Changelog

## v1.6 — 2026-05-11  Parallel processing

Indexing now runs the slow NLP step on multiple CPU cores simultaneously,
significantly reducing wall-clock time for large document sets.

**Two-phase pipeline** (`processor.py`, `gui.py`)

The indexing loop is split into two distinct phases:

*Pass 1 — sequential:* the main thread checks every file against the database
by modification time, exactly as before. Unchanged files are skipped; new or
changed files are queued.

*Pass 2 — parallel:* queued files are submitted to a `ProcessPoolExecutor`.
Each worker process runs `extractor.extract()` followed by the spaCy NLP pass
and returns a serialisable `DocumentAnalysis` dataclass containing lists of
token tuples with local indices. The main thread collects results as they
complete and writes them to SQLite one file at a time, preserving the
single-writer guarantee.

**New internals** (`processor.py`)
- `DocumentAnalysis` — picklable dataclass holding occurrences and
  co-occurrence pairs as plain lists of tuples (no database IDs)
- `analyze_document(pages, model)` — pure NLP, zero DB access, safe in a
  subprocess
- `write_analysis(conn, file_id, analysis)` — resolves local indices to DB
  row IDs and performs all inserts; runs in the main thread only
- `_analyze_file(path_str, model)` — module-level picklable worker that calls
  `extract()` + `analyze_document()`; designed for `ProcessPoolExecutor`
- `process_document()` kept as a thin backward-compatible wrapper

**Configurable worker count** (`gui.py`)  
A new radio-button row in the Options section lets users choose between
**Auto** (= `min(CPU cores, 4)`), **1**, **2**, or **4** workers. The
selection is saved in `~/.allmydox_gui.json` and restored on next launch.

**RAM guidance** (`README.md`)  
New *Architecture* section documents the pipeline with a Mermaid flowchart and
a RAM-per-worker table for small / medium / large spaCy models.

## v1.7 — 2026-05-11  Large-file sequential threshold

Large scanned PDFs can load hundreds of megabytes of image data into RAM via
PyMuPDF. Sending several such files simultaneously to the parallel pool risks
triggering the OS out-of-memory killer, crashing a worker and turning all
pending futures into errors.

**New GUI option** (`gui.py`): *Sequential threshold* spinbox (10–500 MB,
step 10, default 50 MB). Files at or above the threshold are routed to a
dedicated sequential pass (Pass 3) and never enter the parallel pool. Each
large file runs in its own fresh `ProcessPoolExecutor(max_workers=1)` with a
300-second timeout; a crash on one file cannot affect any other file, and the
main process is protected throughout. Log lines for large files include the
file size and note `(sequential)`.

**Four-pass pipeline** (`gui.py`)  
The indexing loop now has four numbered passes:
1. Scan / skip / categorise into parallel or sequential queue
2. Parallel NLP for files below the threshold
3. Sequential isolated NLP for files at or above the threshold
4. Isolated retry for any files whose Pass 2 worker crashed

**Documentation**  
User manual updated with Sequential threshold description, extended log status
table, and a new *How indexing works* section explaining all four passes.

---

## v1.6.2 — 2026-05-11  Bugfix: graceful recovery from worker process crashes

### Problem
If a worker process was killed during Pass 2 (e.g. by the OS OOM killer while
loading a large PDF), `ProcessPoolExecutor` marked the entire pool as broken.
Every file still waiting in the pool also raised `BrokenExecutor`, even though
those files were not at fault. This caused all remaining files in the batch to
be reported as errors.

### Fix (`gui.py`)
`BrokenExecutor` is now caught separately in the parallel loop. Files that
received this error are collected into a retry list rather than counted as
permanent failures. After the parallel pass, each collected file is retried
individually in its own fresh `ProcessPoolExecutor(max_workers=1)` (Pass 4),
so a crash on one file cannot cascade to others.

---

## v1.6.1 — 2026-05-11  Bugfix: stale word-ID caches when switching databases

### Problem
If two indexing runs were performed in the same GUI session against
**different database files**, the word→ID caches (`_noun_ids`, `_name_ids`,
`_verb_ids`) retained entries from the first database. When the second run
began, `prime_caches()` added the new database's vocabulary on top of the
old entries without clearing them first. Any word that had been assigned an
ID in the first database but did not yet exist in the second would be looked
up from the stale cache and its old ID used directly — pointing to a row that
did not exist in the second database — causing a `FOREIGN KEY constraint
failed` error in `noun_occurrences`, `name_occurrences`, or
`verb_occurrences`.

### Fix (`processor.py`)
`prime_caches()` now calls `.clear()` on all three dicts before reloading
from the connection, so IDs from a previous database can never bleed into a
new session.

### Test (`_test_parallel.py`)
New end-to-end test suite covering: `analyze_document()`, `write_analysis()`
FK integrity, `_analyze_file()` worker function, `ProcessPoolExecutor` with
2 workers / 6 files, idempotency (mtime-based skip), and rollback isolation
on a corrupt file.

---

## v1.5 — 2026-05-08  HTML/HTM support

Added support for `.html` and `.htm` files. Only the visible text content
is extracted — tags, scripts, styles, and head sections are discarded.

**HTML extraction** (`extractor.py`)  
Uses Python's built-in `html.parser` (no new dependency). A small
`_TextExtractor` subclass skips content inside `<script>`, `<style>`,
`<head>`, `<noscript>`, and `<template>` elements; all other character
data is collected, blank lines stripped, and returned as a single page.

Default extension list updated in `gui.py` and `main.py`:
`pdf doc docx xls xlsx txt html htm`.

---

## v1.4 — 2026-05-02  Additional file formats: DOC, XLS, XLSX

Support for six file formats, up from three:

| Format | Library | Notes |
|---|---|---|
| `.pdf` | pymupdf | unchanged |
| `.docx` | python-docx | unchanged |
| `.doc` | LibreOffice (subprocess) | requires LibreOffice to be installed |
| `.xlsx` | openpyxl | each sheet = one page |
| `.xls` | xlrd | each sheet = one page |
| `.txt` | built-in | unchanged |

**DOC extraction** (`extractor.py`)  
LibreOffice is invoked headlessly (`--convert-to txt:Text`) to convert the
binary .doc file to plain text in a temporary directory. `_find_soffice()`
locates the executable on both Linux (`libreoffice`/`soffice` in PATH) and
Windows (common Program Files locations). If LibreOffice is not installed
the file is skipped with an informative error message.

**XLSX extraction** (`extractor.py`)  
`openpyxl` reads the workbook in read-only / data-only mode. Each worksheet
becomes one page; rows are joined with two-space separators.

**XLS extraction** (`extractor.py`)  
`xlrd` 2.x reads the legacy binary Excel format. Same per-sheet paging as
XLSX.

New dependencies added to `requirements.txt`, `setup.sh`, `setup.bat`:
`openpyxl>=3.1.0`, `xlrd>=2.0.0`.

Default extension list updated in `gui.py` and `main.py`:
`pdf doc docx xls xlsx txt`.

---

## v1.3 — 2026-05-02  Bugfix: folder-installed language models not found

### Problem
When a language model was downloaded via the GUI into the models folder,
indexing failed with "Can't find model" despite the model appearing in the
list.

### Root causes

**Wrong model name from meta.json** (`gui.py`)  
`_folder_models()` read the `name` field from `meta.json`, which contains
only the short name without the language prefix (e.g. `core_news_lg` instead
of `de_core_news_lg`). spaCy could not find a model under the short name.  
Fix: use the package directory name (`d.name`) which always matches the full
model name.

**Fragile `sys.path` manipulation** (`gui.py`)  
Adding the models folder to `sys.path` is unreliable for `pip --target`
installations because spaCy's import machinery may not resolve the package
correctly at runtime.  
Fix: new helper `_model_data_path()` locates the versioned model data
subdirectory (e.g. `de_core_news_lg/de_core_news_lg-3.8.0/`) and passes
it as a direct filesystem path to `spacy.load()`, which accepts both model
names and explicit paths.

---

## v1.2 — 2026-05-02  GUI, model management, and mtime change detection

### GUI front-end (`gui.py`)
New PyQt6 window replaces the command-line-only workflow:
- **Source folder** and **target database** pickers with Browse buttons
- **Models folder**: configurable directory for spaCy models
  (default `~/.allmydox_models`)
- **Model list**: shows all models in the models folder and system-installed
  models; click to select the model for the current indexing run
- **Download**: installs any of 13 known spaCy models directly from GitHub
  into the models folder via `pip --target` — no system Python changes
- **Progress bar** and live **log** for each document
- Settings (paths, last model) persisted to `~/.allmydox_gui.json`
- **Re-index changed files** checkbox (default: on)

### mtime-based change detection (`db.py`, `gui.py`, `main.py`)
Documents are now tracked by modification time:
- `documents` table gains a `mtime REAL` column; existing databases are
  migrated automatically on open (`ALTER TABLE … ADD COLUMN`)
- New `get_document_info()` returns `(fileID, mtime)` for each known file
- New `delete_document()` cascades through all derived tables
  (co-occurrences → occurrences → document row) before re-indexing
- Per-file logic on each scan:
  - mtime unchanged → skipped
  - file not yet in DB → indexed
  - mtime changed + re-index on → old data deleted, file re-indexed
  - mtime changed + re-index off → skipped
- Summary now reports new and updated counts separately

### Setup and start scripts
- `setup.sh` / `setup.bat`: now also install PyQt6; default model changed
  to `de_core_news_sm`
- `start.sh` / `start.bat`: one-click launcher for the GUI

### User manual (`usermanual.md`)
Full step-by-step guide covering installation, GUI usage, model management,
adding documents later, CLI usage, and troubleshooting.

---

## v1.1 — 2026-05-01  Performance & stability

### Problem
Processing 6,137 documents with the initial code produced a database of
~28 GB (projected) because the co-occurrence tables grow O(n²) with the
number of entities per paragraph. Dense legal paragraphs with 50+ nouns
and names generated thousands of pairs each.

### Changes

**Entity cap for co-occurrence tables** (`processor.py`)  
Added `MAX_ENTITIES_PER_CONTEXT = 15`. Sentences and paragraphs with more
than 15 nouns/names are skipped when building `noun_sentence`,
`noun_paragraph`, and `noun_verb_sentence`. Short, focused contexts — where
co-occurrence is actually meaningful — are still fully recorded.  
Result: 6,097 documents → 2.6 GB instead of a projected ~28 GB.

**In-memory word caches** (`processor.py`)  
Module-level dicts `_noun_ids`, `_name_ids`, `_verb_ids` map each word to
its database ID. On a cache miss the word is written to the DB once; every
subsequent occurrence is a plain dict lookup. `prime_caches()` pre-loads
all existing vocabulary at startup so re-runs are fast from the first file.

**Batch co-occurrence inserts** (`processor.py`)  
Pairs for `noun_sentence`, `noun_paragraph`, and `noun_verb_sentence` are
accumulated in lists per document and flushed with a single `executemany()`
call, replacing one `INSERT` per pair.

**Progress counter** (`main.py`)  
Output now shows `[  42/6137]` in front of each filename.

---

## v1.0 — 2026-05-01  Initial release

### Original feature specification

> Write a Python software to extract information about documents to a SQLite
> database:
> 1. List all documents in one table and create an ID
>    (fileID, filename, folderpath, size, extension)
> 2. List all nouns that appear in the documents in one table and give it an ID
>    (nounID, noun)
> 3. List all occurrences of the nouns in another table
>    (nounOccurrenceID, fileID, nounID, pagenumber, position)
> 4. List all names that appear in the documents in one table and give it an ID
>    (nameID, name)
> 5. List all occurrences of the names in another table
>    (nameOccurrenceID, fileID, nameID, pagenumber, position)
> 6. List all verbs that appear in the documents in one table and give it an ID
>    (verbID, verb)
> 7. List all occurrences of the verbs in another table
>    (verbOccurrenceID, fileID, verbID, pagenumber, position)
> 8. List all nouns and names that occur in the same sentence together
>    (nounsentenceID, nounOccurrenceID, nounOccurrenceID)
> 9. List all nouns and names that occur in the same paragraph together
>    (nounparagraphID, nounOccurrenceID, nounOccurrenceID)
> 10. List all nouns and names that occur in the same sentence with one verb
>     (nounverbsentenceID, nounOccurrenceID, verbOccurrenceID)

### Implementation

**Supported formats:** PDF (via pymupdf), DOCX (via python-docx), TXT

**NLP:** spaCy POS tagging
- `NOUN` tokens → `nouns` table, lemmatised
- `PROPN` tokens → `names` table, original casing preserved
- `VERB` tokens → `verbs` table, lemmatised; stop-word verbs excluded

**Position:** character offset of each token within its page text (0-based)

**Page numbering:** 1-indexed; TXT files = single page 1; DOCX page breaks
detected where present

**Co-occurrence design:** `noun_sentence` and `noun_paragraph` cover
noun–noun, noun–name, and name–name pairs using an `occ_type` discriminator
column (`'noun'` or `'name'`) rather than separate tables

**Idempotency:** documents are skipped if already present by
folderpath + filename

**CLI:** `python3 main.py process <dir>` and `python3 main.py stats`

**Setup script:** `setup.sh` bootstraps pip if absent, installs all
dependencies, and downloads the spaCy model; supports alternate language
models via first argument (e.g. `bash setup.sh de_core_news_sm`)
