"""Warstwa dostępu do bazy SQLite: projekty, słowa kluczowe, historia pozycji, ustawienia."""

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "monitoring.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    site_url TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS keywords (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    keyword TEXT NOT NULL,
    page_url TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    popularity INTEGER,
    popularity_checked_at TEXT,
    positions_checked_at TEXT,
    UNIQUE(project_id, keyword, page_url)
);

CREATE TABLE IF NOT EXISTS positions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    checked_at TEXT NOT NULL,
    position REAL,
    clicks INTEGER,
    impressions INTEGER,
    ctr REAL,
    period_start TEXT NOT NULL,
    period_end TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SETTINGS = {
    "service_account_file": "service-account.json",
    "date_range_days": "7",
    "data_delay_days": "3",
    "trends_geo": "PL",
    "trends_timeframe": "today 12-m",
}


def _migrate(conn: sqlite3.Connection) -> None:
    """Dostosowuje wcześniej utworzone bazy do aktualnego schematu.

    UWAGA: tabelę-rodzica (keywords) trzeba zastąpić nową tabelą pod inną
    nazwą i na końcu zmienić jej nazwę - a NIE odwrotnie (rename starej na
    "_old" i potem ją dropnąć) - bo SQLite przy RENAME automatycznie
    przepisuje odwołanie klucza obcego w "positions" na nową nazwę, a
    następujący potem DROP TABLE z ON DELETE CASCADE kasowałby wtedy całą
    powiązaną historię pozycji."""
    columns = [row[1] for row in conn.execute("PRAGMA table_info(keywords)")]
    if "page_url" not in columns:
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.executescript(
            """
            CREATE TABLE keywords_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
                keyword TEXT NOT NULL,
                page_url TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                UNIQUE(project_id, keyword, page_url)
            );
            INSERT INTO keywords_new (id, project_id, keyword, page_url, created_at)
                SELECT id, project_id, keyword, '', created_at FROM keywords;
            DROP TABLE keywords;
            ALTER TABLE keywords_new RENAME TO keywords;
            """
        )
        conn.commit()
        conn.execute("PRAGMA foreign_keys = ON")

    columns = [row[1] for row in conn.execute("PRAGMA table_info(keywords)")]
    if "popularity" not in columns:
        conn.execute("ALTER TABLE keywords ADD COLUMN popularity INTEGER")
        conn.execute("ALTER TABLE keywords ADD COLUMN popularity_checked_at TEXT")
        conn.commit()

    columns = [row[1] for row in conn.execute("PRAGMA table_info(keywords)")]
    if "positions_checked_at" not in columns:
        conn.execute("ALTER TABLE keywords ADD COLUMN positions_checked_at TEXT")
        # startowo: moment ostatniego zapisanego pomiaru frazy
        conn.execute(
            "UPDATE keywords SET positions_checked_at = "
            "(SELECT MAX(checked_at) FROM positions WHERE keyword_id = keywords.id)"
        )
        conn.commit()

    # Wcześniejsza wersja aplikacji wstawiała pozycje bez sprawdzania duplikatów,
    # więc dla tego samego (słowo kluczowe, okres) mogło powstać kilka wierszy.
    # Unikalny indeks poniżej wymaga ich usunięcia - zostawiamy tylko najnowszy
    # (o najwyższym id) wiersz z każdej grupy.
    conn.execute(
        """
        DELETE FROM positions
        WHERE id NOT IN (
            SELECT MAX(id) FROM positions GROUP BY keyword_id, period_start, period_end
        )
        """
    )
    conn.commit()
    conn.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_positions_period ON positions(keyword_id, period_start, period_end)"
    )
    conn.commit()


def connect() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    _migrate(conn)
    for key, value in DEFAULT_SETTINGS.items():
        conn.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, value))
    conn.commit()
    return conn


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# --- ustawienia ---

def get_setting(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_setting(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
    conn.commit()


# --- projekty ---

def list_projects(conn: sqlite3.Connection):
    return conn.execute("SELECT id, name, site_url FROM projects ORDER BY name").fetchall()


def get_project(conn: sqlite3.Connection, project_id: int):
    return conn.execute("SELECT id, name, site_url FROM projects WHERE id = ?", (project_id,)).fetchone()


def add_project(conn: sqlite3.Connection, name: str, site_url: str) -> int:
    cur = conn.execute(
        "INSERT INTO projects (name, site_url, created_at) VALUES (?, ?, ?)",
        (name, site_url, _now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def update_project(conn: sqlite3.Connection, project_id: int, name: str, site_url: str) -> None:
    conn.execute(
        "UPDATE projects SET name = ?, site_url = ? WHERE id = ?",
        (name, site_url, project_id),
    )
    conn.commit()


def delete_project(conn: sqlite3.Connection, project_id: int) -> None:
    conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
    conn.commit()


# --- słowa kluczowe ---

def list_keywords(conn: sqlite3.Connection, project_id: int):
    """Zwraca (id, keyword, page_url) - page_url pusty oznacza całą domenę."""
    return conn.execute(
        "SELECT id, keyword, page_url FROM keywords WHERE project_id = ? ORDER BY keyword", (project_id,)
    ).fetchall()


def list_keywords_with_popularity(conn: sqlite3.Connection, project_id: int):
    """Zwraca (id, popularity) - popularity None, jeśli nie była jeszcze sprawdzana."""
    return conn.execute(
        "SELECT id, popularity FROM keywords WHERE project_id = ? ORDER BY keyword", (project_id,)
    ).fetchall()


def get_keyword_check_times(conn: sqlite3.Connection, project_id: int) -> dict[int, tuple[str | None, str | None]]:
    """Zwraca {id: (positions_checked_at, popularity_checked_at)} - znaczniki czasu UTC w ISO albo None."""
    rows = conn.execute(
        "SELECT id, positions_checked_at, popularity_checked_at FROM keywords WHERE project_id = ?", (project_id,)
    ).fetchall()
    return {kid: (positions_at, popularity_at) for kid, positions_at, popularity_at in rows}


def mark_positions_checked(conn: sqlite3.Connection, keyword_id: int) -> None:
    conn.execute("UPDATE keywords SET positions_checked_at = ? WHERE id = ?", (_now_iso(), keyword_id))
    conn.commit()


def set_keyword_popularity(conn: sqlite3.Connection, keyword_id: int, popularity: int | None) -> None:
    conn.execute(
        "UPDATE keywords SET popularity = ?, popularity_checked_at = ? WHERE id = ?",
        (popularity, _now_iso(), keyword_id),
    )
    conn.commit()


def add_keyword(conn: sqlite3.Connection, project_id: int, keyword: str, page_url: str = "") -> int:
    cur = conn.execute(
        "INSERT OR IGNORE INTO keywords (project_id, keyword, page_url, created_at) VALUES (?, ?, ?, ?)",
        (project_id, keyword.strip(), page_url.strip(), _now_iso()),
    )
    conn.commit()
    return cur.lastrowid


def delete_keyword(conn: sqlite3.Connection, keyword_id: int) -> None:
    conn.execute("DELETE FROM keywords WHERE id = ?", (keyword_id,))
    conn.commit()


# --- pozycje ---

def insert_position(
    conn: sqlite3.Connection,
    keyword_id: int,
    stats: dict | None,
    period_start: str,
    period_end: str,
) -> None:
    """Zapisuje pomiar dla danego okresu. Jeśli pomiar dla tego samego
    (słowa kluczowego, okresu) już istnieje - nadpisuje go (przydatne przy
    ponownym pobieraniu historii wstecznej)."""
    conn.execute(
        """
        INSERT INTO positions (keyword_id, checked_at, position, clicks, impressions, ctr, period_start, period_end)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(keyword_id, period_start, period_end) DO UPDATE SET
            checked_at = excluded.checked_at,
            position = excluded.position,
            clicks = excluded.clicks,
            impressions = excluded.impressions,
            ctr = excluded.ctr
        """,
        (
            keyword_id,
            _now_iso(),
            stats["position"] if stats else None,
            stats["clicks"] if stats else None,
            stats["impressions"] if stats else None,
            stats["ctr"] if stats else None,
            period_start,
            period_end,
        ),
    )
    conn.commit()


def get_history(conn: sqlite3.Connection, keyword_id: int):
    """Zwraca (period_end, position, clicks, impressions, ctr) w porządku chronologicznym."""
    return conn.execute(
        """
        SELECT period_end, position, clicks, impressions, ctr
        FROM positions WHERE keyword_id = ? ORDER BY period_end
        """,
        (keyword_id,),
    ).fetchall()


def get_last_period_end(conn: sqlite3.Connection, keyword_id: int) -> str | None:
    """Zwraca najpóźniejszy period_end zapisany dla słowa kluczowego (albo None, gdy brak historii)."""
    row = conn.execute("SELECT MAX(period_end) FROM positions WHERE keyword_id = ?", (keyword_id,)).fetchone()
    return row[0] if row else None


def get_latest_for_project(conn: sqlite3.Connection, project_id: int):
    """Dla każdego słowa kluczowego projektu zwraca jego pomiar o najpóźniejszym
    period_end (czyli faktycznie najbardziej aktualne dane, niezależnie od tego,
    kiedy sprawdzenie zostało uruchomione) oraz najlepszą (najniższą liczbowo)
    pozycję, jaka kiedykolwiek została dla niego zanotowana."""
    return conn.execute(
        """
        SELECT k.id, k.keyword, k.page_url, p.period_end, p.position, p.clicks, p.impressions, p.ctr,
            (SELECT MIN(position) FROM positions WHERE keyword_id = k.id AND position IS NOT NULL) AS best_position,
            k.popularity
        FROM keywords k
        LEFT JOIN positions p ON p.id = (
            SELECT id FROM positions WHERE keyword_id = k.id ORDER BY period_end DESC LIMIT 1
        )
        WHERE k.project_id = ?
        ORDER BY k.keyword
        """,
        (project_id,),
    ).fetchall()
