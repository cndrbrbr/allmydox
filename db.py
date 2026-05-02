import sqlite3


def connect(db_path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


def create_tables(conn: sqlite3.Connection):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS documents (
            fileID     INTEGER PRIMARY KEY AUTOINCREMENT,
            filename   TEXT    NOT NULL,
            folderpath TEXT    NOT NULL,
            size       INTEGER NOT NULL,
            extension  TEXT    NOT NULL,
            mtime      REAL
        );

        CREATE TABLE IF NOT EXISTS nouns (
            nounID INTEGER PRIMARY KEY AUTOINCREMENT,
            noun   TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS noun_occurrences (
            nounOccurrenceID INTEGER PRIMARY KEY AUTOINCREMENT,
            fileID           INTEGER NOT NULL REFERENCES documents(fileID),
            nounID           INTEGER NOT NULL REFERENCES nouns(nounID),
            pagenumber       INTEGER NOT NULL,
            position         INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS names (
            nameID INTEGER PRIMARY KEY AUTOINCREMENT,
            name   TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS name_occurrences (
            nameOccurrenceID INTEGER PRIMARY KEY AUTOINCREMENT,
            fileID           INTEGER NOT NULL REFERENCES documents(fileID),
            nameID           INTEGER NOT NULL REFERENCES names(nameID),
            pagenumber       INTEGER NOT NULL,
            position         INTEGER NOT NULL
        );

        CREATE TABLE IF NOT EXISTS verbs (
            verbID INTEGER PRIMARY KEY AUTOINCREMENT,
            verb   TEXT NOT NULL UNIQUE
        );

        CREATE TABLE IF NOT EXISTS verb_occurrences (
            verbOccurrenceID INTEGER PRIMARY KEY AUTOINCREMENT,
            fileID           INTEGER NOT NULL REFERENCES documents(fileID),
            verbID           INTEGER NOT NULL REFERENCES verbs(verbID),
            pagenumber       INTEGER NOT NULL,
            position         INTEGER NOT NULL
        );

        -- Co-occurring noun/name pairs within the same sentence.
        -- occ_type is 'noun' or 'name'; occ_id references the respective occurrence table.
        CREATE TABLE IF NOT EXISTS noun_sentence (
            nounsentenceID INTEGER PRIMARY KEY AUTOINCREMENT,
            occ1_type      TEXT    NOT NULL CHECK (occ1_type IN ('noun', 'name')),
            occ1_id        INTEGER NOT NULL,
            occ2_type      TEXT    NOT NULL CHECK (occ2_type IN ('noun', 'name')),
            occ2_id        INTEGER NOT NULL
        );

        -- Co-occurring noun/name pairs within the same paragraph.
        CREATE TABLE IF NOT EXISTS noun_paragraph (
            nounparagraphID INTEGER PRIMARY KEY AUTOINCREMENT,
            occ1_type       TEXT    NOT NULL CHECK (occ1_type IN ('noun', 'name')),
            occ1_id         INTEGER NOT NULL,
            occ2_type       TEXT    NOT NULL CHECK (occ2_type IN ('noun', 'name')),
            occ2_id         INTEGER NOT NULL
        );

        -- Co-occurring noun/name + verb triples within the same sentence.
        CREATE TABLE IF NOT EXISTS noun_verb_sentence (
            nounverbsentenceID INTEGER PRIMARY KEY AUTOINCREMENT,
            noun_occ_type      TEXT    NOT NULL CHECK (noun_occ_type IN ('noun', 'name')),
            noun_occ_id        INTEGER NOT NULL,
            verb_occ_id        INTEGER NOT NULL REFERENCES verb_occurrences(verbOccurrenceID)
        );

        CREATE INDEX IF NOT EXISTS idx_noun_occ_file ON noun_occurrences(fileID);
        CREATE INDEX IF NOT EXISTS idx_name_occ_file ON name_occurrences(fileID);
        CREATE INDEX IF NOT EXISTS idx_verb_occ_file ON verb_occurrences(fileID);

        CREATE INDEX IF NOT EXISTS idx_noun_occ_noun ON noun_occurrences(nounID);
        CREATE INDEX IF NOT EXISTS idx_name_occ_name ON name_occurrences(nameID);
        CREATE INDEX IF NOT EXISTS idx_verb_occ_verb ON verb_occurrences(verbID);

        CREATE INDEX IF NOT EXISTS idx_noun_sent_occ1 ON noun_sentence(occ1_type, occ1_id);
        CREATE INDEX IF NOT EXISTS idx_noun_sent_occ2 ON noun_sentence(occ2_type, occ2_id);
        CREATE INDEX IF NOT EXISTS idx_noun_para_occ1 ON noun_paragraph(occ1_type, occ1_id);
        CREATE INDEX IF NOT EXISTS idx_noun_para_occ2 ON noun_paragraph(occ2_type, occ2_id);
        CREATE INDEX IF NOT EXISTS idx_nvs_noun_occ   ON noun_verb_sentence(noun_occ_type, noun_occ_id);
        CREATE INDEX IF NOT EXISTS idx_nvs_verb_occ   ON noun_verb_sentence(verb_occ_id);
    """)
    conn.commit()
    # Migrate existing databases that predate the mtime column
    try:
        conn.execute("ALTER TABLE documents ADD COLUMN mtime REAL")
        conn.commit()
    except sqlite3.OperationalError:
        pass  # column already exists


def get_document_info(
    conn: sqlite3.Connection, folderpath: str, filename: str
) -> tuple[int, float | None] | None:
    """Return (fileID, mtime) if the document is in the database, else None."""
    row = conn.execute(
        "SELECT fileID, mtime FROM documents WHERE folderpath = ? AND filename = ?",
        (folderpath, filename),
    ).fetchone()
    return (row[0], row[1]) if row else None


def document_exists(conn: sqlite3.Connection, folderpath: str, filename: str) -> bool:
    return get_document_info(conn, folderpath, filename) is not None


def delete_document(conn: sqlite3.Connection, file_id: int):
    """Delete a document and all its derived data (occurrences, co-occurrences)."""
    # Co-occurrence tables reference occurrence IDs — delete first
    for cooc_table in ("noun_sentence", "noun_paragraph"):
        conn.execute(f"""
            DELETE FROM {cooc_table} WHERE
                (occ1_type='noun' AND occ1_id IN
                    (SELECT nounOccurrenceID FROM noun_occurrences WHERE fileID=?))
                OR (occ1_type='name' AND occ1_id IN
                    (SELECT nameOccurrenceID FROM name_occurrences WHERE fileID=?))
                OR (occ2_type='noun' AND occ2_id IN
                    (SELECT nounOccurrenceID FROM noun_occurrences WHERE fileID=?))
                OR (occ2_type='name' AND occ2_id IN
                    (SELECT nameOccurrenceID FROM name_occurrences WHERE fileID=?))
        """, (file_id, file_id, file_id, file_id))
    conn.execute("""
        DELETE FROM noun_verb_sentence WHERE
            verb_occ_id IN (SELECT verbOccurrenceID FROM verb_occurrences WHERE fileID=?)
            OR (noun_occ_type='noun' AND noun_occ_id IN
                (SELECT nounOccurrenceID FROM noun_occurrences WHERE fileID=?))
            OR (noun_occ_type='name' AND noun_occ_id IN
                (SELECT nameOccurrenceID FROM name_occurrences WHERE fileID=?))
    """, (file_id, file_id, file_id))
    # Occurrence tables
    conn.execute("DELETE FROM noun_occurrences WHERE fileID=?", (file_id,))
    conn.execute("DELETE FROM name_occurrences WHERE fileID=?", (file_id,))
    conn.execute("DELETE FROM verb_occurrences WHERE fileID=?", (file_id,))
    # Document row itself
    conn.execute("DELETE FROM documents WHERE fileID=?", (file_id,))


def insert_document(conn, filename, folderpath, size, extension, mtime=None) -> int:
    cur = conn.execute(
        "INSERT INTO documents (filename, folderpath, size, extension, mtime)"
        " VALUES (?, ?, ?, ?, ?)",
        (filename, folderpath, size, extension, mtime),
    )
    return cur.lastrowid


def get_or_create_noun(conn, noun: str) -> int:
    conn.execute("INSERT OR IGNORE INTO nouns (noun) VALUES (?)", (noun,))
    return conn.execute("SELECT nounID FROM nouns WHERE noun = ?", (noun,)).fetchone()[0]


def insert_noun_occurrence(conn, file_id, noun_id, pagenumber, position) -> int:
    cur = conn.execute(
        "INSERT INTO noun_occurrences (fileID, nounID, pagenumber, position) VALUES (?, ?, ?, ?)",
        (file_id, noun_id, pagenumber, position),
    )
    return cur.lastrowid


def get_or_create_name(conn, name: str) -> int:
    conn.execute("INSERT OR IGNORE INTO names (name) VALUES (?)", (name,))
    return conn.execute("SELECT nameID FROM names WHERE name = ?", (name,)).fetchone()[0]


def insert_name_occurrence(conn, file_id, name_id, pagenumber, position) -> int:
    cur = conn.execute(
        "INSERT INTO name_occurrences (fileID, nameID, pagenumber, position) VALUES (?, ?, ?, ?)",
        (file_id, name_id, pagenumber, position),
    )
    return cur.lastrowid


def get_or_create_verb(conn, verb: str) -> int:
    conn.execute("INSERT OR IGNORE INTO verbs (verb) VALUES (?)", (verb,))
    return conn.execute("SELECT verbID FROM verbs WHERE verb = ?", (verb,)).fetchone()[0]


def insert_verb_occurrence(conn, file_id, verb_id, pagenumber, position) -> int:
    cur = conn.execute(
        "INSERT INTO verb_occurrences (fileID, verbID, pagenumber, position) VALUES (?, ?, ?, ?)",
        (file_id, verb_id, pagenumber, position),
    )
    return cur.lastrowid


def insert_noun_sentence(conn, occ1_type, occ1_id, occ2_type, occ2_id):
    conn.execute(
        "INSERT INTO noun_sentence (occ1_type, occ1_id, occ2_type, occ2_id) VALUES (?, ?, ?, ?)",
        (occ1_type, occ1_id, occ2_type, occ2_id),
    )


def insert_noun_paragraph(conn, occ1_type, occ1_id, occ2_type, occ2_id):
    conn.execute(
        "INSERT INTO noun_paragraph (occ1_type, occ1_id, occ2_type, occ2_id) VALUES (?, ?, ?, ?)",
        (occ1_type, occ1_id, occ2_type, occ2_id),
    )


def insert_noun_verb_sentence(conn, noun_occ_type, noun_occ_id, verb_occ_id):
    conn.execute(
        "INSERT INTO noun_verb_sentence (noun_occ_type, noun_occ_id, verb_occ_id) VALUES (?, ?, ?)",
        (noun_occ_type, noun_occ_id, verb_occ_id),
    )


def get_stats(conn) -> dict:
    tables = [
        "documents", "nouns", "noun_occurrences", "names", "name_occurrences",
        "verbs", "verb_occurrences", "noun_sentence", "noun_paragraph", "noun_verb_sentence",
    ]
    return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] for t in tables}
