"""Warstwa dostępu do bazy SQLite: projekty, słowa kluczowe, historia pozycji, ustawienia."""

import json
import sqlite3
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "monitoring.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    site_url TEXT NOT NULL,
    created_at TEXT NOT NULL,
    data_from TEXT,
    country TEXT NOT NULL DEFAULT '',
    country_positions INTEGER NOT NULL DEFAULT 0,
    ai_brand_terms TEXT NOT NULL DEFAULT ''
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
    data_checked_from TEXT,
    data_checked_to TEXT,
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

CREATE TABLE IF NOT EXISTS keyword_monthly_searches (
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    month TEXT NOT NULL,
    searches INTEGER NOT NULL,
    PRIMARY KEY (keyword_id, month)
);

CREATE TABLE IF NOT EXISTS ai_checks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    keyword_id INTEGER NOT NULL REFERENCES keywords(id) ON DELETE CASCADE,
    engine TEXT NOT NULL,
    checked_at TEXT NOT NULL,
    cited INTEGER,
    citation_rank INTEGER,
    mentioned INTEGER,
    answer TEXT,
    sources TEXT,
    error TEXT
);

CREATE INDEX IF NOT EXISTS idx_ai_checks_keyword ON ai_checks(keyword_id, engine, checked_at);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);
"""

DEFAULT_SETTINGS = {
    "service_account_file": "service-account.json",
    "data_delay_days": "3",
    "trends_timeframe": "today 12-m",
    "popularity_source": "trends",
    "ads_language": "pl",
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

    # Zakres dni sprawdzonych w Search Console (także dni bez wyświetleń, których
    # Search Console nie zwraca) - pozwala nie pobierać drugi raz tych samych dni.
    columns = [row[1] for row in conn.execute("PRAGMA table_info(keywords)")]
    if "data_checked_from" not in columns:
        conn.execute("ALTER TABLE keywords ADD COLUMN data_checked_from TEXT")
        conn.execute("ALTER TABLE keywords ADD COLUMN data_checked_to TEXT")
        # Wcześniejsze "Sprawdź teraz" zapisywało średnią z kilku dni pod datą końca
        # okresu - mieszała się na wykresach z danymi dziennymi. Usuwamy je; te dni
        # zostaną pobrane ponownie jako dane dzienne.
        conn.execute("DELETE FROM positions WHERE period_start != period_end")
        # startowo: zakres zapisanych danych dziennych
        conn.execute(
            """
            UPDATE keywords SET
                data_checked_from = (SELECT MIN(period_end) FROM positions WHERE keyword_id = keywords.id),
                data_checked_to = (SELECT MAX(period_end) FROM positions WHERE keyword_id = keywords.id)
            """
        )
        conn.commit()

    # Data, od której sprawdzane są dane projektu (wspólna dla wszystkich jego fraz).
    project_columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
    if "data_from" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN data_from TEXT")
        # startowo: najwcześniejszy już sprawdzony dzień fraz projektu
        conn.execute(
            """
            UPDATE projects SET data_from = COALESCE(
                (SELECT MIN(data_checked_from) FROM keywords WHERE project_id = projects.id), ?
            )
            """,
            (default_data_from(),),
        )
        conn.commit()

    # Kraj projektu (dwuliterowy kod ISO, pusty = cały świat) - zawęża popularność
    # fraz, a przy country_positions = 1 także dane z Search Console.
    project_columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
    if "country" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN country TEXT NOT NULL DEFAULT ''")
        conn.execute("ALTER TABLE projects ADD COLUMN country_positions INTEGER NOT NULL DEFAULT 0")
        # startowo: dotychczasowy globalny kraj popularności; pozycje bez zawężania,
        # bo zapisana historia pochodzi ze wszystkich krajów
        row = conn.execute("SELECT value FROM settings WHERE key = 'trends_geo'").fetchone()
        conn.execute("UPDATE projects SET country = ?", ((row[0] if row else "PL") or "",))
        conn.commit()

    # Nazwy marki projektu (po przecinku) - szukane w odpowiedziach asystentów AI.
    project_columns = [row[1] for row in conn.execute("PRAGMA table_info(projects)")]
    if "ai_brand_terms" not in project_columns:
        conn.execute("ALTER TABLE projects ADD COLUMN ai_brand_terms TEXT NOT NULL DEFAULT ''")
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


def default_data_from() -> str:
    """Domyślna data początku danych nowego projektu - 90 dni wstecz."""
    return (date.today() - timedelta(days=90)).isoformat()


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


def get_project_data_from(conn: sqlite3.Connection, project_id: int) -> str:
    row = conn.execute("SELECT data_from FROM projects WHERE id = ?", (project_id,)).fetchone()
    return (row[0] if row else None) or default_data_from()


def get_project_country(conn: sqlite3.Connection, project_id: int) -> tuple[str, bool]:
    """Zwraca (kod kraju ISO - pusty = cały świat, czy zawężać do niego dane z Search Console)."""
    row = conn.execute("SELECT country, country_positions FROM projects WHERE id = ?", (project_id,)).fetchone()
    return (row[0], bool(row[1])) if row else ("", False)


def positions_country(country: str, country_positions: bool) -> str:
    """Kraj, do którego zawężane są dane z Search Console ("" = wszystkie kraje)."""
    return country if country_positions else ""


def get_project_ai_brand_terms(conn: sqlite3.Connection, project_id: int) -> str:
    """Nazwy marki projektu szukane w odpowiedziach AI - tekst z przecinkami, jak wpisał użytkownik."""
    row = conn.execute("SELECT ai_brand_terms FROM projects WHERE id = ?", (project_id,)).fetchone()
    return row[0] if row else ""


def add_project(
    conn: sqlite3.Connection,
    name: str,
    site_url: str,
    data_from: str,
    country: str,
    country_positions: bool,
    ai_brand_terms: str = "",
) -> int:
    cur = conn.execute(
        "INSERT INTO projects (name, site_url, created_at, data_from, country, country_positions, ai_brand_terms) "
        "VALUES (?, ?, ?, ?, ?, ?, ?)",
        (name, site_url, _now_iso(), data_from, country, int(country_positions), ai_brand_terms),
    )
    conn.commit()
    return cur.lastrowid


def update_project(
    conn: sqlite3.Connection,
    project_id: int,
    name: str,
    site_url: str,
    data_from: str,
    country: str,
    country_positions: bool,
    ai_brand_terms: str = "",
) -> None:
    """Zapisuje projekt. Zmiana kraju czyści popularność fraz projektu, a zmiana
    kraju, do którego zawężane są dane Search Console - całą historię pozycji
    projektu (dane z innego zakresu krajów nie dają się porównać)."""
    old_country, old_country_positions = get_project_country(conn, project_id)
    conn.execute(
        "UPDATE projects SET name = ?, site_url = ?, data_from = ?, country = ?, country_positions = ?, "
        "ai_brand_terms = ? WHERE id = ?",
        (name, site_url, data_from, country, int(country_positions), ai_brand_terms, project_id),
    )
    if country != old_country:
        conn.execute(
            "UPDATE keywords SET popularity = NULL, popularity_checked_at = NULL WHERE project_id = ?",
            (project_id,),
        )
        conn.execute(
            "DELETE FROM keyword_monthly_searches WHERE keyword_id IN (SELECT id FROM keywords WHERE project_id = ?)",
            (project_id,),
        )
    if positions_country(country, country_positions) != positions_country(old_country, old_country_positions):
        conn.execute(
            "DELETE FROM positions WHERE keyword_id IN (SELECT id FROM keywords WHERE project_id = ?)",
            (project_id,),
        )
        conn.execute(
            "UPDATE keywords SET data_checked_from = NULL, data_checked_to = NULL, positions_checked_at = NULL "
            "WHERE project_id = ?",
            (project_id,),
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


def get_popularity_check_info(conn: sqlite3.Connection, project_id: int) -> dict[int, tuple[int | None, str | None]]:
    """Zwraca {id: (popularity, popularity_checked_at)} - znacznik czasu UTC w ISO albo None."""
    rows = conn.execute(
        "SELECT id, popularity, popularity_checked_at FROM keywords WHERE project_id = ?", (project_id,)
    ).fetchall()
    return {kid: (popularity, checked_at) for kid, popularity, checked_at in rows}


def get_data_coverage(
    conn: sqlite3.Connection, project_id: int
) -> dict[int, tuple[str | None, str | None, str | None]]:
    """Zwraca {id: (data_checked_from, data_checked_to, positions_checked_at)} - zakres dni (ISO)
    już sprawdzonych w Search Console i moment ostatniego pobrania (UTC, ISO)."""
    rows = conn.execute(
        "SELECT id, data_checked_from, data_checked_to, positions_checked_at FROM keywords WHERE project_id = ?",
        (project_id,),
    ).fetchall()
    return {kid: (checked_from, checked_to, checked_at) for kid, checked_from, checked_to, checked_at in rows}


def set_data_coverage(conn: sqlite3.Connection, keyword_id: int, checked_from: str, checked_to: str) -> None:
    conn.execute(
        "UPDATE keywords SET data_checked_from = ?, data_checked_to = ?, positions_checked_at = ? WHERE id = ?",
        (checked_from, checked_to, _now_iso(), keyword_id),
    )
    conn.commit()


def set_keyword_popularity(conn: sqlite3.Connection, keyword_id: int, popularity: int | None) -> None:
    conn.execute(
        "UPDATE keywords SET popularity = ?, popularity_checked_at = ? WHERE id = ?",
        (popularity, _now_iso(), keyword_id),
    )
    conn.commit()


def clear_all_popularity(conn: sqlite3.Connection) -> None:
    """Czyści popularność wszystkich fraz (np. po zmianie jej źródła - wartości z
    Google Trends i Google Ads są w innych skalach i nie wolno ich mieszać)."""
    conn.execute("UPDATE keywords SET popularity = NULL, popularity_checked_at = NULL")
    conn.execute("DELETE FROM keyword_monthly_searches")
    conn.commit()


def set_monthly_searches(conn: sqlite3.Connection, keyword_id: int, monthly: dict[str, int]) -> None:
    """Zastępuje miesięczne liczby wyszukiwań frazy ({"RRRR-MM": liczba}) z Google Ads."""
    conn.execute("DELETE FROM keyword_monthly_searches WHERE keyword_id = ?", (keyword_id,))
    conn.executemany(
        "INSERT INTO keyword_monthly_searches (keyword_id, month, searches) VALUES (?, ?, ?)",
        [(keyword_id, month, searches) for month, searches in monthly.items()],
    )
    conn.commit()


def get_monthly_searches_for_project(conn: sqlite3.Connection, project_id: int) -> dict[int, dict[str, int]]:
    """Zwraca {id_frazy: {"RRRR-MM": liczba_wyszukiwań}} dla fraz projektu."""
    result: dict[int, dict[str, int]] = {}
    rows = conn.execute(
        """
        SELECT m.keyword_id, m.month, m.searches FROM keyword_monthly_searches m
        JOIN keywords k ON k.id = m.keyword_id WHERE k.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    for keyword_id, month, searches in rows:
        result.setdefault(keyword_id, {})[month] = searches
    return result


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

# data początku danych projektu, do którego należy fraza (parametr: id frazy)
_DATA_FROM_OF_KEYWORD = (
    "SELECT COALESCE(p.data_from, '') FROM keywords kk JOIN projects p ON p.id = kk.project_id WHERE kk.id = ?"
)

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
    """Zwraca (period_end, position, clicks, impressions, ctr) w porządku chronologicznym -
    tylko dni od daty początku danych projektu."""
    return conn.execute(
        f"""
        SELECT period_end, position, clicks, impressions, ctr
        FROM positions WHERE keyword_id = ? AND period_end >= ({_DATA_FROM_OF_KEYWORD})
        ORDER BY period_end
        """,
        (keyword_id, keyword_id),
    ).fetchall()


def get_latest_for_project(conn: sqlite3.Connection, project_id: int):
    """Dla każdego słowa kluczowego projektu zwraca AKTUALNE dane - pomiar z
    ostatniego sprawdzonego dnia (data_checked_to). Jeśli tego dnia strona nie
    miała wyświetleń dla frazy, pozycja/kliknięcia/wyświetlenia są None (a nie
    ostatnio znane wartości). Do tego najlepsza (najniższa liczbowo) pozycja,
    jaka kiedykolwiek została zanotowana, popularność i data, od której dni są
    sprawdzone w Search Console."""
    # pod uwagę brane są tylko dni od daty początku danych projektu
    return conn.execute(
        """
        SELECT k.id, k.keyword, k.page_url, k.data_checked_to, p.position, p.clicks, p.impressions, p.ctr,
            (
                SELECT MIN(position) FROM positions
                WHERE keyword_id = k.id AND position IS NOT NULL AND period_end >= pr.data_from
            ) AS best_position,
            k.popularity, MAX(k.data_checked_from, pr.data_from)
        FROM keywords k
        JOIN projects pr ON pr.id = k.project_id
        LEFT JOIN positions p ON p.keyword_id = k.id
            AND p.period_start = k.data_checked_to AND p.period_end = k.data_checked_to
        WHERE k.project_id = ?
        ORDER BY k.keyword
        """,
        (project_id,),
    ).fetchall()


def get_traffic_averages(
    conn: sqlite3.Connection, project_id: int, windows: tuple[int, ...] = (7, 30)
) -> dict[int, dict[int, tuple[float, float] | None]]:
    """Dla każdego słowa kluczowego projektu zwraca {id: {liczba dni: (średnie
    dzienne wyświetlenia, średnie dzienne kliknięcia) albo None}} - z ostatnich
    `liczba dni` sprawdzonych dni (kończąc na data_checked_to). Dni sprawdzone,
    w których Search Console nie zanotowało wyświetleń, liczą się jako 0. Jeśli
    sprawdzony zakres jest krótszy niż okno, średnia liczona jest z dostępnych dni."""
    keywords = conn.execute(
        """
        SELECT k.id, k.data_checked_to, MAX(k.data_checked_from, pr.data_from)
        FROM keywords k JOIN projects pr ON pr.id = k.project_id
        WHERE k.project_id = ?
        """,
        (project_id,),
    ).fetchall()
    result = {}
    for keyword_id, checked_to, checked_from in keywords:
        averages = {}
        for days in windows:
            averages[days] = None
            if not checked_to or not checked_from:
                continue
            end = date.fromisoformat(checked_to)
            start = max(end - timedelta(days=days - 1), date.fromisoformat(checked_from))
            day_count = (end - start).days + 1
            if day_count <= 0:
                continue
            impressions, clicks = conn.execute(
                """
                SELECT COALESCE(SUM(impressions), 0), COALESCE(SUM(clicks), 0) FROM positions
                WHERE keyword_id = ? AND period_start = period_end AND period_end BETWEEN ? AND ?
                """,
                (keyword_id, start.isoformat(), end.isoformat()),
            ).fetchone()
            averages[days] = (impressions / day_count, clicks / day_count)
        result[keyword_id] = averages
    return result


# --- obecność w AI ---

def insert_ai_check(conn: sqlite3.Connection, keyword_id: int, engine: str, result: dict | None, error: str = "") -> None:
    """Zapisuje jedno sprawdzenie frazy w asystencie AI (result z ai_visibility.check albo None przy błędzie).
    Historia jest zachowywana - każde sprawdzenie to osobny wiersz."""
    conn.execute(
        """
        INSERT INTO ai_checks (keyword_id, engine, checked_at, cited, citation_rank, mentioned, answer, sources, error)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            keyword_id,
            engine,
            _now_iso(),
            int(result["cited"]) if result else None,
            result["citation_rank"] if result else None,
            int(result["mentioned"]) if result else None,
            result["answer"] if result else None,
            json.dumps(result["sources"], ensure_ascii=False) if result else None,
            error or None,
        ),
    )
    conn.commit()


def get_latest_ai_checks(conn: sqlite3.Connection, project_id: int) -> dict[int, dict[str, dict]]:
    """Zwraca {id_frazy: {silnik: {"checked_at", "cited", "citation_rank", "mentioned", "answer",
    "sources", "error"}}} - najnowsze sprawdzenie każdej frazy projektu w każdym asystencie AI."""
    rows = conn.execute(
        """
        SELECT a.keyword_id, a.engine, a.checked_at, a.cited, a.citation_rank, a.mentioned, a.answer, a.sources, a.error
        FROM ai_checks a JOIN keywords k ON k.id = a.keyword_id
        WHERE k.project_id = ? AND a.id = (
            SELECT MAX(id) FROM ai_checks WHERE keyword_id = a.keyword_id AND engine = a.engine
        )
        """,
        (project_id,),
    ).fetchall()
    result: dict[int, dict[str, dict]] = {}
    for keyword_id, engine, checked_at, cited, rank, mentioned, answer, sources, error in rows:
        result.setdefault(keyword_id, {})[engine] = {
            "checked_at": checked_at,
            "cited": None if cited is None else bool(cited),
            "citation_rank": rank,
            "mentioned": None if mentioned is None else bool(mentioned),
            "answer": answer or "",
            "sources": json.loads(sources) if sources else [],
            "error": error,
        }
    return result


def get_ai_history_for_project(conn: sqlite3.Connection, project_id: int) -> list[tuple[str, str, int, int]]:
    """Zwraca [(dzień RRRR-MM-DD (UTC), silnik, liczba sprawdzonych fraz, liczba fraz z cytowaną domeną)]
    - bez sprawdzeń zakończonych błędem; przy kilku sprawdzeniach frazy jednego dnia liczy się ostatnie."""
    return conn.execute(
        """
        SELECT day, engine, COUNT(*), SUM(cited) FROM (
            SELECT substr(a.checked_at, 1, 10) AS day, a.engine, a.cited
            FROM ai_checks a JOIN keywords k ON k.id = a.keyword_id
            WHERE k.project_id = ? AND a.error IS NULL AND a.id = (
                SELECT MAX(id) FROM ai_checks
                WHERE keyword_id = a.keyword_id AND engine = a.engine AND error IS NULL
                    AND substr(checked_at, 1, 10) = substr(a.checked_at, 1, 10)
            )
        )
        GROUP BY day, engine ORDER BY day
        """,
        (project_id,),
    ).fetchall()
