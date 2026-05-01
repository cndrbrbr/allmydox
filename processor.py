import re
import sqlite3
from itertools import combinations
from typing import NamedTuple

import spacy

_nlp_cache: dict[str, spacy.language.Language] = {}


def get_nlp(model: str) -> spacy.language.Language:
    if model not in _nlp_cache:
        _nlp_cache[model] = spacy.load(model)
    return _nlp_cache[model]


class _OccRef(NamedTuple):
    type: str   # 'noun', 'name', or 'verb'
    id: int


def process_document(
    conn: sqlite3.Connection,
    file_id: int,
    pages: list[tuple[int, str]],
    model: str = "en_core_web_sm",
):
    import db

    nlp = get_nlp(model)

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
                sent_verb_occs: list[_OccRef] = []

                for token in sent:
                    if not token.is_alpha:
                        continue
                    lemma = token.lemma_.lower().strip()
                    if not lemma:
                        continue

                    # position is the character offset within the full page text
                    position = para_start + token.idx

                    if token.pos_ == "NOUN":
                        noun_id = db.get_or_create_noun(conn, lemma)
                        occ_id = db.insert_noun_occurrence(conn, file_id, noun_id, page_num, position)
                        ref = _OccRef("noun", occ_id)
                        sent_entity_occs.append(ref)
                        para_entity_occs.append(ref)

                    elif token.pos_ == "PROPN":
                        # Preserve original casing for proper names
                        name_id = db.get_or_create_name(conn, token.text)
                        occ_id = db.insert_name_occurrence(conn, file_id, name_id, page_num, position)
                        ref = _OccRef("name", occ_id)
                        sent_entity_occs.append(ref)
                        para_entity_occs.append(ref)

                    elif token.pos_ == "VERB" and not token.is_stop:
                        verb_id = db.get_or_create_verb(conn, lemma)
                        occ_id = db.insert_verb_occurrence(conn, file_id, verb_id, page_num, position)
                        sent_verb_occs.append(_OccRef("verb", occ_id))

                # Sentence-level noun/name pairs
                for a, b in combinations(sent_entity_occs, 2):
                    db.insert_noun_sentence(conn, a.type, a.id, b.type, b.id)

                # Sentence-level noun/name + verb pairs
                for entity_ref in sent_entity_occs:
                    for verb_ref in sent_verb_occs:
                        db.insert_noun_verb_sentence(conn, entity_ref.type, entity_ref.id, verb_ref.id)

            # Paragraph-level noun/name pairs
            for a, b in combinations(para_entity_occs, 2):
                db.insert_noun_paragraph(conn, a.type, a.id, b.type, b.id)


def _paragraph_spans(text: str) -> list[tuple[int, int]]:
    """Return (start, end) character offsets for each paragraph in text."""
    spans = []
    for m in re.finditer(r"[^\n].*?(?=\n\s*\n|\Z)", text, re.DOTALL):
        spans.append((m.start(), m.end()))
    return spans or [(0, len(text))]
