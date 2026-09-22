"""Pobieranie względnej popularności fraz z Google Trends.

UWAGA: To nieoficjalne API (biblioteka pytrends odpytuje wewnętrzne, nie
udokumentowane endpointy Google Trends) - w przeciwieństwie do Search
Console może się zepsuć, jeśli Google zmieni swój wewnętrzny interfejs, i
bywa czasem ograniczane limitami zapytań (błędy 429).

Liczby zwracane przez Google Trends to WZGLĘDNE zainteresowanie w skali
0-100, znormalizowane do najwyższego punktu W OBRĘBIE JEDNEGO zapytania
porównawczego (maks. 5 fraz na raz). Nie są to realne liczby wyszukiwań i
są porównywalne tylko pomiędzy frazami sprawdzonymi w tej samej partii.
"""

import time

from pytrends.request import TrendReq

MAX_KEYWORDS_PER_BATCH = 5


def _fetch_batch(keywords: list[str], geo: str, timeframe: str) -> dict[str, int | None]:
    pytrends = TrendReq(hl="pl-PL", tz=60)
    try:
        pytrends.build_payload(keywords, timeframe=timeframe, geo=geo)
        df = pytrends.interest_over_time()
    except Exception as e:  # noqa: BLE001 - pytrends zgłasza różne typy wyjątków (429, połączenie, itp.)
        raise RuntimeError(f"Błąd Google Trends dla fraz {keywords}: {e}") from e

    result: dict[str, int | None] = {}
    for kw in keywords:
        if df.empty or kw not in df.columns:
            result[kw] = None
        else:
            result[kw] = round(float(df[kw].mean()))
    return result


def get_popularity_for_keywords(
    keywords: list[str], geo: str = "PL", timeframe: str = "today 12-m"
) -> dict[str, int | None]:
    """Zwraca {fraza: popularność_0_100_lub_None} dla podanej listy unikalnych fraz.
    Frazy są dzielone na partie po maks. 5 (limit Google Trends)."""
    unique_keywords = list(dict.fromkeys(keywords))  # zachowaj kolejność, usuń duplikaty
    result: dict[str, int | None] = {}

    for i in range(0, len(unique_keywords), MAX_KEYWORDS_PER_BATCH):
        batch = unique_keywords[i : i + MAX_KEYWORDS_PER_BATCH]
        result.update(_fetch_batch(batch, geo, timeframe))
        if i + MAX_KEYWORDS_PER_BATCH < len(unique_keywords):
            time.sleep(1)  # odstęp między partiami, żeby zmniejszyć ryzyko limitu zapytań

    return result
