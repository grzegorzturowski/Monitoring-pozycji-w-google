"""GUI aplikacji (CustomTkinter): projekty, słowa kluczowe, wykresy, statystyki."""

import threading
from tkinter import filedialog, messagebox, ttk

import customtkinter as ctk

import db
import tracker
from charts import build_position_chart, build_site_popularity_chart
from site_popularity import compute_site_popularity

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")

POPULARITY_REFRESH_DAYS = 7  # jak często (w dniach) odświeżać popularność z Google Trends przy starcie


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
    def __init__(self, master, title: str = "Nowy projekt", confirm_text: str = "Dodaj", initial_name: str = "", initial_site_url: str = ""):
        super().__init__(master)
        self.title(title)
        self.geometry("480x420")
        self.resizable(False, False)
        self.result: tuple[str, str] | None = None
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
        self.result = (name, site_url)
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, conn):
        super().__init__(master)
        self.conn = conn
        self.title("Ustawienia")
        self.geometry("500x430")
        self.resizable(False, False)
        self.grab_set()

        ctk.CTkLabel(self, text="Plik konta usługi (service-account.json):").pack(anchor="w", padx=16, pady=(16, 0))
        row = ctk.CTkFrame(self, fg_color="transparent")
        row.pack(fill="x", padx=16, pady=(4, 12))
        self.service_account_entry = ctk.CTkEntry(row, width=340)
        self.service_account_entry.insert(0, db.get_setting(conn, "service_account_file") or "")
        self.service_account_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(row, text="Wybierz...", width=90, command=self._browse_file).pack(side="left")

        ctk.CTkLabel(self, text="Okres agregacji pozycji (dni):").pack(anchor="w", padx=16, pady=(4, 0))
        self.date_range_entry = ctk.CTkEntry(self, width=100)
        self.date_range_entry.insert(0, db.get_setting(conn, "date_range_days") or "7")
        self.date_range_entry.pack(anchor="w", padx=16, pady=(4, 12))

        ctk.CTkLabel(self, text="Opóźnienie danych Search Console (dni):").pack(anchor="w", padx=16)
        self.delay_entry = ctk.CTkEntry(self, width=100)
        self.delay_entry.insert(0, db.get_setting(conn, "data_delay_days") or "3")
        self.delay_entry.pack(anchor="w", padx=16, pady=(4, 16))

        ctk.CTkLabel(
            self, text="Google Trends - kraj (kod ISO, np. PL; puste = cały świat):"
        ).pack(anchor="w", padx=16)
        self.trends_geo_entry = ctk.CTkEntry(self, width=100)
        self.trends_geo_entry.insert(0, db.get_setting(conn, "trends_geo") or "PL")
        self.trends_geo_entry.pack(anchor="w", padx=16, pady=(4, 12))

        ctk.CTkLabel(
            self, text="Google Trends - okres (np. \"today 12-m\", \"today 3-m\", \"today 5-y\"):"
        ).pack(anchor="w", padx=16)
        self.trends_timeframe_entry = ctk.CTkEntry(self, width=200)
        self.trends_timeframe_entry.insert(0, db.get_setting(conn, "trends_timeframe") or "today 12-m")
        self.trends_timeframe_entry.pack(anchor="w", padx=16, pady=(4, 16))

        button_row = ctk.CTkFrame(self, fg_color="transparent")
        button_row.pack(pady=4)
        ctk.CTkButton(button_row, text="Anuluj", command=self.destroy, fg_color="gray40").pack(side="left", padx=8)
        ctk.CTkButton(button_row, text="Zapisz", command=self._on_save).pack(side="left", padx=8)

    def _browse_file(self):
        path = filedialog.askopenfilename(title="Wybierz plik JSON konta usługi", filetypes=[("JSON", "*.json")])
        if path:
            self.service_account_entry.delete(0, "end")
            self.service_account_entry.insert(0, path)

    def _on_save(self):
        try:
            date_range_days = int(self.date_range_entry.get().strip())
            data_delay_days = int(self.delay_entry.get().strip())
        except ValueError:
            messagebox.showwarning("Błędne dane", "Okres i opóźnienie muszą być liczbami całkowitymi.", parent=self)
            return

        db.set_setting(self.conn, "service_account_file", self.service_account_entry.get().strip())
        db.set_setting(self.conn, "date_range_days", str(date_range_days))
        db.set_setting(self.conn, "data_delay_days", str(data_delay_days))
        db.set_setting(self.conn, "trends_geo", self.trends_geo_entry.get().strip())
        db.set_setting(self.conn, "trends_timeframe", self.trends_timeframe_entry.get().strip() or "today 12-m")
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.conn = db.connect()
        self.current_project_id: int | None = None
        self.selected_keyword_ids: set[int] = set()  # frazy zaznaczone do wykresu
        self.keyword_row_ids: list[int] = []  # frazy aktualnie widoczne w tabeli
        self.chart_canvas = None
        self.keywords_sort_index = 1  # indeks w krotce z db.get_latest_for_project - domyślnie "Fraza kluczowa"
        self.keywords_sort_reverse = False

        self.title("Monitoring pozycji w Google")
        self.geometry("1100x700")
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
            name, site_url = dialog.result
            try:
                project_id = db.add_project(self.conn, name, site_url)
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
        dialog = ProjectDialog(
            self, title="Edytuj projekt", confirm_text="Zapisz", initial_name=name, initial_site_url=site_url
        )
        self.wait_window(dialog)
        if dialog.result:
            new_name, new_site_url = dialog.result
            try:
                db.update_project(self.conn, self.current_project_id, new_name, new_site_url)
            except Exception as e:
                ErrorDialog(self, "Błąd", f"Nie udało się zapisać zmian:\n\n{e}")
                return
            self.refresh_projects()
            self._highlight_selected_project()

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
        self._tab_refreshers = {
            "Słowa kluczowe": self.refresh_keywords_tab,
            "Statystyki": self.refresh_stats_tab,
            "Popularność strony": self.refresh_site_popularity_tab,
        }
        self._dirty_tabs: set[str] = set(self._tab_refreshers)

        self._setup_table_style()
        self._build_keywords_tab()
        self._build_stats_tab()
        self._build_site_popularity_tab()

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
            rowheight=int(32 * scaling),
            borderwidth=0,
            font=("Segoe UI", 12),
        )
        style.map("Treeview", background=[("selected", "#1F6AA5")], foreground=[("selected", "white")])
        style.configure(
            "Treeview.Heading",
            background=heading_bg,
            foreground=fg,
            relief="flat",
            font=("Segoe UI", 12, "bold"),
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
        self.backfill_button = ctk.CTkButton(
            action_grid, text="Pobierz dane historyczne", width=210, fg_color="gray40", command=self._on_run_backfill
        )
        self.backfill_button.grid(row=0, column=1, pady=(0, 6))
        self.popularity_button = ctk.CTkButton(
            action_grid,
            text="Sprawdź popularność",
            width=210,
            fg_color="gray40",
            command=self._on_run_popularity_check,
        )
        self.popularity_button.grid(row=1, column=0, padx=(0, 8))
        self.select_all_button = ctk.CTkButton(
            action_grid,
            text="Zaznacz / odznacz wszystkie",
            width=210,
            fg_color="gray40",
            command=self._on_toggle_select_all,
        )
        self.select_all_button.grid(row=1, column=1)

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
                ("impressions", "Wyświetlenia", 95, "center"),
                ("clicks", "Kliknięcia", 80, "center"),
                ("date", "Dane z dnia", 95, "center"),
                ("delete", "", 60, "center"),
            ],
        )
        self.keywords_table.bind("<ButtonRelease-1>", self._on_keywords_table_click)

    # (id kolumny tabeli, indeks w krotce z db.get_latest_for_project, nagłówek) - sortowalne kolumny
    KEYWORD_SORT_COLUMNS = [
        ("keyword", 1, "Fraza kluczowa"),
        ("page", 2, "Podstrona"),
        ("position", 4, "Pozycja"),
        ("best", 8, "Najlepsza"),
        ("popularity", 9, "Popularność"),
        ("impressions", 6, "Wyświetlenia"),
        ("clicks", 5, "Kliknięcia"),
        ("date", 3, "Dane z dnia"),
    ]

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
        with_value.sort(key=lambda r: r[idx], reverse=self.keywords_sort_reverse)
        return with_value + without_value

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

        rows = self._sort_keyword_rows(db.get_latest_for_project(self.conn, self.current_project_id))
        if not rows:
            table.insert("", "end", values=("", "Brak słów kluczowych - dodaj pierwsze powyżej."))
            self._redraw_chart()
            return

        self.keyword_row_ids = [r[0] for r in rows]
        self.selected_keyword_ids &= set(self.keyword_row_ids)  # usuń frazy, których już nie ma

        for row_number, (
            keyword_id,
            keyword,
            page_url,
            period_end,
            position,
            clicks,
            impressions,
            _ctr,
            best_position,
            popularity,
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
                    popularity if popularity is not None else "-",
                    impressions if impressions is not None else "-",
                    clicks if clicks is not None else "-",
                    period_end or "-",
                    "✕ Usuń",
                ),
            )

        self._redraw_chart()

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

    def _on_delete_keyword(self, keyword_id: int):
        if messagebox.askyesno("Usuń słowo kluczowe", "Usunąć to słowo kluczowe wraz z jego historią?"):
            db.delete_keyword(self.conn, keyword_id)
            self.refresh_all()

    def _on_run_check(self):
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return

        self.check_button.configure(state="disabled")
        self.status_label.configure(text="Sprawdzanie w toku...")
        project_id = self.current_project_id

        def progress(message: str):
            self.after(0, lambda: self.status_label.configure(text=message))

        def worker():
            error = None
            try:
                tracker.run_check(self.conn, project_id, progress_callback=progress)
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                error = e
            self.after(0, lambda: self._on_check_finished(error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_backfill(self):
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return

        dialog = ctk.CTkInputDialog(
            text="Ile dni wstecz pobrać? (Search Console przechowuje dane ok. 16 miesięcy)",
            title="Pobierz dane historyczne",
        )
        value = dialog.get_input()
        if not value:
            return
        try:
            days_back = int(value.strip())
        except ValueError:
            messagebox.showwarning("Błędne dane", "Podaj liczbę dni (np. 90).")
            return
        if days_back <= 0:
            return

        self.check_button.configure(state="disabled")
        self.backfill_button.configure(state="disabled")
        self.status_label.configure(text="Pobieranie historii w toku...")
        project_id = self.current_project_id

        def progress(message: str):
            self.after(0, lambda: self.status_label.configure(text=message))

        def worker():
            error = None
            try:
                tracker.run_backfill(self.conn, project_id, days_back, progress_callback=progress)
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                error = e
            self.after(0, lambda: self._on_check_finished(error))

        threading.Thread(target=worker, daemon=True).start()

    def _on_run_popularity_check(self):
        if self.current_project_id is None:
            messagebox.showinfo("Brak projektu", "Najpierw wybierz lub utwórz projekt.")
            return

        self.check_button.configure(state="disabled")
        self.backfill_button.configure(state="disabled")
        self.popularity_button.configure(state="disabled")
        self.status_label.configure(text="Sprawdzanie popularności w toku...")
        project_id = self.current_project_id

        def progress(message: str):
            self.after(0, lambda: self.status_label.configure(text=message))

        def worker():
            error = None
            try:
                tracker.run_popularity_check(self.conn, project_id, progress_callback=progress)
            except Exception as e:  # noqa: BLE001 - pokazujemy dowolny błąd użytkownikowi
                error = e
            self.after(0, lambda: self._on_check_finished(error))

        threading.Thread(target=worker, daemon=True).start()

    def _run_startup_update(self):
        """Przy starcie aplikacji dociąga dane wszystkich fraz we wszystkich
        projektach od daty ostatniego pomiaru do dziś (tylko frazy, których nie
        aktualizowano jeszcze dzisiaj) oraz odświeża popularność z Google Trends
        (tylko frazy sprawdzane ponad POPULARITY_REFRESH_DAYS dni temu)."""
        projects = db.list_projects(self.conn)
        if not projects:
            return

        self.check_button.configure(state="disabled")
        self.backfill_button.configure(state="disabled")
        self.popularity_button.configure(state="disabled")
        self.status_label.configure(text="Aktualizacja danych od ostatniego sprawdzenia...")

        def worker():
            errors = []
            updated_keywords = total_rows = popularity_checked = 0
            for project_id, name, _site_url in projects:

                def progress(message: str, name=name):
                    self.after(0, lambda: self.status_label.configure(text=f"[{name}] {message}"))

                try:
                    keywords_count, rows_count = tracker.run_update_since_last_check(
                        self.conn, project_id, progress_callback=progress
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
                except Exception as e:  # noqa: BLE001 - Google Trends bywa niestabilne, nie blokuje reszty
                    errors.append(f"{name} (popularność): {e}")

            error = (
                RuntimeError("Automatyczna aktualizacja przy starcie nie powiodła się:\n\n" + "\n\n".join(errors))
                if errors
                else None
            )
            positions_info = (
                f"pozycje: {updated_keywords} fraz, {total_rows} dziennych wpisów"
                if updated_keywords
                else "pozycje już dziś aktualne"
            )
            popularity_info = (
                f"popularność: {popularity_checked} fraz"
                if popularity_checked
                else f"popularność aktualna (< {POPULARITY_REFRESH_DAYS} dni)"
            )
            done_text = f"Start: {positions_info}; {popularity_info}."
            self.after(0, lambda: self._on_check_finished(error, done_text=done_text))

        threading.Thread(target=worker, daemon=True).start()

    def _on_check_finished(self, error: Exception | None, done_text: str = "Zakończono."):
        self.check_button.configure(state="normal")
        self.backfill_button.configure(state="normal")
        self.popularity_button.configure(state="normal")
        if error:
            self.status_label.configure(text="Błąd podczas sprawdzania.")
            ErrorDialog(self, "Błąd", str(error))
        else:
            self.status_label.configure(text=done_text)
        self.refresh_all()

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
                ("impressions", "Wyświetlenia", 100, "center"),
                ("clicks", "Kliknięcia", 90, "center"),
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

        rows = db.get_latest_for_project(self.conn, self.current_project_id)
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
            clicks,
            impressions,
            ctr,
            _best_position,
            _popularity,
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
                    impressions if impressions is not None else "-",
                    clicks if clicks is not None else "-",
                    f"{ctr * 100:.1f}%" if ctr is not None else "-",
                ),
            )

    # --- zakładka: popularność strony ---

    def _build_site_popularity_tab(self):
        tab = self.tab_site_popularity
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(2, weight=1)

        ctk.CTkLabel(
            tab,
            text=(
                "Wypadkowa pozycji wszystkich fraz ważonych ich popularnością (Google Trends) i klikalnością "
                "danej pozycji.\n100% = wszystkie frazy na pozycji 1. Frazy bez sprawdzonej popularności "
                "liczone są ze średnią mocą - użyj \"Sprawdź popularność\", by uzyskać dokładniejszy wynik."
            ),
            text_color="gray60",
            justify="left",
        ).grid(row=0, column=0, sticky="w", pady=(0, 8))

        self.site_popularity_cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.site_popularity_cards_frame.grid(row=1, column=0, sticky="we", pady=(0, 12))

        self.site_popularity_chart_area = ctk.CTkFrame(tab)
        self.site_popularity_chart_area.grid(row=2, column=0, sticky="nswe")

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

        canvas = build_site_popularity_chart(self.site_popularity_chart_area, series)
        canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)
