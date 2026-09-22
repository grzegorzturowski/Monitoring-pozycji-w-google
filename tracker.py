"""Logika sprawdzania pozycji: łączy bazę danych z Google Search Console API."""

import sqlite3
from datetime import date, timedelta
from typing import Callable

import db
from search_console import build_service, get_keyword_daily_stats, get_keyword_stats
from trends import get_popularity_for_keywords


def compute_date_range(date_range_days: int, data_delay_days: int) -> tuple[str, str]:
    end_date = date.today() - timedelta(days=data_delay_days)
    start_date = end_date - timedelta(days=date_range_days - 1)
    return start_date.isoformat(), end_date.isoformat()


def _load_common(conn: sqlite3.Connection, project_id: int):
    service_account_file = db.get_setting(conn, "service_account_file")
    if not service_account_file:
        raise RuntimeError("Nie skonfigurowano pliku konta usługi (Ustawienia).")

    project = db.get_project(conn, project_id)
    if project is None:
        raise ValueError("Nie znaleziono projektu.")

    keywords = db.list_keywords(conn, project_id)
    service = build_service(service_account_file)
    return project, keywords, service


def run_check(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
) -> None:
    """Sprawdza aktualną (uśrednioną z ostatnich N dni) pozycję wszystkich
    słów kluczowych danego projektu i zapisuje wyniki w bazie."""
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
        for row in daily_rows:
            stats = {
                "position": row["position"],
                "clicks": row["clicks"],
                "impressions": row["impressions"],
                "ctr": row["ctr"],
            }
            db.insert_position(conn, keyword_id, stats, row["date"], row["date"])
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
) -> None:
    """Pobiera z Google Trends względną popularność (0-100) każdej unikalnej
    frazy w projekcie i zapisuje ją przy wszystkich jej wpisach (tej samej
    frazy dla różnych podstron dotyczy ta sama popularność - to metryka
    samej frazy, niezależna od podstrony)."""
    keywords = db.list_keywords(conn, project_id)
    if not keywords:
        if progress_callback:
            progress_callback("Brak słów kluczowych do sprawdzenia.")
        return

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
