#!/usr/bin/env python3
"""Expand activity_log_structured.json into flat CSV tables."""

import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent
STRUCTURED = ROOT / "activity_log_structured.json"
SESSIONS_CSV = ROOT / "activity_log_sessions.csv"
ACTIVITIES_CSV = ROOT / "activity_log_activities.csv"


def flatten_activities(activities, date, period, feelings, prefix=""):
    rows = []
    for i, act in enumerate(activities, start=1):
        children = act.pop("children", None) if "children" in act else None
        row = {
            "date": date,
            "period": period,
            "session_feelings": feelings,
            "activity_index": i,
            "parent_group": prefix or None,
            "name": act.get("name"),
            "duration": act.get("duration"),
            "sets": act.get("sets"),
            "reps": act.get("reps"),
            "reps_per_side": act.get("reps_per_side"),
            "notes": act.get("notes"),
        }
        rows.append(row)
        if children:
            group_name = act.get("name")
            rows.extend(
                flatten_activities(children, date, period, feelings, prefix=group_name)
            )
    return rows


def main():
    data = json.loads(STRUCTURED.read_text())
    session_rows = []
    activity_rows = []

    for day in data["days"]:
        date = day["date"]
        for session in day["sessions"]:
            feelings = session.get("feelings")
            feelings_str = "/".join(feelings) if feelings else ""
            session_rows.append(
                {
                    "date": date,
                    "period": session["period"],
                    "feelings": feelings_str,
                    "feelings_detail": session.get("feelings_detail") or "",
                    "activity_count": len(session.get("activities", [])),
                    "session_notes": session.get("session_notes") or "",
                }
            )
            activity_rows.extend(
                flatten_activities(
                    [dict(a) for a in session.get("activities", [])],
                    date,
                    session["period"],
                    feelings_str,
                )
            )

        for inc in day.get("incidents", []):
            session_rows.append(
                {
                    "date": date,
                    "period": "incident",
                    "feelings": "/".join(inc.get("feelings", [])),
                    "feelings_detail": inc.get("description", ""),
                    "activity_count": 0,
                    "session_notes": inc.get("notes") or "",
                }
            )

    if session_rows:
        with SESSIONS_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=session_rows[0].keys())
            w.writeheader()
            w.writerows(session_rows)

    if activity_rows:
        with ACTIVITIES_CSV.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=activity_rows[0].keys())
            w.writeheader()
            w.writerows(activity_rows)

    print(f"Wrote {SESSIONS_CSV.name} ({len(session_rows)} rows)")
    print(f"Wrote {ACTIVITIES_CSV.name} ({len(activity_rows)} rows)")


if __name__ == "__main__":
    main()
