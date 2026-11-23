"""In-process counters. Labels stay low-cardinality: no member or tenant id."""

from __future__ import annotations


class Metrics:
    def __init__(self) -> None:
        self.counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}

    def inc(self, name: str, labels: dict[str, str], amount: int = 1) -> None:
        key = (name, tuple(sorted(labels.items())))
        self.counters[key] = self.counters.get(key, 0) + amount

    def render(self) -> str:
        names = sorted({name for name, _ in self.counters})
        lines: list[str] = []
        for name in names:
            lines.append(f"# TYPE {name} counter")
            rows = [(labels, value) for (metric, labels), value in self.counters.items() if metric == name]
            for labels, value in sorted(rows):
                rendered = ",".join(f'{key}="{val}"' for key, val in labels)
                lines.append(f"{name}{{{rendered}}} {value}")
        return ("\n".join(lines) + "\n") if lines else ""
