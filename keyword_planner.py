"""Pobieranie średniej miesięcznej liczby wyszukiwań fraz z Planera słów
kluczowych Google Ads (oficjalne Google Ads API, KeywordPlanIdeaService).

W przeciwieństwie do Google Trends są to bezwzględne liczby (średnia
miesięczna liczba wyszukiwań z ostatnich 12 miesięcy), porównywalne między
wszystkimi frazami. Przy bardzo małych wolumenach Google i tak je zaokrągla,
a na kontach bez aktywnych kampanii może zwracać mniej dokładne wartości.

Wymaga (od 9.09.2026 tokeny dewelopera nie są już używane):
- projektu Google Cloud z przyznanym poziomem dostępu do Google Ads API
  innym niż testowy (dostęp testowy działa tylko z kontami testowymi, które
  nie mają prawdziwych danych planera),
- klienta OAuth z tego projektu typu "Aplikacja komputerowa" (plik JSON z Google Cloud) oraz
  refresh tokenu uzyskanego przez jednorazowe logowanie (authorize()).
"""

import json

SCOPES = ["https://www.googleapis.com/auth/adwords"]
MONTH_NAMES = [
    "JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE",
    "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER",
]
MAX_KEYWORDS_PER_REQUEST = 1000  # limit API to 10 000, mniejsze partie są bezpieczniejsze


def _read_oauth_client(oauth_client_file: str) -> tuple[str, str]:
    with open(oauth_client_file, encoding="utf-8") as f:
        data = json.load(f)
    client = data.get("installed") or data.get("web")
    if not client:
        raise RuntimeError("Plik klienta OAuth nie zawiera sekcji \"installed\" - utwórz klienta typu "
                           "\"Aplikacja komputerowa\" w Google Cloud.")
    return client["client_id"], client["client_secret"]


def authorize(oauth_client_file: str) -> str:
    """Otwiera przeglądarkę z logowaniem Google i zwraca refresh token
    (wystarczy zrobić to raz - token jest potem zapisywany w ustawieniach)."""
    from google_auth_oauthlib.flow import InstalledAppFlow

    flow = InstalledAppFlow.from_client_secrets_file(oauth_client_file, scopes=SCOPES)
    credentials = flow.run_local_server(port=0, prompt="consent", access_type="offline")
    if not credentials.refresh_token:
        raise RuntimeError("Google nie zwróciło refresh tokenu - spróbuj zalogować się ponownie.")
    return credentials.refresh_token


def _normalize_customer_id(customer_id: str) -> str:
    return customer_id.replace("-", "").replace(" ", "").strip()


def _build_client(oauth_client_file: str, refresh_token: str, login_customer_id: str = ""):
    from google.ads.googleads.client import GoogleAdsClient

    client_id, client_secret = _read_oauth_client(oauth_client_file)
    config = {
        "client_id": client_id,
        "client_secret": client_secret,
        "refresh_token": refresh_token,
        "use_proto_plus": True,
    }
    if login_customer_id:
        config["login_customer_id"] = _normalize_customer_id(login_customer_id)
    return GoogleAdsClient.load_from_dict(config)


def _format_ads_error(e) -> str:
    """Czytelny opis błędu GoogleAdsException (domyślny str() to długi zrzut protobufa)."""
    messages = [error.message for error in e.failure.errors]
    return "; ".join(messages) or str(e)


def _monthly_volumes(item) -> dict[str, int]:
    """{"RRRR-MM": liczba wyszukiwań} z wyniku planera (miesiące bez liczby są pomijane)."""
    volumes = {}
    for entry in item.keyword_metrics.monthly_search_volumes:
        if "monthly_searches" not in entry or entry.month.name not in MONTH_NAMES:
            continue
        month_number = MONTH_NAMES.index(entry.month.name) + 1
        volumes[f"{entry.year:04d}-{month_number:02d}"] = entry.monthly_searches
    return volumes


def _find_constant(client, customer_id: str, query: str, what: str) -> str:
    service = client.get_service("GoogleAdsService")
    for row in service.search(customer_id=customer_id, query=query):
        constant = row.geo_target_constant if "geo_target_constant" in row else row.language_constant
        return constant.resource_name
    raise RuntimeError(f"Google Ads nie zna {what}.")


def get_search_volume_for_keywords(
    keywords: list[str],
    oauth_client_file: str,
    refresh_token: str,
    customer_id: str,
    login_customer_id: str = "",
    geo: str = "PL",
    language: str = "pl",
) -> tuple[dict[str, int | None], dict[str, dict[str, int]]]:
    """Zwraca ({fraza: średnia_miesięczna_liczba_wyszukiwań_lub_None},
    {fraza: {"RRRR-MM": liczba_wyszukiwań_w_miesiącu}}) - liczby z ostatnich 12 miesięcy.
    0 = Google zna frazę, ale ma mniej niż ~10 wyszukiwań miesięcznie (nie podaje liczby),
    None = Google nie zwróciło frazy wcale.
    geo: kod kraju ISO (puste = cały świat), language: kod języka (np. "pl", puste = wszystkie)."""
    from google.ads.googleads.errors import GoogleAdsException

    customer_id = _normalize_customer_id(customer_id)
    unique_keywords = list(dict.fromkeys(keywords))
    result: dict[str, int | None] = {kw: None for kw in unique_keywords}
    monthly: dict[str, dict[str, int]] = {}

    try:
        client = _build_client(oauth_client_file, refresh_token, login_customer_id)
        geo_resource = (
            _find_constant(
                client,
                customer_id,
                "SELECT geo_target_constant.resource_name FROM geo_target_constant "
                f"WHERE geo_target_constant.country_code = '{geo.upper()}' "
                "AND geo_target_constant.target_type = 'Country'",
                f"kraju o kodzie \"{geo}\"",
            )
            if geo
            else None
        )
        language_resource = (
            _find_constant(
                client,
                customer_id,
                "SELECT language_constant.resource_name FROM language_constant "
                f"WHERE language_constant.code = '{language.lower()}'",
                f"języka o kodzie \"{language}\"",
            )
            if language
            else None
        )

        service = client.get_service("KeywordPlanIdeaService")
        # Planer normalizuje frazy (m.in. małe litery) - dopasowujemy wyniki bez rozróżniania wielkości liter
        by_lower = {kw.lower(): kw for kw in unique_keywords}
        for i in range(0, len(unique_keywords), MAX_KEYWORDS_PER_REQUEST):
            request = client.get_type("GenerateKeywordHistoricalMetricsRequest")
            request.customer_id = customer_id
            request.keywords.extend(unique_keywords[i : i + MAX_KEYWORDS_PER_REQUEST])
            if geo_resource:
                request.geo_target_constants.append(geo_resource)
            if language_resource:
                request.language = language_resource
            request.keyword_plan_network = client.enums.KeywordPlanNetworkEnum.GOOGLE_SEARCH

            response = service.generate_keyword_historical_metrics(request=request)
            for item in response.results:
                # fraza zwrócona bez liczby wyszukiwań = poniżej progu Google (< 10 miesięcznie) -> 0
                has_volume = "keyword_metrics" in item and "avg_monthly_searches" in item.keyword_metrics
                volume = item.keyword_metrics.avg_monthly_searches if has_volume else 0
                item_monthly = _monthly_volumes(item) if has_volume else {}
                # wynik może dotyczyć bliskiego wariantu - przypisz go wszystkim pasującym frazom
                for text in [item.text, *item.close_variants]:
                    original = by_lower.get(text.lower())
                    if original is not None and not result[original]:
                        result[original] = volume
                        monthly[original] = item_monthly
    except GoogleAdsException as e:
        raise RuntimeError(
            f"Błąd Google Ads API: {_format_ads_error(e)}\n\n"
            "Jeśli błąd dotyczy uprawnień: Planer słów kluczowych (KeywordPlanIdeaService) wymaga poziomu "
            "dostępu Basic lub Standard projektu Google Cloud - na poziomie Testowanie i Eksplorator jest "
            "zablokowany."
        ) from e

    return result, monthly
