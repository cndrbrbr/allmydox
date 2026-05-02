#!/usr/bin/env python3
import argparse
import sys
from pathlib import Path

import db
import extractor
import processor


def cmd_process(args):
    directory = Path(args.directory).resolve()
    if not directory.is_dir():
        print(f"Error: '{args.directory}' is not a directory.", file=sys.stderr)
        sys.exit(1)

    extensions = [e if e.startswith(".") else f".{e}" for e in args.ext]

    doc_files = []
    for ext in extensions:
        doc_files.extend(sorted(directory.rglob(f"*{ext}")))

    print(f"Found {len(doc_files)} document(s) in '{directory}'.")

    conn = db.connect(args.db)
    db.create_tables(conn)
    processor.prime_caches(conn)

    total = len(doc_files)
    width = len(str(total))

    new_count = 0
    upd_count = 0

    for idx, doc_path in enumerate(doc_files, start=1):
        rel        = doc_path.relative_to(directory)
        file_mtime = doc_path.stat().st_mtime
        info       = db.get_document_info(conn, str(doc_path.parent), doc_path.name)

        if info is not None:
            file_id, stored_mtime = info
            if stored_mtime is not None and stored_mtime == file_mtime:
                print(f"  [{idx:{width}}/{total}] {rel}  —  skipped (unchanged)")
                continue
            if not args.reindex_changed or stored_mtime is None:
                print(f"  [{idx:{width}}/{total}] {rel}  —  skipped (already indexed)")
                continue
            print(f"  [{idx:{width}}/{total}] {rel}  —  changed, re-indexing ...", flush=True)
            db.delete_document(conn, file_id)
            conn.commit()
            is_update = True
        else:
            print(f"  [{idx:{width}}/{total}] {rel} ... ", end="", flush=True)
            is_update = False

        try:
            file_id = db.insert_document(
                conn,
                filename=doc_path.name,
                folderpath=str(doc_path.parent),
                size=doc_path.stat().st_size,
                extension=doc_path.suffix.lower(),
                mtime=file_mtime,
            )
            pages = extractor.extract(doc_path)
            processor.process_document(conn, file_id, pages, model=args.model)
            conn.commit()
            if is_update:
                upd_count += 1
                print(f"done ({len(pages)} page(s)) [updated]")
            else:
                new_count += 1
                print(f"done ({len(pages)} page(s))")
        except Exception as exc:
            conn.rollback()
            print(f"ERROR: {exc}", file=sys.stderr)

    conn.close()
    parts = []
    if new_count:
        parts.append(f"{new_count} new")
    if upd_count:
        parts.append(f"{upd_count} updated")
    print("Finished.", ", ".join(parts) if parts else "No changes.")


def cmd_stats(args):
    conn = db.connect(args.db)
    try:
        db.create_tables(conn)
        stats = db.get_stats(conn)
    finally:
        conn.close()

    width = max(len(k) for k in stats)
    print(f"Database: {args.db}")
    for table, count in stats.items():
        print(f"  {table:<{width}}  {count:>10,}")


def main():
    parser = argparse.ArgumentParser(
        description="Index documents into a SQLite linguistic database.",
    )
    parser.add_argument("--db", default="allmydox.db", metavar="PATH",
                        help="SQLite database file (default: allmydox.db)")

    sub = parser.add_subparsers(dest="command", required=True)

    p_process = sub.add_parser("process", help="Scan a directory and index documents")
    p_process.add_argument("directory", help="Directory to scan")
    p_process.add_argument("--ext", nargs="+", default=["pdf", "docx", "txt"],
                           metavar="EXT", help="Extensions to include (default: pdf docx txt)")
    p_process.add_argument("--model", default="en_core_web_sm", metavar="MODEL",
                           help="spaCy language model (default: en_core_web_sm)")
    p_process.add_argument("--reindex-changed", action="store_true", default=True,
                           help="Re-index files whose modification time changed (default: on)")
    p_process.add_argument("--no-reindex-changed", dest="reindex_changed",
                           action="store_false",
                           help="Skip files already in the database regardless of mtime")

    sub.add_parser("stats", help="Show row counts for all tables")

    args = parser.parse_args()

    if args.command == "process":
        cmd_process(args)
    elif args.command == "stats":
        cmd_stats(args)


if __name__ == "__main__":
    main()
