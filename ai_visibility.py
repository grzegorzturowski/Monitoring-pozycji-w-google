"""Sprawdzanie obecności domeny w odpowiedziach Gemini z groundingiem w
wyszukiwarce Google (wyszukiwanie w sieci).

Każda fraza kluczowa jest wysyłana do Gemini tak, jak wpisałby ją
użytkownik. W odpowiedzi sprawdzamy:
- czy domena jest wśród źródeł (linków), na które powołuje się AI ("cytowana"),
  i na którym miejscu na liście źródeł,
- czy domena albo nazwa marki pada w samym tekście odpowiedzi ("wspomniana").

Odpowiedzi AI są niedeterministyczne - ten sam wynik przy kolejnym pytaniu
może się różnić, dlatego warto patrzeć na trend z wielu sprawdzeń.
"""

import re
from urllib.parse import urlparse

import requests

ENGINE_GEMINI = "gemini"

# id silnika: (nazwa wyświetlana, klucz ustawienia z kluczem API, klucz ustawienia z modelem, domyślny model)
# gemini-3.1-flash-lite - najtańszy dostępny model z groundingiem (10.2026: $0.25/$1.50 za 1M tokenów
# wej./wyj., 5000 wyszukiwań miesięcznie gratis, potem $14 / 1000). Modele 2.5 nie są już dostępne
# dla nowych kont (HTTP 404).
ENGINES = {
    ENGINE_GEMINI: ("Gemini", "ai_gemini_key", "ai_gemini_model", "gemini-3.1-flash-lite"),
}

REQUEST_TIMEOUT = 180  # s - odpowiedź z wyszukiwaniem w sieci potrafi trwać ponad minutę


# ---------- dopasowanie domeny ----------

def domain_from_site_url(site_url: str) -> str:
    """"sc-domain:mojadomena.pl" / "https://www.mojadomena.pl/" -> "mojadomena.pl"."""
    site_url = site_url.strip()
    if site_url.startswith("sc-domain:"):
        host = site_url[len("sc-domain:"):]
    else:
        host = urlparse(site_url if "://" in site_url else f"https://{site_url}").hostname or site_url
    host = host.strip().strip("/").lower()
    return host[4:] if host.startswith("www.") else host


def _host_matches(url_or_title: str, domain: str) -> bool:
    host = (urlparse(url_or_title).hostname or "") if "://" in url_or_title else url_or_title
    host = host.strip().lower()
    return host == domain or host.endswith("." + domain)


def source_matches(source: dict, domain: str) -> bool:
    """Czy źródło {"url", "title"} pochodzi z domeny. Tytuł też jest sprawdzany - Gemini podaje
    zamiast adresów stron linki przekierowujące, a domenę źródła w tytule."""
    return _host_matches(source.get("url") or "", domain) or _host_matches(source.get("title") or "", domain)


def _text_mentions(text: str, terms: list[str]) -> bool:
    """Czy tekst zawiera któreś z określeń (całe słowo, bez rozróżniania wielkości liter)."""
    lowered = text.casefold()
    return any(re.search(rf"(?<!\w){re.escape(term.casefold())}(?!\w)", lowered) for term in terms if term)


def evaluate(answer: str, sources: list[dict], domain: str, brand_terms: list[str]) -> dict:
    """Wynik sprawdzenia: cited (bool), citation_rank (1-based albo None), mentioned (bool).
    sources: [{"url": ..., "title": ...}] w kolejności, w jakiej podało je AI."""
    rank = next((index for index, source in enumerate(sources, start=1) if source_matches(source, domain)), None)
    return {
        "cited": rank is not None,
        "citation_rank": rank,
        "mentioned": _text_mentions(answer, [domain, *brand_terms]),
    }


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    seen = set()
    result = []
    for source in sources:
        url = source.get("url") or ""
        if url and url not in seen:
            seen.add(url)
            result.append({"url": url, "title": source.get("title") or ""})
    return result


# ---------- Gemini ----------

class QuotaExceededError(RuntimeError):
    """Limit API wyczerpany (HTTP 429) - kolejne zapytania też się nie udadzą, nie ma sensu ich wysyłać."""


def _raise_for_status(response: requests.Response, engine_name: str) -> None:
    if response.ok:
        return
    try:
        error = response.json().get("error")
        message = error.get("message") if isinstance(error, dict) else error
    except ValueError:
        message = None
    text = f"{engine_name}: HTTP {response.status_code} - {message or response.text[:500]}"
    if response.status_code == 429:
        raise QuotaExceededError(
            f"{text}\n\nWyszukiwanie Google w Gemini (grounding) wymaga projektu z włączonymi płatnościami - na "
            "darmowym planie jego limit wynosi 0. Włącz płatności w https://aistudio.google.com/ (Billing) dla "
            "projektu tego klucza API. 5000 wyszukiwań miesięcznie nadal jest gratis. Jeśli płatności są już "
            "włączone, to wyczerpano limit zapytań na minutę/dzień - spróbuj później."
        )
    raise RuntimeError(text)


def _ask_gemini(query: str, api_key: str, model: str) -> tuple[str, list[dict]]:
    """Gemini API z groundingiem w wyszukiwarce Google (kraju nie da się tu ustawić)."""
    response = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent",
        headers={"x-goog-api-key": api_key},
        json={"contents": [{"parts": [{"text": query}]}], "tools": [{"google_search": {}}]},
        timeout=REQUEST_TIMEOUT,
    )
    _raise_for_status(response, "Gemini")
    candidates = response.json().get("candidates") or []
    if not candidates:
        raise RuntimeError("Gemini nie zwróciło odpowiedzi.")
    candidate = candidates[0]
    text = "".join(part.get("text", "") for part in (candidate.get("content") or {}).get("parts", []))
    chunks = (candidate.get("groundingMetadata") or {}).get("groundingChunks") or []
    sources = [{"url": c["web"].get("uri"), "title": c["web"].get("title")} for c in chunks if "web" in c]
    return text, _dedupe_sources(sources)


_ASK = {
    ENGINE_GEMINI: _ask_gemini,
}


def check(engine: str, query: str, api_key: str, model: str, domain: str, brand_terms: list[str]) -> dict:
    """Zadaje frazę asystentowi AI i zwraca {"answer", "sources", "cited", "citation_rank", "mentioned"}."""
    answer, sources = _ASK[engine](query, api_key, model)
    return {"answer": answer, "sources": sources, **evaluate(answer, sources, domain, brand_terms)}
