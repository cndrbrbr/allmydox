import re
import sqlite3
from itertools import combinations
from typing import NamedTuple

import spacy

# Sentences or paragraphs with more entities than this produce no co-occurrence pairs.
# Keeps the DB from exploding on dense legal/technical paragraphs.
MAX_ENTITIES_PER_CONTEXT = 15

_nlp_cache: dict[str, spacy.language.Language] = {}

# Module-level word→ID caches; survive across documents within one run.
_noun_ids: dict[str, int] = {}
_name_ids: dict[str, int] = {}
_verb_ids: dict[str, int] = {}


def get_nlp(model: str) -> spacy.language.Language:
    if model not in _nlp_cache:
        _nlp_cache[model] = spacy.load(model)
    return _nlp_cache[model]


def prime_caches(conn: sqlite3.Connection):
    """Load all existing vocabulary into the in-memory caches."""
    _noun_ids.update(conn.execute("SELECT noun, nounID FROM nouns").fetchall())
    _name_ids.update(conn.execute("SELECT name, nameID FROM names").fetchall())
    _verb_ids.update(conn.execute("SELECT verb, verbID FROM verbs").fetchall())


class _OccRef(NamedTuple):
    type: str   # 'noun', 'name', or 'verb'
    id: int


def _noun_id(conn, word: str) -> int:
    if word not in _noun_ids:
        conn.execute("INSERT OR IGNORE INTO nouns (noun) VALUES (?)", (word,))
        _noun_ids[word] = conn.execute(
            "SELECT nounID FROM nouns WHERE noun = ?", (word,)
        ).fetchone()[0]
    return _noun_ids[word]


def _name_id(conn, word: str) -> int:
    if word not in _name_ids:
        conn.execute("INSERT OR IGNORE INTO names (name) VALUES (?)", (word,))
        _name_ids[word] = conn.execute(
            "SELECT nameID FROM names WHERE name = ?", (word,)
        ).fetchone()[0]
    return _name_ids[word]


def _verb_id(conn, word: str) -> int:
    if word not in _verb_ids:
        conn.execute("INSERT OR IGNORE INTO verbs (verb) VALUES (?)", (word,))
        _verb_ids[word] = conn.execute(
            "SELECT verbID FROM verbs WHERE verb = ?", (word,)
        ).fetchone()[0]
    return _verb_ids[word]


def process_document(
    conn: sqlite3.Connection,
    file_id: int,
    pages: list[tuple[int, str]],
    model: str = "en_core_web_sm",
):
    nlp = get_nlp(model)

    noun_sent_batch:  list[tuple] = []
    noun_para_batch:  list[tuple] = []
    noun_verb_batch:  list[tuple] = []

    for page_num, page_text in pages:
        para_spans = _paragraph_spans(page_text)

        for para_start, para_end in para_spans:
            para_text = page_text[para_start:para_end]
            if not para_text.strip():
                continue

            doc = nlp(para_text)
            para_entity_occs: list[_OccRef] = []

            for sent in doc.sents:
                sent_entity_occs: list[_OccRef] = []
                sent_verb_occs:   list[_OccRef] = []

                for token in sent:
                    if not token.is_alpha:
                        continue
                    lemma = token.lemma_.lower().strip()
                    if not lemma:
                        continue

                    position = para_start + token.idx

                    if token.pos_ == "NOUN":
                        nid = _noun_id(conn, lemma)
                        cur = conn.execute(
                            "INSERT INTO noun_occurrences "
                            "(fileID, nounID, pagenumber, position) VALUES (?,?,?,?)",
                            (file_id, nid, page_num, position),
                        )
                        ref = _OccRef("noun", cur.lastrowid)
                        sent_entity_occs.append(ref)
                        para_entity_occs.append(ref)

                    elif token.pos_ == "PROPN":
                        nid = _name_id(conn, token.text)
                        cur = conn.execute(
                            "INSERT INTO name_occurrences "
                            "(fileID, nameID, pagenumber, position) VALUES (?,?,?,?)",
                            (file_id, nid, page_num, position),
                        )
                        ref = _OccRef("name", cur.lastrowid)
                        sent_entity_occs.append(ref)
                        para_entity_occs.append(ref)

                    elif token.pos_ == "VERB" and not token.is_stop:
                        vid = _verb_id(conn, lemma)
                        cur = conn.execute(
                            "INSERT INTO verb_occurrences "
                            "(fileID, verbID, pagenumber, position) VALUES (?,?,?,?)",
                            (file_id, vid, page_num, position),
                        )
                        sent_verb_occs.append(_OccRef("verb", cur.lastrowid))

                if len(sent_entity_occs) <= MAX_ENTITIES_PER_CONTEXT:
                    for a, b in combinations(sent_entity_occs, 2):
                        noun_sent_batch.append((a.type, a.id, b.type, b.id))
                    for e in sent_entity_occs:
                        for v in sent_verb_occs:
                            noun_verb_batch.append((e.type, e.id, v.id))

            if len(para_entity_occs) <= MAX_ENTITIES_PER_CONTEXT:
                for a, b in combinations(para_entity_occs, 2):
                    noun_para_batch.append((a.type, a.id, b.type, b.id))

    conn.executemany(
        "INSERT INTO noun_sentence (occ1_type,occ1_id,occ2_type,occ2_id) VALUES (?,?,?,?)",
        noun_sent_batch,
    )
    conn.executemany(
        "INSERT INTO noun_paragraph (occ1_type,occ1_id,occ2_type,occ2_id) VALUES (?,?,?,?)",
        noun_para_batch,
    )
    conn.executemany(
        "INSERT INTO noun_verb_sentence (noun_occ_type,noun_occ_id,verb_occ_id) VALUES (?,?,?)",
        noun_verb_batch,
    )


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character offsets for each paragraph in text."""
    spans = []
    for m in re.finditer(r"[^\n].*?(?=\n\s*\n|\Z)", text, re.DOTALL):
        spans.append((m.start(), m.end()))
    return spans or [(0, len(text))]
