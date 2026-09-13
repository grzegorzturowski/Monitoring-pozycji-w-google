"""Budowanie wykresu pozycji w czasie (matplotlib osadzony w widgetach CustomTkinter)."""

from datetime import datetime

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def build_position_chart(parent, keyword_series: dict[str, list[tuple[str, float | None]]]) -> FigureCanvasTkAgg:
    """keyword_series: {fraza: [(checked_at_iso, position_lub_None), ...]} -> canvas gotowy do .get_tk_widget()."""
    fig = Figure(figsize=(7, 4.2), dpi=100)
    ax = fig.add_subplot(111)

    any_data = False
    for keyword, series in keyword_series.items():
        points = [(datetime.fromisoformat(ts), pos) for ts, pos in series if pos is not None]
        if not points:
            continue
        any_data = True
        points.sort(key=lambda p: p[0])
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        ax.plot(xs, ys, marker="o", label=keyword)

    ax.set_xlabel("Data")
    ax.set_ylabel("Średnia pozycja")
    ax.grid(True, alpha=0.3)

    if any_data:
        ax.invert_yaxis()  # pozycja 1 = najlepsza, ma być u góry wykresu
        ax.legend(loc="best", fontsize=8)
        fig.autofmt_xdate()
    else:
        ax.text(0.5, 0.5, "Brak danych do wyświetlenia", ha="center", va="center", transform=ax.transAxes)

    fig.tight_layout()

    canvas = FigureCanvasTkAgg(fig, master=parent)
    canvas.draw()
    return canvas
