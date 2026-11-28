from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, ROUND_HALF_UP
from importlib.resources import files
import json
from pathlib import Path
from typing import Any


REFINING_ROUTES = {
    "L0": ("LF",),
    "R0": ("RH",),
    "L0R0": ("LF", "RH"),
    "R0L0": ("RH", "LF"),
}


@dataclass(frozen=True)
class Stage:
    kind: str
    candidates: tuple[str, ...]
    planned_start: datetime | None
    planned_end: datetime | None

    @property
    def planned_seconds(self) -> int | None:
        if self.planned_start is None or self.planned_end is None:
            return None
        seconds = int((self.planned_end - self.planned_start).total_seconds())
        return seconds if seconds > 0 else None


@dataclass(frozen=True)
class Heat:
    job_id: str
    heat_id: str
    route_code: str
    batch_id: str
    cast_id: str
    cast_sub_id: str
    cast_sequence: int
    caster: str
    converter: str
    steel_grade: str
    replace_tundish: bool
    rethread: bool
    pack_flag: int
    stages: tuple[Stage, ...]
    source_row: int
    issues: tuple[str, ...]

    @property
    def transport_edges(self) -> tuple[str, ...]:
        return tuple(f"{a.kind}->{b.kind}" for a, b in zip(self.stages, self.stages[1:]))

    @property
    def cast_start(self) -> datetime:
        start = self.stages[-1].planned_start
        if start is None:
            raise ValueError(f"{self.job_id} has no planned casting start")
        return start


@dataclass(frozen=True)
class History:
    source_row: int
    heat_id: str
    ladle_id: str | None
    converter: str | None
    lf: str | None
    rh: str | None
    caster: str | None
    gross_tonnes: float | None
    ladle_tare_tonnes: float | None
    events: dict[str, datetime]
    issues: tuple[str, ...]

    def elapsed_seconds(self, start: str, end: str) -> int | None:
        """Return the observed interval only when both endpoints are ordered."""
        if start not in self.events or end not in self.events:
            return None
        seconds = int((self.events[end] - self.events[start]).total_seconds())
        return seconds if seconds >= 0 else None


@dataclass(frozen=True)
class Inputs:
    jobs: tuple[Heat, ...]
    history: tuple[History, ...]
    transport: dict[str, dict[str, Any]]
    transport_samples: tuple[dict[str, Any], ...]
    process_stats: tuple[dict[str, Any], ...]
    weight_stats: tuple[dict[str, Any], ...]
    resources: dict[str, Any]
    transport_rules: tuple[dict[str, Any], ...]
    waiting_rules: tuple[dict[str, Any], ...]
    rejected_plan_rows: tuple[dict[str, Any], ...]
    rejected_history_rows: tuple[dict[str, Any], ...]
    sources: dict[str, Any]

    def jobs_between(self, start: datetime, end: datetime) -> tuple[Heat, ...]:
        """Select by planned casting start in the half-open interval [start, end)."""
        if start >= end:
            raise ValueError("start must precede end")
        return tuple(job for job in self.jobs if start <= job.cast_start < end)

    def jobs_for_cast(self, caster: str, cast_id: str) -> tuple[Heat, ...]:
        """Select a planned casting series, in planned time order."""
        return tuple(job for job in self.jobs if job.caster == caster and job.cast_id == cast_id)

    def history_for(self, heat_id: str) -> tuple[History, ...]:
        """Return all observations. Repeated heat IDs are deliberately preserved."""
        return tuple(row for row in self.history if row.heat_id == heat_id)

    def transport_seconds(self, edge: str, statistic: str = "median") -> int:
        """Look up a loaded-crane interval in seconds. Missing routes raise KeyError."""
        if statistic not in {"p10", "median", "p90"}:
            raise ValueError(f"Unknown transport statistic: {statistic}")
        minutes = self.transport[edge][statistic]
        return int((Decimal(str(minutes)) * 60).quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _datetime(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value is not None else None


def _heat(row: dict[str, Any]) -> Heat:
    stages = tuple(
        Stage(s["kind"], tuple(s["candidates"]), _datetime(s["planned_start"]), _datetime(s["planned_end"]))
        for s in row["stages"]
    )
    kinds = tuple(stage.kind for stage in stages)
    if kinds != ("BOF", *REFINING_ROUTES[row["route_code"]], "CC"):
        raise ValueError(f"Route and stages disagree for {row['job_id']}")
    values = {key: value for key, value in row.items() if key not in {"stages", "issues"}}
    return Heat(**values, stages=stages, issues=tuple(row["issues"]))


def _history(row: dict[str, Any]) -> History:
    values = {key: value for key, value in row.items() if key not in {"events", "issues"}}
    events = {key: datetime.fromisoformat(value) for key, value in row["events"].items()}
    return History(**values, events=events, issues=tuple(row["issues"]))


def load_inputs(path: str | Path | None = None) -> Inputs:
    """Read bundled data by default, or another JSON built with the same schema."""
    source = Path(path) if path is not None else files(__package__).joinpath("data", "inputs.json")
    with source.open(encoding="utf-8") as file:
        data = json.load(file)
    if data.get("schema_version") != 1:
        raise ValueError("Unsupported steel input schema")
    jobs = tuple(sorted((_heat(row) for row in data["jobs"]), key=lambda job: (job.cast_start, job.source_row)))
    if len({job.job_id for job in jobs}) != len(jobs):
        raise ValueError("Duplicate production order IDs")
    transport = data["transport"]
    for job in jobs:
        if missing := set(job.transport_edges) - transport.keys():
            raise ValueError(f"{job.job_id} has no transport statistics for {sorted(missing)}")
    return Inputs(
        jobs=jobs,
        history=tuple(_history(row) for row in data["history"]),
        transport=transport,
        transport_samples=tuple(data["transport_samples"]),
        process_stats=tuple(data["process_stats"]),
        weight_stats=tuple(data["weight_stats"]),
        resources=data["resources"],
        transport_rules=tuple(data["transport_rules"]),
        waiting_rules=tuple(data["waiting_rules"]),
        rejected_plan_rows=tuple(data["rejected_plan_rows"]),
        rejected_history_rows=tuple(data["rejected_history_rows"]),
        sources=data["sources"],
    )
