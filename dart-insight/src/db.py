"""SQLite database manager for DART financial data."""
from __future__ import annotations

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "dart_insight.db"


def get_connection() -> sqlite3.Connection:
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    conn = get_connection()
    cursor = conn.cursor()

    cursor.executescript("""
        CREATE TABLE IF NOT EXISTS companies (
            corp_code TEXT PRIMARY KEY,
            corp_name TEXT NOT NULL,
            stock_code TEXT,
            market TEXT,
            sector TEXT,
            updated_at TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS financials (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corp_code TEXT NOT NULL,
            year INTEGER NOT NULL,
            quarter TEXT NOT NULL,
            report_type TEXT NOT NULL,
            account_name TEXT NOT NULL,
            amount REAL,
            prev_amount REAL,
            is_new_item INTEGER DEFAULT 0,
            collected_at TEXT DEFAULT (datetime('now')),
            FOREIGN KEY (corp_code) REFERENCES companies(corp_code),
            UNIQUE(corp_code, year, quarter, report_type, account_name)
        );

        CREATE TABLE IF NOT EXISTS disclosures (
            rcept_no TEXT PRIMARY KEY,
            corp_code TEXT NOT NULL,
            corp_name TEXT,
            report_nm TEXT NOT NULL,
            rcept_dt TEXT NOT NULL,
            importance_score TEXT DEFAULT 'LOW',
            processed INTEGER DEFAULT 0,
            FOREIGN KEY (corp_code) REFERENCES companies(corp_code)
        );

        CREATE TABLE IF NOT EXISTS blog_posts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            corp_code TEXT NOT NULL,
            corp_name TEXT,
            title TEXT NOT NULL,
            content TEXT NOT NULL,
            summary TEXT,
            tags TEXT DEFAULT '',
            created_at TEXT DEFAULT (datetime('now')),
            disclosure_ref TEXT,
            FOREIGN KEY (corp_code) REFERENCES companies(corp_code)
        );

        CREATE INDEX IF NOT EXISTS idx_financials_corp ON financials(corp_code);
        CREATE INDEX IF NOT EXISTS idx_financials_year_qtr ON financials(year, quarter);
        CREATE INDEX IF NOT EXISTS idx_disclosures_date ON disclosures(rcept_dt);
        CREATE INDEX IF NOT EXISTS idx_blog_posts_corp ON blog_posts(corp_code);
    """)

    conn.commit()
    conn.close()


def upsert_company(corp_code: str, corp_name: str, stock_code: str = "",
                   market: str = "", sector: str = "") -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO companies (corp_code, corp_name, stock_code, market, sector)
           VALUES (?, ?, ?, ?, ?)
           ON CONFLICT(corp_code) DO UPDATE SET
             corp_name=excluded.corp_name,
             stock_code=excluded.stock_code,
             market=excluded.market,
             updated_at=datetime('now')""",
        (corp_code, corp_name, stock_code, market, sector),
    )
    conn.commit()
    conn.close()


def upsert_financial(corp_code: str, year: int, quarter: str,
                     report_type: str, account_name: str,
                     amount: float | None, prev_amount: float | None,
                     is_new_item: bool = False) -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO financials
           (corp_code, year, quarter, report_type, account_name, amount, prev_amount, is_new_item)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(corp_code, year, quarter, report_type, account_name) DO UPDATE SET
             amount=excluded.amount,
             prev_amount=excluded.prev_amount,
             is_new_item=excluded.is_new_item,
             collected_at=datetime('now')""",
        (corp_code, year, quarter, report_type, account_name, amount, prev_amount, int(is_new_item)),
    )
    conn.commit()
    conn.close()


def upsert_disclosure(rcept_no: str, corp_code: str, corp_name: str,
                      report_nm: str, rcept_dt: str,
                      importance_score: str = "LOW") -> None:
    conn = get_connection()
    conn.execute(
        """INSERT INTO disclosures (rcept_no, corp_code, corp_name, report_nm, rcept_dt, importance_score)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(rcept_no) DO UPDATE SET
             importance_score=excluded.importance_score""",
        (rcept_no, corp_code, corp_name, report_nm, rcept_dt, importance_score),
    )
    conn.commit()
    conn.close()


def insert_blog_post(corp_code: str, corp_name: str, title: str,
                     content: str, summary: str = "",
                     tags: str = "", disclosure_ref: str = "") -> int:
    conn = get_connection()
    cursor = conn.execute(
        """INSERT INTO blog_posts (corp_code, corp_name, title, content, summary, tags, disclosure_ref)
           VALUES (?, ?, ?, ?, ?, ?, ?)""",
        (corp_code, corp_name, title, content, summary, tags, disclosure_ref),
    )
    post_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return post_id


def search_companies(query: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM companies WHERE corp_name LIKE ? OR stock_code LIKE ? LIMIT 50",
        (f"%{query}%", f"%{query}%"),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_financials(corp_code: str, year: int | None = None) -> list[dict]:
    conn = get_connection()
    if year:
        rows = conn.execute(
            "SELECT * FROM financials WHERE corp_code=? AND year=? ORDER BY quarter, account_name",
            (corp_code, year),
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT * FROM financials WHERE corp_code=? ORDER BY year DESC, quarter, account_name",
            (corp_code,),
        ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_new_items(corp_code: str) -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM financials WHERE corp_code=? AND is_new_item=1 ORDER BY year DESC, quarter",
        (corp_code,),
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_blog_posts(corp_code: str | None = None, tag: str | None = None,
                   limit: int = 20) -> list[dict]:
    conn = get_connection()
    conditions = []
    params = []
    if corp_code:
        conditions.append("corp_code=?")
        params.append(corp_code)
    if tag:
        conditions.append("tags LIKE ?")
        params.append(f"%{tag}%")
    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    params.append(limit)
    rows = conn.execute(
        f"SELECT * FROM blog_posts {where} ORDER BY created_at DESC LIMIT ?",
        params,
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def get_all_tags() -> list[str]:
    conn = get_connection()
    rows = conn.execute("SELECT DISTINCT tags FROM blog_posts WHERE tags != ''").fetchall()
    conn.close()
    all_tags = set()
    for r in rows:
        for t in r[0].split(","):
            t = t.strip()
            if t:
                all_tags.add(t)
    return sorted(all_tags)


def get_unprocessed_disclosures() -> list[dict]:
    conn = get_connection()
    rows = conn.execute(
        "SELECT * FROM disclosures WHERE processed=0 ORDER BY rcept_dt DESC",
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def mark_disclosure_processed(rcept_no: str) -> None:
    conn = get_connection()
    conn.execute("UPDATE disclosures SET processed=1 WHERE rcept_no=?", (rcept_no,))
    conn.commit()
    conn.close()
