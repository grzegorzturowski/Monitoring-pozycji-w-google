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
- Pozycja to **średnia dzienna** z Search Console (średnia ze wszystkich
  wyświetleń danego dnia), a nie wynik pojedynczego wyszukiwania.
- Kolumna "Popularność" korzysta z **Google Trends** (nieoficjalne API) albo
  z **Planera słów kluczowych Google Ads** - patrz sekcje 5 i 6 poniżej.

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
   Możesz tam też zmienić opóźnienie danych Search Console.
2. Kliknij **"+ Nowy projekt"** i dodaj domenę - `site_url` musi dokładnie
   odpowiadać nazwie usługi widocznej w Search Console (sprawdź typ w
   Ustawienia → Informacje o usłudze):
   - usługa typu **"Domena"** → wpisz `sc-domain:mojadomena.pl`
   - usługa typu **"Prefiks adresu URL"** → wpisz dokładnie zweryfikowany
     adres, razem z ukośnikiem na końcu, np. `https://mojadomena.pl/`

   W polu **"Sprawdzaj dane od"** ustaw datę, od której mają być dane
   wszystkich fraz projektu (Search Console przechowuje ok. 16 miesięcy).
3. Powtórz dla drugiej domeny - w panelu bocznym możesz swobodnie
   **przełączać się między projektami**, a przyciskiem "Edytuj projekt"
   poprawić nazwę/`site_url`/datę "Sprawdzaj dane od" bez utraty zapisanej
   historii.

## 4. Codzienne korzystanie

W zakładce **"Słowa kluczowe"**:
- dodawaj frazy do śledzenia dla aktualnie wybranego projektu. Pole
  "Podstrona" jest opcjonalne - zostaw je puste, aby śledzić pozycję dla
  całej domeny, albo wpisz pełny adres URL konkretnej podstrony (np.
  `https://mojadomena.pl/oferta/`), żeby śledzić pozycję tylko tej strony dla
  danej frazy. Ta sama fraza może mieć wiele wpisów - po jednym dla domeny i
  po jednym dla każdej interesującej Cię podstrony.
- dzienna pozycja, kliknięcia i wyświetlenia każdej frazy są pobierane od
  daty "Sprawdzaj dane od" projektu do dziś:
  - przy każdym uruchomieniu aplikacji - dociągane są dni do dziś, a
    dodatkowo (raz dziennie) pobierane ponownie jest 7 dni wcześniej, bo
    Search Console potrafi uzupełniać dane z opóźnieniem,
  - po dodaniu frazy - od razu pobierany jest cały okres projektu,
  - po cofnięciu daty "Sprawdzaj dane od" w "Edytuj projekt" - dociągane są
    brakujące wcześniejsze dni (po przesunięciu daty na późniejszą starsze
    dane są tylko ukrywane na wykresach i w statystykach),
  - przycisk **"Sprawdź teraz"** robi to samo na żądanie.

  Przy każdej frazie zapamiętywany jest zakres już sprawdzonych dni (także
  dni bez wyświetleń), więc poza tym 7-dniowym
  odświeżeniem te same dni nie są pobierane drugi raz.
- zaznacz checkboxem jedną lub więcej fraz w tabeli - wykres pod tabelą
  rysuje się automatycznie, bez dodatkowego przycisku (oś pozycji jest
  odwrócona - im wyżej na wykresie, tym lepsza pozycja). Przycisk "Zaznacz /
  odznacz wszystkie" zaznacza lub czyści zaznaczenie wszystkich fraz naraz.
- kliknij **"Sprawdź popularność"**, żeby pobrać z Google Trends / Google Ads kolumnę
  "Popularność" dla wszystkich fraz projektu (patrz sekcja niżej).

W zakładce **"Statystyki"**:
- podsumowanie projektu (liczba fraz, średnia pozycja, suma wyświetleń i
  kliknięć) oraz tabela z trendem (poprawa/spadek) dla każdej frazy względem
  poprzedniego sprawdzenia.

## 5. Popularność fraz (Google Trends)

Kolumna "Popularność" w tabeli słów kluczowych pokazuje **względne**
zainteresowanie daną frazą w Google Trends, w skali 0-100, uśrednione z
wybranego okresu (domyślnie ostatnie 12 miesięcy, ustawienie "Google Trends -
okres" w Ustawieniach). To **nie jest** realna liczba wyszukiwań miesięcznie
- Google Trends nie ujawnia takich danych publicznie. Liczby są w pełni
porównywalne tylko pomiędzy frazami sprawdzonymi w tej samej partii (Google
Trends porównuje maks. 5 fraz naraz - przy większej liczbie fraz aplikacja
dzieli je automatycznie na kilka partii, każda znormalizowana osobno).

Źródłem jest **nieoficjalne** API Google Trends (biblioteka `pytrends`
odpytuje wewnętrzny, nieudokumentowany interfejs) - w przeciwieństwie do
Search Console może się kiedyś zepsuć wraz ze zmianami po stronie Google i
bywa czasem ograniczane limitami zapytań (błąd 429 - w takim wypadku po
prostu spróbuj ponownie za jakiś czas).

Okres, dla którego liczona jest popularność, można zmienić w Ustawieniach
("Google Trends - okres"). Kraj ustawia się osobno w każdym projekcie
("Edytuj projekt" → "Kraj", dwuliterowy kod ISO, np. `PL`; puste = cały
świat). Opcja "Pozycje z Search Console tylko z tego kraju" zawęża do niego
także pozycje, wyświetlenia i kliknięcia. Zmiana kraju czyści popularność fraz
projektu, a zmiana zawężenia pozycji - całą historię pozycji projektu (jest
pobierana ponownie z Search Console, która trzyma dane ok. 16 miesięcy).

## 6. Popularność fraz z Planera słów kluczowych Google Ads

Zamiast Google Trends kolumna "Popularność" może pokazywać **średnią
miesięczną liczbę wyszukiwań** frazy (ostatnie 12 miesięcy) z Planera słów
kluczowych Google Ads - oficjalne API, liczby bezwzględne, porównywalne
między wszystkimi frazami. Przy bardzo małych wolumenach Google je
zaokrągla, a na kontach bez aktywnych kampanii dane mogą być mniej dokładne.

Jednorazowa konfiguracja:

Od 9.09.2026 Google Ads API nie używa już tokenów dewelopera ani Centrum API
w Google Ads - poziom dostępu do API ma **projekt Google Cloud**, z którego
pochodzi klient OAuth. Konto menedżera (MCC) nie jest potrzebne.

1. **Dostęp do API** - w https://console.cloud.google.com/ (ten sam projekt co
   Search Console):
   - włącz API: https://console.cloud.google.com/apis/library/googleads.googleapis.com
   - na stronie przeglądu Google Ads API (APIs & Services → Google Ads API)
     zarejestruj się i złóż wniosek o poziom dostępu **Basic** - wymaga
     weryfikacji marki (brand verification) i projektu z włączonymi
     płatnościami; po weryfikacji wniosek jest rozpatrywany automatycznie.
     Poziom testowy działa tylko z kontami testowymi (bez prawdziwych danych
     planera).
2. **Klient OAuth** - w tym samym projekcie:
   - "Ekran zgody OAuth" → typ "Zewnętrzny", dodaj swój adres e-mail jako
     użytkownika testowego,
   - "Dane uwierzytelniające" → "Utwórz dane uwierzytelniające" → **Identyfikator
     klienta OAuth** → typ **"Aplikacja komputerowa"** → pobierz plik JSON
     (np. `client_secret_....json` - jest wykluczony z gita).
3. W aplikacji: **Ustawienia** → "Źródło popularności fraz" = **Google Ads**,
   wpisz ID konta Google Ads (widoczne w prawym górnym rogu
   Google Ads, np. `123-456-7890`), ewentualnie ID konta menedżera (jeśli
   konto jest dostępne przez MCC), kod języka (`pl`), wskaż plik klienta
   OAuth i kliknij **"Zaloguj do Google Ads"** - w przeglądarce zaloguj się na
   konto Google z dostępem do Google Ads. Token logowania zapisuje się w
   `data/monitoring.db`, więc logowanie wystarczy zrobić raz.

Oprócz średniej zapisywane są liczby wyszukiwań z każdego z ostatnich 12
miesięcy - wykres "Popularność strony" waży frazy liczbą wyszukiwań z
miesiąca danego dnia (dla miesięcy, których Google jeszcze nie podsumował,
używany jest ten sam miesiąc rok wcześniej).

Kraj jest wspólny z Google Trends (ustawienie "Kraj" w projekcie). Przy zmianie źródła
popularności zapisane wartości są czyszczone (skale 0-100 i liczba wyszukiwań
są nieporównywalne) - kliknij potem "Sprawdź popularność" w każdym projekcie.

## 7. Obecność w AI (Gemini)

Zakładka **"Obecność w AI"** sprawdza, czy Gemini z wyszukiwaniem Google
(grounding) poleca Twoją domenę. Każda fraza kluczowa jest wysyłana do Gemini
tak, jak wpisałby ją użytkownik, a w odpowiedzi sprawdzane jest:

- **✔ #N** - domena jest wśród źródeł (linków) odpowiedzi, na N-tym miejscu,
- **~ wzmianka** - domena albo nazwa marki pada tylko w tekście odpowiedzi,
- **✗ brak** - ani jedno, ani drugie.

Konfiguracja: w **Ustawieniach** (sekcja "Obecność w AI") wklej klucz API z
https://aistudio.google.com/apikey. Domyślny model to `gemini-3.1-flash-lite` -
najtańszy dostępny z wyszukiwaniem Google (stan na 10.2026: 5000 wyszukiwań
miesięcznie gratis, potem $14 / 1000; tokeny ok. $0.001-0.003 na zapytanie).
Modele 2.5 nie są już dostępne dla nowych kont. Model można
zmienić w polu obok klucza. W **"Edytuj projekt"** możesz podać nazwy marki (po
przecinku) - są szukane w odpowiedziach obok samej domeny. Kraju projektu nie
da się przekazać do Gemini - wyniki nie są lokalizowane.

Sprawdzanie uruchamia się automatycznie przy starcie aplikacji (jeśli podano
klucz API), najwyżej raz dziennie - kolejne uruchomienia tego samego dnia je
pomijają, nawet gdy pierwsze zakończyło się błędem. Można je też uruchomić
ręcznie przyciskiem; frazy sprawdzone dziś są wtedy domyślnie pomijane. Odpowiedzi AI są niedeterministyczne - wynik pojedynczego sprawdzenia
bywa przypadkowy, miarodajny jest trend na wykresie (% fraz z cytowaną domeną w
kolejnych dniach). Kliknięcie frazy w tabeli pokazuje pełną odpowiedź Gemini i
listę źródeł z zaznaczoną Twoją domeną.

## Dane

Wszystko - projekty, słowa kluczowe, historia pozycji i ustawienia - jest
zapisywane lokalnie w `data/monitoring.db` (SQLite). Plik
`service-account.json` (i cała reszta katalogu `data/`) jest wykluczony z
gita w `.gitignore` - nie udostępniaj go nikomu, daje dostęp odczytu do
danych Search Console Twoich domen.
