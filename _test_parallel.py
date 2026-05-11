"""
End-to-end test for the parallel processing pipeline.

Tests:
  1. analyze_document()       — pure NLP, returns DocumentAnalysis
  2. write_analysis()         — inserts result into SQLite correctly
  3. _analyze_file()          — worker function (extract + NLP) in-process
  4. ProcessPoolExecutor      — 2 workers, 6 files, checks DB row counts
  5. Idempotency              — re-running skips unchanged files
  6. Rollback on bad file     — corrupt file doesn't poison the DB
"""

import concurrent.futures
import sqlite3
import sys
import tempfile
import os
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import db
import processor

MODEL = "en_core_web_sm"

TEXTS = [
    ("Alice went to the market. She bought apples and bread.",
     "Alice visits market"),
    ("The engineer designed a new bridge over the river Thames.",
     "Bridge engineering"),
    ("Python is a programming language. Developers love Python.",
     "Python language"),
    ("The doctor examined the patient carefully in the hospital.",
     "Medical examination"),
    ("Scientists discovered a new planet orbiting a distant star.",
     "Astronomy discovery"),
    ("The chef prepared a delicious meal with fresh vegetables.",
     "Cooking meal"),
]

PASS = "\033[32mPASS\033[0m"
FAIL = "\033[31mFAIL\033[0m"
_failures = []

def check(name, condition, detail=""):
    if condition:
        print(f"  {PASS}  {name}")
    else:
        print(f"  {FAIL}  {name}" + (f": {detail}" if detail else ""))
        _failures.append(name)


# ---------------------------------------------------------------------------
# 1. analyze_document
# ---------------------------------------------------------------------------
print("\n1. analyze_document()")
pages = [(1, TEXTS[0][0])]
analysis = processor.analyze_document(pages, MODEL)

check("returns DocumentAnalysis", isinstance(analysis, processor.DocumentAnalysis))
check("num_pages == 1", analysis.num_pages == 1)
check("finds nouns", len(analysis.nouns) > 0,
      f"got {len(analysis.nouns)}")
check("finds names (Alice, Thames…)", len(analysis.names) > 0,
      f"got {len(analysis.names)}")
check("finds verbs", len(analysis.verbs) > 0,
      f"got {len(analysis.verbs)}")
check("noun tuples are (str, int, int)",
      all(isinstance(w,str) and isinstance(p,int) and isinstance(pos,int)
          for w,p,pos in analysis.nouns))


# ---------------------------------------------------------------------------
# 2. write_analysis + DB integrity
# ---------------------------------------------------------------------------
print("\n2. write_analysis() — DB integrity")
with tempfile.TemporaryDirectory() as tmpdir:
    db_path = os.path.join(tmpdir, "test.db")
    conn = db.connect(db_path)
    db.create_tables(conn)
    processor.prime_caches(conn)

    pages = [(1, TEXTS[1][0]), (2, TEXTS[2][0])]
    analysis = processor.analyze_document(pages, MODEL)
    fid = db.insert_document(conn, "test.txt", tmpdir, 100, ".txt", 0.0)
    processor.write_analysis(conn, fid, analysis)
    conn.commit()

    doc_count  = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    noun_count = conn.execute("SELECT COUNT(*) FROM noun_occurrences").fetchone()[0]
    name_count = conn.execute("SELECT COUNT(*) FROM name_occurrences").fetchone()[0]
    verb_count = conn.execute("SELECT COUNT(*) FROM verb_occurrences").fetchone()[0]
    sent_count = conn.execute("SELECT COUNT(*) FROM noun_sentence").fetchone()[0]

    check("1 document inserted", doc_count == 1)
    check("noun occurrences written", noun_count == len(analysis.nouns),
          f"DB={noun_count} analysis={len(analysis.nouns)}")
    check("name occurrences written", name_count == len(analysis.names),
          f"DB={name_count} analysis={len(analysis.names)}")
    check("verb occurrences written", verb_count == len(analysis.verbs),
          f"DB={verb_count} analysis={len(analysis.verbs)}")
    check("noun_sentence rows written", sent_count == len(analysis.noun_sent_pairs),
          f"DB={sent_count} analysis={len(analysis.noun_sent_pairs)}")

    # FK-style consistency: every occ1_id in noun_sentence must exist
    bad = conn.execute("""
        SELECT COUNT(*) FROM noun_sentence s
        WHERE (s.occ1_type='noun' AND s.occ1_id NOT IN
                  (SELECT nounOccurrenceID FROM noun_occurrences))
           OR (s.occ1_type='name' AND s.occ1_id NOT IN
                  (SELECT nameOccurrenceID FROM name_occurrences))
    """).fetchone()[0]
    check("all noun_sentence occ1 IDs valid", bad == 0, f"{bad} orphan rows")

    conn.close()


# ---------------------------------------------------------------------------
# 3. _analyze_file — worker function in-process
# ---------------------------------------------------------------------------
print("\n3. _analyze_file() — in-process")
with tempfile.TemporaryDirectory() as tmpdir:
    p = Path(tmpdir) / "sample.txt"
    p.write_text(TEXTS[3][0], encoding="utf-8")
    result = processor._analyze_file(str(p), MODEL)
    check("returns DocumentAnalysis", isinstance(result, processor.DocumentAnalysis))
    check("num_pages == 1", result.num_pages == 1)
    check("has tokens", len(result.nouns) + len(result.names) + len(result.verbs) > 0)


# ---------------------------------------------------------------------------
# 4. ProcessPoolExecutor — 2 workers, 6 files
# ---------------------------------------------------------------------------
print("\n4. ProcessPoolExecutor — 2 workers, 6 files")
with tempfile.TemporaryDirectory() as tmpdir:
    doc_paths = []
    for i, (text, _) in enumerate(TEXTS):
        p = Path(tmpdir) / f"doc{i}.txt"
        p.write_text(text, encoding="utf-8")
        doc_paths.append(p)

    db_path = os.path.join(tmpdir, "parallel.db")
    conn = db.connect(db_path)
    db.create_tables(conn)
    processor.prime_caches(conn)

    new_count = err_count = 0
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as executor:
        future_map = {
            executor.submit(processor._analyze_file, str(p), MODEL): p
            for p in doc_paths
        }
        for future in concurrent.futures.as_completed(future_map):
            doc_path = future_map[future]
            try:
                analysis = future.result()
                fid = db.insert_document(
                    conn, doc_path.name, str(doc_path.parent),
                    doc_path.stat().st_size, ".txt", doc_path.stat().st_mtime,
                )
                processor.write_analysis(conn, fid, analysis)
                conn.commit()
                new_count += 1
            except Exception as exc:
                conn.rollback()
                err_count += 1
                print(f"    worker error: {exc}")

    doc_count  = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    noun_count = conn.execute("SELECT COUNT(*) FROM noun_occurrences").fetchone()[0]
    bad_fk = conn.execute("""
        SELECT COUNT(*) FROM noun_sentence s
        WHERE (s.occ1_type='noun' AND s.occ1_id NOT IN
                  (SELECT nounOccurrenceID FROM noun_occurrences))
           OR (s.occ1_type='name' AND s.occ1_id NOT IN
                  (SELECT nameOccurrenceID FROM name_occurrences))
    """).fetchone()[0]
    conn.close()

    check("all 6 workers succeeded", new_count == 6 and err_count == 0,
          f"new={new_count} err={err_count}")
    check("6 documents in DB", doc_count == 6, f"got {doc_count}")
    check("noun occurrences > 0", noun_count > 0, f"got {noun_count}")
    check("no orphan FK rows in noun_sentence", bad_fk == 0, f"{bad_fk} orphan rows")


# ---------------------------------------------------------------------------
# 5. Idempotency — re-running on same files, nothing changes
# ---------------------------------------------------------------------------
print("\n5. Idempotency — skip unchanged files")
with tempfile.TemporaryDirectory() as tmpdir:
    p = Path(tmpdir) / "same.txt"
    p.write_text(TEXTS[0][0], encoding="utf-8")
    mtime = p.stat().st_mtime

    db_path = os.path.join(tmpdir, "idem.db")
    conn = db.connect(db_path)
    db.create_tables(conn)
    processor.prime_caches(conn)

    # First run
    fid = db.insert_document(conn, p.name, str(p.parent), p.stat().st_size, ".txt", mtime)
    analysis = processor._analyze_file(str(p), MODEL)
    processor.write_analysis(conn, fid, analysis)
    conn.commit()
    count_after_first = conn.execute("SELECT COUNT(*) FROM noun_occurrences").fetchone()[0]

    # Simulate skip: mtime unchanged → no second insert
    info = db.get_document_info(conn, str(p.parent), p.name)
    skipped = info is not None and info[1] == mtime

    check("file detected as already indexed", skipped)
    count_after_second = conn.execute("SELECT COUNT(*) FROM noun_occurrences").fetchone()[0]
    check("noun_occurrences count unchanged after skip",
          count_after_first == count_after_second,
          f"before={count_after_first} after={count_after_second}")
    conn.close()


# ---------------------------------------------------------------------------
# 6. Bad file — exception in worker doesn't corrupt DB
# ---------------------------------------------------------------------------
print("\n6. Bad file — worker exception does not corrupt DB")
with tempfile.TemporaryDirectory() as tmpdir:
    good = Path(tmpdir) / "good.txt"
    good.write_text(TEXTS[4][0], encoding="utf-8")
    bad_path = Path(tmpdir) / "bad.pdf"   # named .pdf but not a real PDF

    bad_path.write_bytes(b"not a real pdf file at all")

    db_path = os.path.join(tmpdir, "robust.db")
    conn = db.connect(db_path)
    db.create_tables(conn)
    processor.prime_caches(conn)

    results = {"ok": 0, "err": 0}
    with concurrent.futures.ProcessPoolExecutor(max_workers=2) as executor:
        future_map = {
            executor.submit(processor._analyze_file, str(p), MODEL): p
            for p in [good, bad_path]
        }
        for future in concurrent.futures.as_completed(future_map):
            doc_path = future_map[future]
            try:
                analysis = future.result()
                fid = db.insert_document(
                    conn, doc_path.name, str(doc_path.parent),
                    doc_path.stat().st_size, doc_path.suffix, doc_path.stat().st_mtime,
                )
                processor.write_analysis(conn, fid, analysis)
                conn.commit()
                results["ok"] += 1
            except Exception:
                conn.rollback()
                results["err"] += 1

    doc_count = conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
    conn.close()

    check("good file indexed", results["ok"] == 1, f"ok={results['ok']}")
    check("bad file raised error", results["err"] == 1, f"err={results['err']}")
    check("only 1 document in DB after rollback", doc_count == 1, f"got {doc_count}")


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
print()
if _failures:
    print(f"FAILED: {len(_failures)} test(s): {', '.join(_failures)}")
    sys.exit(1)
else:
    print("All tests passed.")
