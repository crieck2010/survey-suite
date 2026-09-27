# Toolbox registry (`suite.toolboxes`) — v0.3.0

Since v0.3.0 the SurveySuite notebook is **registry-driven**: `suite.app`
does not hardcode a tab list. It iterates `toolboxes.all_toolboxes()`,
calls each toolbox's `tab_factory(app, notebook, toolbox)`, and adds the
returned frame under the toolbox's title. A new toolbox is one new
module with one `register_toolbox(...)` call — `app.py` is never touched.

## The `Toolbox` spec

```python
@dataclass(frozen=True)
class Toolbox:
    id: str            # stable, unique: "project", "import", ...
    title: str         # notebook tab label: "Project", "Import", ...
    tab_factory: Callable[[app, ttk.Notebook, Toolbox], ttk.Frame]
    engine_deps: tuple = ()   # importable engine module names, e.g. ("crs",)
    description: str = ""
    order: int = 100   # notebook position; built-ins use 10..70
```

Registry functions (`suite.toolboxes`):

- `register_toolbox(toolbox)` → returns the stored spec. Rejects empty
  ids and duplicate ids with `ValueError`.
- `all_toolboxes()` → registered toolboxes sorted by `(order, title)`.
- `toolbox_by_id(id)` → the spec or `None`.
- `missing_engine_deps(toolbox)` → engine module names not importable.

## Rules every toolbox follows

1. **Factories are lazy.** The registry wraps `tab_factory` so that when
   any `engine_deps` entry is not importable, the tab builds a
   "not installed" notice frame (`pip install <engine>`) instead of
   raising. The app always launches; the missing tab explains itself.
   Modules that need an optional engine must also import it lazily
   (inside functions), so `import suite.toolbox_x` never fails.
2. **Tk-free logic stays out of the factory.** The factory builds
   widgets; orchestration lives in `suite.runners`; math lives in the
   engines. (The Coordinates picker's search helpers are plain
   functions for exactly this reason — they're unit-tested headless.)
3. **Cross-tab state goes through the app.** A toolbox may read/write
   documented `app` attributes (e.g. `app.project`,
   `app.coord_reproject_var`) and call documented `app` sync methods
   (e.g. `app.refresh_import_crs_status()`), but must not reach into
   another toolbox's widgets.
4. **Frames are keyed by stable id.** `app._toolbox_frames[id]` and
   `app.select_toolbox(id)` switch tabs programmatically.

## The seven built-in toolboxes (v0.3.0)

| id | Title | order | engine_deps |
|---|---|---|---|
| `project` | Project | 10 | — |
| `import` | Import | 20 | `field` |
| `adjust` | Adjust | 30 | `adjustflow` |
| `map` | Map | 40 | `field`, `drafting`, `basemap` |
| `draft` | Draft | 50 | `drafting` |
| `basemap` | Basemap | 60 | `basemap` |
| `coordinates` | Coordinates | 70 | `crs` |

The first six are thin delegates over the pre-v0.3.0 tab builders —
registered in `suite.toolboxes` itself. `coordinates` is the first
native registry toolbox (`suite.toolbox_coordinates`).

## Auto-discovery

At import time `suite.toolboxes` imports every `suite.toolbox_*`
module. A new toolbox module needs only:

```python
# src/suite/toolbox_levels.py
from suite.toolboxes import Toolbox, register_toolbox

def _build_levels_tab(app, notebook, toolbox):
    frame = ttk.Frame(notebook, padding=10)
    ...build widgets, reading app.project...
    return frame

register_toolbox(Toolbox(
    id="levels",
    title="Levels",
    tab_factory=_build_levels_tab,
    engine_deps=("levels",),
    description="Differential leveling reduction.",
    order=80,
))
```

No edit to `app.py`, no edit to `toolboxes.py`. Tests for the new
toolbox go in `tests/test_toolboxes.py` (registry contract) plus a
headless helper-test module; GUI flow tests go in
`tests/test_app_smoke.py` behind the `$DISPLAY` skip.

**Packaging note:** toolbox modules self-register through
`importlib.import_module()` with a computed name, which PyInstaller's
static analysis cannot see. `SurveySuite.spec` and `build.py` therefore
re-run the same `pkgutil` discovery at build time and add every
`suite.toolbox_*` module as a hidden import — a new toolbox module is
picked up by the frozen build automatically, no spec edit needed.

## Coordinates toolbox contract (the reference implementation)

`suite.toolbox_coordinates` is the pattern to copy:

- Tk-free helpers (`_search_entries`, `_describe`, `_datum_note_text`,
  `_did_you_mean`) — unit-tested without a display.
- One `_build_coordinates_tab(app, notebook, toolbox)` factory that
  wires widgets to those helpers.
- Exposes a small handle surface on `app`
  (`app.coords_query_var`, `app.coords_results`, `app.coords_do_search`,
  `app.coords_set_project_crs`, …) so GUI tests can drive the picker
  flow without poking at widget internals.
- Shared state it owns: `app.coord_reproject_var` (BooleanVar),
  `app.coord_target_var` (StringVar). The Import tab reads the toggle
  via `app._import_target_crs()`; both tabs refresh through
  `app.refresh_import_crs_status()` /
  `app.refresh_coords_crs_display()`.
