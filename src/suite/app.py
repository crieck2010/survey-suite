"""SurveySuite desktop application.

Thin tkinter UI over the seven survey-suite engines: every button calls
engine functions and formats the result. No surveying math lives here.
Importing this module is side-effect free (no Tk objects are created);
call :func:`main` to launch.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from suite import __version__
from suite.licensing import check_license


# ---------------------------------------------------------------------------
# small UI helpers
# ---------------------------------------------------------------------------

def parse_grid(text: str) -> list[list[float]]:
    """Parse ``"1,2;3,4"`` into [[1.0, 2.0], [3.0, 4.0]]."""
    rows = []
    for line in text.strip().split(";"):
        line = line.strip()
        if line:
            rows.append([float(x) for x in line.split(",")])
    if not rows or any(len(r) != len(rows[0]) for r in rows):
        raise ValueError("Grid must be rectangular, e.g. '1,2;3,4'")
    return rows


class Tab:
    """A notebook tab with labeled entries, an optional text box, a run
    button, and a read-only output area."""

    def __init__(self, notebook: ttk.Notebook, title: str):
        self.frame = ttk.Frame(notebook, padding=10)
        notebook.add(self.frame, text=title)
        self.frame.columnconfigure(1, weight=1)
        self._row = 0
        self.entries: dict[str, ttk.Entry] = {}
        self.text: tk.Text | None = None
        self.out: tk.Text = tk.Text(self.frame, height=10, width=60,
                                   state="disabled")
        self.out.grid(row=100, column=0, columnspan=2, sticky="nsew",
                      pady=(10, 0))
        self.frame.rowconfigure(100, weight=1)

    def add_entry(self, label: str, default: str = "") -> None:
        ttk.Label(self.frame, text=label).grid(row=self._row, column=0,
                                               sticky="w", pady=2)
        e = ttk.Entry(self.frame)
        e.insert(0, default)
        e.grid(row=self._row, column=1, sticky="ew", pady=2)
        self.entries[label] = e
        self._row += 1

    def add_text(self, label: str, height: int = 6) -> None:
        ttk.Label(self.frame, text=label).grid(row=self._row, column=0,
                                               sticky="nw", pady=2)
        self.text = tk.Text(self.frame, height=height, width=50)
        self.text.grid(row=self._row, column=1, sticky="ew", pady=2)
        self._row += 1

    def add_button(self, label: str, command) -> None:
        ttk.Button(self.frame, text=label,
                   command=lambda: self._run(command)).grid(
                       row=self._row, column=0, columnspan=2, pady=6)
        self._row += 1

    def get(self, label: str) -> str:
        return self.entries[label].get().strip()

    def get_text(self) -> str:
        return self.text.get("1.0", "end") if self.text else ""

    def _run(self, command) -> None:
        try:
            result = command()
        except Exception as exc:  # noqa: BLE001 -- show errors in the UI
            result = f"Error: {exc}"
        self.out.configure(state="normal")
        self.out.delete("1.0", "end")
        self.out.insert("1.0", result)
        self.out.configure(state="disabled")


# ---------------------------------------------------------------------------
# tab builders (one per engine)
# ---------------------------------------------------------------------------

def build_cogo_tab(nb: ttk.Notebook) -> None:
    from cogo import Point, forward, inverse
    t = Tab(nb, "COGO")
    t.add_entry("N1", "1000"); t.add_entry("E1", "1000")
    t.add_entry("N2", "1100"); t.add_entry("E2", "1150")

    def run_inverse():
        p1 = Point(float(t.get("N1")), float(t.get("E1")))
        p2 = Point(float(t.get("N2")), float(t.get("E2")))
        inv = inverse(p1, p2)
        return (f"Azimuth:  {inv.azimuth:.4f} deg\n"
                f"Distance: {inv.distance:.4f}")

    t.add_button("Inverse (azimuth + distance)", run_inverse)
    t.add_entry("Azimuth (deg)", "45"); t.add_entry("Distance", "100")

    def run_forward():
        p = Point(float(t.get("N1")), float(t.get("E1")))
        q = forward(p, float(t.get("Azimuth (deg)")), float(t.get("Distance")))
        return f"N: {q.northing:.4f}\nE: {q.easting:.4f}"

    t.add_button("Forward from P1", run_forward)


def build_levels_tab(nb: ttk.Notebook) -> None:
    from levels import Setup, page_check, reduce_levels
    t = Tab(nb, "Levels")
    t.add_entry("Start station", "BM-A")
    t.add_entry("Start elevation", "100.0")
    t.add_text("Setups (bs_sta,bs,fs_sta,fs per line)",
               height=5)

    def run():
        setups = []
        for line in t.get_text().strip().splitlines():
            bs_sta, bs, fs_sta, fs = [x.strip() for x in line.split(",")]
            setups.append(Setup(bs_sta, float(bs), fs_sta, float(fs)))
        pts = reduce_levels(t.get("Start station"),
                            float(t.get("Start elevation")), setups)
        check = page_check(setups, float(t.get("Start elevation")),
                           pts[-1].elevation)
        lines = [f"{p.station:>8}: {p.elevation:.4f} ({p.role})" for p in pts]
        lines.append(f"\nPage check: BS-FS={check.check:.4f}, "
                     f"elev diff={check.actual:.4f} -> "
                     f"{'OK' if check.ok else 'FAIL'}")
        return "\n".join(lines)

    t.add_button("Reduce levels", run)


def build_adjust_tab(nb: ttk.Notebook) -> None:
    from adjust import adjust_angles
    t = Tab(nb, "Adjust")
    t.add_entry("Observed angles, deg (comma-separated)",
                "89.999, 90.001, 90.000, 90.000")

    def run():
        angles = [float(x) for x in t.get("Observed angles, deg (comma-separated)").split(",")]
        adj, corr = adjust_angles(angles)
        lines = ["Adjusted angles:"]
        lines += [f"  {a:.6f}  (corr {c:+.6f})" for a, c in zip(adj, corr)]
        lines.append(f"Sum: {sum(adj):.6f}")
        return "\n".join(lines)

    t.add_button("Adjust closed-horizon angles", run)


def build_geodesy_tab(nb: ttk.Notebook) -> None:
    from geodesy import latlon_to_utm
    t = Tab(nb, "Geodesy")
    t.add_entry("Latitude (deg)", "43.1566")
    t.add_entry("Longitude (deg)", "-77.6088")

    def run():
        e, n, zone, hemi = latlon_to_utm(float(t.get("Latitude (deg)")),
                                        float(t.get("Longitude (deg)")))
        return (f"Easting:  {e:.3f}\nNorthing: {n:.3f}\n"
                f"Zone: {zone}{hemi}")

    t.add_button("Lat/Lon to UTM", run)


def build_raster_tab(nb: ttk.Notebook) -> None:
    from raster import ndvi
    t = Tab(nb, "Raster")
    t.add_entry("Red band  (\"1,2;3,4\")", "0.1,0.2;0.15,0.3")
    t.add_entry("NIR band  (\"1,2;3,4\")", "0.5,0.6;0.55,0.7")

    def run():
        red = parse_grid(t.get("Red band  (\"1,2;3,4\")"))
        nir = parse_grid(t.get("NIR band  (\"1,2;3,4\")"))
        out = ndvi(nir, red)
        return "NDVI:\n" + "\n".join(
            "  ".join(f"{v:.4f}" for v in row) for row in out)

    t.add_button("Compute NDVI", run)


def build_pointcloud_tab(nb: ttk.Notebook) -> None:
    from suite.workflows import dem_volume_workflow
    t = Tab(nb, "Point Cloud")
    t.add_text("Points (x,y,z per line)", height=5)
    t.add_entry("Origin X", "0"); t.add_entry("Origin Y", "0")
    t.add_entry("Pixel size", "1.0")
    t.add_entry("Grid width", "10"); t.add_entry("Grid height", "10")
    t.add_entry("Base elevation", "0.0")

    def run():
        pts = []
        for line in t.get_text().strip().splitlines():
            x, y, z = (float(v) for v in line.split(","))
            pts.append((x, y, z))
        r = dem_volume_workflow(
            pts, float(t.get("Origin X")), float(t.get("Origin Y")),
            float(t.get("Pixel size")), int(t.get("Grid width")),
            int(t.get("Grid height")), float(t.get("Base elevation")))
        return (f"Ground points: {r['ground_count']}\n"
                f"Cut:  {r['cut']:.3f}\nFill: {r['fill']:.3f}\n"
                f"Net:  {r['net']:.3f} (cubic units)")

    t.add_button("Classify + DTM + volume", run)


def build_gnss_tab(nb: ttk.Notebook) -> None:
    from suite.workflows import gnss_cogo_control_workflow
    t = Tab(nb, "GNSS")
    t.add_text("NMEA log lines", height=6)
    t.add_entry("Control point name", "CTRL-1")

    def run():
        r = gnss_cogo_control_workflow(t.get_text().strip().splitlines(),
                                       t.get("Control point name"))
        cp = r["control_point"]
        return (f"Fixes: {r['n_fixes']}\n"
                f"Mean: {r['mean_lat']:.9f}, {r['mean_lon']:.9f}, "
                f"{r['mean_h']:.3f} m\n"
                f"95% horiz. accuracy: {r['accuracy_m']:.3f} m\n"
                f"UTM {r['zone']}{r['hemisphere']}: "
                f"E {r['easting']:.3f}  N {r['northing']:.3f}\n"
                f"COGO control {cp.name}: N {cp.northing:.3f}  "
                f"E {cp.easting:.3f}")

    t.add_button("NMEA log to control point", run)


# ---------------------------------------------------------------------------
# application entry point
# ---------------------------------------------------------------------------

def build_app() -> tk.Tk:
    root = tk.Tk()
    root.title(f"SurveySuite {__version__}")
    root.geometry("640x560")
    nb = ttk.Notebook(root)
    nb.pack(fill="both", expand=True)
    for builder in (build_cogo_tab, build_levels_tab, build_adjust_tab,
                    build_geodesy_tab, build_raster_tab,
                    build_pointcloud_tab, build_gnss_tab):
        builder(nb)
    lic = check_license()
    status = tk.Label(root, text=f"v{__version__} | license: {lic.tier}",
                      anchor="w")
    status.pack(fill="x")
    return root


def main() -> None:
    build_app().mainloop()


if __name__ == "__main__":
    main()
