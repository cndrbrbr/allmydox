"""
Live test of the 4-pass pipeline against the real folder.
Uses a temporary database — no permanent changes.
"""
import concurrent.futures
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import db
import processor

DIRECTORY    = Path("/mnt/sv25/sv_2025/_AktuelleMandate/LAN_RIE")
MODEL        = "de_core_news_sm"
EXTENSIONS   = [".pdf", ".doc", ".docx", ".xls", ".xlsx", ".txt", ".html", ".htm"]
LARGE_FILE_MB = 50
NUM_WORKERS  = 4

threshold_bytes = LARGE_FILE_MB * 1024 * 1024


def emit(text):
    print(text, flush=True)


with tempfile.TemporaryDirectory() as tmpdir:
    conn = db.connect(os.path.join(tmpdir, "test.db"))
    db.create_tables(conn)
    processor.prime_caches(conn)

    # --- collect files ---
    doc_files = []
    for ext in EXTENSIONS:
        doc_files.extend(sorted(DIRECTORY.rglob(f"*{ext}")))

    total = len(doc_files)
    width = len(str(total))
    emit(f"Found {total} document(s) in '{DIRECTORY}'.")

    to_process:     list[tuple[int, Path]] = []
    to_process_seq: list[tuple[int, Path]] = []

    # --- Pass 1 ---
    for idx, doc_path in enumerate(doc_files, start=1):
        rel = doc_path.relative_to(DIRECTORY)
        if doc_path.stat().st_size >= threshold_bytes:
            size_mb = doc_path.stat().st_size / (1024 * 1024)
            emit(f"  [{idx:{width}}/{total}] {rel}  — large ({size_mb:.0f} MB), queued sequential")
            to_process_seq.append((idx, doc_path))
        else:
            to_process.append((idx, doc_path))

    new_count = err_count = 0

    # --- Pass 2: parallel ---
    broken_files: list[tuple[int, Path]] = []
    if to_process:
        num_workers = min(NUM_WORKERS, len(to_process))
        emit(f"\n  Pass 2 — parallel pool ({num_workers} workers), {len(to_process)} file(s) …")
        with concurrent.futures.ProcessPoolExecutor(max_workers=num_workers) as executor:
            future_map = {
                executor.submit(processor._analyze_file, str(p), MODEL): (i, p)
                for i, p in to_process
            }
            for future in concurrent.futures.as_completed(future_map):
                orig_idx, doc_path = future_map[future]
                rel = doc_path.relative_to(DIRECTORY)
                try:
                    analysis = future.result()
                    fid = db.insert_document(conn, doc_path.name, str(doc_path.parent),
                                             doc_path.stat().st_size, doc_path.suffix.lower(),
                                             doc_path.stat().st_mtime)
                    processor.write_analysis(conn, fid, analysis)
                    conn.commit()
                    new_count += 1
                    emit(f"  [{orig_idx:{width}}/{total}] {rel}  ok  {analysis.num_pages} page(s)  [new]")
                except concurrent.futures.BrokenExecutor:
                    broken_files.append((orig_idx, doc_path))
                    emit(f"  [{orig_idx:{width}}/{total}] {rel}  — worker crashed, will retry …")
                except Exception as exc:
                    conn.rollback()
                    err_count += 1
                    emit(f"  [{orig_idx:{width}}/{total}] {rel}  ERROR: {exc}")

    # --- Pass 3: large files sequential ---
    if to_process_seq:
        emit(f"\n  Pass 3 — sequential, {len(to_process_seq)} large file(s) …")
        for orig_idx, doc_path in to_process_seq:
            rel = doc_path.relative_to(DIRECTORY)
            size_mb = doc_path.stat().st_size / (1024 * 1024)
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=1) as ex:
                    analysis = ex.submit(
                        processor._analyze_file, str(doc_path), MODEL
                    ).result(timeout=300)
                fid = db.insert_document(conn, doc_path.name, str(doc_path.parent),
                                         doc_path.stat().st_size, doc_path.suffix.lower(),
                                         doc_path.stat().st_mtime)
                processor.write_analysis(conn, fid, analysis)
                conn.commit()
                new_count += 1
                emit(f"  [{orig_idx:{width}}/{total}] {rel}  ok  {analysis.num_pages} page(s)  [new]  ({size_mb:.0f} MB, sequential)")
            except Exception as exc:
                conn.rollback()
                err_count += 1
                emit(f"  [{orig_idx:{width}}/{total}] {rel}  ERROR: {exc}")

    # --- Pass 4: retry crash victims ---
    if broken_files:
        emit(f"\n  Pass 4 — retrying {len(broken_files)} crash victim(s) …")
        for orig_idx, doc_path in broken_files:
            rel = doc_path.relative_to(DIRECTORY)
            try:
                with concurrent.futures.ProcessPoolExecutor(max_workers=1) as ex:
                    analysis = ex.submit(
                        processor._analyze_file, str(doc_path), MODEL
                    ).result(timeout=300)
                fid = db.insert_document(conn, doc_path.name, str(doc_path.parent),
                                         doc_path.stat().st_size, doc_path.suffix.lower(),
                                         doc_path.stat().st_mtime)
                processor.write_analysis(conn, fid, analysis)
                conn.commit()
                new_count += 1
                emit(f"  [{orig_idx:{width}}/{total}] {rel}  ok  {analysis.num_pages} page(s)  [retried]")
            except Exception as exc:
                conn.rollback()
                err_count += 1
                emit(f"  [{orig_idx:{width}}/{total}] {rel}  ERROR: {exc}")

    # --- summary ---
    stats = db.get_stats(conn)
    conn.close()

    emit(f"\nFinished.  {new_count} new,  {err_count} errors.")
    emit(f"  documents       {stats['documents']}")
    emit(f"  noun_occ        {stats['noun_occurrences']}")
    emit(f"  name_occ        {stats['name_occurrences']}")
    emit(f"  verb_occ        {stats['verb_occurrences']}")
    emit(f"  noun_sentence   {stats['noun_sentence']}")
