"""GUI aplikacji (CustomTkinter): projekty, słowa kluczowe, wykresy, statystyki."""

import threading
from datetime import date, datetime
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import ai_visibility
import countries
import db
import tracker
from charts import build_ai_visibility_chart, build_position_chart, build_site_popularity_chart
import site_popularity
from site_popularity import aggregate_series, compute_site_popularity

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

RECENT_DATA_REFRESH_DAYS = 7  # ile ostatnich dni pozycji pobierać ponownie przy starcie (Search Console je uzupełnia)
POPULARITY_REFRESH_DAYS = 7  # jak często (w dniach) odświeżać popularność fraz (Google Ads / Trends) przy starcie


class ErrorDialog(ctk.CTkToplevel):
    """Okno błędu z tekstem, który można zaznaczyć i skopiować (zamiast standardowego messagebox)."""

    def __init__(self, master, title: str, message: str):
        super().__init__(master)
        self.title(title)
        self.geometry("600x320")
        self.grab_set()

        textbox = ctk.CTkTextbox(self, wrap="word")
        textbox.pack(fill="both", expand=True, padx=16, pady=(16, 8))
        textbox.insert("1.0", message)
        textbox.configure(state="disabled")

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=(0, 16))
        ctk.CTkButton(button_row, text="Kopiuj", command=lambda: self._copy(message)).pack(side="left", padx=8)
        ctk.CTkButton(button_row, text="Zamknij", command=self.destroy, fg_color="gray40").pack(side="left", padx=8)

    def _copy(self, text: str):
        self.clipboard_clear()
        self.clipboard_append(text)


class ProjectDialog(ctk.CTkToplevel):
    def __init__(
        self,
        master,
        title: str = "Nowy projekt",
        confirm_text: str = "Dodaj",
        initial_name: str = "",
        initial_site_url: str = "",
        initial_data_from: str = "",
        initial_country: str = "PL",
        initial_country_positions: bool = True,
        initial_ai_brand_terms: str = "",
    ):
        super().__init__(master)
        self.title(title)
        self.geometry("480x760")
        self.resizable(False, False)
        self.result: tuple[str, str, str, str, bool, str] | None = None
        self.grab_set()

        ctk.CTkLabel(self, text="Nazwa projektu:").pack(anchor="w", padx=16, pady=(16, 0))
        self.name_entry = ctk.CTkEntry(self, width=420, placeholder_text="np. Moja Domena")
        self.name_entry.insert(0, initial_name)
        self.name_entry.pack(padx=16, pady=(4, 12))

        ctk.CTkLabel(self, text="Adres usługi w Search Console (site_url):").pack(anchor="w", padx=16)
        self.site_entry = ctk.CTkEntry(
            self, width=420, placeholder_text="sc-domain:mojadomena.pl albo https://mojadomena.pl/"
        )
        self.site_entry.insert(0, initial_site_url)
        self.site_entry.pack(padx=16, pady=(4, 4))
        ctk.CTkLabel(
            self,
            text="Musi dokładnie odpowiadać usłudze z listy w Search Console.",
            text_color="gray60",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))

        examples_box = ctk.CTkFrame(self, fg_color=("gray90", "gray20"))
        examples_box.pack(fill="x", padx=16, pady=(0, 12))
        ctk.CTkLabel(
            examples_box,
            text="Wzór dla całej domeny (usługa typu \"Domena\"):",
            text_color=("gray20", "gray80"),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            examples_box,
            text="sc-domain:mojadomena.pl",
            font=ctk.CTkFont(family="Consolas", weight="bold"),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 6))
        ctk.CTkLabel(
            examples_box,
            text="Wzór dla konkretnego adresu URL (usługa typu \"Prefiks adresu URL\",\npamiętaj o ukośniku na końcu):",
            text_color=("gray20", "gray80"),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 0))
        ctk.CTkLabel(
            examples_box,
            text="https://mojadomena.pl/",
            font=ctk.CTkFont(family="Consolas", weight="bold"),
            justify="left",
        ).pack(anchor="w", padx=12, pady=(0, 8))

        ctk.CTkLabel(self, text="Sprawdzaj dane od (RRRR-MM-DD):").pack(anchor="w", padx=16)
        self.data_from_entry = ctk.CTkEntry(self, width=120)
        self.data_from_entry.insert(0, initial_data_from or db.default_data_from())
        self.data_from_entry.pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            self,
            text="Wspólna dla wszystkich fraz projektu. Search Console przechowuje dane ok. 16 miesięcy.",
            text_color="gray60",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        ctk.CTkLabel(self, text="Kraj (kod ISO, np. PL, DE, US; puste = cały świat):").pack(anchor="w", padx=16)
        self.country_entry = ctk.CTkEntry(self, width=80)
        self.country_entry.insert(0, initial_country)
        self.country_entry.pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            self,
            text="Dotyczy popularności fraz (Google Ads / Trends).",
            text_color="gray60",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 4))
        self.country_positions_var = ctk.BooleanVar(value=initial_country_positions)
        ctk.CTkCheckBox(
            self, text="Pozycje z Search Console tylko z tego kraju", variable=self.country_positions_var
        ).pack(anchor="w", padx=16, pady=(4, 12))

        ctk.CTkLabel(self, text="Nazwy marki dla \"Obecności w AI\" (po przecinku, opcjonalnie):").pack(
            anchor="w", padx=16
        )
        self.brand_terms_entry = ctk.CTkEntry(self, width=420, placeholder_text="np. Moja Domena, MojaDomena")
        self.brand_terms_entry.insert(0, initial_ai_brand_terms)
        self.brand_terms_entry.pack(anchor="w", padx=16, pady=(4, 4))
        ctk.CTkLabel(
            self,
            text="Szukane w odpowiedziach asystentów AI obok samej domeny.",
            text_color="gray60",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 12))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=4)
        ctk.CTkButton(button_row, text="Anuluj", command=self.destroy, fg_color="gray40").pack(side="left", padx=8)
        ctk.CTkButton(button_row, text=confirm_text, command=self._on_confirm).pack(side="left", padx=8)

        self.name_entry.focus()

    def _on_confirm(self):
        name = self.name_entry.get().strip()
        site_url = self.site_entry.get().strip()
        if not name or not site_url:
            messagebox.showwarning("Brak danych", "Podaj nazwę projektu oraz adres site_url.", parent=self)
            return
        try:
            data_from = date.fromisoformat(self.data_from_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Błędna data", "Podaj datę w formacie RRRR-MM-DD, np. 2026-01-01.", parent=self)
            return
        if data_from > date.today():
            messagebox.showwarning("Błędna data", "Data nie może być z przyszłości.", parent=self)
            return
        country = self.country_entry.get().strip().upper()
        if not countries.is_valid(country):
            messagebox.showwarning(
                "Błędny kraj", "Podaj dwuliterowy kod kraju ISO, np. PL, DE, US - albo zostaw puste.", parent=self
            )
            return
        self.result = (
            name,
            site_url,
            data_from.isoformat(),
            country,
            self.country_positions_var.get(),
            self.brand_terms_entry.get().strip(),
        )
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    POPULARITY_SOURCES = {
        "Google Ads (liczba wyszukiwań)": tracker.POPULARITY_SOURCE_ADS,
        "Google Trends (0-100)": tracker.POPULARITY_SOURCE_TRENDS,
    }

    def __init__(self, master, conn):
        super().__init__(master)
        self.conn = conn
        self.title("Ustawienia")
        self.geometry("560x640")
        self.resizable(False, True)
        self.grab_set()

        body = ctk.CTkScrollableFrame(self, fg_color="transparent")
        body.pack(fill="both", expand=True)

        ctk.CTkLabel(body, text="Plik konta usługi (service-account.json):").pack(anchor="w", padx=16, pady=(16, 0))
        self.service_account_entry = self._file_row(
            body, db.get_setting(conn, "service_account_file"), "Wybierz plik JSON konta usługi"
        )

        ctk.CTkLabel(body, text="Opóźnienie danych Search Console (dni):").pack(anchor="w", padx=16)
        self.delay_entry = ctk.CTkEntry(body, width=100)
        self.delay_entry.insert(0, db.get_setting(conn, "data_delay_days") or "3")
        self.delay_entry.pack(anchor="w", padx=16, pady=(4, 16))

        # --- popularność fraz ---
        ctk.CTkLabel(body, text="Źródło popularności fraz:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16
        )
        current_source = db.get_setting(conn, "popularity_source") or tracker.POPULARITY_SOURCE_TRENDS
        self.source_selector = ctk.CTkSegmentedButton(body, values=list(self.POPULARITY_SOURCES))
        self.source_selector.set(
            next(label for label, value in self.POPULARITY_SOURCES.items() if value == current_source)
        )
        self.source_selector.pack(anchor="w", padx=16, pady=(4, 12))

        ctk.CTkLabel(
            body, text="Kraj ustawia się osobno w każdym projekcie (Edytuj projekt).", text_color="gray60"
        ).pack(anchor="w", padx=16, pady=(0, 12))

        ctk.CTkLabel(
            body, text="Google Trends - okres (np. \"today 12-m\", \"today 3-m\", \"today 5-y\"):"
        ).pack(anchor="w", padx=16)
        self.trends_timeframe_entry = ctk.CTkEntry(body, width=200)
        self.trends_timeframe_entry.insert(0, db.get_setting(conn, "trends_timeframe") or "today 12-m")
        self.trends_timeframe_entry.pack(anchor="w", padx=16, pady=(4, 16))

        ctk.CTkLabel(body, text="Google Ads - Planer słów kluczowych", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16
        )
        self.ads_customer_id_entry = self._labeled_entry(
            body, "ID konta Google Ads (np. 123-456-7890):", "ads_customer_id", 160
        )
        self.ads_login_customer_id_entry = self._labeled_entry(
            body,
            "ID konta menedżera (MCC), jeśli dostęp do konta jest przez MCC (opcjonalne):",
            "ads_login_customer_id",
            160,
        )
        self.ads_language_entry = self._labeled_entry(
            body, "Język (kod, np. pl, en; puste = wszystkie):", "ads_language", 100
        )

        ctk.CTkLabel(body, text="Plik klienta OAuth (typ \"Aplikacja komputerowa\", JSON):").pack(
            anchor="w", padx=16
        )
        self.ads_oauth_client_entry = self._file_row(
            body, db.get_setting(conn, "ads_oauth_client_file"), "Wybierz plik JSON klienta OAuth"
        )

        login_row = ctk.CTkFrame(body, fg_color="transparent")
        login_row.pack(fill="x", padx=16, pady=(0, 16))
        self.ads_login_button = ctk.CTkButton(
            login_row, text="Zaloguj do Google Ads", width=180, command=self._on_ads_login
        )
        self.ads_login_button.pack(side="left", padx=(0, 8))
        self.ads_login_status = ctk.CTkLabel(
            login_row, text="Zalogowano." if db.get_setting(conn, "ads_refresh_token") else "Nie zalogowano."
        )
        self.ads_login_status.pack(side="left")

        # --- obecność w AI ---
        ctk.CTkLabel(body, text="Obecność w AI (Gemini)", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=16
        )
        ctk.CTkLabel(
            body,
            text="Klucz API z https://aistudio.google.com/apikey. Puste pole modelu = model domyślny.",
            text_color="gray60",
            justify="left",
        ).pack(anchor="w", padx=16, pady=(0, 8))
        self.ai_entries: list[tuple[str, ctk.CTkEntry]] = []
        for name, key_setting, model_setting, default_model in ai_visibility.ENGINES.values():
            ctk.CTkLabel(body, text=f"{name} - klucz API / model:").pack(anchor="w", padx=16)
            row = ctk.CTkFrame(body, fg_color="transparent")
            row.pack(fill="x", padx=16, pady=(4, 12))
            key_entry = ctk.CTkEntry(row, width=300, show="•")
            key_entry.insert(0, db.get_setting(conn, key_setting) or "")
            key_entry.pack(side="left", padx=(0, 8))
            model_entry = ctk.CTkEntry(row, width=170, placeholder_text=default_model)
            model_entry.insert(0, db.get_setting(conn, model_setting) or "")
            model_entry.pack(side="left")
            self.ai_entries += [(key_setting, key_entry), (model_setting, model_entry)]

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=8)
        ctk.CTkButton(button_row, text="Anuluj", command=self.destroy, fg_color="gray40").pack(side="left", padx=8)
        ctk.CTkButton(button_row, text="Zapisz", command=self._on_save).pack(side="left", padx=8)

    def _labeled_entry(self, parent, label: str, setting_key: str, width: int) -> ctk.CTkEntry:
        ctk.CTkLabel(parent, text=label).pack(anchor="w", padx=16)
        entry = ctk.CTkEntry(parent, width=width)
        entry.insert(0, db.get_setting(self.conn, setting_key) or "")
        entry.pack(anchor="w", padx=16, pady=(4, 12))
        return entry

    def _file_row(self, parent, value: str | None, dialog_title: str) -> ctk.CTkEntry:
        row = ctk.CTkFrame(parent, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 12))
        entry = ctk.CTkEntry(row, width=380)
        entry.insert(0, value or "")
        entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(
            row, text="Wybierz...", width=90, command=lambda: self._browse_file(entry, dialog_title)
        ).pack(side="left")
        return entry

    def _browse_file(self, entry: ctk.CTkEntry, title: str):
        path = filedialog.askopenfilename(parent=self, title=title, filetypes=[("JSON", "*.json")])
        if path:
            entry.delete(0, "end")
            entry.insert(0, path)

    def _on_ads_login(self):
        oauth_client_file = self.ads_oauth_client_entry.get().strip()
        if not oauth_client_file:
            messagebox.showwarning("Brak pliku", "Najpierw wskaż plik JSON klienta OAuth.", parent=self)
            return
        self.ads_login_button.configure(state="disabled")
        self.ads_login_status.configure(text="Dokończ logowanie w przeglądarce...")

        def worker():
            from keyword_planner import authorize

            try:
                refresh_token = authorize(oauth_client_file)
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                self.after(0, lambda e=e: self._on_ads_login_finished(None, e))
                return
            self.after(0, lambda: self._on_ads_login_finished(refresh_token, None))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ads_login_finished(self, refresh_token: str | None, error: Exception | None):
        if not self.winfo_exists():
            return
        self.ads_login_button.configure(state="normal")
        if error:
            self.ads_login_status.configure(text="Logowanie nie powiodło się.")
            ErrorDialog(self, "Błąd logowania do Google Ads", str(error))
            return
        db.set_setting(self.conn, "ads_refresh_token", refresh_token)
        db.set_setting(self.conn, "ads_oauth_client_file", self.ads_oauth_client_entry.get().strip())
        self.ads_login_status.configure(text="Zalogowano.")

    def _on_save(self):
        try:
            data_delay_days = int(self.delay_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Błędne dane", "Opóźnienie musi być liczbą całkowitą.", parent=self)
            return

        new_source = self.POPULARITY_SOURCES[self.source_selector.get()]
        old_source = db.get_setting(self.conn, "popularity_source") or tracker.POPULARITY_SOURCE_TRENDS
        if new_source != old_source:
            if not messagebox.askyesno(
                "Zmiana źródła popularności",
                "Wartości z Google Trends (0-100) i Google Ads (liczba wyszukiwań) są w innych skalach, więc "
                "zapisana popularność wszystkich fraz zostanie wyczyszczona. Potem kliknij \"Sprawdź "
                "popularność\" w każdym projekcie (albo uruchom aplikację ponownie). Kontynuować?",
                parent=self,
            ):
                return
            db.clear_all_popularity(self.conn)

        db.set_setting(self.conn, "service_account_file", self.service_account_entry.get().strip())
        db.set_setting(self.conn, "data_delay_days", str(data_delay_days))
        db.set_setting(self.conn, "popularity_source", new_source)
        db.set_setting(self.conn, "trends_timeframe", self.trends_timeframe_entry.get().strip() or "today 12-m")
        db.set_setting(self.conn, "ads_customer_id", self.ads_customer_id_entry.get().strip())
        db.set_setting(self.conn, "ads_login_customer_id", self.ads_login_customer_id_entry.get().strip())
        db.set_setting(self.conn, "ads_language", self.ads_language_entry.get().strip())
        db.set_setting(self.conn, "ads_oauth_client_file", self.ads_oauth_client_entry.get().strip())
        for setting_key, entry in self.ai_entries:
            db.set_setting(self.conn, setting_key, entry.get().strip())
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.conn = db.connect()
        self.current_project_id: int | None = None
        self.selected_keyword_ids: set[int] = set()  # frazy zaznaczone do wykresu
        self.keyword_row_ids: list[int] = []  # frazy aktualnie widoczne w tabeli
        self.chart_canvas = None
        self.sync_pending = False  # pobranie danych zlecone w trakcie innego sprawdzania
        self.sync_pending_popularity = False  # ...razem ze sprawdzeniem popularności nowych fraz
        self.keywords_sort_index = 1  # indeks w krotce z db.get_latest_for_project - domyślnie "Fraza kluczowa"
        self.keywords_sort_reverse = False

        self.title("Monitoring pozycji w Google")
        self.geometry("1100x700")  # rozmiar po wyjściu z maksymalizacji
        # CustomTkinter ustawia geometrię okna po __init__, więc maksymalizacja dopiero w pętli zdarzeń
        self.after(0, lambda: self.state("zoomed"))
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self.refresh_projects()
        self.after(500, self._run_startup_update)

    # ---------- sidebar ----------

    def _build_sidebar(self):
        sidebar = ctk.CTkFrame(self, width=220, corner_radius=0)
        sidebar.grid(row=0, column=0, sticky="nswe")
        sidebar.grid_rowconfigure(1, weight=1)

        ctk.CTkLabel(sidebar, text="Projekty", font=ctk.CTkFont(size=16, weight="bold")).grid(
            row=0, column=0, padx=16, pady=(16, 8), sticky="w"
        )

        self.project_list_frame = ctk.CTkScrollableFrame(sidebar, width=190)
        self.project_list_frame.grid(row=1, column=0, padx=12, sticky="nswe")

        ctk.CTkButton(sidebar, text="+ Nowy projekt", command=self._on_add_project).grid(
            row=2, column=0, padx=16, pady=(12, 4), sticky="we"
        )
        ctk.CTkButton(sidebar, text="Edytuj projekt", fg_color="gray40", command=self._on_edit_project).grid(
            row=3, column=0, padx=16, pady=4, sticky="we"
        )
        ctk.CTkButton(
            sidebar, text="Usuń projekt", fg_color="#8B2E2E", hover_color="#6E2424", command=self._on_delete_project
        ).grid(row=4, column=0, padx=16, pady=4, sticky="we")
        ctk.CTkButton(sidebar, text="Ustawienia", fg_color="gray40", command=self._on_open_settings).grid(
            row=5, column=0, padx=16, pady=(4, 16), sticky="we"
        )

        self.sidebar = sidebar
        self.project_buttons: dict[int, ctk.CTkButton] = {}

    def refresh_projects(self):
        for widget in self.project_list_frame.winfo_children():
            widget.destroy()
        self.project_buttons.clear()

        projects = db.list_projects(self.conn)
        for project_id, name, _site_url in projects:
            btn = ctk.CTkButton(
                self.project_list_frame,
                text=name,
                anchor="w",
                fg_color="transparent",
                text_color=("gray10", "gray90"),
                hover_color=("gray80", "gray25"),
                command=lambda pid=project_id: self._select_project(pid),
            )
            btn.pack(fill="x", pady=2)
            self.project_buttons[project_id] = btn

        if projects and self.current_project_id not in self.project_buttons:
            self._select_project(projects[0][0])
        elif not projects:
            self.current_project_id = None
            self._highlight_selected_project()
            self.refresh_all()

    def refresh_all(self):
        """Oznacza wszystkie zakładki do odświeżenia, ale przebudowuje tylko
        aktualnie widoczną - pozostałe odświeżą się przy przełączeniu na nie."""
        self._dirty_tabs = set(self._tab_refreshers)
        self._refresh_current_tab()

    def _refresh_current_tab(self):
        name = self.tabview.get()
        if name in self._dirty_tabs:
            self._dirty_tabs.discard(name)
            self._tab_refreshers[name]()

    def _highlight_selected_project(self):
        for project_id, btn in self.project_buttons.items():
            btn.configure(fg_color="#1F6AA5" if project_id == self.current_project_id else "transparent")

    def _select_project(self, project_id: int):
        self.current_project_id = project_id
        self._highlight_selected_project()
        self.refresh_all()

    def _on_add_project(self):
        dialog = ProjectDialog(self, title="Nowy projekt", confirm_text="Dodaj")
        self.wait_window(dialog)
        if dialog.result:
            try:
                project_id = db.add_project(self.conn, *dialog.result)
            except Exception as e:
                ErrorDialog(self, "Błąd", f"Nie udało się dodać projektu:\n\n{e}")
                return
            self.refresh_projects()
            self._select_project(project_id)

    def _on_edit_project(self):
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz projekt do edycji.")
            return
        project = db.get_project(self.conn, self.current_project_id)
        if not project:
            return
        _, name, site_url = project
        country, country_positions = db.get_project_country(self.conn, self.current_project_id)
        dialog = ProjectDialog(
            self,
            title="Edytuj projekt",
            confirm_text="Zapisz",
            initial_name=name,
            initial_site_url=site_url,
            initial_data_from=db.get_project_data_from(self.conn, self.current_project_id),
            initial_country=country,
            initial_country_positions=country_positions,
            initial_ai_brand_terms=db.get_project_ai_brand_terms(self.conn, self.current_project_id),
        )
        self.wait_window(dialog)
        if dialog.result:
            new_country, new_country_positions = dialog.result[3:5]
            losses = []
            if new_country != country:
                losses.append("popularność fraz projektu (zostanie sprawdzona ponownie dla nowego kraju)")
            if db.positions_country(new_country, new_country_positions) != db.positions_country(
                country, country_positions
            ):
                losses.append(
                    "cała historia pozycji projektu (zostanie pobrana ponownie z Search Console od daty "
                    "początku danych - dni starsze niż ok. 16 miesięcy przepadną)"
                )
            if losses and not messagebox.askyesno(
                "Zmiana kraju",
                "Po zmianie kraju zostaną usunięte:\n\n- " + "\n- ".join(losses) + "\n\nKontynuować?",
            ):
                return
            try:
                db.update_project(self.conn, self.current_project_id, *dialog.result)
            except Exception as e:
                ErrorDialog(self, "Błąd", f"Nie udało się zapisać zmian:\n\n{e}")
                return
            self.refresh_projects()
            self._highlight_selected_project()
            self.refresh_all()
            # dociąga dni sprzed dotychczasowej daty początku (jeśli ją cofnięto) i dane po zmianie kraju
            self._on_run_check(with_popularity=new_country != country)

    def _on_delete_project(self):
        if self.current_project_id is None:
            return
        project = db.get_project(self.conn, self.current_project_id)
        if not project:
            return
        if messagebox.askyesno(
            "Usuń projekt", f"Usunąć projekt '{project[1]}' wraz z całą historią pozycji?"
        ):
            db.delete_project(self.conn, self.current_project_id)
            self.current_project_id = None
            self.refresh_projects()

    def _on_open_settings(self):
        dialog = SettingsDialog(self, self.conn)
        self.wait_window(dialog)

    # ---------- główny obszar (zakładki) ----------

    def _build_main_area(self):
        self.tabview = ctk.CTkTabview(self, command=self._refresh_current_tab)
        self.tabview.grid(row=0, column=1, sticky="nswe", padx=16, pady=16)

        self.tab_keywords = self.tabview.add("Słowa kluczowe")
        self.tab_stats = self.tabview.add("Statystyki")
        self.tab_site_popularity = self.tabview.add("Popularność strony")
        self.tab_ai = self.tabview.add("Obecność w AI")
        self._tab_refreshers = {
            "Słowa kluczowe": self.refresh_keywords_tab,
            "Statystyki": self.refresh_stats_tab,
            "Popularność strony": self.refresh_site_popularity_tab,
            "Obecność w AI": self.refresh_ai_tab,
        }
        self._dirty_tabs: set[str] = set(self._tab_refreshers)

        self._setup_table_style()
        self._build_keywords_tab()
        self._build_stats_tab()
        self._build_site_popularity_tab()
        self._build_ai_tab()

    def _setup_table_style(self):
        """Styl natywnych tabel (ttk.Treeview) dopasowany do motywu CustomTkinter.
        Treeview to jedna kontrolka na całą tabelę - w przeciwieństwie do siatki
        widgetów CTk (osobny widget na każdą komórkę) odświeża się natychmiast."""
        dark = ctk.get_appearance_mode() == "Dark"
        bg = "#2b2b2b" if dark else "#f9f9fa"
        fg = "#dce4ee" if dark else "#1a1a1a"
        heading_bg = "#3a3a3a" if dark else "#e4e4e4"
        heading_active = "#454545" if dark else "#d6d6d6"
        scaling = ctk.ScalingTracker.get_widget_scaling(self)

        style = ttk.Style(self)
        style.theme_use("clam")
        style.configure(
            "Treeview",
            background=bg,
            fieldbackground=bg,
            foreground=fg,
            rowheight=int(38 * scaling),
            borderwidth=0,
            font=("Segoe UI", 14),
        )
        style.map("Treeview", background=[("selected", "#1F6AA5")], foreground=[("selected", "white")])
        style.configure(
            "Treeview.Heading",
            background=heading_bg,
            foreground=fg,
            relief="flat",
            font=("Segoe UI", 14, "bold"),
            padding=(4, 6),
        )
        style.map("Treeview.Heading", background=[("active", heading_active)])
        self._table_stripe_bg = "#303030" if dark else "#f0f0f2"
        self._table_checked_bg = "#1d3b57" if dark else "#dbe9f7"

    def _make_table(self, parent, columns: list[tuple[str, str, int, str]]) -> ttk.Treeview:
        """columns: [(id, nagłówek, szerokość, wyrównanie "w"/"center"), ...]. Zwraca Treeview
        umieszczony w `parent` razem z paskiem przewijania (parent musi używać grid)."""
        tree = ttk.Treeview(parent, columns=[c[0] for c in columns], show="headings", selectmode="none")
        # szerokości kolumn Treeview są w pikselach i nie skalują się same z DPI (czcionki tak)
        scaling = ctk.ScalingTracker.get_widget_scaling(self)
        for col_id, heading, width, anchor in columns:
            tree.heading(col_id, text=heading, anchor=anchor)
            tree.column(col_id, width=int(width * scaling), minwidth=30, anchor=anchor, stretch=anchor == "w")
        scrollbar = ctk.CTkScrollbar(parent, command=tree.yview)
        tree.configure(yscrollcommand=scrollbar.set)
        tree.grid(row=0, column=0, sticky="nswe")
        scrollbar.grid(row=0, column=1, sticky="ns")
        parent.grid_columnconfigure(0, weight=1)
        parent.grid_rowconfigure(0, weight=1)
        tree.tag_configure("stripe", background=self._table_stripe_bg)
        tree.tag_configure("checked", background=self._table_checked_bg)
        return tree

    # --- zakładka: słowa kluczowe ---

    def _build_keywords_tab(self):
        tab = self.tab_keywords
        tab.grid_columnconfigure(0, weight=0)
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        # --- lewa kolumna: dodawanie fraz i przyciski akcji ---
        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=0, column=0, sticky="nw", padx=(0, 12), pady=(0, 8))

        entry_row = ctk.CTkFrame(controls, fg_color="transparent")
        entry_row.pack(anchor="w", pady=(0, 4))
        self.new_keyword_entry = ctk.CTkEntry(entry_row, width=210, placeholder_text="Nowa fraza kluczowa")
        self.new_keyword_entry.pack(side="left", padx=(0, 8))
        self.new_page_entry = ctk.CTkEntry(
            entry_row, width=210, placeholder_text="Podstrona (opcjonalnie, pełny URL)"
        )
        self.new_page_entry.pack(side="left")

        ctk.CTkButton(controls, text="Dodaj słowo kluczowe", width=428, command=self._on_add_keyword).pack(
            anchor="w", pady=(0, 2)
        )
        ctk.CTkLabel(
            controls,
            text="Puste pole podstrony = śledzenie pozycji całej domeny.",
            text_color="gray60",
        ).pack(anchor="w", pady=(0, 8))

        action_grid = ctk.CTkFrame(controls, fg_color="transparent")
        action_grid.pack(anchor="w")
        self.check_button = ctk.CTkButton(action_grid, text="Sprawdź teraz", width=210, command=self._on_run_check)
        self.check_button.grid(row=0, column=0, padx=(0, 8), pady=(0, 6))
        self.popularity_button = ctk.CTkButton(
            action_grid,
            text="Sprawdź popularność",
            width=210,
            fg_color="gray40",
            command=self._on_run_popularity_check,
        )
        self.popularity_button.grid(row=0, column=1, pady=(0, 6))
        self.select_all_button = ctk.CTkButton(
            action_grid,
            text="Zaznacz / odznacz wszystkie",
            width=210,
            fg_color="gray40",
            command=self._on_toggle_select_all,
        )
        self.select_all_button.grid(row=1, column=0, padx=(0, 8))

        self.status_label = ctk.CTkLabel(controls, text="", wraplength=428, justify="left")
        self.status_label.pack(anchor="w", pady=(8, 0))

        # --- prawa kolumna: mały wykres pozycji zaznaczonych fraz ---
        self.chart_area = ctk.CTkFrame(tab, height=230)
        self.chart_area.grid(row=0, column=1, sticky="nswe", pady=(0, 8))

        # --- tabela fraz na całą szerokość ---
        table_frame = ctk.CTkFrame(tab, fg_color="transparent")
        table_frame.grid(row=1, column=0, columnspan=2, sticky="nswe")
        self.keywords_table = self._make_table(
            table_frame,
            [
                ("check", "☑", 36, "center"),
                ("keyword", "Fraza kluczowa", 200, "w"),
                ("page", "Podstrona", 160, "w"),
                ("position", "Pozycja", 70, "center"),
                ("best", "Najlepsza", 75, "center"),
                ("popularity", "Popularność", 90, "center"),
                ("impressions7", "Wyśw. 7 dni", 85, "center"),
                ("impressions30", "Wyśw. 30 dni", 90, "center"),
                ("clicks7", "Klik. 7 dni", 80, "center"),
                ("clicks30", "Klik. 30 dni", 85, "center"),
                ("date", "Dane z dnia", 95, "center"),
                ("delete", "", 60, "center"),
            ],
        )
        self.keywords_table.bind("<ButtonRelease-1>", self._on_keywords_table_click)

    # (id kolumny tabeli, indeks w krotce z _get_keyword_rows, nagłówek) - sortowalne kolumny
    KEYWORD_SORT_COLUMNS = [
        ("keyword", 1, "Fraza kluczowa"),
        ("page", 2, "Podstrona"),
        ("position", 4, "Pozycja"),
        ("best", 8, "Najlepsza"),
        ("popularity", 9, "Popularność"),
        ("impressions7", 11, "Wyśw. 7 dni"),
        ("impressions30", 12, "Wyśw. 30 dni"),
        ("clicks7", 13, "Klik. 7 dni"),
        ("clicks30", 14, "Klik. 30 dni"),
        ("date", 3, "Dane z dnia"),
    ]

    def _get_keyword_rows(self):
        """Krotki z db.get_latest_for_project uzupełnione o średnie dzienne
        (wyświetlenia 7 dni, wyświetlenia 30 dni, kliknięcia 7 dni, kliknięcia 30 dni)."""
        averages = db.get_traffic_averages(self.conn, self.current_project_id, (7, 30))
        rows = []
        for row in db.get_latest_for_project(self.conn, self.current_project_id):
            by_window = averages.get(row[0], {})
            avg7, avg30 = by_window.get(7), by_window.get(30)
            rows.append(
                tuple(row)
                + (
                    avg7[0] if avg7 else None,
                    avg30[0] if avg30 else None,
                    avg7[1] if avg7 else None,
                    avg30[1] if avg30 else None,
                )
            )
        return rows

    @staticmethod
    def _format_average(value: float | None) -> str:
        return f"{value:.1f}" if value is not None else "-"

    def _on_sort_keywords(self, sort_index: int):
        if self.keywords_sort_index == sort_index:
            self.keywords_sort_reverse = not self.keywords_sort_reverse
        else:
            self.keywords_sort_index = sort_index
            self.keywords_sort_reverse = False
        self.refresh_keywords_tab()

    def _sort_keyword_rows(self, rows):
        idx = self.keywords_sort_index
        with_value = [r for r in rows if r[idx] is not None]
        without_value = [r for r in rows if r[idx] is None]
        with_value.sort(key=lambda r: self._sort_value(r[idx]), reverse=self.keywords_sort_reverse)
        return with_value + without_value

    POLISH_ALPHABET = "aąbcćdeęfghijklłmnńoóprqsśtuvwxyzźż"

    @classmethod
    def _sort_value(cls, value):
        """Teksty sortowane alfabetycznie po polsku, bez rozróżniania wielkości liter
        (zwykłe porównanie stawia wielkie litery przed małymi, a ą, ś, ż... za z)."""
        if not isinstance(value, str):
            return value
        return [
            1000 + cls.POLISH_ALPHABET.index(ch) if ch in cls.POLISH_ALPHABET else ord(ch)
            for ch in value.casefold()
        ]

    def _update_keyword_headings(self):
        for col_id, sort_index, text in self.KEYWORD_SORT_COLUMNS:
            if self.keywords_sort_index == sort_index:
                text += " ▼" if self.keywords_sort_reverse else " ▲"
            self.keywords_table.heading(col_id, text=text, command=lambda idx=sort_index: self._on_sort_keywords(idx))

    def _keyword_row_tags(self, row_number: int, keyword_id: int) -> tuple[str, ...]:
        if keyword_id in self.selected_keyword_ids:
            return ("checked",)
        return ("stripe",) if row_number % 2 else ()

    def _set_keyword_checked(self, keyword_id: int, checked: bool, row_number: int):
        if checked:
            self.selected_keyword_ids.add(keyword_id)
        else:
            self.selected_keyword_ids.discard(keyword_id)
        self.keywords_table.set(str(keyword_id), "check", "☑" if checked else "☐")
        self.keywords_table.item(str(keyword_id), tags=self._keyword_row_tags(row_number, keyword_id))

    def refresh_keywords_tab(self):
        table = self.keywords_table
        table.delete(*table.get_children())
        self._update_keyword_headings()
        self.keyword_row_ids = []

        if self.current_project_id is None:
            table.insert("", "end", values=("", "Wybierz lub utwórz projekt."))
            self._redraw_chart()
            return

        rows = self._sort_keyword_rows(self._get_keyword_rows())
        if not rows:
            table.insert("", "end", values=("", "Brak słów kluczowych - dodaj pierwsze powyżej."))
            self._redraw_chart()
            return

        self.keyword_row_ids = [r[0] for r in rows]
        ads_source = db.get_setting(self.conn, "popularity_source") == tracker.POPULARITY_SOURCE_ADS
        self.selected_keyword_ids &= set(self.keyword_row_ids)  # usuń frazy, których już nie ma

        for row_number, (
            keyword_id,
            keyword,
            page_url,
            period_end,
            position,
            _clicks,
            _impressions,
            _ctr,
            best_position,
            popularity,
            _checked_from,
            impressions7,
            impressions30,
            clicks7,
            clicks30,
        ) in enumerate(rows):
            table.insert(
                "",
                "end",
                iid=str(keyword_id),
                tags=self._keyword_row_tags(row_number, keyword_id),
                values=(
                    "☑" if keyword_id in self.selected_keyword_ids else "☐",
                    keyword,
                    page_url or "cała domena",
                    f"{position:.1f}" if position is not None else "-",
                    f"{best_position:.1f}" if best_position is not None else "-",
                    self._format_popularity(popularity, ads_source),
                    self._format_average(impressions7),
                    self._format_average(impressions30),
                    self._format_average(clicks7),
                    self._format_average(clicks30),
                    period_end or "-",
                    "✕ Usuń",
                ),
            )

        self._redraw_chart()

    @staticmethod
    def _format_popularity(popularity: int | None, ads_source: bool) -> str:
        if popularity is None:
            return "-"
        if ads_source and popularity == 0:
            return "<10"  # Google Ads nie podaje liczby wyszukiwań poniżej progu
        return str(popularity)

    def _on_keywords_table_click(self, event):
        """Kliknięcie w wiersz przełącza zaznaczenie frazy (do wykresu),
        kliknięcie w kolumnę "✕ Usuń" usuwa frazę."""
        table = self.keywords_table
        if table.identify_region(event.x, event.y) != "cell":
            return
        item = table.identify_row(event.y)
        if not item or not item.isdigit():
            return
        keyword_id = int(item)
        if table.identify_column(event.x) == f"#{len(table['columns'])}":
            self._on_delete_keyword(keyword_id)
            return
        row_number = self.keyword_row_ids.index(keyword_id)
        self._set_keyword_checked(keyword_id, keyword_id not in self.selected_keyword_ids, row_number)
        self._redraw_chart()

    def _on_add_keyword(self):
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return
        keyword = self.new_keyword_entry.get().strip()
        if not keyword:
            return
        page_url = self.new_page_entry.get().strip()
        db.add_keyword(self.conn, self.current_project_id, keyword, page_url)
        self.new_keyword_entry.delete(0, "end")
        self.new_page_entry.delete(0, "end")
        self.refresh_all()
        # pobiera całą historię nowej frazy z okresu projektu i sprawdza jej popularność
        self._on_run_check(with_popularity=True)

    def _on_delete_keyword(self, keyword_id: int):
        if messagebox.askyesno("Usuń słowo kluczowe", "Usunąć to słowo kluczowe wraz z jego historią?"):
            db.delete_keyword(self.conn, keyword_id)
            self.refresh_all()

    def _on_run_check(self, with_popularity: bool = False):
        """Pobiera brakujące dzienne dane fraz projektu. with_popularity: dodatkowo
        sprawdza popularność fraz, które jej jeszcze nie mają (np. świeżo dodanych) -
        pozostałe są pomijane, jeśli sprawdzano je w ciągu POPULARITY_REFRESH_DAYS dni."""
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return
        if self.check_button.cget("state") == "disabled":
            # trwa inne sprawdzanie (np. przy starcie) - uruchom ponownie po jego zakończeniu
            self.sync_pending = True
            self.sync_pending_popularity |= with_popularity
            return

        self.check_button.configure(state="disabled")
        self.popularity_button.configure(state="disabled")
        self.status_label.configure(text="Sprawdzanie w toku...")
        project_id = self.current_project_id

        def progress(message: str):
            self.after(0, lambda: self.status_label.configure(text=message))

        def worker():
            error = None
            done_text = "Zakończono."
            try:
                keywords_count, rows_count = tracker.run_sync(self.conn, project_id, progress_callback=progress)
                done_text = (
                    f"Zakończono. Pobrano dane {keywords_count} fraz, {rows_count} dziennych wpisów."
                    if keywords_count
                    else "Dane wszystkich fraz są już aktualne - nic nie pobrano."
                )
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                error = e
            if with_popularity:
                try:
                    checked = tracker.run_popularity_check(
                        self.conn,
                        project_id,
                        progress_callback=progress,
                        skip_checked_within_days=POPULARITY_REFRESH_DAYS,
                    )
                    if checked:
                        done_text += f" Sprawdzono popularność {checked} fraz."
                except Exception as e:  # noqa: BLE001 - Google Trends/Ads bywa niestabilne
                    popularity_error = RuntimeError(f"Sprawdzanie popularności nie powiodło się:\n\n{e}")
                    error = RuntimeError(f"{error}\n\n{popularity_error}") if error else popularity_error
            self.after(0, lambda: self._on_check_finished(error, done_text=done_text))

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_popularity_check(self):
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return

        self.check_button.configure(state="disabled")
        self.popularity_button.configure(state="disabled")
        self.status_label.configure(text="Sprawdzanie popularności w toku...")
        project_id = self.current_project_id

        def progress(message: str):
            self.after(0, lambda: self.status_label.configure(text=message))

        def worker():
            error = None
            done_text = "Zakończono."
            try:
                checked = tracker.run_popularity_check(
                    self.conn, project_id, progress_callback=progress, skip_checked_today=True
                )
                done_text = (
                    f"Zakończono. Sprawdzono popularność {checked} fraz."
                    if checked
                    else "Popularność wszystkich fraz już dziś aktualna - pominięto sprawdzanie."
                )
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                error = e
            self.after(0, lambda: self._on_check_finished(error, done_text=done_text))

        threading.Thread(target=worker, daemon=True).start()

    def _run_startup_update(self):
        """Przy starcie aplikacji dociąga dzienne dane wszystkich fraz we wszystkich
        projektach do dziś (dni jeszcze niesprawdzone + ponownie ostatnie
        RECENT_DATA_REFRESH_DAYS dni, raz dziennie)
        oraz odświeża popularność fraz (Google Ads / Trends)
        (tylko frazy sprawdzane ponad POPULARITY_REFRESH_DAYS dni temu),
        a raz dziennie sprawdza obecność fraz w AI (jeśli podano klucz API)."""
        projects = db.list_projects(self.conn)
        if not projects:
            return

        today = date.today().isoformat()
        run_ai = bool(tracker.configured_ai_engines(self.conn)) and db.get_setting(
            self.conn, "ai_last_auto_check"
        ) != today
        if run_ai:
            # zapisujemy od razu - nawet nieudane sprawdzenie nie powtórzy się przy kolejnym starcie tego dnia
            db.set_setting(self.conn, "ai_last_auto_check", today)
            self.ai_busy = True
            self._update_ai_buttons()
            self.ai_status_label.configure(text="Sprawdzanie przy starcie...")

        self.check_button.configure(state="disabled")
        self.popularity_button.configure(state="disabled")
        self.status_label.configure(text="Aktualizacja danych od ostatniego sprawdzenia...")

        def worker():
            errors = []
            updated_keywords = total_rows = popularity_checked = ai_queries = 0
            for project_id, name, _site_url in projects:

                def progress(message: str, name=name):
                    self.after(0, lambda: self.status_label.configure(text=f"[{name}] {message}"))

                try:
                    keywords_count, rows_count = tracker.run_sync(
                        self.conn, project_id, progress_callback=progress, refresh_days=RECENT_DATA_REFRESH_DAYS
                    )
                    updated_keywords += keywords_count
                    total_rows += rows_count
                except Exception as e:  # noqa: BLE001 - błąd jednego projektu nie blokuje pozostałych
                    errors.append(f"{name} (pozycje): {e}")
                try:
                    popularity_checked += tracker.run_popularity_check(
                        self.conn,
                        project_id,
                        progress_callback=progress,
                        skip_checked_within_days=POPULARITY_REFRESH_DAYS,
                    )
                except Exception as e:  # noqa: BLE001 - Google Trends/Ads bywa niestabilne, nie blokuje reszty
                    errors.append(f"{name} (popularność): {e}")
                if run_ai:
                    try:
                        queries, ai_errors = tracker.run_ai_visibility_check(
                            self.conn, project_id, progress_callback=progress
                        )
                        ai_queries += queries
                        errors += [f"{name} (obecność w AI): {e}" for e in ai_errors]
                    except Exception as e:  # noqa: BLE001 - błąd AI nie blokuje reszty
                        errors.append(f"{name} (obecność w AI): {e}")

            error = (
                RuntimeError("Automatyczna aktualizacja przy starcie nie powiodła się:\n\n" + "\n\n".join(errors))
                if errors
                else None
            )
            positions_info = (
                f"pozycje: {updated_keywords} fraz, {total_rows} dziennych wpisów"
                if updated_keywords
                else "pozycje aktualne"
            )
            popularity_info = (
                f"popularność: {popularity_checked} fraz"
                if popularity_checked
                else f"popularność aktualna (< {POPULARITY_REFRESH_DAYS} dni)"
            )
            done_text = f"Start: {positions_info}; {popularity_info}."
            if run_ai:
                done_text = done_text[:-1] + f"; obecność w AI: {ai_queries} zapytań."

            def finish():
                if run_ai:
                    self.ai_busy = False
                    self._update_ai_buttons()
                    self.ai_status_label.configure(text=f"Przy starcie wykonano {ai_queries} zapytań.")
                self._on_check_finished(error, done_text=done_text)

            self.after(0, finish)

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_finished(self, error: Exception | None, done_text: str = "Zakończono."):
        self.check_button.configure(state="normal")
        self.popularity_button.configure(state="normal")
        if error:
            self.status_label.configure(text="Błąd podczas sprawdzania.")
            ErrorDialog(self, "Błąd", str(error))
        else:
            self.status_label.configure(text=done_text)
        self.refresh_all()
        if self.sync_pending:
            with_popularity = self.sync_pending_popularity
            self.sync_pending = self.sync_pending_popularity = False
            self._on_run_check(with_popularity=with_popularity)

    def _on_toggle_select_all(self):
        if not self.keyword_row_ids:
            return
        new_value = not all(kid in self.selected_keyword_ids for kid in self.keyword_row_ids)
        for row_number, keyword_id in enumerate(self.keyword_row_ids):
            self._set_keyword_checked(keyword_id, new_value, row_number)
        self._redraw_chart()

    def _redraw_chart(self):
        for widget in self.chart_area.winfo_children():
            widget.destroy()
        self.chart_canvas = None

        selected_ids = [kid for kid in self.keyword_row_ids if kid in self.selected_keyword_ids]
        if not selected_ids:
            ctk.CTkLabel(
                self.chart_area,
                text="Zaznacz frazy w tabeli poniżej,\naby zobaczyć wykres pozycji.",
                text_color="gray60",
            ).pack(expand=True, padx=8, pady=8)
            return

        labels_by_id = {
            kid: (f"{keyword} ({page_url})" if page_url else keyword)
            for kid, keyword, page_url in db.list_keywords(self.conn, self.current_project_id)
        }
        series = {}
        for keyword_id in selected_ids:
            label = labels_by_id.get(keyword_id, f"#{keyword_id}")
            history = db.get_history(self.conn, keyword_id)
            series[label] = [(period_end, position) for period_end, position, *_ in history]

        self.chart_canvas = build_position_chart(self.chart_area, series, figsize=(4.2, 2.3))
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

    # --- zakładka: statystyki ---

    def _build_stats_tab(self):
        tab = self.tab_stats
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        self.stats_cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.stats_cards_frame.grid(row=0, column=0, sticky="we", pady=(0, 12))

        table_frame = ctk.CTkFrame(tab, fg_color="transparent")
        table_frame.grid(row=1, column=0, sticky="nswe")
        self.stats_table = self._make_table(
            table_frame,
            [
                ("keyword", "Fraza kluczowa", 260, "w"),
                ("position", "Pozycja", 80, "center"),
                ("trend", "Zmiana", 150, "center"),
                ("impressions7", "Wyśw. 7 dni", 90, "center"),
                ("impressions30", "Wyśw. 30 dni", 95, "center"),
                ("clicks7", "Klik. 7 dni", 85, "center"),
                ("clicks30", "Klik. 30 dni", 90, "center"),
                ("ctr", "CTR", 80, "center"),
            ],
        )

    def _make_stat_card(self, parent, title: str, value: str, column: int):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.grid(row=0, column=column, padx=6, sticky="we")
        ctk.CTkLabel(card, text=title, text_color="gray60").pack(padx=16, pady=(12, 0))
        ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold")).pack(padx=16, pady=(0, 12))

    def refresh_stats_tab(self):
        for widget in self.stats_cards_frame.winfo_children():
            widget.destroy()
        table = self.stats_table
        table.delete(*table.get_children())

        if self.current_project_id is None:
            table.insert("", "end", values=("Wybierz lub utwórz projekt.",))
            return

        rows = self._get_keyword_rows()
        with_data = [r for r in rows if r[4] is not None]

        keyword_count = len(rows)
        avg_position = sum(r[4] for r in with_data) / len(with_data) if with_data else None
        total_impressions = sum(r[6] or 0 for r in rows)
        total_clicks = sum(r[5] or 0 for r in rows)

        self._make_stat_card(self.stats_cards_frame, "Słowa kluczowe", str(keyword_count), 0)
        self._make_stat_card(
            self.stats_cards_frame, "Średnia pozycja", f"{avg_position:.1f}" if avg_position is not None else "-", 1
        )
        self._make_stat_card(self.stats_cards_frame, "Wyświetlenia", str(total_impressions), 2)
        self._make_stat_card(self.stats_cards_frame, "Kliknięcia", str(total_clicks), 3)

        for row_number, (
            keyword_id,
            keyword,
            _page_url,
            _period_end,
            position,
            _clicks,
            _impressions,
            ctr,
            _best_position,
            _popularity,
            _checked_from,
            impressions7,
            impressions30,
            clicks7,
            clicks30,
        ) in enumerate(rows):
            history = db.get_history(self.conn, keyword_id)
            positions_with_data = [h[1] for h in history if h[1] is not None]
            trend = "-"
            if len(positions_with_data) >= 2:
                diff = positions_with_data[-2] - positions_with_data[-1]
                if diff > 0.05:
                    trend = f"▲ poprawa o {diff:.1f}"
                elif diff < -0.05:
                    trend = f"▼ spadek o {abs(diff):.1f}"
                else:
                    trend = "= bez zmian"

            table.insert(
                "",
                "end",
                tags=("stripe",) if row_number % 2 else (),
                values=(
                    keyword,
                    f"{position:.1f}" if position is not None else "-",
                    trend,
                    self._format_average(impressions7),
                    self._format_average(impressions30),
                    self._format_average(clicks7),
                    self._format_average(clicks30),
                    f"{ctr * 100:.1f}%" if ctr is not None else "-",
                ),
            )

    # --- zakładka: popularność strony ---

    SITE_POPULARITY_AGGREGATIONS = {
        "Dzień": site_popularity.AGGREGATION_DAY,
        "Tydzień": site_popularity.AGGREGATION_WEEK,
        "Miesiąc": site_popularity.AGGREGATION_MONTH,
    }

    def _build_site_popularity_tab(self):
        tab = self.tab_site_popularity
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(3, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Wypadkowa pozycji wszystkich fraz ważonych ich popularnością (Google Ads lub Trends) i klikalnością "
                "danej pozycji.\n100% = wszystkie frazy na pozycji 1. Frazy bez sprawdzonej popularności "
                "liczone są ze średnią mocą - użyj \"Sprawdź popularność\", by uzyskać dokładniejszy wynik."
            ),
            text_color="gray60",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.site_popularity_cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.site_popularity_cards_frame.grid(row=1, column=0, sticky="we", pady=(0, 12))

        # przedział wykresu: wartości dzienne albo średnie z tygodni / miesięcy
        aggregation_bar = ctk.CTkFrame(tab, fg_color="transparent")
        aggregation_bar.grid(row=2, column=0, sticky="w", pady=(0, 8))
        ctk.CTkLabel(aggregation_bar, text="Przedział:").pack(side="left", padx=(0, 8))
        self.site_popularity_aggregation = ctk.CTkSegmentedButton(
            aggregation_bar,
            values=list(self.SITE_POPULARITY_AGGREGATIONS),
            command=lambda _value: self.refresh_site_popularity_tab(),
        )
        self.site_popularity_aggregation.set("Dzień")
        self.site_popularity_aggregation.pack(side="left")

        self.site_popularity_chart_area = ctk.CTkFrame(tab)
        self.site_popularity_chart_area.grid(row=3, column=0, sticky="nswe")

    def refresh_site_popularity_tab(self):
        for widget in self.site_popularity_cards_frame.winfo_children():
            widget.destroy()
        for widget in self.site_popularity_chart_area.winfo_children():
            widget.destroy()

        if self.current_project_id is None:
            ctk.CTkLabel(self.site_popularity_chart_area, text="Wybierz lub utwórz projekt.").pack(padx=8, pady=8)
            return

        series = compute_site_popularity(self.conn, self.current_project_id)
        current = series[-1][1] if series else None
        month_ago = series[-31][1] if len(series) >= 31 else None

        self._make_stat_card(
            self.site_popularity_cards_frame,
            "Popularność strony",
            f"{current:.1f}%" if current is not None else "-",
            0,
        )
        change_text = "-"
        if current is not None and month_ago is not None:
            diff = current - month_ago
            change_text = f"{'▲' if diff > 0 else '▼' if diff < 0 else '='} {abs(diff):.1f} pp"
        self._make_stat_card(self.site_popularity_cards_frame, "Zmiana (30 dni)", change_text, 1)
        self._make_stat_card(
            self.site_popularity_cards_frame,
            "Dane z dnia",
            series[-1][0] if series else "-",
            2,
        )

        aggregation = self.SITE_POPULARITY_AGGREGATIONS[self.site_popularity_aggregation.get()]
        canvas = build_site_popularity_chart(self.site_popularity_chart_area, aggregate_series(series, aggregation))
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)


    # --- zakładka: obecność w AI ---

    def _build_ai_tab(self):
        tab = self.tab_ai
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(4, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Każda fraza jest zadawana Gemini (z wyszukiwaniem Google) tak, jak wpisałby ją użytkownik. "
                "✔ = domena wśród źródeł odpowiedzi (#miejsce na liście),\n~ = domena lub nazwa marki tylko "
                "wspomniana w tekście, ✗ = brak. Odpowiedzi AI są zmienne - patrz na trend. Klucz API ustawisz w "
                "Ustawieniach, nazwy marki w \"Edytuj projekt\"."
            ),
            text_color="gray60",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        controls = ctk.CTkFrame(tab, fg_color="transparent")
        controls.grid(row=1, column=0, sticky="we", pady=(0, 8))
        self.ai_check_button = ctk.CTkButton(
            controls, text="Sprawdź obecność w AI", width=210, command=self._on_run_ai_check
        )
        self.ai_check_button.pack(side="left", padx=(0, 8))
        self.ai_retry_button = ctk.CTkButton(
            controls,
            text="Ponów frazy z błędem",
            width=210,
            fg_color="gray40",
            command=lambda: self._on_run_ai_check(only_failed=True),
        )
        self.ai_retry_button.pack(side="left", padx=(0, 12))
        self.ai_busy = False  # trwa sprawdzanie obecności w AI (ręczne albo przy starcie)
        self.ai_failed_count = 0  # frazy bieżącego projektu, których ostatnie sprawdzenie AI skończyło się błędem
        self.ai_skip_today_var = ctk.BooleanVar(value=True)
        ctk.CTkCheckBox(controls, text="Pomijaj frazy sprawdzone dzisiaj", variable=self.ai_skip_today_var).pack(
            side="left", padx=(0, 12)
        )
        self.ai_status_label = ctk.CTkLabel(controls, text="", justify="left")
        self.ai_status_label.pack(side="left")

        self.ai_cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.ai_cards_frame.grid(row=2, column=0, sticky="we", pady=(0, 8))

        self.ai_chart_area = ctk.CTkFrame(tab, height=200)
        self.ai_chart_area.grid(row=3, column=0, sticky="we", pady=(0, 8))

        bottom = ctk.CTkFrame(tab, fg_color="transparent")
        bottom.grid(row=4, column=0, sticky="nswe")
        bottom.grid_columnconfigure(0, weight=3)
        bottom.grid_columnconfigure(1, weight=2)
        bottom.grid_rowconfigure(0, weight=1)

        table_frame = ctk.CTkFrame(bottom, fg_color="transparent")
        table_frame.grid(row=0, column=0, sticky="nswe", padx=(0, 8))
        self.ai_table = self._make_table(
            table_frame,
            [("keyword", "Fraza kluczowa", 220, "w")]
            + [(engine, name, 120, "center") for engine, (name, *_rest) in ai_visibility.ENGINES.items()]
            + [("date", "Sprawdzono", 130, "center")],
        )
        self.ai_table.bind("<ButtonRelease-1>", self._on_ai_table_click)

        self.ai_details = ctk.CTkTextbox(bottom, wrap="word")
        self.ai_details.grid(row=0, column=1, sticky="nswe")
        self.ai_selected_keyword_id: int | None = None

    @staticmethod
    def _format_ai_result(check: dict | None) -> str:
        if not check:
            return "-"
        if check["error"]:
            return "⚠ błąd"
        if check["cited"]:
            return f"✔ #{check['citation_rank']}" + (" + wzmianka" if check["mentioned"] else "")
        return "~ wzmianka" if check["mentioned"] else "✗ brak"

    @staticmethod
    def _format_local_time(timestamp: str) -> str:
        return datetime.fromisoformat(timestamp).astimezone().strftime("%Y-%m-%d %H:%M")

    def _update_ai_buttons(self):
        self.ai_check_button.configure(state="disabled" if self.ai_busy else "normal")
        self.ai_retry_button.configure(
            text=f"Ponów frazy z błędem ({self.ai_failed_count})",
            state="disabled" if self.ai_busy or not self.ai_failed_count else "normal",
        )

    def refresh_ai_tab(self):
        for widget in self.ai_cards_frame.winfo_children():
            widget.destroy()
        for widget in self.ai_chart_area.winfo_children():
            widget.destroy()
        table = self.ai_table
        table.delete(*table.get_children())

        if self.current_project_id is None:
            table.insert("", "end", values=("Wybierz lub utwórz projekt.",))
            self._show_ai_details(None)
            self.ai_failed_count = 0
            self._update_ai_buttons()
            return

        latest = db.get_latest_ai_checks(self.conn, self.current_project_id)
        keywords = db.list_keywords(self.conn, self.current_project_id)
        self.ai_failed_count = len(
            {
                keyword
                for keyword_id, keyword, _page_url in keywords
                if any(check["error"] for check in latest.get(keyword_id, {}).values())
            }
        )
        self._update_ai_buttons()
        if not keywords:
            table.insert("", "end", values=("Brak słów kluczowych - dodaj je w zakładce \"Słowa kluczowe\".",))

        for row_number, (keyword_id, keyword, page_url) in enumerate(keywords):
            checks = latest.get(keyword_id, {})
            last_checked = max((c["checked_at"] for c in checks.values()), default=None)
            table.insert(
                "",
                "end",
                iid=str(keyword_id),
                tags=("stripe",) if row_number % 2 else (),
                values=(
                    f"{keyword} ({page_url})" if page_url else keyword,
                    *(self._format_ai_result(checks.get(engine)) for engine in ai_visibility.ENGINES),
                    self._format_local_time(last_checked) if last_checked else "-",
                ),
            )

        # karty: udział fraz z cytowaną domeną w najnowszych sprawdzeniach każdego asystenta
        column = 0
        for engine, (name, *_rest) in ai_visibility.ENGINES.items():
            results = [c[engine] for c in latest.values() if engine in c and not c[engine]["error"]]
            if not results:
                continue
            cited = sum(1 for r in results if r["cited"])
            self._make_stat_card(
                self.ai_cards_frame, f"{name} - cytowana", f"{cited}/{len(results)} ({cited / len(results):.0%})", column
            )
            column += 1
        if column == 0:
            ctk.CTkLabel(
                self.ai_cards_frame, text="Brak sprawdzeń - kliknij \"Sprawdź obecność w AI\".", text_color="gray60"
            ).grid(row=0, column=0, sticky="w")

        series: dict[str, list[tuple[str, float]]] = {}
        for day, engine, checked, cited in db.get_ai_history_for_project(self.conn, self.current_project_id):
            name = ai_visibility.ENGINES.get(engine, (engine,))[0]
            series.setdefault(name, []).append((day, 100 * (cited or 0) / checked))
        canvas = build_ai_visibility_chart(self.ai_chart_area, series)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=4, pady=4)

        if self.ai_selected_keyword_id not in {k[0] for k in keywords}:
            self.ai_selected_keyword_id = None
        self._show_ai_details(self.ai_selected_keyword_id, latest)

    def _on_ai_table_click(self, event):
        item = self.ai_table.identify_row(event.y)
        if item and item.isdigit():
            self.ai_selected_keyword_id = int(item)
            self._show_ai_details(self.ai_selected_keyword_id)

    def _show_ai_details(self, keyword_id: int | None, latest: dict | None = None):
        """Pokazuje w panelu obok tabeli odpowiedzi asystentów AI i ich źródła dla wybranej frazy."""
        box = self.ai_details
        box.configure(state="normal")
        box.delete("1.0", "end")
        if keyword_id is None:
            box.insert("1.0", "Kliknij frazę w tabeli, aby zobaczyć odpowiedzi asystentów AI i ich źródła.")
            box.configure(state="disabled")
            return
        if latest is None:
            latest = db.get_latest_ai_checks(self.conn, self.current_project_id)
        checks = latest.get(keyword_id, {})
        project = db.get_project(self.conn, self.current_project_id)
        domain = ai_visibility.domain_from_site_url(project[2]) if project else ""
        if not checks:
            box.insert("1.0", "Tej frazy nie sprawdzano jeszcze w żadnym asystencie AI.")
        for engine, (name, *_rest) in ai_visibility.ENGINES.items():
            check = checks.get(engine)
            if not check:
                continue
            box.insert(
                "end",
                f"===== {name} ({self._format_local_time(check['checked_at'])}): "
                f"{self._format_ai_result(check)} =====\n\n",
            )
            if check["error"]:
                box.insert("end", f"Błąd: {check['error']}\n\n")
                continue
            box.insert("end", (check["answer"].strip() or "(pusta odpowiedź)") + "\n\n")
            if check["sources"]:
                box.insert("end", "Źródła:\n")
                for index, source in enumerate(check["sources"], start=1):
                    marker = "  ◀ TWOJA DOMENA" if ai_visibility.source_matches(source, domain) else ""
                    title = f"{source['title']} - " if source.get("title") else ""
                    box.insert("end", f"{index}. {title}{source['url']}{marker}\n")
                box.insert("end", "\n")
        box.configure(state="disabled")

    def _on_run_ai_check(self, only_failed: bool = False):
        """only_failed: ponawia tylko frazy, których ostatnie sprawdzenie skończyło się błędem."""
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return
        engines = tracker.configured_ai_engines(self.conn)
        if not engines:
            messagebox.showinfo(
                "Brak klucza API",
                "Podaj klucz API Gemini w Ustawieniach (sekcja \"Obecność w AI\").",
            )
            return

        self.ai_busy = True
        self._update_ai_buttons()
        self.ai_status_label.configure(text="Ponawianie fraz z błędem..." if only_failed else "Sprawdzanie w toku...")
        project_id = self.current_project_id
        skip_today = self.ai_skip_today_var.get()

        def progress(message: str):
            self.after(0, lambda: self.ai_status_label.configure(text=message))

        def worker():
            error = None
            done_text = "Zakończono."
            try:
                queries, errors = tracker.run_ai_visibility_check(
                    self.conn,
                    project_id,
                    progress_callback=progress,
                    skip_checked_today=skip_today,
                    only_failed=only_failed,
                )
                if queries:
                    done_text = f"Zakończono. Wykonano {queries} zapytań."
                elif only_failed:
                    done_text = "Brak fraz z błędem - nic nie wysłano."
                else:
                    done_text = "Wszystkie frazy sprawdzono już dzisiaj - nic nie wysłano."
                if errors:
                    error = RuntimeError(f"Błędy ({len(errors)}):\n\n" + "\n\n".join(errors))
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                error = e
            self.after(0, lambda: self._on_ai_check_finished(error, done_text))

        threading.Thread(target=worker, daemon=True).start()

    def _on_ai_check_finished(self, error: Exception | None, done_text: str):
        self.ai_busy = False
        self._update_ai_buttons()
        self.ai_status_label.configure(text=done_text if not error else f"{done_text} Wystąpiły błędy.")
        if error:
            ErrorDialog(self, "Błąd sprawdzania obecności w AI", str(error))
        self.refresh_all()
