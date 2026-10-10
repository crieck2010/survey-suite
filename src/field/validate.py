"""Validation for field jobs: errors block clean import, warnings flag suspect data.

Checks, per the v0.1.0 scope:

* ERROR ``duplicate-name`` — the same point name shot twice in one session
  (ambiguous for adjustment / drafting).
* ERROR ``no-position`` — a point with neither projected nor geographic
  coordinates.
* ERROR ``base-missing`` — an RTK point (FIX/FLOAT) with no base-station
  coordinates at all; the correction source cannot be verified.
* WARNING ``not-fixed`` — solution is FLOAT or SINGLE instead of FIX.
* WARNING ``rms-lateral`` / ``rms-elev`` — RMS above the acceptance threshold.
* WARNING ``no-antenna-height`` — rover antenna (pole) height missing; the
  elevation refers to the APC, not the ground point.
* WARNING ``high-pdop`` — PDOP above the threshold (weak geometry).
* WARNING ``long-baseline`` — baseline beyond the RTK-reliable range.
* WARNING ``low-samples`` — FLOAT point with very few averaged epochs.

Thresholds are parameters so the desktop app / build #2 can expose them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .models import Project, Solution, SurveyPoint


@dataclass
class ValidationIssue:
    severity: str          # "error" | "warning"
    code: str
    message: str
    session_id: str = ""
    point_name: str = ""

    def __str__(self) -> str:
        where = ""
        if self.session_id or self.point_name:
            where = f" [{self.session_id}{'/' if self.session_id and self.point_name else ''}{self.point_name}]"
        return f"{self.severity.upper()} {self.code}{where}: {self.message}"


def validate_project(project: Project,
                     rms_lateral_warn: float = 0.050,
                     rms_elev_warn: float = 0.100,
                     pdop_warn: float = 6.0,
                     baseline_warn_m: float = 20000.0,
                     min_samples_float: int = 10) -> List[ValidationIssue]:
    """Validate a project; returns issues (errors first, then warnings)."""
    issues: List[ValidationIssue] = []

    for session in project.sessions:
        base = project.base_station(session.base_station_id)
        base_ok = base is not None and (
            (base.easting is not None and base.northing is not None)
            or (base.longitude is not None and base.latitude is not None)
        )
        seen: dict = {}
        for point in session.points:
            where = {"session_id": session.id, "point_name": point.name}

            # --- duplicate names (error) ---
            if point.name in seen:
                issues.append(ValidationIssue(
                    "error", "duplicate-name",
                    f"point name '{point.name}' occurs more than once in this session",
                    **where))
            else:
                seen[point.name] = True

            # --- no position at all (error) ---
            if not point.has_any_position():
                issues.append(ValidationIssue(
                    "error", "no-position",
                    "point has neither projected nor geographic coordinates",
                    **where))
                continue

            # --- base missing for RTK solutions (error) ---
            if point.solution in (Solution.FIX, Solution.FLOAT) and not base_ok:
                issues.append(ValidationIssue(
                    "error", "base-missing",
                    f"{point.solution} solution but no base-station coordinates recorded",
                    **where))

            # --- solution not fixed (warning) ---
            if point.solution == Solution.FLOAT:
                issues.append(ValidationIssue(
                    "warning", "not-fixed",
                    "FLOAT solution: centimetre accuracy not achieved; "
                    "re-observe or down-weight in adjustment",
                    **where))
            elif point.solution == Solution.SINGLE:
                issues.append(ValidationIssue(
                    "warning", "not-fixed",
                    "SINGLE (autonomous) solution: metre-level accuracy only",
                    **where))
            elif point.solution == Solution.UNKNOWN:
                issues.append(ValidationIssue(
                    "warning", "not-fixed",
                    "solution status not recorded; treat accuracy as unknown",
                    **where))

            # --- RMS thresholds (warnings) ---
            if point.rms_lateral is not None and point.rms_lateral > rms_lateral_warn:
                issues.append(ValidationIssue(
                    "warning", "rms-lateral",
                    f"lateral RMS {point.rms_lateral:.3f} m exceeds {rms_lateral_warn:.3f} m",
                    **where))
            if point.rms_u is not None and point.rms_u > rms_elev_warn:
                issues.append(ValidationIssue(
                    "warning", "rms-elev",
                    f"elevation RMS {point.rms_u:.3f} m exceeds {rms_elev_warn:.3f} m",
                    **where))

            # --- antenna height (warning) ---
            if point.antenna_height_m is None and point.solution in (
                    Solution.FIX, Solution.FLOAT):
                issues.append(ValidationIssue(
                    "warning", "no-antenna-height",
                    "rover antenna height missing: elevation is at the antenna "
                    "phase centre, not the ground point",
                    **where))

            # --- PDOP (warning) ---
            if point.pdop is not None and point.pdop > pdop_warn:
                issues.append(ValidationIssue(
                    "warning", "high-pdop",
                    f"PDOP {point.pdop:.1f} exceeds {pdop_warn:.1f} (weak satellite geometry)",
                    **where))

            # --- baseline length (warning) ---
            if point.baseline_m is not None and point.baseline_m > baseline_warn_m:
                issues.append(ValidationIssue(
                    "warning", "long-baseline",
                    f"baseline {point.baseline_m/1000:.1f} km exceeds "
                    f"{baseline_warn_m/1000:.0f} km: RTK accuracy degrades with distance",
                    **where))

            # --- few samples on a float (warning) ---
            if (point.solution == Solution.FLOAT and point.samples is not None
                    and point.samples < min_samples_float):
                issues.append(ValidationIssue(
                    "warning", "low-samples",
                    f"FLOAT solution from only {point.samples} samples; "
                    "consider longer averaging",
                    **where))

    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    return errors + warnings


def has_errors(issues: List[ValidationIssue]) -> bool:
    return any(i.severity == "error" for i in issues)
