# Changelog

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
