#!/usr/bin/env python3
"""Merge GitHub Traffic clone metrics and render a dependency-free SVG chart."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
from xml.sax.saxutils import escape


WIDTH = 960
HEIGHT = 360
PADDING_LEFT = 64
PADDING_RIGHT = 28
PADDING_TOP = 48
PADDING_BOTTOM = 56


def parseArguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--latest", type=Path, required=True, help="GitHub Traffic API clone response")
    parser.add_argument("--history", type=Path, required=True, help="Persisted aggregate JSON")
    parser.add_argument("--output", type=Path, required=True, help="Rendered SVG output")
    return parser.parse_args()


def loadJson(path: Path, fallback: object) -> object:
    if not path.exists():
        return fallback
    return json.loads(path.read_text(encoding="utf-8"))


def normalizeDay(timestamp: str) -> str:
    return timestamp[:10]


def mergeHistory(history: object, latest: object) -> dict[str, object]:
    previousDays = history.get("days", []) if isinstance(history, dict) else []
    daysByDate = {
        str(day["date"]): {
            "date": str(day["date"]),
            "clones": int(day.get("clones", 0)),
            "uniqueCloners": int(day.get("uniqueCloners", 0)),
        }
        for day in previousDays
        if isinstance(day, dict) and day.get("date")
    }
    latestClones = latest.get("clones", []) if isinstance(latest, dict) else []
    for item in latestClones:
        if not isinstance(item, dict) or not item.get("timestamp"):
            continue
        date = normalizeDay(str(item["timestamp"]))
        daysByDate[date] = {
            "date": date,
            "clones": int(item.get("count", 0)),
            "uniqueCloners": int(item.get("uniques", 0)),
        }
    return {
        "updatedAt": datetime.now(UTC).replace(microsecond=0).isoformat(),
        "days": [daysByDate[date] for date in sorted(daysByDate)],
    }


def chartPoints(values: list[int]) -> str:
    chartWidth = WIDTH - PADDING_LEFT - PADDING_RIGHT
    chartHeight = HEIGHT - PADDING_TOP - PADDING_BOTTOM
    maximum = max(values or [1])
    denominator = max(1, len(values) - 1)
    points = []
    for index, value in enumerate(values):
        x = PADDING_LEFT + chartWidth * index / denominator
        y = PADDING_TOP + chartHeight * (1 - value / maximum)
        points.append(f"{x:.1f},{y:.1f}")
    return " ".join(points)


def renderSvg(history: dict[str, object]) -> str:
    days = history.get("days", [])
    days = days if isinstance(days, list) else []
    clones = [int(day.get("clones", 0)) for day in days if isinstance(day, dict)]
    uniques = [int(day.get("uniqueCloners", 0)) for day in days if isinstance(day, dict)]
    labels = [str(day.get("date", "")) for day in days if isinstance(day, dict)]
    maximum = max(clones + uniques + [1])
    firstLabel = escape(labels[0]) if labels else "Waiting for first workflow run"
    lastLabel = escape(labels[-1]) if labels else ""
    emptyMessage = (
        ""
        if labels
        else '<text x="480" y="190" text-anchor="middle" fill="#64748b" font-size="16">'
        "Clone metrics will appear after the first scheduled run.</text>"
    )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{WIDTH}" height="{HEIGHT}" viewBox="0 0 {WIDTH} {HEIGHT}" role="img" aria-label="Repository clone history">
  <rect width="{WIDTH}" height="{HEIGHT}" fill="#ffffff"/>
  <text x="{PADDING_LEFT}" y="28" fill="#0f172a" font-family="Arial, sans-serif" font-size="18" font-weight="700">Repository clone history</text>
  <line x1="{PADDING_LEFT}" y1="{PADDING_TOP}" x2="{PADDING_LEFT}" y2="{HEIGHT - PADDING_BOTTOM}" stroke="#cbd5e1"/>
  <line x1="{PADDING_LEFT}" y1="{HEIGHT - PADDING_BOTTOM}" x2="{WIDTH - PADDING_RIGHT}" y2="{HEIGHT - PADDING_BOTTOM}" stroke="#cbd5e1"/>
  <text x="{PADDING_LEFT - 12}" y="{PADDING_TOP + 5}" text-anchor="end" fill="#64748b" font-family="Arial, sans-serif" font-size="12">{maximum}</text>
  <text x="{PADDING_LEFT - 12}" y="{HEIGHT - PADDING_BOTTOM + 5}" text-anchor="end" fill="#64748b" font-family="Arial, sans-serif" font-size="12">0</text>
  <polyline fill="none" stroke="#2563eb" stroke-width="3" points="{chartPoints(clones)}"/>
  <polyline fill="none" stroke="#16a34a" stroke-width="3" points="{chartPoints(uniques)}"/>
  {emptyMessage}
  <text x="{PADDING_LEFT}" y="{HEIGHT - 24}" fill="#64748b" font-family="Arial, sans-serif" font-size="12">{firstLabel}</text>
  <text x="{WIDTH - PADDING_RIGHT}" y="{HEIGHT - 24}" text-anchor="end" fill="#64748b" font-family="Arial, sans-serif" font-size="12">{lastLabel}</text>
  <line x1="640" y1="22" x2="672" y2="22" stroke="#2563eb" stroke-width="3"/>
  <text x="680" y="26" fill="#334155" font-family="Arial, sans-serif" font-size="12">Clones</text>
  <line x1="756" y1="22" x2="788" y2="22" stroke="#16a34a" stroke-width="3"/>
  <text x="796" y="26" fill="#334155" font-family="Arial, sans-serif" font-size="12">Unique cloners</text>
</svg>
"""


def main() -> int:
    arguments = parseArguments()
    history = mergeHistory(loadJson(arguments.history, {}), loadJson(arguments.latest, {}))
    arguments.history.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.history.write_text(f"{json.dumps(history, ensure_ascii=True, indent=2)}\n", encoding="utf-8")
    arguments.output.write_text(renderSvg(history), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
