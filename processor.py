import re
import sqlite3
from dataclasses import dataclass, field
from itertools import combinations
from typing import NamedTuple, Optional

import spacy

MAX_ENTITIES_PER_CONTEXT = 15

# Codes: runs of letters/digits joined by . _ : / - + (or , between digits)
# that contain a digit,
# e.g. 0600997, M393, ERR-0042, 2024-08-23, 10:15:02, 192.168.0.1, 1.234,56
_CODE_RE = re.compile(r"[^\W_]+(?:(?:[._:/\-+]|(?<=\d),(?=\d))[^\W_]+)*")
_CODE_MAX_LEN = 64

# Longer paragraphs (e.g. spreadsheet sheets without blank lines) are split
# at line breaks; spaCy refuses texts over nlp.max_length (1,000,000 chars)
_MAX_CHUNK = 100_000

# Documents with more text are analysed in sections of this size, each in its
# own worker and written to the DB one by one, so memory stays bounded
_SECTION_CHARS = 1_000_000

# (page_number, text, char offset of text within the page)
Section = list[tuple[int, str, int]]

_nlp_cache: dict[str, spacy.language.Language] = {}

_noun_ids: dict[str, int] = {}
_name_ids: dict[str, int] = {}
_verb_ids: dict[str, int] = {}
_code_ids: dict[str, int] = {}


def get_nlp(model: str) -> spacy.language.Language:
    if model not in _nlp_cache:
        _nlp_cache[model] = spacy.load(model)
    return _nlp_cache[model]


def prime_caches(conn: sqlite3.Connection):
    """Clear and reload all word→ID caches from the given DB connection."""
    _noun_ids.clear()
    _name_ids.clear()
    _verb_ids.clear()
    _code_ids.clear()
    _noun_ids.update(conn.execute("SELECT noun, nounID FROM nouns").fetchall())
    _name_ids.update(conn.execute("SELECT name, nameID FROM names").fetchall())
    _verb_ids.update(conn.execute("SELECT verb, verbID FROM verbs").fetchall())
    _code_ids.update(conn.execute("SELECT code, codeID FROM codes").fetchall())


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
    # (code text, page_number, char_position)
    codes: list[tuple[str, int, int]] = field(default_factory=list)
    # (code_local_idx, other_local_idx, other_type) — type 'noun'/'name'/'code'
    code_sent_pairs: list[tuple[int, int, str]] = field(default_factory=list)
    code_para_pairs: list[tuple[int, int, str]] = field(default_factory=list)
    num_pages: int = 0


@dataclass
class LargeDocument:
    """Returned by _analyze_file() for texts over _SECTION_CHARS: the text split
    into sections, to be analysed with analyze_sections() and written per section."""
    sections: list[Section]
    num_pages: int
    num_chars: int


# ---------------------------------------------------------------------------
# Pure NLP — no DB access, safe to run in a subprocess
# ---------------------------------------------------------------------------

def analyze_document(pages: list[tuple[int, str]], model: str) -> DocumentAnalysis:
    analysis = analyze_section([(page_num, text, 0) for page_num, text in pages], model)
    analysis.num_pages = len(pages)
    return analysis


def analyze_section(section: Section, model: str) -> DocumentAnalysis:
    nlp = get_nlp(model)

    nouns: list[tuple[str, int, int]] = []
    names: list[tuple[str, int, int]] = []
    verbs: list[tuple[str, int, int]] = []
    noun_sent_pairs: list[tuple[int, str, int, str]] = []
    noun_para_pairs: list[tuple[int, str, int, str]] = []
    noun_verb_pairs: list[tuple[int, str, int]] = []
    codes: list[tuple[str, int, int]] = []
    code_sent_pairs: list[tuple[int, int, str]] = []
    code_para_pairs: list[tuple[int, int, str]] = []

    for page_num, page_text, offset in section:
        for para_start, para_end in _chunk_spans(page_text, _paragraph_spans(page_text)):
            para_text = page_text[para_start:para_end]
            para_pos  = offset + para_start
            if not para_text.strip():
                continue

            doc = nlp(para_text)
            para_entity_refs: list[tuple[int, str]] = []
            para_code_idxs:   list[int] = []

            for sent in doc.sents:
                sent_entity_refs: list[tuple[int, str]] = []
                sent_verb_idxs:   list[int] = []
                sent_code_idxs:   list[int] = []

                # Codes are found by regex on the sentence text, so that
                # 2024-08-23 or 10.0.0.1 stay one code however spaCy splits them
                code_spans: list[tuple[int, int]] = []
                for m in _CODE_RE.finditer(sent.text):
                    code = m.group()
                    if (len(code) >= 2 and len(code) <= _CODE_MAX_LEN
                            and any(ch.isdigit() for ch in code)):
                        code_spans.append((sent.start_char + m.start(),
                                           sent.start_char + m.end()))
                        sent_code_idxs.append(len(codes))
                        codes.append((code, page_num,
                                      para_pos + sent.start_char + m.start()))

                for token in sent:
                    if not token.is_alpha:
                        continue
                    lemma = token.lemma_.lower().strip()
                    if not lemma:
                        continue

                    position = para_pos + token.idx

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
                    elif _is_abbreviation(token.text) and not any(
                            a <= token.idx < b for a, b in code_spans):
                        # Upper-case abbreviation that is no noun/name/verb (e.g. ERR, OK)
                        sent_code_idxs.append(len(codes))
                        codes.append((token.text, page_num, position))

                if len(sent_entity_refs) <= MAX_ENTITIES_PER_CONTEXT:
                    for a, b in combinations(sent_entity_refs, 2):
                        noun_sent_pairs.append((a[0], a[1], b[0], b[1]))
                    for e in sent_entity_refs:
                        for vi in sent_verb_idxs:
                            noun_verb_pairs.append((e[0], e[1], vi))

                if len(sent_entity_refs) + len(sent_code_idxs) <= MAX_ENTITIES_PER_CONTEXT:
                    code_sent_pairs.extend(_code_pairs(sent_code_idxs, sent_entity_refs))
                para_code_idxs.extend(sent_code_idxs)

            if len(para_entity_refs) <= MAX_ENTITIES_PER_CONTEXT:
                for a, b in combinations(para_entity_refs, 2):
                    noun_para_pairs.append((a[0], a[1], b[0], b[1]))
            if len(para_entity_refs) + len(para_code_idxs) <= MAX_ENTITIES_PER_CONTEXT:
                code_para_pairs.extend(_code_pairs(para_code_idxs, para_entity_refs))

    return DocumentAnalysis(
        nouns=nouns,
        names=names,
        verbs=verbs,
        noun_sent_pairs=noun_sent_pairs,
        noun_para_pairs=noun_para_pairs,
        noun_verb_pairs=noun_verb_pairs,
        codes=codes,
        code_sent_pairs=code_sent_pairs,
        code_para_pairs=code_para_pairs,
        num_pages=len({page_num for page_num, _, _ in section}),
    )


def _is_abbreviation(text: str) -> bool:
    """ERR, HTTP, OK — 2–10 upper-case letters (checked after NOUN/PROPN/VERB)."""
    return 2 <= len(text) <= 10 and text.isalpha() and text.isupper()


def _code_pairs(code_idxs: list[int], entity_refs: list[tuple[int, str]]):
    """(code_idx, other_idx, other_type) for each code with every noun/name
    and every later code of the same context."""
    for i, ci in enumerate(code_idxs):
        for ei, et in entity_refs:
            yield (ci, ei, et)
        for cj in code_idxs[i + 1:]:
            yield (ci, cj, "code")


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

    code_occ_ids: list[int] = []
    for code, page_num, pos in analysis.codes:
        cid = _code_id(conn, code)
        cur = conn.execute(
            "INSERT INTO code_occurrences (fileID,codeID,pagenumber,position) VALUES (?,?,?,?)",
            (file_id, cid, page_num, pos),
        )
        code_occ_ids.append(cur.lastrowid)

    def _resolve(idx: int, typ: str) -> int:
        if typ == "code":
            return code_occ_ids[idx]
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
    for table, pairs in (("code_sentence", analysis.code_sent_pairs),
                         ("code_paragraph", analysis.code_para_pairs)):
        conn.executemany(
            f"INSERT INTO {table} (code_occ_id,occ_type,occ_id) VALUES (?,?,?)",
            [(code_occ_ids[ci], ot, _resolve(oi, ot)) for ci, oi, ot in pairs],
        )


# ---------------------------------------------------------------------------
# Top-level worker — picklable, used by ProcessPoolExecutor
# ---------------------------------------------------------------------------

def _analyze_file(path_str: str, model: str) -> "DocumentAnalysis | LargeDocument":
    """Extract text and run NLP analysis. Designed to run in a worker process.

    Texts over _SECTION_CHARS are not analysed here; a LargeDocument with the
    sections is returned instead."""
    import os, sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.insert(0, _dir)

    import extractor
    from pathlib import Path

    pages = extractor.extract(Path(path_str))
    num_chars = sum(len(text) for _, text in pages)
    if num_chars > _SECTION_CHARS:
        return LargeDocument(split_sections(pages), len(pages), num_chars)
    return analyze_document(pages, model)


def _analyze_section(section: Section, model: str) -> DocumentAnalysis:
    """Worker entry point for one section of a LargeDocument."""
    import os, sys
    _dir = os.path.dirname(os.path.abspath(__file__))
    if _dir not in sys.path:
        sys.path.insert(0, _dir)
    return analyze_section(section, model)


def analyze_sections(sections: list[Section], model: str, workers: int = 1,
                     timeout: Optional[float] = None):
    """Yield the analysis of each section in order.

    Up to `workers` sections are analysed in parallel worker processes; at most
    2 × workers results are held at a time, so memory does not grow with the
    document size."""
    import concurrent.futures
    from collections import deque

    with concurrent.futures.ProcessPoolExecutor(max_workers=workers) as executor:
        pending: deque = deque()
        todo = iter(sections)
        try:
            while True:
                while len(pending) < 2 * workers:
                    section = next(todo, None)
                    if section is None:
                        break
                    pending.append(executor.submit(_analyze_section, section, model))
                if not pending:
                    break
                yield pending.popleft().result(timeout=timeout)
        finally:
            for future in pending:
                future.cancel()


def split_sections(pages: list[tuple[int, str]],
                   size: int = _SECTION_CHARS) -> list[Section]:
    """Split pages into sections of at most `size` characters.

    Long pages are cut at paragraph boundaries (or the line breaks used by
    _chunk_spans), so sentence and paragraph pairs are the same as in one pass."""
    sections: list[Section] = []
    current: Section = []
    current_len = 0
    for page_num, text in pages:
        for start, end in _section_spans(text, size):
            if current and current_len + end - start > size:
                sections.append(current)
                current, current_len = [], 0
            current.append((page_num, text[start:end], start))
            current_len += end - start
    if current:
        sections.append(current)
    return sections


# ---------------------------------------------------------------------------
# Backward-compatible entry point (sequential, single-process)
# ---------------------------------------------------------------------------

def process_document(
    conn: sqlite3.Connection,
    file_id: int,
    pages: list[tuple[int, str]],
    model: str = "en_core_web_sm",
):
    for section in split_sections(pages):
        write_analysis(conn, file_id, analyze_section(section, model))


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


def _code_id(conn, code: str) -> int:
    if code not in _code_ids:
        conn.execute("INSERT OR IGNORE INTO codes (code) VALUES (?)", (code,))
        _code_ids[code] = conn.execute(
            "SELECT codeID FROM codes WHERE code = ?", (code,)
        ).fetchone()[0]
    return _code_ids[code]


def _chunk_spans(text: str, spans: list[tuple[int, int]],
                 limit: int = _MAX_CHUNK) -> list[tuple[int, int]]:
    """Split spans longer than limit at the last line break (else whitespace)."""
    out = []
    for start, end in spans:
        while end - start > limit:
            cut = text.rfind("\n", start + 1, start + limit)
            if cut == -1:
                cut = max(text.rfind(" ", start + 1, start + limit),
                          text.rfind("\t", start + 1, start + limit))
            if cut == -1:
                cut = start + limit
                out.append((start, cut))
                start = cut
            else:
                out.append((start, cut))
                start = cut + 1   # the next piece starts after the line break
        out.append((start, end))
    return out


def _section_spans(text: str, size: int) -> list[tuple[int, int]]:
    """Group the paragraph/chunk spans of text into ranges of at most size chars."""
    if len(text) <= size:
        return [(0, len(text))]
    out = []
    start = end = None
    for s, e in _chunk_spans(text, _paragraph_spans(text)):
        if start is None:
            start = s
        elif e - start > size:
            out.append((start, end))
            start = s
        end = e
    out.append((start, end))
    return out


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character offsets for each paragraph in text."""
    spans = []
    for m in re.finditer(r"[^\n].*?(?=\n\s*\n|\Z)", text, re.DOTALL):
        spans.append((m.start(), m.end()))
    return spans or [(0, len(text))]
