# Changelog

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
