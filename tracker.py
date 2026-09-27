"""Logika sprawdzania pozycji: łączy bazę danych z Google Search Console API."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import db

# search_console (Google API, ~5 s) i trends (pytrends + pandas, ~2 s) są importowane
# dopiero wewnątrz funkcji - dzięki temu okno aplikacji pojawia się od razu, a import
# odbywa się w wątku roboczym przy pierwszym sprawdzeniu.


def compute_date_range(date_range_days: int, data_delay_days: int) -> tuple[str, str]:
    end_date = date.today() - timedelta(days=data_delay_days)
    start_date = end_date - timedelta(days=date_range_days - 1)
    return start_date.isoformat(), end_date.isoformat()


def _load_common(conn: sqlite3.Connection, project_id: int):
    from search_console import build_service

    service_account_file = db.get_setting(conn, "service_account_file")
    if not service_account_file:
        raise RuntimeError("Nie skonfigurowano pliku konta usługi (Ustawienia).")

    project = db.get_project(conn, project_id)
    if project is None:
        raise ValueError("Nie znaleziono projektu.")

    keywords = db.list_keywords(conn, project_id)
    service = build_service(service_account_file)
    return project, keywords, service


def _checked_today(timestamp: str | None) -> bool:
    """Czy znacznik czasu (UTC, ISO) przypada na dzisiejszy dzień w lokalnej strefie czasowej."""
    return timestamp is not None and datetime.fromisoformat(timestamp).astimezone().date() == date.today()


def _checked_within(timestamp: str | None, days: int) -> bool:
    return timestamp is not None and datetime.now(timezone.utc) - datetime.fromisoformat(timestamp) < timedelta(
        days=days
    )


def _store_daily_rows(conn: sqlite3.Connection, keyword_id: int, daily_rows: list[dict]) -> None:
    for row in daily_rows:
        stats = {
            "position": row["position"],
            "clicks": row["clicks"],
            "impressions": row["impressions"],
            "ctr": row["ctr"],
        }
        db.insert_position(conn, keyword_id, stats, row["date"], row["date"])


def run_update_since_last_check(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
) -> int:
    """Dla każdego słowa kluczowego projektu pobiera dzienne dane od daty
    ostatniego zapisanego pomiaru do dziś (z uwzględnieniem opóźnienia danych
    Search Console). Ostatni zapisany dzień jest pobierany ponownie, bo Search
    Console potrafi jeszcze uzupełniać najświeższe dane. Frazy bez żadnej
    historii dostają dane z ostatnich `date_range_days` dni.
    Frazy, których pozycje były już dziś aktualizowane, są pomijane.
    Zwraca (liczba zaktualizowanych fraz, liczba zapisanych dziennych wpisów)."""
    from search_console import get_keyword_daily_stats

    check_times = db.get_keyword_check_times(conn, project_id)
    to_update = {kid for kid, (positions_at, _popularity_at) in check_times.items() if not _checked_today(positions_at)}
    if not to_update:
        return 0, 0  # wszystko sprawdzone dziś - nie ładujemy nawet klienta Search Console

    project, keywords, service = _load_common(conn, project_id)
    _, _, site_url = project
    keywords = [k for k in keywords if k[0] in to_update]

    date_range_days = int(db.get_setting(conn, "date_range_days") or 7)
    data_delay_days = int(db.get_setting(conn, "data_delay_days") or 3)
    end_date = date.today() - timedelta(days=data_delay_days)

    total_rows = 0
    for index, (keyword_id, keyword, page_url) in enumerate(keywords, start=1):
        last_period_end = db.get_last_period_end(conn, keyword_id)
        if last_period_end:
            start_date = date.fromisoformat(last_period_end)
        else:
            start_date = end_date - timedelta(days=date_range_days - 1)
        if start_date <= end_date:
            if progress_callback:
                progress_callback(f"Aktualizuję ({index}/{len(keywords)}): {keyword} od {start_date.isoformat()}")
            daily_rows = get_keyword_daily_stats(
                service, site_url, keyword, start_date.isoformat(), end_date.isoformat(), page_url
            )
            _store_daily_rows(conn, keyword_id, daily_rows)
            total_rows += len(daily_rows)
        db.mark_positions_checked(conn, keyword_id)

    return len(keywords), total_rows


def run_check(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
) -> None:
    """Sprawdza aktualną (uśrednioną z ostatnich N dni) pozycję wszystkich
    słów kluczowych danego projektu i zapisuje wyniki w bazie."""
    from search_console import get_keyword_stats

    project, keywords, service = _load_common(conn, project_id)
    _, _, site_url = project

    if not keywords:
        if progress_callback:
            progress_callback("Brak słów kluczowych do sprawdzenia.")
        return

    date_range_days = int(db.get_setting(conn, "date_range_days") or 7)
    data_delay_days = int(db.get_setting(conn, "data_delay_days") or 3)
    start_str, end_str = compute_date_range(date_range_days, data_delay_days)

    for index, (keyword_id, keyword, page_url) in enumerate(keywords, start=1):
        if progress_callback:
            progress_callback(f"Sprawdzam ({index}/{len(keywords)}): {keyword}")
        stats = get_keyword_stats(service, site_url, keyword, start_str, end_str, page_url)
        db.insert_position(conn, keyword_id, stats, start_str, end_str)
        db.mark_positions_checked(conn, keyword_id)

    if progress_callback:
        progress_callback("Zakończono.")


def run_backfill(
    conn: sqlite3.Connection,
    project_id: int,
    days_back: int,
    progress_callback: Callable[[str], None] | None = None,
) -> None:
    """Pobiera dzienną historię pozycji za ostatnie `days_back` dni (z
    uwzględnieniem opóźnienia danych Search Console) i zapisuje ją w bazie -
    pozwala uzupełnić wykresy o dane sprzed instalacji aplikacji."""
    from search_console import get_keyword_daily_stats

    project, keywords, service = _load_common(conn, project_id)
    _, _, site_url = project

    if not keywords:
        if progress_callback:
            progress_callback("Brak słów kluczowych do sprawdzenia.")
        return

    data_delay_days = int(db.get_setting(conn, "data_delay_days") or 3)
    end_date = date.today() - timedelta(days=data_delay_days)
    start_date = end_date - timedelta(days=days_back - 1)
    start_str, end_str = start_date.isoformat(), end_date.isoformat()

    total_rows = 0
    for index, (keyword_id, keyword, page_url) in enumerate(keywords, start=1):
        if progress_callback:
            progress_callback(f"Pobieram historię ({index}/{len(keywords)}): {keyword}")
        daily_rows = get_keyword_daily_stats(service, site_url, keyword, start_str, end_str, page_url)
        _store_daily_rows(conn, keyword_id, daily_rows)
        db.mark_positions_checked(conn, keyword_id)
        total_rows += len(daily_rows)
        if progress_callback:
            info = f"znaleziono dane z {len(daily_rows)} dni" if daily_rows else "brak wyświetleń w tym okresie"
            progress_callback(f"({index}/{len(keywords)}) {keyword}: {info}")

    if progress_callback:
        if total_rows:
            progress_callback(f"Zakończono. Pobrano łącznie {total_rows} dziennych wpisów.")
        else:
            progress_callback(
                "Zakończono - Search Console nie zwróciło żadnych wyświetleń dla wybranych fraz w tym okresie."
            )


def run_popularity_check(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
    skip_checked_within_days: int | None = None,
) -> int:
    """Pobiera z Google Trends względną popularność (0-100) każdej unikalnej
    frazy w projekcie i zapisuje ją przy wszystkich jej wpisach (tej samej
    frazy dla różnych podstron dotyczy ta sama popularność - to metryka
    samej frazy, niezależna od podstrony).
    skip_checked_within_days: pomija frazy, których popularność sprawdzano
    w ciągu tylu ostatnich dni (None = sprawdza wszystkie).
    Zwraca liczbę sprawdzonych unikalnych fraz."""
    keywords = db.list_keywords(conn, project_id)
    if skip_checked_within_days is not None:
        check_times = db.get_keyword_check_times(conn, project_id)
        stale_texts = {
            keyword
            for kid, keyword, _page in keywords
            if not _checked_within(check_times[kid][1], skip_checked_within_days)
        }
        keywords = [k for k in keywords if k[1] in stale_texts]
    if not keywords:
        if progress_callback:
            progress_callback("Brak słów kluczowych do sprawdzenia.")
        return 0

    from trends import get_popularity_for_keywords

    geo = db.get_setting(conn, "trends_geo") or "PL"
    timeframe = db.get_setting(conn, "trends_timeframe") or "today 12-m"

    unique_texts = list(dict.fromkeys(keyword for _kid, keyword, _page in keywords))
    if progress_callback:
        progress_callback(f"Pobieram popularność {len(unique_texts)} unikalnych fraz z Google Trends...")

    popularity_by_text = get_popularity_for_keywords(unique_texts, geo=geo, timeframe=timeframe)

    for keyword_id, keyword, _page_url in keywords:
        db.set_keyword_popularity(conn, keyword_id, popularity_by_text.get(keyword))

    if progress_callback:
        found = sum(1 for v in popularity_by_text.values() if v is not None)
        progress_callback(f"Zakończono. Popularność pobrana dla {found}/{len(unique_texts)} fraz.")
    return len(unique_texts)
