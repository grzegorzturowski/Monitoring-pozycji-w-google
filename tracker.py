"""Logika sprawdzania pozycji: łączy bazę danych z Google Search Console API."""

import sqlite3
from datetime import date, datetime, timedelta, timezone
from typing import Callable

import countries
import db

POPULARITY_SOURCE_TRENDS = "trends"
POPULARITY_SOURCE_ADS = "google_ads"

# search_console (Google API, ~5 s), trends (pytrends + pandas, ~2 s) i keyword_planner są importowane
# dopiero wewnątrz funkcji - dzięki temu okno aplikacji pojawia się od razu, a import
# odbywa się w wątku roboczym przy pierwszym sprawdzeniu.


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


def _missing_ranges(
    start_date: date,
    end_date: date,
    checked_from: str | None,
    checked_to: str | None,
    refresh_days: int = 0,
) -> list[tuple[date, date]]:
    """Zakresy dni z [start_date, end_date], których jeszcze nie sprawdzano
    (sprawdzony zakres frazy zawsze pozostaje ciągły). refresh_days > 0
    dodaje ponowne pobranie tylu dni przed end_date - Search Console potrafi
    jeszcze uzupełniać dane z ostatnich dni."""
    if not checked_from or not checked_to:
        return [(start_date, end_date)] if start_date <= end_date else []
    covered_from, covered_to = date.fromisoformat(checked_from), date.fromisoformat(checked_to)
    ranges = []
    if start_date < covered_from:
        ranges.append((start_date, covered_from - timedelta(days=1)))
    tail_start = covered_to + timedelta(days=1)
    if refresh_days > 0:
        tail_start = min(tail_start, end_date - timedelta(days=refresh_days))
    tail_start = max(tail_start, covered_from, start_date)
    if tail_start <= end_date:
        ranges.append((tail_start, end_date))
    return ranges


def run_sync(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
    refresh_days: int = 0,
) -> tuple[int, int]:
    """Pobiera z Search Console dzienne dane (pozycja, kliknięcia, wyświetlenia)
    wszystkich fraz projektu od daty początku danych projektu do dziś (z
    uwzględnieniem opóźnienia danych). Dni już wcześniej sprawdzone (zakres
    zapisany przy frazie) nie są pobierane ponownie - dociągane są tylko nowe
    dni, nowe frazy i starsze dni po przesunięciu daty początku wstecz.
    refresh_days: dodatkowo pobiera ponownie tyle ostatnich dni (Search
    Console uzupełnia je z opóźnieniem) - raz dziennie dla każdej frazy.
    Zwraca (liczba fraz, dla których coś pobrano, liczba zapisanych dziennych wpisów)."""
    data_delay_days = int(db.get_setting(conn, "data_delay_days") or 3)
    end_date = date.today() - timedelta(days=data_delay_days)
    start_date = date.fromisoformat(db.get_project_data_from(conn, project_id))

    coverage = db.get_data_coverage(conn, project_id)
    to_fetch = {
        kid: ranges
        for kid, (checked_from, checked_to, checked_at) in coverage.items()
        if (
            ranges := _missing_ranges(
                start_date,
                end_date,
                checked_from,
                checked_to,
                refresh_days=0 if _checked_today(checked_at) else refresh_days,
            )
        )
    }
    if not to_fetch:
        if progress_callback:
            progress_callback("Dane wszystkich fraz są aktualne.")
        return 0, 0  # nie ładujemy nawet klienta Search Console

    from search_console import get_keyword_daily_stats

    project, keywords, service = _load_common(conn, project_id)
    _, _, site_url = project
    country = countries.to_search_console(db.positions_country(*db.get_project_country(conn, project_id)))
    keywords = [k for k in keywords if k[0] in to_fetch]

    total_rows = 0
    for index, (keyword_id, keyword, page_url) in enumerate(keywords, start=1):
        for range_start, range_end in to_fetch[keyword_id]:
            if progress_callback:
                progress_callback(
                    f"Pobieram ({index}/{len(keywords)}): {keyword} - {range_start.isoformat()} do {range_end.isoformat()}"
                )
            daily_rows = get_keyword_daily_stats(
                service, site_url, keyword, range_start.isoformat(), range_end.isoformat(), page_url, country
            )
            _store_daily_rows(conn, keyword_id, daily_rows)
            total_rows += len(daily_rows)
        checked_from, checked_to, _checked_at = coverage[keyword_id]
        db.set_data_coverage(
            conn,
            keyword_id,
            min(filter(None, [checked_from, start_date.isoformat()])),
            max(filter(None, [checked_to, end_date.isoformat()])),
        )

    if progress_callback:
        progress_callback(f"Zakończono. Pobrano dane {len(keywords)} fraz, {total_rows} dziennych wpisów.")
    return len(keywords), total_rows


def _fetch_ads_search_volume(
    conn: sqlite3.Connection, keywords: list[str], geo: str
) -> tuple[dict[str, int | None], dict[str, dict[str, int]]]:
    from keyword_planner import get_search_volume_for_keywords

    settings = {
        key: (db.get_setting(conn, key) or "").strip()
        for key in ("ads_oauth_client_file", "ads_refresh_token", "ads_customer_id")
    }
    if not all(settings.values()):
        raise RuntimeError(
            "Google Ads nie jest skonfigurowane - uzupełnij w Ustawieniach ID konta, "
            "plik klienta OAuth i zaloguj się przyciskiem \"Zaloguj do Google Ads\"."
        )
    return get_search_volume_for_keywords(
        keywords,
        oauth_client_file=settings["ads_oauth_client_file"],
        refresh_token=settings["ads_refresh_token"],
        customer_id=settings["ads_customer_id"],
        login_customer_id=(db.get_setting(conn, "ads_login_customer_id") or "").strip(),
        geo=geo,
        language=(db.get_setting(conn, "ads_language") or "").strip(),
    )


def run_popularity_check(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
    skip_checked_within_days: int | None = None,
    skip_checked_today: bool = False,
) -> int:
    """Pobiera popularność każdej unikalnej frazy w projekcie - zależnie od
    ustawienia "popularity_source": średnią miesięczną liczbę wyszukiwań z
    Planera słów kluczowych Google Ads albo względną popularność (0-100) z
    Google Trends - i zapisuje ją przy wszystkich jej wpisach (tej samej
    frazy dla różnych podstron dotyczy ta sama popularność - to metryka
    samej frazy, niezależna od podstrony).
    skip_checked_within_days: pomija frazy, których popularność sprawdzano
    w ciągu tylu ostatnich dni (None = sprawdza wszystkie).
    skip_checked_today: pomija frazy, których popularność sprawdzano dzisiaj.
    Frazy bez wartości popularności nie są pomijane.
    Zwraca liczbę sprawdzonych unikalnych fraz."""
    keywords = db.list_keywords(conn, project_id)
    if not keywords:
        if progress_callback:
            progress_callback("Brak słów kluczowych do sprawdzenia.")
        return 0
    if skip_checked_within_days is not None or skip_checked_today:
        check_info = db.get_popularity_check_info(conn, project_id)
        ads_source = (db.get_setting(conn, "popularity_source") or POPULARITY_SOURCE_TRENDS) == POPULARITY_SOURCE_ADS
        with_monthly = set(db.get_monthly_searches_for_project(conn, project_id))

        def is_fresh(keyword_id: int, popularity: int | None, timestamp: str | None) -> bool:
            if popularity is None:
                return False  # brak wartości - warto spróbować ponownie
            if ads_source and popularity > 0 and keyword_id not in with_monthly:
                return False  # sprawdzona przed zapisywaniem liczb miesięcznych
            return (skip_checked_today and _checked_today(timestamp)) or (
                skip_checked_within_days is not None and _checked_within(timestamp, skip_checked_within_days)
            )

        stale_texts = {keyword for kid, keyword, _page in keywords if not is_fresh(kid, *check_info[kid])}
        keywords = [k for k in keywords if k[1] in stale_texts]
        if not keywords:
            if progress_callback:
                progress_callback("Popularność wszystkich fraz jest aktualna.")
            return 0

    unique_texts = list(dict.fromkeys(keyword for _kid, keyword, _page in keywords))
    source = db.get_setting(conn, "popularity_source") or POPULARITY_SOURCE_TRENDS
    if progress_callback:
        source_name = "Planera słów kluczowych Google Ads" if source == POPULARITY_SOURCE_ADS else "Google Trends"
        progress_callback(f"Pobieram popularność {len(unique_texts)} unikalnych fraz z {source_name}...")

    geo, _country_positions = db.get_project_country(conn, project_id)
    if source == POPULARITY_SOURCE_ADS:
        popularity_by_text, monthly_by_text = _fetch_ads_search_volume(conn, unique_texts, geo)
    else:
        from trends import get_popularity_for_keywords

        timeframe = db.get_setting(conn, "trends_timeframe") or "today 12-m"
        popularity_by_text = get_popularity_for_keywords(unique_texts, geo=geo, timeframe=timeframe)
        monthly_by_text = {}

    for keyword_id, keyword, _page_url in keywords:
        db.set_keyword_popularity(conn, keyword_id, popularity_by_text.get(keyword))
        db.set_monthly_searches(conn, keyword_id, monthly_by_text.get(keyword, {}))

    if progress_callback:
        found = sum(1 for v in popularity_by_text.values() if v is not None)
        progress_callback(f"Zakończono. Popularność pobrana dla {found}/{len(unique_texts)} fraz.")
    return len(unique_texts)


def configured_ai_engines(conn: sqlite3.Connection) -> dict[str, tuple[str, str]]:
    """{silnik: (klucz API, model)} - tylko asystenci AI, dla których podano klucz API w Ustawieniach."""
    from ai_visibility import ENGINES

    result = {}
    for engine, (_name, key_setting, model_setting, default_model) in ENGINES.items():
        api_key = (db.get_setting(conn, key_setting) or "").strip()
        if api_key:
            result[engine] = (api_key, (db.get_setting(conn, model_setting) or "").strip() or default_model)
    return result


def run_ai_visibility_check(
    conn: sqlite3.Connection,
    project_id: int,
    progress_callback: Callable[[str], None] | None = None,
    skip_checked_today: bool = True,
    only_failed: bool = False,
) -> tuple[int, list[str]]:
    """Zadaje każdą unikalną frazę projektu skonfigurowanym asystentom AI (Gemini z wyszukiwaniem
    w sieci) i zapisuje, czy domena projektu jest cytowana / wspomniana w odpowiedzi.
    skip_checked_today: pomija pary (fraza, asystent) sprawdzone dziś bez błędu.
    only_failed: sprawdza tylko pary, których ostatnie sprawdzenie zakończyło się błędem.
    Zwraca (liczba wykonanych zapytań, lista błędów "asystent - fraza: opis")."""
    import ai_visibility

    engines = configured_ai_engines(conn)
    if not engines:
        raise RuntimeError("Nie podano klucza API Gemini - uzupełnij go w Ustawieniach (sekcja \"Obecność w AI\").")
    project = db.get_project(conn, project_id)
    if project is None:
        raise ValueError("Nie znaleziono projektu.")
    domain = ai_visibility.domain_from_site_url(project[2])
    brand_terms = [t.strip() for t in db.get_project_ai_brand_terms(conn, project_id).split(",") if t.strip()]

    keywords = db.list_keywords(conn, project_id)
    ids_by_text: dict[str, list[int]] = {}
    for keyword_id, keyword, _page_url in keywords:
        ids_by_text.setdefault(keyword, []).append(keyword_id)

    latest = db.get_latest_ai_checks(conn, project_id) if skip_checked_today or only_failed else {}

    def engines_to_check(keyword_ids: list[int]) -> list[str]:
        if only_failed:
            return [
                engine
                for engine in engines
                if any((check := latest.get(kid, {}).get(engine)) and check["error"] for kid in keyword_ids)
            ]
        return [
            engine
            for engine in engines
            if not all(
                (check := latest.get(kid, {}).get(engine)) and not check["error"] and _checked_today(check["checked_at"])
                for kid in keyword_ids
            )
        ]

    todo = [(text, ids, todo_engines) for text, ids in ids_by_text.items() if (todo_engines := engines_to_check(ids))]
    if not todo:
        if progress_callback:
            progress_callback(
                "Brak fraz z błędem." if only_failed else "Obecność w AI wszystkich fraz sprawdzono już dzisiaj."
            )
        return 0, []

    queries = 0
    errors = []
    for index, (text, keyword_ids, todo_engines) in enumerate(todo, start=1):
        for engine in todo_engines:
            name = ai_visibility.ENGINES[engine][0]
            if progress_callback:
                progress_callback(f"Pytam {name} ({index}/{len(todo)}): {text}")
            api_key, model = engines[engine]
            result, error = None, ""
            try:
                result = ai_visibility.check(engine, text, api_key, model, domain, brand_terms)
            except ai_visibility.QuotaExceededError as e:
                # wyczerpany limit - pozostałe frazy też by się nie udały; nic nie zapisujemy
                errors.append(f"{name}: przerwano sprawdzanie po {queries} z {len(todo)} fraz.\n\n{e}")
                return queries, errors
            except Exception as e:  # noqa: BLE001 - błąd jednej frazy nie przerywa pozostałych
                error = str(e) or type(e).__name__
                errors.append(f"{name} - {text}: {error}")
            queries += 1
            for keyword_id in keyword_ids:
                db.insert_ai_check(conn, keyword_id, engine, result, error)

    if progress_callback:
        progress_callback(f"Zakończono. Wykonano {queries} zapytań do AI.")
    return queries, errors
