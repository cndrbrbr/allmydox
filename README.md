# allmydox

Scans a folder of documents and indexes every noun, proper name, and verb into a SQLite database — including the page and character position of each occurrence and co-occurrence relationships at sentence and paragraph level.

Supported document formats: **PDF**, **DOCX**, **TXT**

---

## Requirements

- Python 3.9 or newer
- Internet access (first-time setup only, to download the language model)

---

## Setup

Run the setup script once before first use:

```bash
bash setup.sh
```

This installs the Python dependencies (`spacy`, `pymupdf`, `python-docx`) and downloads the default English language model (`en_core_web_sm`).

For a different language, pass the spaCy model name as an argument:

```bash
bash setup.sh de_core_news_sm    # German
bash setup.sh fr_core_news_sm    # French
```

A full list of available models is at <https://spacy.io/models>.

---

## Usage

### Index a folder

```bash
python3 main.py process <directory>
```

Recursively scans `<directory>` for PDF, DOCX, and TXT files and writes results to `allmydox.db` in the current folder. Documents already in the database are skipped automatically.

**Options**

| Option | Default | Description |
|--------|---------|-------------|
| `--db PATH` | `allmydox.db` | Path to the SQLite database file |
| `--ext EXT …` | `pdf docx txt` | File extensions to include |
| `--model MODEL` | `en_core_web_sm` | spaCy language model to use |

**Examples**

```bash
# Index all documents in ~/Documents
python3 main.py process ~/Documents

# Use a custom database path
python3 main.py --db ~/myindex.db process ~/Documents

# Index only PDFs
python3 main.py process ~/Documents --ext pdf

# Index with a German language model
python3 main.py process ~/Dokumente --model de_core_news_sm
```

### Show row counts

```bash
python3 main.py stats
python3 main.py --db ~/myindex.db stats
```

---

## Database schema

The database is a standard SQLite file and can be opened with any SQLite browser (e.g. [DB Browser for SQLite](https://sqlitebrowser.org/)).

### `documents`
One row per indexed file.

| Column | Type | Description |
|--------|------|-------------|
| `fileID` | INTEGER PK | Unique file identifier |
| `filename` | TEXT | File name including extension |
| `folderpath` | TEXT | Absolute path to the containing folder |
| `size` | INTEGER | File size in bytes |
| `extension` | TEXT | Lowercase extension, e.g. `.pdf` |

### `nouns` / `noun_occurrences`
Common nouns, lemmatised (e.g. *running* → *run*).

| Column | Type | Description |
|--------|------|-------------|
| `nounID` | INTEGER PK | |
| `noun` | TEXT UNIQUE | Lemma form |

| Column | Type | Description |
|--------|------|-------------|
| `nounOccurrenceID` | INTEGER PK | |
| `fileID` | INTEGER FK | Source document |
| `nounID` | INTEGER FK | |
| `pagenumber` | INTEGER | 1-indexed page number |
| `position` | INTEGER | Character offset within the page |

### `names` / `name_occurrences`
Proper nouns (people, places, organisations), original casing preserved.

Same structure as `nouns` / `noun_occurrences` with `nameID` / `nameOccurrenceID`.

### `verbs` / `verb_occurrences`
Verbs, lemmatised (e.g. *ran* → *run*).

Same structure as `nouns` / `noun_occurrences` with `verbID` / `verbOccurrenceID`.

### `noun_sentence`
Every pair of noun/name occurrences that appear in the **same sentence**.

| Column | Type | Description |
|--------|------|-------------|
| `nounsentenceID` | INTEGER PK | |
| `occ1_type` | TEXT | `noun` or `name` |
| `occ1_id` | INTEGER | Row in `noun_occurrences` or `name_occurrences` |
| `occ2_type` | TEXT | `noun` or `name` |
| `occ2_id` | INTEGER | Row in `noun_occurrences` or `name_occurrences` |

### `noun_paragraph`
Every pair of noun/name occurrences that appear in the **same paragraph**.
Same columns as `noun_sentence` with `nounparagraphID`.

### `noun_verb_sentence`
Every noun/name + verb triple that appears in the **same sentence**.

| Column | Type | Description |
|--------|------|-------------|
| `nounverbsentenceID` | INTEGER PK | |
| `noun_occ_type` | TEXT | `noun` or `name` |
| `noun_occ_id` | INTEGER | Row in `noun_occurrences` or `name_occurrences` |
| `verb_occ_id` | INTEGER FK | Row in `verb_occurrences` |

---

## Example queries

Open the database:

```bash
sqlite3 allmydox.db
```

**Which nouns appear most often across all documents?**

```sql
SELECT n.noun, COUNT(*) AS occurrences
FROM noun_occurrences o
JOIN nouns n USING (nounID)
GROUP BY n.nounID
ORDER BY occurrences DESC
LIMIT 20;
```

**Which names appear in a specific document?**

```sql
SELECT DISTINCT na.name
FROM name_occurrences o
JOIN documents d USING (fileID)
JOIN names na USING (nameID)
WHERE d.filename = 'report.pdf'
ORDER BY na.name;
```

**Which nouns and names share the most sentences?**

```sql
SELECT
    COALESCE(n.noun, na.name)     AS term1,
    COALESCE(n2.noun, na2n.name) AS term2,
    COUNT(*) AS shared_sentences
FROM noun_sentence s
LEFT JOIN noun_occurrences no1 ON s.occ1_type = 'noun' AND s.occ1_id = no1.nounOccurrenceID
LEFT JOIN nouns            n   ON no1.nounID = n.nounID
LEFT JOIN name_occurrences na1 ON s.occ1_type = 'name' AND s.occ1_id = na1.nameOccurrenceID
LEFT JOIN names            na  ON na1.nameID = na.nameID
LEFT JOIN noun_occurrences no2 ON s.occ2_type = 'noun' AND s.occ2_id = no2.nounOccurrenceID
LEFT JOIN nouns            n2  ON no2.nounID = n2.nounID
LEFT JOIN name_occurrences na2 ON s.occ2_type = 'name' AND s.occ2_id = na2.nameOccurrenceID
LEFT JOIN names            na2n ON na2.nameID = na2n.nameID
GROUP BY s.occ1_type, s.occ1_id, s.occ2_type, s.occ2_id
ORDER BY shared_sentences DESC
LIMIT 20;
```

**Which verbs are most associated with a given name?**

```sql
SELECT v.verb, COUNT(*) AS co_occurrences
FROM noun_verb_sentence nvs
JOIN name_occurrences no ON nvs.noun_occ_type = 'name'
                        AND nvs.noun_occ_id = no.nameOccurrenceID
JOIN names na  USING (nameID)
JOIN verb_occurrences vo ON nvs.verb_occ_id = vo.verbOccurrenceID
JOIN verbs v   USING (verbID)
WHERE na.name = 'Alice'
GROUP BY v.verbID
ORDER BY co_occurrences DESC;
```

---

## Notes

- **Page numbers** are 1-indexed. For TXT files the entire file counts as page 1. For DOCX files, explicit page breaks are detected where present; otherwise the whole file is page 1.
- **Position** is the character offset of the word within the page text, counting from 0.
- **Lemmatisation** is applied to nouns and verbs so that inflected forms are grouped under one entry. Names retain their original capitalisation.
- Re-running `process` on an already-indexed folder is safe — existing documents are detected by folder path + filename and skipped.
