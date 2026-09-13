"""Klient Google Search Console API (Search Analytics) - pobieranie średniej
pozycji Twojej witryny (lub konkretnej podstrony) dla wybranej frazy kluczowej."""

from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/webmasters.readonly"]


def build_service(service_account_file: str):
    credentials = service_account.Credentials.from_service_account_file(service_account_file, scopes=SCOPES)
    return build("searchconsole", "v1", credentials=credentials, cache_discovery=False)


def _query_filters(keyword: str, page_url: str = "") -> list[dict]:
    filters = [{"dimension": "query", "operator": "equals", "expression": keyword.lower()}]
    if page_url:
        filters.append({"dimension": "page", "operator": "equals", "expression": page_url})
    return filters


def _run_query(service, site_url: str, body: dict) -> dict:
    try:
        return service.searchanalytics().query(siteUrl=site_url, body=body).execute()
    except HttpError as e:
        raise RuntimeError(f"Błąd Search Console API dla {site_url}: {e}") from e


def get_keyword_stats(
    service, site_url: str, keyword: str, start_date: str, end_date: str, page_url: str = ""
) -> dict | None:
    """Zwraca statystyki (position, clicks, impressions, ctr) dla dokładnej frazy
    (opcjonalnie zawężone do jednej podstrony) zagregowane w podanym okresie,
    albo None jeśli Google nie zarejestrowało żadnych wyświetleń w tym okresie."""
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["query"],
        "dimensionFilterGroups": [{"filters": _query_filters(keyword, page_url)}],
        "rowLimit": 1,
    }

    rows = _run_query(service, site_url, body).get("rows", [])
    if not rows:
        return None

    row = rows[0]
    return {
        "position": row.get("position"),
        "clicks": row.get("clicks"),
        "impressions": row.get("impressions"),
        "ctr": row.get("ctr"),
    }


def get_keyword_daily_stats(
    service, site_url: str, keyword: str, start_date: str, end_date: str, page_url: str = ""
) -> list[dict]:
    """Zwraca dzienną historię (date, position, clicks, impressions, ctr) dla
    frazy w podanym okresie - jednym zapytaniem, przydatne do sprawdzania
    pozycji wstecz (Search Console przechowuje dane ok. 16 miesięcy)."""
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "dimensions": ["date", "query"],
        "dimensionFilterGroups": [{"filters": _query_filters(keyword, page_url)}],
        "rowLimit": 1000,
    }

    rows = _run_query(service, site_url, body).get("rows", [])
    return [
        {
            "date": row["keys"][0],
            "position": row.get("position"),
            "clicks": row.get("clicks"),
            "impressions": row.get("impressions"),
            "ctr": row.get("ctr"),
        }
        for row in rows
    ]
