"""Fail-loud error hierarchy for survey-linework.

Every error names the exact problem: the offending point name, raw code,
config key, or schema version. Nothing in this engine silently drops a
coded point.
"""

from __future__ import annotations


class LineworkError(ValueError):
    """Base class: anything that stops a build loudly."""


class CodeSetError(LineworkError):
    """The linework code-set config is invalid or unreadable."""


class DescriptionKeyError(LineworkError):
    """The description-keys config is invalid or unreadable."""


class PrefixDBError(LineworkError):
    """The figure-prefix database is invalid or unreadable."""


class FigureBuildError(LineworkError):
    """A coded sequence cannot be resolved into figures.

    Raised for end-without-begin, continue-without-begin, unknown codes,
    degenerate figures, and unresolvable curves. Carries the point name
    and raw code that triggered it.
    """


class InterchangeError(LineworkError):
    """A figures JSON file is not readable (wrong format / newer schema)."""
