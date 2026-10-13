"""Wskaźnik popularności (widoczności) całej strony w czasie - wypadkowa
pozycji wszystkich fraz projektu ważonych ich "mocą" (popularnością z
Google Ads - liczba wyszukiwań - albo z Google Trends).

Dla każdego dnia:
    wynik = suma(moc_frazy * oczekiwany_CTR(pozycja_frazy))
    wskaźnik = 100 * wynik / suma(moc_frazy * oczekiwany_CTR(1))

czyli procent maksymalnej możliwej widoczności (100 = wszystkie frazy na
pozycji 1). Oczekiwany CTR to przybliżona krzywa klikalności wyników Google -
pozycja 1 jest warta dużo więcej niż pozycja 10, a dalej niż 30 praktycznie nic.

Search Console zwraca dane tylko z dni, w których fraza miała wyświetlenia,
dlatego ostatnio znana pozycja frazy jest "przenoszona" na kolejne dni przez
maks. CARRY_FORWARD_DAYS dni - dopiero potem (albo wcześniej, jeśli pomiar
wprost pokazał brak wyświetleń) fraza liczy się jako niewidoczna.
Frazy bez sprawdzonej popularności dostają średnią moc pozostałych fraz.
Przy źródle Google Ads frazy z wartością 0 (poniżej progu Google, < 10
wyszukiwań miesięcznie) dostają moc ADS_BELOW_THRESHOLD_WEIGHT.

Przy źródle Google Ads moc frazy zmienia się w czasie: dla każdego dnia
brana jest liczba wyszukiwań z jego miesiąca (Google Ads podaje ostatnie 12
miesięcy). Dla dni spoza tych 12 miesięcy (np. bieżący miesiąc, którego Google
jeszcze nie podsumował) używany jest ten sam miesiąc kalendarzowy z dostępnych
danych - zachowuje to sezonowość. Bez danych miesięcznych - średnia z 12 miesięcy.
Wskaźnik każdego dnia jest liczony względem maksimum przy mocach z tego dnia.
"""

import sqlite3
from datetime import date, timedelta

import db

# (pozycja, oczekiwany CTR) - wartości pośrednie są interpolowane liniowo
CTR_CURVE = [
    (1, 0.28),
    (2, 0.15),
    (3, 0.11),
    (4, 0.08),
    (5, 0.07),
    (6, 0.05),
    (7, 0.04),
    (8, 0.03),
    (9, 0.03),
    (10, 0.025),
    (20, 0.01),
    (30, 0.0),
]

CARRY_FORWARD_DAYS = 14
ADS_BELOW_THRESHOLD_WEIGHT = 5.0  # szacunkowa liczba wyszukiwań fraz "< 10" z Google Ads


def expected_ctr(position: float) -> float:
    if position <= CTR_CURVE[0][0]:
        return CTR_CURVE[0][1]
    for (p1, c1), (p2, c2) in zip(CTR_CURVE, CTR_CURVE[1:]):
        if position <= p2:
            return c1 + (c2 - c1) * (position - p1) / (p2 - p1)
    return 0.0


def _keyword_weights(conn: sqlite3.Connection, project_id: int) -> dict[int, float]:
    keywords = db.list_keywords_with_popularity(conn, project_id)
    if db.get_setting(conn, "popularity_source") == "google_ads":
        keywords = [(kid, ADS_BELOW_THRESHOLD_WEIGHT if p == 0 else p) for kid, p in keywords]
    known = [p for _kid, p in keywords if p is not None]
    default_weight = sum(known) / len(known) if known else 1.0
    weights = {kid: float(p) if p is not None else default_weight for kid, p in keywords}
    if weights and sum(weights.values()) == 0:
        # wszystkie frazy mają popularność 0 - traktujemy je jednakowo
        weights = {kid: 1.0 for kid in weights}
    return weights


def _monthly_weight_lookup(conn: sqlite3.Connection, project_id: int):
    """Zwraca funkcję (id_frazy, dzień) -> moc frazy w tym dniu albo None (brak danych miesięcznych)."""
    if db.get_setting(conn, "popularity_source") != "google_ads":
        return lambda _keyword_id, _day: None
    monthly = db.get_monthly_searches_for_project(conn, project_id)
    # ten sam miesiąc kalendarzowy z dostępnych danych (najnowszy rok) - dla dni spoza 12 miesięcy
    by_calendar_month = {
        kid: {int(month[5:]): searches for month, searches in sorted(months.items())}
        for kid, months in monthly.items()
    }

    def lookup(keyword_id: int, day: date) -> float | None:
        months = monthly.get(keyword_id)
        if not months:
            return None
        searches = months.get(f"{day.year:04d}-{day.month:02d}")
        if searches is None:
            searches = by_calendar_month[keyword_id].get(day.month)
        return float(searches) if searches is not None else None

    return lookup


def compute_site_popularity(conn: sqlite3.Connection, project_id: int) -> list[tuple[str, float]]:
    """Zwraca [(data_iso, wskaźnik_0_100), ...] dla każdego dnia od pierwszego do ostatniego pomiaru."""
    weights = _keyword_weights(conn, project_id)
    if not weights:
        return []
    monthly_weight = _monthly_weight_lookup(conn, project_id)

    # pozycja None = pomiar bez wyświetleń - przerywa przenoszenie ostatnio znanej pozycji
    positions_by_keyword: dict[int, dict[date, float | None]] = {}
    for keyword_id in weights:
        positions_by_keyword[keyword_id] = {
            date.fromisoformat(period_end): position
            for period_end, position, *_ in db.get_history(conn, keyword_id)
        }

    all_days = [
        d for positions in positions_by_keyword.values() for d, position in positions.items() if position is not None
    ]
    if not all_days:
        return []

    last_known: dict[int, tuple[date, float]] = {}
    result = []
    day, last_day = min(all_days), max(all_days)
    while day <= last_day:
        score = max_score = 0.0
        for keyword_id, default_weight in weights.items():
            weight = monthly_weight(keyword_id, day)
            if weight is None:
                weight = default_weight
            max_score += weight * expected_ctr(1)
            positions = positions_by_keyword[keyword_id]
            if day in positions:
                if positions[day] is None:
                    last_known.pop(keyword_id, None)
                else:
                    last_known[keyword_id] = (day, positions[day])
            known = last_known.get(keyword_id)
            if known and (day - known[0]).days <= CARRY_FORWARD_DAYS:
                score += weight * expected_ctr(known[1])
        result.append((day.isoformat(), 100 * score / max_score if max_score else 0.0))
        day += timedelta(days=1)

    return result


AGGREGATION_DAY = "day"
AGGREGATION_WEEK = "week"
AGGREGATION_MONTH = "month"


def aggregate_series(series: list[tuple[str, float]], aggregation: str) -> list[tuple[str, str, float]]:
    """Grupuje dzienną serię [(data_iso, wskaźnik), ...] w okresy (tydzień od
    poniedziałku albo miesiąc kalendarzowy) i zwraca [(początek_iso, koniec_iso,
    średni wskaźnik), ...]. Koniec to ostatni dzień okresu, z którego są dane -
    pierwszy i ostatni okres mogą być niepełne. Dla AGGREGATION_DAY każdy dzień
    jest osobnym okresem."""
    groups: dict[date, list[tuple[date, float]]] = {}
    for day_iso, value in series:
        day = date.fromisoformat(day_iso)
        if aggregation == AGGREGATION_WEEK:
            key = day - timedelta(days=day.weekday())
        elif aggregation == AGGREGATION_MONTH:
            key = day.replace(day=1)
        else:
            key = day
        groups.setdefault(key, []).append((day, value))
    return [
        (start.isoformat(), max(d for d, _ in points).isoformat(), sum(v for _, v in points) / len(points))
        for start, points in sorted(groups.items())
    ]
