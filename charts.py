"""Budowanie wykresów pozycji i popularności strony w czasie (matplotlib osadzony w widgetach CustomTkinter)."""

from datetime import datetime

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure

SERIES_COLOR = "#2a78d6"


def build_position_chart(
    parent,
    keyword_series: dict[str, list[tuple[str, float | None]]],
    figsize: tuple[float, float] = (9, 3.4),
) -> FigureCanvasTkAgg:
    """keyword_series: {fraza: [(checked_at_iso, position_lub_None), ...]} -> canvas gotowy do .get_tk_widget().
    Przy małym figsize wykres przechodzi w wersję kompaktową (mniejsze czcionki i znaczniki)."""
    compact = figsize[0] < 6
    font_size = 7 if compact else 10
    # layout "constrained" przelicza marginesy także po zmianie rozmiaru okna
    fig = Figure(figsize=figsize, dpi=100, layout="constrained")
    ax = fig.add_subplot(111)
    ax.tick_params(labelsize=font_size)

    plotted_lines = []  # [(Line2D, fraza), ...] - do obsługi tooltipa po najechaniu
    any_data = False
    for keyword, series in keyword_series.items():
        points = [(datetime.fromisoformat(ts), pos) for ts, pos in series if pos is not None]
        if not points:
            continue
        any_data = True
        points.sort(key=lambda p: p[0])
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        (line,) = ax.plot(
            xs, ys, marker="o", markersize=3 if compact else 6, linewidth=1.5, label=keyword, pickradius=6
        )
        plotted_lines.append((line, keyword))

    if not compact:
        ax.set_xlabel("Data")
    ax.set_ylabel("Średnia pozycja", fontsize=font_size)
    ax.grid(True, alpha=0.3)

    if any_data:
        ax.invert_yaxis()  # pozycja 1 = najlepsza, ma być u góry wykresu
        ax.legend(loc="best", fontsize=6 if compact else 8)
        fig.autofmt_xdate()
    else:
        ax.text(
            0.5, 0.5, "Brak danych do wyświetlenia", ha="center", va="center", transform=ax.transAxes,
            fontsize=font_size,
        )

    canvas = FigureCanvasTkAgg(fig, master=parent)

    if any_data:
        _attach_tooltip(
            canvas,
            ax,
            plotted_lines,
            lambda keyword, x_val, y_val: f"{keyword}\n{x_val.strftime('%Y-%m-%d')}\nPozycja: {y_val:.1f}",
        )

    canvas.draw()
    return canvas


def build_site_popularity_chart(parent, series: list[tuple[str, str, float]]) -> FigureCanvasTkAgg:
    """series: [(początek_okresu_iso, koniec_okresu_iso, wskaźnik_0_100), ...] -> canvas gotowy do
    .get_tk_widget(). Okres jednodniowy (początek == koniec) to wartość dzienna, dłuższy - średnia z okresu."""
    fig = Figure(figsize=(9, 3.4), dpi=100)
    ax = fig.add_subplot(111)

    if series:
        xs = [datetime.fromisoformat(start) for start, _, _ in series]
        ys = [v for _, _, v in series]
        aggregated = any(start != end for start, end, _ in series)
        period_by_x = {datetime.fromisoformat(start): (start, end) for start, end, _ in series}
        (line,) = ax.plot(
            xs, ys, color=SERIES_COLOR, linewidth=2, pickradius=6, marker="o" if aggregated else None, markersize=5
        )
        ax.fill_between(xs, ys, color=SERIES_COLOR, alpha=0.12, linewidth=0)
        ax.set_ylim(bottom=0, top=max(max(ys) * 1.15, 1))
        fig.autofmt_xdate()
    else:
        ax.text(0.5, 0.5, "Brak danych do wyświetlenia", ha="center", va="center", transform=ax.transAxes)

    ax.set_xlabel("Data")
    ax.set_ylabel("Popularność strony (% maks.)")
    ax.grid(True, alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=parent)
    if series:
        _attach_tooltip(
            canvas,
            ax,
            [(line, "Popularność strony")],
            lambda _label, x_val, y_val: _format_period_tooltip(period_by_x.get(x_val), x_val, y_val),
        )
    canvas.draw()
    return canvas


def build_ai_visibility_chart(parent, engine_series: dict[str, list[tuple[str, float]]]) -> FigureCanvasTkAgg:
    """engine_series: {nazwa asystenta AI: [(dzień_iso, % fraz z cytowaną domeną), ...]} -> canvas
    gotowy do .get_tk_widget()."""
    fig = Figure(figsize=(9, 2.6), dpi=100, layout="constrained")
    ax = fig.add_subplot(111)

    plotted_lines = []
    for engine_name, series in engine_series.items():
        if not series:
            continue
        xs = [datetime.fromisoformat(day) for day, _ in series]
        ys = [value for _, value in series]
        (line,) = ax.plot(xs, ys, marker="o", markersize=5, linewidth=1.5, label=engine_name, pickradius=6)
        plotted_lines.append((line, engine_name))

    ax.set_ylabel("Frazy z cytowaną domeną (%)")
    ax.set_ylim(0, 105)
    ax.grid(True, alpha=0.3)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    if plotted_lines:
        ax.legend(loc="best", fontsize=8)
        fig.autofmt_xdate()
    else:
        ax.text(0.5, 0.5, "Brak danych do wyświetlenia", ha="center", va="center", transform=ax.transAxes)

    canvas = FigureCanvasTkAgg(fig, master=parent)
    if plotted_lines:
        _attach_tooltip(
            canvas,
            ax,
            plotted_lines,
            lambda engine_name, x_val, y_val: f"{engine_name}\n{x_val.strftime('%Y-%m-%d')}\nCytowana: {y_val:.0f}%",
        )
    canvas.draw()
    return canvas


def _format_period_tooltip(period: tuple[str, str] | None, x_val, y_val: float) -> str:
    start, end = period or (x_val.strftime("%Y-%m-%d"),) * 2
    if start == end:
        return f"{start}\nPopularność: {y_val:.1f}%"
    return f"{start} – {end}\nŚrednia popularność: {y_val:.1f}%"


def _attach_tooltip(canvas, ax, plotted_lines, format_text) -> None:
    """Pokazuje dymek z wartością punktu po najechaniu myszą na linię.
    plotted_lines: [(Line2D, etykieta), ...]; format_text(etykieta, x, y) -> tekst dymka."""
    annotation = ax.annotate(
        "",
        xy=(0, 0),
        xytext=(12, 12),
        textcoords="offset points",
        bbox=dict(boxstyle="round", fc="#ffffe0", ec="gray", alpha=0.95),
        arrowprops=dict(arrowstyle="->"),
        fontsize=11,
        visible=False,
        zorder=10,
    )
    # dymek nie może brać udziału w layoucie "constrained" - inaczej wystający poza osie dymek
    # powoduje przeliczenie marginesów i kurczenie się wykresu przy każdym najechaniu
    annotation.set_in_layout(False)

    shown = {"point": None}  # (linia, indeks) aktualnie pokazanego punktu - przerysowujemy tylko przy zmianie

    def hide():
        if shown["point"] is not None:
            shown["point"] = None
            annotation.set_visible(False)
            canvas.draw_idle()

    def on_move(event):
        if event.inaxes != ax:
            hide()
            return

        for line, label in plotted_lines:
            contains, info = line.contains(event)
            if not contains:
                continue
            idx = info["ind"][0]
            if shown["point"] == (line, idx):
                return
            shown["point"] = (line, idx)
            x_val, y_val = line.get_data()[0][idx], line.get_data()[1][idx]
            annotation.xy = (x_val, y_val)
            annotation.set_text(format_text(label, x_val, y_val))
            # dymek otwieramy w stronę środka osi, żeby przy krawędziach nie wychodził poza wykres
            ax_x, ax_y = ax.transAxes.inverted().transform((event.x, event.y))
            to_left, to_bottom = ax_x > 0.5, ax_y > 0.5
            annotation.xyann = (-12 if to_left else 12, -12 if to_bottom else 12)
            annotation.set_horizontalalignment("right" if to_left else "left")
            annotation.set_verticalalignment("top" if to_bottom else "bottom")
            annotation.set_visible(True)
            canvas.draw_idle()
            return

        hide()

    canvas.mpl_connect("motion_notify_event", on_move)
