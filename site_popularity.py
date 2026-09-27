"""Wskaźnik popularności (widoczności) całej strony w czasie - wypadkowa
pozycji wszystkich fraz projektu ważonych ich "mocą" (popularnością z
Google Trends).

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


def expected_ctr(position: float) -> float:
    if position <= CTR_CURVE[0][0]:
        return CTR_CURVE[0][1]
    for (p1, c1), (p2, c2) in zip(CTR_CURVE, CTR_CURVE[1:]):
        if position <= p2:
            return c1 + (c2 - c1) * (position - p1) / (p2 - p1)
    return 0.0


def _keyword_weights(conn: sqlite3.Connection, project_id: int) -> dict[int, float]:
    keywords = db.list_keywords_with_popularity(conn, project_id)
    known = [p for _kid, p in keywords if p is not None]
    default_weight = sum(known) / len(known) if known else 1.0
    weights = {kid: float(p) if p is not None else default_weight for kid, p in keywords}
    if weights and sum(weights.values()) == 0:
        # wszystkie frazy mają popularność 0 - traktujemy je jednakowo
        weights = {kid: 1.0 for kid in weights}
    return weights


def compute_site_popularity(conn: sqlite3.Connection, project_id: int) -> list[tuple[str, float]]:
    """Zwraca [(data_iso, wskaźnik_0_100), ...] dla każdego dnia od pierwszego do ostatniego pomiaru."""
    weights = _keyword_weights(conn, project_id)
    if not weights:
        return []

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

    max_score = sum(weights.values()) * expected_ctr(1)
    last_known: dict[int, tuple[date, float]] = {}
    result = []
    day, last_day = min(all_days), max(all_days)
    while day <= last_day:
        score = 0.0
        for keyword_id, weight in weights.items():
            positions = positions_by_keyword[keyword_id]
            if day in positions:
                if positions[day] is None:
                    last_known.pop(keyword_id, None)
                else:
                    last_known[keyword_id] = (day, positions[day])
            known = last_known.get(keyword_id)
            if known and (day - known[0]).days <= CARRY_FORWARD_DAYS:
                score += weight * expected_ctr(known[1])
        result.append((day.isoformat(), 100 * score / max_score))
        day += timedelta(days=1)

    return result
