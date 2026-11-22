"""
db.py - SQLiteラッパー
"""
import sqlite3
import os

DB_PATH = os.path.join(os.path.dirname(__file__), "data", "cpu.db")


def get_connection():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_connection()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS cpus (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            brand           TEXT,
            family          TEXT,
            cores           TEXT,
            threads         TEXT,
            base_clock      TEXT,
            boost_clock     TEXT,
            tdp             TEXT,
            socket          TEXT,
            process         TEXT,
            memory_support  TEXT,
            igpu            TEXT,
            passmark_score  INTEGER,
            source_url      TEXT,
            updated_at      TEXT DEFAULT (datetime('now'))
        );
        CREATE INDEX IF NOT EXISTS idx_name ON cpus(name);
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
    """)
    conn.commit()
    conn.close()


def search_cpus(query: str, limit: int = 20):
    conn = get_connection()
    rows = conn.execute(
        """
        SELECT * FROM cpus
        WHERE name LIKE ?
        ORDER BY
            CASE WHEN name LIKE ? THEN 0 ELSE 1 END,
            passmark_score DESC NULLS LAST
        LIMIT ?
        """,
        (f"%{query}%", f"{query}%", limit),
    ).fetchall()
    conn.close()
    return rows


def get_cpu_by_id(cpu_id: int):
    conn = get_connection()
    row = conn.execute("SELECT * FROM cpus WHERE id = ?", (cpu_id,)).fetchone()
    conn.close()
    return row


def upsert_cpu(data: dict):
    conn = get_connection()
    conn.execute(
        """
        INSERT INTO cpus
            (name, brand, family, cores, threads, base_clock, boost_clock,
             tdp, socket, process, memory_support, igpu, passmark_score, source_url, updated_at)
        VALUES
            (:name, :brand, :family, :cores, :threads, :base_clock, :boost_clock,
             :tdp, :socket, :process, :memory_support, :igpu, :passmark_score, :source_url,
             datetime('now'))
        ON CONFLICT DO NOTHING
        """,
        data,
    )
    conn.commit()
    conn.close()


def upsert_many(records: list):
    conn = get_connection()
    conn.executemany(
        """
        INSERT OR REPLACE INTO cpus
            (name, brand, family, cores, threads, base_clock, boost_clock,
             tdp, socket, process, memory_support, igpu, passmark_score, source_url, updated_at)
        VALUES
            (:name, :brand, :family, :cores, :threads, :base_clock, :boost_clock,
             :tdp, :socket, :process, :memory_support, :igpu, :passmark_score, :source_url,
             datetime('now'))
        """,
        records,
    )
    conn.commit()
    conn.close()


def set_meta(key: str, value: str):
    conn = get_connection()
    conn.execute(
        "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, value)
    )
    conn.commit()
    conn.close()


def get_meta(key: str):
    conn = get_connection()
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    conn.close()
    return row["value"] if row else None


def count_cpus():
    conn = get_connection()
    n = conn.execute("SELECT COUNT(*) FROM cpus").fetchone()[0]
    conn.close()
    return n


def db_exists():
    return os.path.exists(DB_PATH) and count_cpus() > 0
