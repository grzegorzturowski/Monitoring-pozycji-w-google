"""Budowanie wykresu pozycji w czasie (matplotlib osadzony w widgetach CustomTkinter)."""

from datetime import datetime

import matplotlib

matplotlib.use("TkAgg")
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
from matplotlib.figure import Figure


def build_position_chart(parent, keyword_series: dict[str, list[tuple[str, float | None]]]) -> FigureCanvasTkAgg:
    """keyword_series: {fraza: [(checked_at_iso, position_lub_None), ...]} -> canvas gotowy do .get_tk_widget()."""
    fig = Figure(figsize=(9, 3.4), dpi=100)
    ax = fig.add_subplot(111)

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
        (line,) = ax.plot(xs, ys, marker="o", label=keyword, pickradius=6)
        plotted_lines.append((line, keyword))

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

    if any_data:
        annotation = ax.annotate(
            "",
            xy=(0, 0),
            xytext=(12, 12),
            textcoords="offset points",
            bbox=dict(boxstyle="round", fc="#ffffe0", ec="gray", alpha=0.95),
            arrowprops=dict(arrowstyle="->"),
            fontsize=8,
            visible=False,
            zorder=10,
        )

        def on_move(event, ax=ax, annotation=annotation, plotted_lines=plotted_lines, canvas=canvas):
            if event.inaxes != ax:
                if annotation.get_visible():
                    annotation.set_visible(False)
                    canvas.draw_idle()
                return

            for line, keyword in plotted_lines:
                contains, info = line.contains(event)
                if not contains:
                    continue
                idx = info["ind"][0]
                x_val, y_val = line.get_data()[0][idx], line.get_data()[1][idx]
                annotation.xy = (x_val, y_val)
                annotation.set_text(f"{keyword}\n{x_val.strftime('%Y-%m-%d')}\nPozycja: {y_val:.1f}")
                annotation.set_visible(True)
                canvas.draw_idle()
                return

            if annotation.get_visible():
                annotation.set_visible(False)
                canvas.draw_idle()

        canvas.mpl_connect("motion_notify_event", on_move)

    canvas.draw()
    return canvas
