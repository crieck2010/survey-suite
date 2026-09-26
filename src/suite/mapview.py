"""Tk map canvas for the SurveySuite desktop app.

A self-contained, engine-free drawing widget: the caller supplies point
dicts (name/easting/northing/solution/held, as returned by
``suite.runners.map_points``) and an optional parcel point order.
Basemap imagery is supplied as a ready-made ``tk.PhotoImage`` plus its
world extent -- the app renders the GeoTIFF (via runners) and hands the
photo to the view, so this module stays pure Tk.

Importing this module creates no Tk objects.
"""
from __future__ import annotations

import os
import tempfile
import tkinter as tk
from tkinter import ttk

#: point fill colors by solution status
SOLUTION_COLORS = {
    "FIX": "#1a9e4b",      # green
    "FLOAT": "#e07b1a",    # orange
    "SINGLE": "#d23b3b",   # red
    "BASE": "#2563eb",     # blue (also used for held squares)
    "UNKNOWN": "#8a8a8a",  # gray
}

NO_DATA_TEXT = "import a job to begin"


def photoimage_from_rgb(data: bytes, w: int, h: int) -> tk.PhotoImage:
    """Build a ``tk.PhotoImage`` from raw RGB bytes via a P6 PPM temp file.

    ``tk.PhotoImage`` cannot consume raw bytes directly, so the data is
    staged through a temporary ``.ppm`` file which is removed as soon as
    the image is created.
    """
    fd, path = tempfile.mkstemp(suffix=".ppm")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(f"P6\n{w} {h}\n255\n".encode("ascii"))
            fh.write(data)
        return tk.PhotoImage(file=path)
    finally:
        try:
            os.unlink(path)
        except OSError:
            pass


def _nice_number(raw: float) -> float:
    """Round ``raw`` down to a 1/2/5 x 10^n step."""
    if raw <= 0:
        return 1.0
    import math
    exp = math.floor(math.log10(raw))
    frac = raw / (10 ** exp)
    if frac >= 5:
        step = 5.0
    elif frac >= 2:
        step = 2.0
    else:
        step = 1.0
    return step * (10 ** exp)


class SurveyMapView(ttk.Frame):
    """Zoomable/pannable survey map canvas.

    Data model (all world units, e.g. metres in the project CRS):

    * :meth:`set_data` -- points + optional world extent + parcel order
    * :meth:`set_basemap_image` -- PhotoImage + its world extent
    * :meth:`show_basemap` -- toggle the imagery layer
    """

    def __init__(self, master, **kw):
        super().__init__(master, **kw)
        self.canvas = tk.Canvas(self, bg="white", highlightthickness=1,
                                highlightbackground="#cccccc")
        self.canvas.pack(fill="both", expand=True)

        self._points: list[dict] = []
        self._extent: tuple | None = None     # (xmin, ymin, xmax, ymax)
        self._parcel_names: list[str] = []    # boundary order
        self._units = "m"

        self._basemap_photo: tk.PhotoImage | None = None
        self._basemap_extent: tuple | None = None
        self._basemap_visible = False

        # view: canvas pixels per world unit + world center
        self._scale = 1.0
        self._cx = 0.0
        self._cy = 0.0

        self._drag_from: tuple | None = None

        self.canvas.bind("<ButtonPress-1>", self._on_press)
        self.canvas.bind("<B1-Motion>", self._on_drag)
        self.canvas.bind("<ButtonRelease-1>", self._on_release)
        self.canvas.bind("<MouseWheel>", self._on_wheel)      # Windows/macOS
        self.canvas.bind("<Button-4>", lambda e: self._zoom(1.25, e.x, e.y))
        self.canvas.bind("<Button-5>", lambda e: self._zoom(1 / 1.25, e.x, e.y))
        self.canvas.bind("<Configure>", lambda e: self._redraw())

    # -- data ------------------------------------------------------------
    def set_data(self, points, extent=None, parcel_names=None, units="m"):
        """Replace the point layer.

        ``points``: list of dicts with ``name``, ``easting``,
        ``northing``, ``solution`` and ``held`` keys.
        """
        self._points = list(points or [])
        self._parcel_names = list(parcel_names or [])
        self._units = units or "m"
        if extent is not None:
            self._extent = tuple(extent)
        else:
            self._extent = self._extent_of(self._points)
        self.fit()
        self._redraw()

    def set_basemap_image(self, photo, extent):
        """Install a rendered basemap image and its world extent."""
        self._basemap_photo = photo
        self._basemap_extent = tuple(extent) if extent else None
        self._redraw()

    def clear_basemap(self):
        self._basemap_photo = None
        self._basemap_extent = None
        self._redraw()

    def show_basemap(self, visible: bool):
        self._basemap_visible = bool(visible)
        self._redraw()

    @staticmethod
    def _extent_of(points):
        es = [p["easting"] for p in points if p.get("easting") is not None]
        ns = [p["northing"] for p in points if p.get("northing") is not None]
        if not es:
            return None
        return (min(es), min(ns), max(es), max(ns))

    # -- view transforms --------------------------------------------------
    def _world_to_canvas(self, x, y):
        w, h = self._canvas_size()
        return ((x - self._cx) * self._scale + w / 2,
                h / 2 - (y - self._cy) * self._scale)

    def _canvas_size(self):
        w = self.canvas.winfo_width()
        h = self.canvas.winfo_height()
        return (w if w > 1 else 600, h if h > 1 else 400)

    def fit(self):
        """Fit the view to the data extent."""
        if not self._extent:
            return
        xmin, ymin, xmax, ymax = self._extent
        w, h = self._canvas_size()
        dx = max(xmax - xmin, 1e-9)
        dy = max(ymax - ymin, 1e-9)
        self._scale = min(w / dx, h / dy) * 0.88
        self._cx = (xmin + xmax) / 2
        self._cy = (ymin + ymax) / 2

    def _zoom(self, factor, cx_px, cy_px):
        if not self._points and not self._basemap_photo:
            return
        # world point under the cursor stays under the cursor
        w, h = self._canvas_size()
        wx = self._cx + (cx_px - w / 2) / self._scale
        wy = self._cy - (cy_px - h / 2) / self._scale
        self._scale = min(max(self._scale * factor, 1e-9), 1e12)
        self._cx = wx - (cx_px - w / 2) / self._scale
        self._cy = wy + (cy_px - h / 2) / self._scale
        self._redraw()

    def _on_wheel(self, event):
        self._zoom(1.25 if event.delta > 0 else 1 / 1.25, event.x, event.y)

    def _on_press(self, event):
        self._drag_from = (event.x, event.y, self._cx, self._cy)
        self.canvas.configure(cursor="fleur")

    def _on_drag(self, event):
        if self._drag_from is None:
            return
        x0, y0, cx0, cy0 = self._drag_from
        self._cx = cx0 - (event.x - x0) / self._scale
        self._cy = cy0 + (event.y - y0) / self._scale
        self._redraw()

    def _on_release(self, _event):
        self._drag_from = None
        self.canvas.configure(cursor="")

    # -- drawing -----------------------------------------------------------
    def _draw_basemap(self):
        if (not self._basemap_visible or self._basemap_photo is None
                or self._basemap_extent is None):
            return
        xmin, ymin, xmax, ymax = self._basemap_extent
        want_w = max((xmax - xmin) * self._scale, 1.0)
        want_h = max((ymax - ymin) * self._scale, 1.0)
        img = self._basemap_photo
        iw, ih = img.width(), img.height()
        if iw <= 0 or ih <= 0:
            return
        # integer subsample/zoom to approximate the desired display size
        rx, ry = want_w / iw, want_h / ih
        ratio = min(rx, ry)
        if ratio >= 1:
            k = max(1, int(round(ratio)))
            shown = img.zoom(k, k) if k > 1 else img
        else:
            k = max(1, int(round(1 / ratio)))
            shown = img.subsample(k, k) if k > 1 else img
        cx, cy = self._world_to_canvas((xmin + xmax) / 2,
                                       (ymin + ymax) / 2)
        self._basemap_shown = shown  # keep a live reference
        self.canvas.create_image(cx, cy, image=shown)

    def _draw_boundary(self):
        if not self._parcel_names:
            return
        by_name = {p["name"]: p for p in self._points}
        coords = []
        for name in self._parcel_names:
            p = by_name.get(name)
            if p is None or p.get("easting") is None:
                return  # incomplete parcel: skip the polyline
            coords.extend(self._world_to_canvas(p["easting"], p["northing"]))
        if len(coords) >= 4:
            self.canvas.create_line(*coords, fill="#7a4fd0", width=2,
                                    dash=(6, 3), tags="boundary")

    def _draw_points(self):
        for p in self._points:
            e, n = p.get("easting"), p.get("northing")
            if e is None or n is None:
                continue
            x, y = self._world_to_canvas(e, n)
            sol = str(p.get("solution") or "UNKNOWN").upper()
            color = SOLUTION_COLORS.get(sol, SOLUTION_COLORS["UNKNOWN"])
            if p.get("held") or sol == "BASE":
                r = 6
                self.canvas.create_rectangle(x - r, y - r, x + r, y + r,
                                             fill="#2563eb", outline="black")
            else:
                r = 5
                self.canvas.create_oval(x - r, y - r, x + r, y + r,
                                        fill=color, outline="black")
            self.canvas.create_text(x + 8, y - 8, text=p.get("name", ""),
                                    anchor="sw", font=("TkDefaultFont", 8),
                                    fill="#333333")

    def _draw_north_arrow(self):
        w, _h = self._canvas_size()
        x, y = w - 36, 40
        self.canvas.create_line(x, y + 18, x, y - 14, arrow="last",
                                width=2, fill="black")
        self.canvas.create_text(x, y + 28, text="N", font=("TkDefaultFont", 10,
                                                           "bold"))

    def _draw_scale_bar(self):
        if self._scale <= 0:
            return
        units_per_px = 1.0 / self._scale
        raw = 140.0 * units_per_px          # aim for ~140 px bar
        nice = _nice_number(raw)
        bar_px = nice / units_per_px
        _w, h = self._canvas_size()
        x0, y0 = 20, h - 28
        self.canvas.create_line(x0, y0, x0 + bar_px, y0, width=3,
                                fill="black")
        self.canvas.create_line(x0, y0 - 5, x0, y0 + 5, width=2)
        self.canvas.create_line(x0 + bar_px, y0 - 5, x0 + bar_px, y0 + 5,
                                width=2)
        if nice >= 1000 and self._units == "m":
            label = f"{nice / 1000:g} km"
        else:
            label = f"{nice:g} {self._units}"
        self.canvas.create_text(x0 + bar_px / 2, y0 - 12, text=label,
                                font=("TkDefaultFont", 9))

    def _redraw(self):
        self.canvas.delete("all")
        self._basemap_shown = None
        if not self._points and self._basemap_photo is None:
            w, h = self._canvas_size()
            self.canvas.create_text(w / 2, h / 2, text=NO_DATA_TEXT,
                                    font=("TkDefaultFont", 12),
                                    fill="#777777")
            return
        self._draw_basemap()
        self._draw_boundary()
        self._draw_points()
        self._draw_north_arrow()
        self._draw_scale_bar()
