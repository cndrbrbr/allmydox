import re
import sqlite3
from dataclasses import dataclass, field
from itertools import combinations
from typing import NamedTuple

import spacy

MAX_ENTITIES_PER_CONTEXT = 15

_nlp_cache: dict[str, spacy.language.Language] = {}

_noun_ids: dict[str, int] = {}
_name_ids: dict[str, int] = {}
_verb_ids: dict[str, int] = {}


def get_nlp(model: str) -> spacy.language.Language:
    if model not in _nlp_cache:
        _nlp_cache[model] = spacy.load(model)
    return _nlp_cache[model]


def prime_caches(conn: sqlite3.Connection):
    """Clear and reload all word→ID caches from the given DB connection."""
    _noun_ids.clear()
    _name_ids.clear()
    _verb_ids.clear()
    _noun_ids.update(conn.execute("SELECT noun, nounID FROM nouns").fetchall())
    _name_ids.update(conn.execute("SELECT name, nameID FROM names").fetchall())
    _verb_ids.update(conn.execute("SELECT verb, verbID FROM verbs").fetchall())


# ---------------------------------------------------------------------------
# Serialisable analysis result — safe to pass across process boundaries
# ---------------------------------------------------------------------------

@dataclass
class DocumentAnalysis:
    # (word/lemma, page_number, char_position)
    nouns: list[tuple[str, int, int]] = field(default_factory=list)
    names: list[tuple[str, int, int]] = field(default_factory=list)
    verbs: list[tuple[str, int, int]] = field(default_factory=list)
    # Co-occurrence pairs use local list indices:
    #   type 'noun' → index into nouns; type 'name' → index into names
    noun_sent_pairs: list[tuple[int, str, int, str]] = field(default_factory=list)
    noun_para_pairs: list[tuple[int, str, int, str]] = field(default_factory=list)
    # (entity_local_idx, entity_type, verb_local_idx)
    noun_verb_pairs: list[tuple[int, str, int]] = field(default_factory=list)
    num_pages: int = 0


# ---------------------------------------------------------------------------
# Pure NLP — no DB access, safe to run in a subprocess
# ---------------------------------------------------------------------------

def analyze_document(pages: list[tuple[int, str]], model: str) -> DocumentAnalysis:
    nlp = get_nlp(model)

    nouns: list[tuple[str, int, int]] = []
    names: list[tuple[str, int, int]] = []
    verbs: list[tuple[str, int, int]] = []
    noun_sent_pairs: list[tuple[int, str, int, str]] = []
    noun_para_pairs: list[tuple[int, str, int, str]] = []
    noun_verb_pairs: list[tuple[int, str, int]] = []

    for page_num, page_text in pages:
        for para_start, para_end in _paragraph_spans(page_text):
            para_text = page_text[para_start:para_end]
            if not para_text.strip():
                continue

            doc = nlp(para_text)
            para_entity_refs: list[tuple[int, str]] = []

            for sent in doc.sents:
                sent_entity_refs: list[tuple[int, str]] = []
                sent_verb_idxs:   list[int] = []

                for token in sent:
                    if not token.is_alpha:
                        continue
                    lemma = token.lemma_.lower().strip()
                    if not lemma:
                        continue

                    position = para_start + token.idx

                    if token.pos_ == "NOUN":
                        ref = (len(nouns), "noun")
                        nouns.append((lemma, page_num, position))
                        sent_entity_refs.append(ref)
                        para_entity_refs.append(ref)
                    elif token.pos_ == "PROPN":
                        ref = (len(names), "name")
                        names.append((token.text, page_num, position))
                        sent_entity_refs.append(ref)
                        para_entity_refs.append(ref)
                    elif token.pos_ == "VERB" and not token.is_stop:
                        sent_verb_idxs.append(len(verbs))
                        verbs.append((lemma, page_num, position))

                if len(sent_entity_refs) <= MAX_ENTITIES_PER_CONTEXT:
                    for a, b in combinations(sent_entity_refs, 2):
                        noun_sent_pairs.append((a[0], a[1], b[0], b[1]))
                    for e in sent_entity_refs:
                        for vi in sent_verb_idxs:
                            noun_verb_pairs.append((e[0], e[1], vi))

            if len(para_entity_refs) <= MAX_ENTITIES_PER_CONTEXT:
                for a, b in combinations(para_entity_refs, 2):
                    noun_para_pairs.append((a[0], a[1], b[0], b[1]))

    return DocumentAnalysis(
        nouns=nouns,
        names=names,
        verbs=verbs,
        noun_sent_pairs=noun_sent_pairs,
        noun_para_pairs=noun_para_pairs,
        noun_verb_pairs=noun_verb_pairs,
        num_pages=len(pages),
    )


# ---------------------------------------------------------------------------
# DB writes — runs in the main thread only
# ---------------------------------------------------------------------------

def write_analysis(conn: sqlite3.Connection, file_id: int, analysis: DocumentAnalysis):
    """Insert a DocumentAnalysis into the DB using the shared word→ID caches."""
    noun_occ_ids: list[int] = []
    for lemma, page_num, pos in analysis.nouns:
        nid = _noun_id(conn, lemma)
        cur = conn.execute(
            "INSERT INTO noun_occurrences (fileID,nounID,pagenumber,position) VALUES (?,?,?,?)",
            (file_id, nid, page_num, pos),
        )
        noun_occ_ids.append(cur.lastrowid)

    name_occ_ids: list[int] = []
    for text, page_num, pos in analysis.names:
        nid = _name_id(conn, text)
        cur = conn.execute(
            "INSERT INTO name_occurrences (fileID,nameID,pagenumber,position) VALUES (?,?,?,?)",
            (file_id, nid, page_num, pos),
        )
        name_occ_ids.append(cur.lastrowid)

    verb_occ_ids: list[int] = []
    for lemma, page_num, pos in analysis.verbs:
        vid = _verb_id(conn, lemma)
        cur = conn.execute(
            "INSERT INTO verb_occurrences (fileID,verbID,pagenumber,position) VALUES (?,?,?,?)",
            (file_id, vid, page_num, pos),
        )
        verb_occ_ids.append(cur.lastrowid)

    def _resolve(idx: int, typ: str) -> int:
        return noun_occ_ids[idx] if typ == "noun" else name_occ_ids[idx]

    conn.executemany(
        "INSERT INTO noun_sentence (occ1_type,occ1_id,occ2_type,occ2_id) VALUES (?,?,?,?)",
        [(t1, _resolve(i1, t1), t2, _resolve(i2, t2))
         for i1, t1, i2, t2 in analysis.noun_sent_pairs],
    )
    conn.executemany(
        "INSERT INTO noun_paragraph (occ1_type,occ1_id,occ2_type,occ2_id) VALUES (?,?,?,?)",
        [(t1, _resolve(i1, t1), t2, _resolve(i2, t2))
         for i1, t1, i2, t2 in analysis.noun_para_pairs],
    )
    conn.executemany(
        "INSERT INTO noun_verb_sentence (noun_occ_type,noun_occ_id,verb_occ_id) VALUES (?,?,?)",
        [(et, _resolve(ei, et), verb_occ_ids[vi])
         for ei, et, vi in analysis.noun_verb_pairs],
    )


# ---------------------------------------------------------------------------
# Top-level worker — picklable, used by ProcessPoolExecutor
# ---------------------------------------------------------------------------

def _analyze_file(path_str: str, model: str) -> DocumentAnalysis:
    """Extract text and run NLP analysis. Designed to run in a worker process."""
    import os, sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

    import extractor
    from pathlib import Path

    pages = extractor.extract(Path(path_str))
    return analyze_document(pages, model)


# ---------------------------------------------------------------------------
# Backward-compatible entry point (sequential, single-process)
# ---------------------------------------------------------------------------

def process_document(
    conn: sqlite3.Connection,
    file_id: int,
    pages: list[tuple[int, str]],
    model: str = "en_core_web_sm",
):
    analysis = analyze_document(pages, model)
    write_analysis(conn, file_id, analysis)


# ---------------------------------------------------------------------------
# Private helpers
# ---------------------------------------------------------------------------

class _OccRef(NamedTuple):
    type: str
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


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character offsets for each paragraph in text."""
    spans = []
    for m in re.finditer(r"[^\n].*?(?=\n\s*\n|\Z)", text, re.DOTALL):
        spans.append((m.start(), m.end()))
    return spans or [(0, len(text))]
