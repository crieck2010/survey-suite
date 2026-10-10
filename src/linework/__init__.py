"""survey-linework: field-coding/linework engine (field-to-finish).

Coded field points in, drafted figures out. Pure Python, stdlib only,
engine-only (zero UI imports).

Pipeline::

    Emlid CSV --(survey-field)--> job.sfield.json
        --(linework build)--> figures.json (survey-linework/figures, schema v1)
        --(adapters)--> survey-drafting layer entities (linework layer)
                     --> survey-cogo Point lists (area / inverse on closed figures)

Public API:
    codeset.LineworkCodeSet / load_codeset / codeset_template
    keys.DescriptionKeys / load_keys / keys_template
    prefixes.FigurePrefixDB / load_prefixes / prefixes_template
    figures.FigureBuilder / build_figures
    interchange.dump_figures / write_figures / read_figures
    adapters.figures_to_drafting_layers / figures_to_cogo
"""

from __future__ import annotations

__version__ = "0.1.0"
__all__ = [
    "__version__",
    "LineworkError", "CodeSetError", "DescriptionKeyError",
    "PrefixDBError", "FigureBuildError", "InterchangeError",
    "LineworkCodeSet", "load_codeset", "codeset_template",
    "DescriptionKeys", "load_keys", "keys_template",
    "FigurePrefixDB", "load_prefixes", "prefixes_template",
    "FigureBuilder", "build_figures",
    "dump_figures", "write_figures", "read_figures",
    "figures_to_drafting_layers", "figures_to_cogo",
]

from .errors import (
    LineworkError, CodeSetError, DescriptionKeyError,
    PrefixDBError, FigureBuildError, InterchangeError,
)
from .codeset import LineworkCodeSet, load_codeset, codeset_template
from .keys import DescriptionKeys, load_keys, keys_template
from .prefixes import FigurePrefixDB, load_prefixes, prefixes_template
from .figures import FigureBuilder, build_figures
from .interchange import dump_figures, write_figures, read_figures
from .adapters import figures_to_drafting_layers, figures_to_cogo
