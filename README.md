# Monitoring pozycji w Google

Aplikacja desktopowa (GUI w CustomTkinter) do śledzenia średniej pozycji
Twoich domen dla wybranych fraz kluczowych, na podstawie danych z **Google
Search Console**. Wszystko obsługuje się z okna aplikacji - dodawanie
projektów (domen), słów kluczowych, sprawdzanie pozycji, wykresy w czasie i
statystyki.

Ograniczenia, o których warto wiedzieć:

- Dane pojawiają się dopiero, gdy Google zarejestruje wyświetlenie Twojej
  strony dla danej frazy - jeśli fraza nie generuje żadnych wyświetleń,
  aplikacja pokaże "brak danych" zamiast np. "pozycja 100+".
- Search Console publikuje dane z opóźnieniem 2-3 dni.
- Pozycja to **średnia** z wybranego okresu (domyślnie 7 dni), a nie wynik
  pojedynczego wyszukiwania w danym momencie.

## 1. Konfiguracja Google Search Console API (konto usługi)

1. Upewnij się, że obie domeny są dodane i zweryfikowane w
   https://search.google.com/search-console (jako usługa typu "domena" albo
   "prefiks adresu URL").
2. Wejdź na https://console.cloud.google.com/, utwórz/wybierz projekt.
3. Włącz API: https://console.cloud.google.com/apis/library/searchconsole.googleapis.com
   (przycisk "Włącz").
4. Przejdź do "Dane uwierzytelniające" (Credentials) → "Utwórz dane
   uwierzytelniające" → **Konto usługi** (Service account). Nadaj dowolną
   nazwę, resztę kroków możesz pominąć (Dalej/Gotowe).
5. Wejdź w utworzone konto usługi → zakładka "Klucze" (Keys) → "Dodaj klucz"
   → "Utwórz nowy klucz" → typ **JSON**. Pobierze się plik JSON - zapisz go
   np. jako `service-account.json` w katalogu projektu.
6. Skopiuj adres e-mail konta usługi (wygląda jak
   `nazwa@projekt.iam.gserviceaccount.com` - znajdziesz go też w pobranym
   pliku JSON, pole `client_email`).
7. Wróć do Google Search Console → dla **każdej** z monitorowanych domen:
   Ustawienia → Użytkownicy i uprawnienia → Dodaj użytkownika → wklej e-mail
   konta usługi → uprawnienie **"Pełny"** (Full) lub **"Ograniczony"**
   (Restricted - wystarczy do samego odczytu danych o pozycjach).

## 2. Instalacja

```
pip install -r requirements.txt
```

## 3. Uruchomienie

```
python main.py
```

(albo dwuklik na `main.py`, jeśli masz skojarzone pliki `.py` z Pythonem).

Przy pierwszym uruchomieniu:

1. Kliknij **"Ustawienia"** w panelu bocznym i wskaż plik
   `service-account.json` pobrany w kroku 1 (przycisk "Wybierz...").
   Możesz tam też zmienić okres agregacji pozycji i opóźnienie danych.
2. Kliknij **"+ Nowy projekt"** i dodaj domenę - `site_url` musi dokładnie
   odpowiadać nazwie usługi widocznej w Search Console (sprawdź typ w
   Ustawienia → Informacje o usłudze):
   - usługa typu **"Domena"** → wpisz `sc-domain:mojadomena.pl`
   - usługa typu **"Prefiks adresu URL"** → wpisz dokładnie zweryfikowany
     adres, razem z ukośnikiem na końcu, np. `https://mojadomena.pl/`
3. Powtórz dla drugiej domeny - w panelu bocznym możesz swobodnie
   **przełączać się między projektami**, a przyciskiem "Edytuj projekt"
   poprawić nazwę/`site_url` bez utraty zapisanej historii.

## 4. Codzienne korzystanie

W zakładce **"Słowa kluczowe"**:
- dodawaj frazy do śledzenia dla aktualnie wybranego projektu. Pole
  "Podstrona" jest opcjonalne - zostaw je puste, aby śledzić pozycję dla
  całej domeny, albo wpisz pełny adres URL konkretnej podstrony (np.
  `https://mojadomena.pl/oferta/`), żeby śledzić pozycję tylko tej strony dla
  danej frazy. Ta sama fraza może mieć wiele wpisów - po jednym dla domeny i
  po jednym dla każdej interesującej Cię podstrony.
- kliknij **"Sprawdź teraz"**, aby pobrać z Search Console aktualną średnią
  pozycję wszystkich fraz projektu (działa w tle, nie blokuje okna).
- kliknij **"Pobierz dane historyczne"**, żeby jednym zapytaniem uzupełnić
  wykresy o dane sprzed instalacji aplikacji - podajesz liczbę dni wstecz
  (Search Console przechowuje dane ok. 16 miesięcy), a aplikacja pobiera
  dzienną pozycję dla każdej frazy w tym okresie. Przydatne przy pierwszym
  uruchomieniu, żeby od razu zobaczyć historyczny trend zamiast czekać na
  kolejne codzienne sprawdzenia.

W zakładce **"Wykresy"**:
- zaznacz jedną lub więcej fraz po lewej i kliknij "Rysuj wykres", aby
  zobaczyć zmianę średniej pozycji w czasie (oś pozycji jest odwrócona - im
  wyżej na wykresie, tym lepsza pozycja).

W zakładce **"Statystyki"**:
- podsumowanie projektu (liczba fraz, średnia pozycja, suma wyświetleń i
  kliknięć) oraz tabela z trendem (poprawa/spadek) dla każdej frazy względem
  poprzedniego sprawdzenia.

## Dane

Wszystko - projekty, słowa kluczowe, historia pozycji i ustawienia - jest
zapisywane lokalnie w `data/monitoring.db` (SQLite). Plik
`service-account.json` (i cała reszta katalogu `data/`) jest wykluczony z
gita w `.gitignore` - nie udostępniaj go nikomu, daje dostęp odczytu do
danych Search Console Twoich domen.
