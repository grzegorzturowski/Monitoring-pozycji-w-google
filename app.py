"""GUI aplikacji (CustomTkinter): projekty, słowa kluczowe, wykresy, statystyki."""

import threading
from tkinter import filedialog, messagebox

import customtkinter as ctk

import db
import tracker
from charts import build_position_chart

ctk.set_appearance_mode("System")
ctk.set_default_color_theme("blue")


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
        self.geometry("460x240")
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
            text="Musi dokładnie odpowiadać usłudze z listy w Search Console\n"
            "(dla \"prefiksu URL\" pamiętaj o ukośniku na końcu: https://domena.pl/).",
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
        self.result = (name, site_url)
        self.destroy()


class SettingsDialog(ctk.CTkToplevel):
    def __init__(self, master, conn):
        super().__init__(master)
        self.conn = conn
        self.title("Ustawienia")
        self.geometry("500x300")
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
        self.destroy()


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.conn = db.connect()
        self.current_project_id: int | None = None
        self.keyword_checkboxes: dict[int, tuple[ctk.CTkCheckBox, ctk.BooleanVar]] = {}
        self.chart_canvas = None

        self.title("Monitoring pozycji w Google")
        self.geometry("1100x700")
        self.grid_columnconfigure(1, weight=1)
        self.grid_rowconfigure(0, weight=1)

        self._build_sidebar()
        self._build_main_area()
        self.refresh_projects()

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
                command=lambda pid=project_id: self._select_project(pid),
            )
            btn.pack(fill="x", pady=2)
            self.project_buttons[project_id] = btn

        if projects and self.current_project_id not in self.project_buttons:
            self._select_project(projects[0][0])
        elif not projects:
            self.current_project_id = None
            self._highlight_selected_project()
            self.refresh_keywords_tab()
            self.refresh_charts_tab()
            self.refresh_stats_tab()

    def _highlight_selected_project(self):
        for project_id, btn in self.project_buttons.items():
            btn.configure(fg_color="#1F6AA5" if project_id == self.current_project_id else "transparent")

    def _select_project(self, project_id: int):
        self.current_project_id = project_id
        self._highlight_selected_project()
        self.refresh_keywords_tab()
        self.refresh_charts_tab()
        self.refresh_stats_tab()

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
        self.tabview = ctk.CTkTabview(self)
        self.tabview.grid(row=0, column=1, sticky="nswe", padx=16, pady=16)

        self.tab_keywords = self.tabview.add("Słowa kluczowe")
        self.tab_charts = self.tabview.add("Wykresy")
        self.tab_stats = self.tabview.add("Statystyki")

        self._build_keywords_tab()
        self._build_charts_tab()
        self._build_stats_tab()

    # --- zakładka: słowa kluczowe ---

    def _build_keywords_tab(self):
        tab = self.tab_keywords
        tab.grid_columnconfigure(0, weight=1)

        top_row = ctk.CTkFrame(tab, fg_color="transparent")
        top_row.grid(row=0, column=0, sticky="we", pady=(0, 4))
        self.new_keyword_entry = ctk.CTkEntry(top_row, width=260, placeholder_text="Nowa fraza kluczowa")
        self.new_keyword_entry.pack(side="left", padx=(0, 8))
        self.new_page_entry = ctk.CTkEntry(
            top_row, width=280, placeholder_text="Podstrona (opcjonalnie, pełny URL)"
        )
        self.new_page_entry.pack(side="left", padx=(0, 8))
        ctk.CTkButton(top_row, text="Dodaj słowo kluczowe", command=self._on_add_keyword).pack(side="left")

        ctk.CTkLabel(
            tab,
            text="Zostaw pole podstrony puste, aby śledzić pozycję całej domeny dla danej frazy.",
            text_color="gray60",
        ).grid(row=1, column=0, sticky="w", pady=(0, 8))

        action_row = ctk.CTkFrame(tab, fg_color="transparent")
        action_row.grid(row=2, column=0, sticky="we", pady=(0, 8))
        self.check_button = ctk.CTkButton(action_row, text="Sprawdź teraz", command=self._on_run_check)
        self.check_button.pack(side="left")
        self.backfill_button = ctk.CTkButton(
            action_row, text="Pobierz historię wsteczną", fg_color="gray40", command=self._on_run_backfill
        )
        self.backfill_button.pack(side="left", padx=(8, 0))
        self.status_label = ctk.CTkLabel(action_row, text="")
        self.status_label.pack(side="left", padx=12)

        self.keywords_scroll = ctk.CTkScrollableFrame(tab)
        self.keywords_scroll.grid(row=3, column=0, sticky="nswe")
        for col, weight in enumerate([2, 2, 1, 1, 1, 2, 1]):
            self.keywords_scroll.grid_columnconfigure(col, weight=weight)
        tab.grid_rowconfigure(3, weight=1)

    def refresh_keywords_tab(self):
        for widget in self.keywords_scroll.winfo_children():
            widget.destroy()

        headers = ["Fraza kluczowa", "Podstrona", "Pozycja", "Wyświetlenia", "Kliknięcia", "Dane z dnia", ""]
        for col, text in enumerate(headers):
            ctk.CTkLabel(self.keywords_scroll, text=text, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, sticky="w", padx=6, pady=(0, 6)
            )

        if self.current_project_id is None:
            ctk.CTkLabel(self.keywords_scroll, text="Wybierz lub utwórz projekt.").grid(
                row=1, column=0, columnspan=7, sticky="w", padx=6
            )
            return

        rows = db.get_latest_for_project(self.conn, self.current_project_id)
        if not rows:
            ctk.CTkLabel(self.keywords_scroll, text="Brak słów kluczowych - dodaj pierwsze powyżej.").grid(
                row=1, column=0, columnspan=7, sticky="w", padx=6
            )
            return

        for row_index, (keyword_id, keyword, page_url, period_end, position, clicks, impressions, _ctr) in enumerate(
            rows, start=1
        ):
            ctk.CTkLabel(self.keywords_scroll, text=keyword, anchor="w").grid(
                row=row_index, column=0, sticky="w", padx=6, pady=2
            )
            ctk.CTkLabel(self.keywords_scroll, text=page_url or "cała domena", anchor="w").grid(
                row=row_index, column=1, sticky="w", padx=6
            )
            ctk.CTkLabel(self.keywords_scroll, text=f"{position:.1f}" if position is not None else "-").grid(
                row=row_index, column=2
            )
            ctk.CTkLabel(self.keywords_scroll, text=str(impressions) if impressions is not None else "-").grid(
                row=row_index, column=3
            )
            ctk.CTkLabel(self.keywords_scroll, text=str(clicks) if clicks is not None else "-").grid(
                row=row_index, column=4
            )
            ctk.CTkLabel(self.keywords_scroll, text=period_end or "-").grid(row=row_index, column=5)
            ctk.CTkButton(
                self.keywords_scroll,
                text="Usuń",
                width=60,
                fg_color="#8B2E2E",
                hover_color="#6E2424",
                command=lambda kid=keyword_id: self._on_delete_keyword(kid),
            ).grid(row=row_index, column=6, padx=6)

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
        self.refresh_keywords_tab()
        self.refresh_charts_tab()

    def _on_delete_keyword(self, keyword_id: int):
        if messagebox.askyesno("Usuń słowo kluczowe", "Usunąć to słowo kluczowe wraz z jego historią?"):
            db.delete_keyword(self.conn, keyword_id)
            self.refresh_keywords_tab()
            self.refresh_charts_tab()
            self.refresh_stats_tab()

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
            title="Pobierz historię wsteczną",
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

    def _on_check_finished(self, error: Exception | None):
        self.check_button.configure(state="normal")
        self.backfill_button.configure(state="normal")
        if error:
            self.status_label.configure(text="Błąd podczas sprawdzania.")
            ErrorDialog(self, "Błąd", str(error))
        else:
            self.status_label.configure(text="Zakończono.")
        self.refresh_keywords_tab()
        self.refresh_charts_tab()
        self.refresh_stats_tab()

    # --- zakładka: wykresy ---

    def _build_charts_tab(self):
        tab = self.tab_charts
        tab.grid_columnconfigure(1, weight=1)
        tab.grid_rowconfigure(0, weight=1)

        left = ctk.CTkFrame(tab, width=220)
        left.grid(row=0, column=0, sticky="ns", padx=(0, 12))
        ctk.CTkLabel(left, text="Wybierz słowa kluczowe:", font=ctk.CTkFont(weight="bold")).pack(
            anchor="w", padx=8, pady=(8, 4)
        )
        self.chart_checkbox_frame = ctk.CTkScrollableFrame(left, width=200, height=400)
        self.chart_checkbox_frame.pack(fill="both", expand=True, padx=8, pady=4)
        ctk.CTkButton(left, text="Rysuj wykres", command=self._on_draw_chart).pack(padx=8, pady=8, fill="x")

        self.chart_area = ctk.CTkFrame(tab)
        self.chart_area.grid(row=0, column=1, sticky="nswe")

    def refresh_charts_tab(self):
        for widget in self.chart_checkbox_frame.winfo_children():
            widget.destroy()
        self.keyword_checkboxes.clear()

        if self.chart_canvas is not None:
            self.chart_canvas.get_tk_widget().destroy()
            self.chart_canvas = None

        if self.current_project_id is None:
            return

        for keyword_id, keyword, page_url in db.list_keywords(self.conn, self.current_project_id):
            label = f"{keyword} ({page_url})" if page_url else keyword
            var = ctk.BooleanVar(value=False)
            checkbox = ctk.CTkCheckBox(self.chart_checkbox_frame, text=label, variable=var)
            checkbox.pack(anchor="w", pady=2)
            self.keyword_checkboxes[keyword_id] = (checkbox, var)

    def _on_draw_chart(self):
        selected = [(kid, cb.cget("text")) for kid, (cb, var) in self.keyword_checkboxes.items() if var.get()]
        if not selected:
            messagebox.showinfo("Brak wyboru", "Zaznacz co najmniej jedno słowo kluczowe.")
            return

        series = {}
        for keyword_id, keyword_text in selected:
            history = db.get_history(self.conn, keyword_id)
            series[keyword_text] = [(checked_at, position) for checked_at, position, *_ in history]

        if self.chart_canvas is not None:
            self.chart_canvas.get_tk_widget().destroy()

        self.chart_canvas = build_position_chart(self.chart_area, series)
        self.chart_canvas.get_tk_widget().pack(fill="both", expand=True, padx=8, pady=8)

    # --- zakładka: statystyki ---

    def _build_stats_tab(self):
        tab = self.tab_stats
        tab.grid_columnconfigure(0, weight=1)
        tab.grid_rowconfigure(1, weight=1)

        self.stats_cards_frame = ctk.CTkFrame(tab, fg_color="transparent")
        self.stats_cards_frame.grid(row=0, column=0, sticky="we", pady=(0, 12))

        self.stats_table_frame = ctk.CTkScrollableFrame(tab)
        self.stats_table_frame.grid(row=1, column=0, sticky="nswe")
        for col, weight in enumerate([3, 1, 1, 1, 1, 1]):
            self.stats_table_frame.grid_columnconfigure(col, weight=weight)

    def _make_stat_card(self, parent, title: str, value: str, column: int):
        card = ctk.CTkFrame(parent, corner_radius=10)
        card.grid(row=0, column=column, padx=6, sticky="we")
        ctk.CTkLabel(card, text=title, text_color="gray60").pack(padx=16, pady=(12, 0))
        ctk.CTkLabel(card, text=value, font=ctk.CTkFont(size=22, weight="bold")).pack(padx=16, pady=(0, 12))

    def refresh_stats_tab(self):
        for widget in self.stats_cards_frame.winfo_children():
            widget.destroy()
        for widget in self.stats_table_frame.winfo_children():
            widget.destroy()

        if self.current_project_id is None:
            ctk.CTkLabel(self.stats_table_frame, text="Wybierz lub utwórz projekt.").grid(row=0, column=0, sticky="w")
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

        headers = ["Fraza kluczowa", "Pozycja", "Zmiana", "Wyświetlenia", "Kliknięcia", "CTR"]
        for col, text in enumerate(headers):
            ctk.CTkLabel(self.stats_table_frame, text=text, font=ctk.CTkFont(weight="bold")).grid(
                row=0, column=col, sticky="w", padx=6, pady=(0, 6)
            )

        for row_index, (keyword_id, keyword, _page_url, _period_end, position, clicks, impressions, ctr) in enumerate(
            rows, start=1
        ):
            history = db.get_history(self.conn, keyword_id)
            positions_with_data = [h[1] for h in history if h[1] is not None]
            trend = "-"
            trend_color = "gray60"
            if len(positions_with_data) >= 2:
                diff = positions_with_data[-2] - positions_with_data[-1]
                if diff > 0.05:
                    trend, trend_color = f"▲ poprawa o {diff:.1f}", "#2FA84F"
                elif diff < -0.05:
                    trend, trend_color = f"▼ spadek o {abs(diff):.1f}", "#C0392B"
                else:
                    trend = "= bez zmian"

            ctk.CTkLabel(self.stats_table_frame, text=keyword, anchor="w").grid(
                row=row_index, column=0, sticky="w", padx=6, pady=2
            )
            ctk.CTkLabel(self.stats_table_frame, text=f"{position:.1f}" if position is not None else "-").grid(
                row=row_index, column=1
            )
            ctk.CTkLabel(self.stats_table_frame, text=trend, text_color=trend_color).grid(row=row_index, column=2)
            ctk.CTkLabel(self.stats_table_frame, text=str(impressions) if impressions is not None else "-").grid(
                row=row_index, column=3
            )
            ctk.CTkLabel(self.stats_table_frame, text=str(clicks) if clicks is not None else "-").grid(
                row=row_index, column=4
            )
            ctk.CTkLabel(self.stats_table_frame, text=f"{ctr * 100:.1f}%" if ctr is not None else "-").grid(
                row=row_index, column=5
            )
