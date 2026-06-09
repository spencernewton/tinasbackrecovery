#!/usr/bin/env python3
"""Sync activity_log_structured.json from Activity_Log_raw."""

import json
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "Activity_Log_raw"
STRUCTURED = ROOT / "activity_log_structured.json"

FEELING_PARTS = ("GREEN", "YELLOW", "RED")
DATE_LINE = re.compile(r"^(\d{1,2})/(\d{1,2}):\s*(.*)$", re.I)
FEELING_STAR = re.compile(
    r"\*\s*((?:" + "|".join(FEELING_PARTS) + r")(?:/(?:" + "|".join(FEELING_PARTS) + r"))*)\s*\*",
    re.I,
)
PCT_GREEN = re.compile(r"\(?\s*(\d+)\s*%\s*GREEN\s*\)?", re.I)
WALK_MIN = re.compile(r"(\d+)\s*min(?:ute)?\s+walk", re.I)


def parse_feelings(text: str) -> Tuple[Optional[List[str]], Optional[str]]:
    m = FEELING_STAR.search(text or "")
    feelings = None
    if m:
        parts = [p.upper() for p in m.group(1).split("/") if p.upper() in FEELING_PARTS]
        feelings = parts if parts else None
    detail = None
    pm = PCT_GREEN.search(text or "")
    if pm:
        detail = f"~{pm.group(1)}% GREEN"
    return feelings, detail


def log_date(year: int, month: int, day: int) -> str:
    return f"{year}-{month:02d}-{day:02d}"


def parse_raw_days(text: str, default_year: int | None = None):
    if default_year is None:
        from datetime import datetime
        default_year = datetime.now().year
    lines = text.splitlines()
    days = []
    current = None

    def flush():
        nonlocal current
        if current:
            days.append(current)
            current = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line or line.upper().startswith("ACTIVITY LOG"):
            continue
        dm = DATE_LINE.match(line)
        if dm:
            flush()
            month, day = int(dm.group(1)), int(dm.group(2))
            current = {
                "date": log_date(default_year, month, day),
                "rest": dm.group(3).strip(),
                "blocks": [],
            }
            continue
        if current is None:
            continue
        current["blocks"].append(line)

    flush()
    return days


def split_day_blocks(day_entry):
    parts = []
    if day_entry.get("rest"):
        parts.append(("body", day_entry["rest"]))
    for line in day_entry.get("blocks", []):
        stripped = line.strip()
        upper = stripped.lstrip("->").strip()
        if upper.upper().startswith("AM:"):
            parts.append(("AM", stripped.split(":", 1)[1].strip()))
        elif upper.upper().startswith("EVENING:"):
            parts.append(("Evening", stripped.split(":", 1)[1].strip()))
        elif upper.upper().startswith("PM:"):
            parts.append(("PM", stripped.split(":", 1)[1].strip()))
        elif upper.upper().startswith("INCIDENT:"):
            parts.append(("Incident", stripped.split(":", 1)[1].strip()))
        elif stripped.startswith("-->"):
            parts.append(("Incident", stripped[3:].strip()))
        else:
            parts.append(("body", stripped))
    return parts


def session_by_period(day: dict, period: str):
    return next((s for s in day.get("sessions", []) if s.get("period") == period), None)


def upsert_evening_session(day: dict, evening: Optional[dict]) -> None:
    sessions = day.setdefault("sessions", [])
    sessions[:] = [s for s in sessions if s.get("period") != "Evening"]
    if not evening or not evening.get("feelings"):
        return
    insert_at = 0
    for i, s in enumerate(sessions):
        if s.get("period") == "AM":
            insert_at = i + 1
            break
    sessions.insert(
        insert_at,
        {
            "period": "Evening",
            "feelings": evening["feelings"],
            "feelings_detail": evening.get("feelings_detail"),
            "activities": [],
            "session_notes": None,
        },
    )


def reorder_sessions(day: dict) -> None:
    order = {"day": 0, "AM": 1, "Evening": 2, "PM": 3}
    day["sessions"].sort(key=lambda s: order.get(s.get("period"), 99))


def apply_feelings_to_session(session: dict, text: str, extra_detail: Optional[str] = None) -> None:
    feelings, detail = parse_feelings(text)
    if feelings:
        session["feelings"] = feelings
        session["feelings_detail"] = detail or extra_detail
    elif not FEELING_STAR.search(text or ""):
        session["feelings"] = None
        session["feelings_detail"] = extra_detail
    elif extra_detail:
        session["feelings_detail"] = extra_detail


IBUPROFEN_TYPO = re.compile(r"\biburp[a-z]*fen\b", re.I)


def fix_note_typos(note: str) -> str:
    return IBUPROFEN_TYPO.sub("ibuprofen", note or "")


def normalize_note_for_compare(note: str) -> str:
    n = fix_note_typos((note or "").strip().lower())
    n = re.sub(r"\s+", " ", n)
    n = re.sub(r"[^\w\s%/]", " ", n)
    n = re.sub(r"\s+", " ", n).strip()
    return n


def split_session_notes(notes: Optional[str]) -> List[str]:
    if not notes:
        return []
    return [fix_note_typos(p.strip()) for p in notes.split(";") if p.strip()]


def notes_redundant(a: str, b: str) -> bool:
    na = normalize_note_for_compare(a)
    nb = normalize_note_for_compare(b)
    if not na or not nb:
        return False
    if na == nb or na in nb or nb in na:
        return True
    if "burning sensation" in na and "burning sensation" in nb:
        if "lower right back" in na and "lower right back" in nb:
            return True
    if "glute/hamstring irritation" in na and "glute/hamstring irritation" in nb:
        return True
    if na.replace("no ibuprofen", "") == "" and nb.replace("no ibuprofen", "") == "":
        return True
    return False


def note_words(note: str) -> set:
    return {w for w in normalize_note_for_compare(note).split() if len(w) > 2}


def note_covered_by_fragment(fragment: str, whole: str) -> bool:
    fw, ww = note_words(fragment), note_words(whole)
    if len(fw) < 3 or len(whole) <= len(fragment):
        return False
    return fw.issubset(ww)


def compact_session_notes(session: dict) -> None:
    parts = split_session_notes(session.get("session_notes"))
    if not parts:
        session["session_notes"] = None
        return
    kept: List[str] = []
    for part in parts:
        replaced = False
        for i, existing in enumerate(kept):
            if notes_redundant(part, existing):
                if len(part) > len(existing):
                    kept[i] = part
                replaced = True
                break
        if not replaced:
            kept.append(part)
    pruned = []
    for part in kept:
        if any(
            note_covered_by_fragment(part, other)
            for other in kept
            if other != part
        ):
            continue
        pruned.append(part)
    if len(pruned) > 1:
        longest = max(pruned, key=len)
        if all(
            note_covered_by_fragment(p, longest) or notes_redundant(p, longest)
            for p in pruned
            if p != longest
        ):
            pruned = [longest]
        else:
            combined = ", ".join(pruned)
            if all(note_covered_by_fragment(p, combined) for p in pruned):
                pruned = [combined]
    session["session_notes"] = "; ".join(pruned) if pruned else None


def append_session_note(session: dict, note: str) -> None:
    note = fix_note_typos((note or "").strip())
    if not note:
        return
    for existing in split_session_notes(session.get("session_notes")):
        if notes_redundant(note, existing):
            return
    prev = (session.get("session_notes") or "").strip()
    session["session_notes"] = f"{prev}; {note}" if prev else note


def session_trailing_paren_notes(text: str) -> List[str]:
    """Parentheticals after the session feeling tag — not inline exercise detail."""
    matches = list(FEELING_STAR.finditer(text or ""))
    if not matches:
        return []
    tail = text[matches[-1].end() :]
    out: List[str] = []
    for part in re.findall(r"\(([^)]+)\)", tail):
        part = part.strip()
        if not part or PCT_GREEN.search(part):
            continue
        if re.fullmatch(r"no ibuprofen", part, re.I):
            out.append("No ibuprofen")
        else:
            out.append(fix_note_typos(part))
    return out


def pct_detail_from_text(text: str) -> Optional[str]:
    pm = PCT_GREEN.search(text or "")
    return f"~{pm.group(1)}% GREEN" if pm else None


def sync_walk_in_session(session: dict, text: str, period: str) -> None:
    if not session:
        return
    walks = list(WALK_MIN.finditer(text or ""))
    acts = session.setdefault("activities", [])
    walk_acts = [a for a in acts if a.get("name") and "walk" in a["name"].lower()]

    if not walks:
        if period == "PM":
            session["activities"] = [
                a for a in acts if not (a.get("name") and "walk" in a["name"].lower())
            ]
        return

    for i, m in enumerate(walks):
        dur = f"{m.group(1)}min"
        if i < len(walk_acts):
            walk_acts[i]["duration"] = dur
        else:
            acts.append(
                {
                    "name": "walk",
                    "duration": dur,
                    "sets": None,
                    "reps": None,
                    "notes": None,
                }
            )


def normalize_incident_description(desc: str) -> str:
    d = (desc or "").strip()
    d = re.sub(r"^incident:\s*", "", d, flags=re.I).strip()
    d = re.sub(r"^[->\s]+", "", d).strip()
    return d


def incident_descriptions_overlap(a: str, b: str) -> bool:
    na = normalize_incident_description(a).lower()
    nb = normalize_incident_description(b).lower()
    if not na or not nb:
        return False
    if na == nb:
        return True
    return na in nb or nb in na


def parse_incident_block(text: str) -> Optional[dict]:
    feelings, _ = parse_feelings(text)
    desc = normalize_incident_description(FEELING_STAR.sub("", text or "").strip())
    if not desc and not feelings:
        return None
    return {
        "feelings": feelings or ["RED"],
        "description": desc or "incident",
        "notes": None,
    }


def dedupe_incidents(day: dict) -> None:
    incidents = day.get("incidents") or []
    if len(incidents) < 2:
        return
    merged: List[dict] = []
    for inc in incidents:
        dup_idx = next(
            (
                i
                for i, kept in enumerate(merged)
                if incident_descriptions_overlap(
                    inc.get("description") or "", kept.get("description") or ""
                )
            ),
            None,
        )
        if dup_idx is None:
            merged.append(dict(inc))
            continue
        kept = merged[dup_idx]
        kept["feelings"] = inc.get("feelings") or kept.get("feelings")
        kept["after_session"] = inc.get("after_session") or kept.get("after_session")
        d_new = normalize_incident_description(inc.get("description") or "")
        d_old = normalize_incident_description(kept.get("description") or "")
        if len(d_new) > len(d_old):
            kept["description"] = d_new
        kept["notes"] = kept.get("notes") or inc.get("notes")
        desc_norm = normalize_incident_description(kept.get("description") or "").lower()
        notes_norm = (kept.get("notes") or "").strip().lower()
        if notes_norm and notes_norm == desc_norm:
            kept["notes"] = None
    day["incidents"] = merged


def incident_after_session(blocks, incident_text: str) -> str:
    """Where to show incident in the day table log columns."""
    idx = next(
        (i for i, (k, t) in enumerate(blocks) if k == "Incident" and t == incident_text),
        -1,
    )
    if idx < 0:
        return "PM"
    seen_am = False
    seen_evening = False
    for k, _ in blocks[:idx]:
        if k == "AM":
            seen_am = True
        if k == "Evening":
            seen_evening = True
    if not seen_am:
        return "AM"
    if seen_evening:
        return "PM"
    return "AM"


def sync_day_from_raw(day: dict, blocks: List[Tuple[str, str]]) -> None:
    has_am_pm = any(k in ("AM", "PM", "Evening") for k, _ in blocks)
    trailing_notes: Dict[str, List[str]] = {"AM": [], "PM": [], "Evening": [], "day": []}
    last_period: Optional[str] = None

    for kind, text in blocks:
        if kind in ("AM", "PM", "Evening"):
            last_period = kind
            sess = session_by_period(day, kind)
            if not sess:
                continue
            extra = pct_detail_from_text(text)
            apply_feelings_to_session(sess, text, extra_detail=extra)
            sync_walk_in_session(sess, text, kind)
            if kind in ("AM", "PM"):
                for note in session_trailing_paren_notes(text):
                    append_session_note(sess, note)
        elif kind == "body" and not has_am_pm:
            last_period = "day"
            sess = session_by_period(day, "day")
            if sess:
                apply_feelings_to_session(sess, text)
        elif kind == "body" and last_period:
            trailing_notes.setdefault(last_period, []).append(text)
        elif kind == "Incident":
            last_period = None
            raw_inc = parse_incident_block(text)
            if not raw_inc:
                continue
            after = incident_after_session(blocks, text)
            raw_inc["after_session"] = after
            incidents = day.setdefault("incidents", [])
            matched = False
            for inc in incidents:
                if not incident_descriptions_overlap(
                    raw_inc["description"], inc.get("description") or ""
                ):
                    continue
                inc["feelings"] = raw_inc["feelings"]
                inc["after_session"] = after
                existing_desc = normalize_incident_description(inc.get("description") or "")
                raw_desc = normalize_incident_description(raw_inc["description"])
                if len(raw_desc) >= len(existing_desc):
                    inc["description"] = raw_desc
                if raw_inc.get("notes") and not inc.get("notes"):
                    inc["notes"] = raw_inc["notes"]
                desc_norm = normalize_incident_description(inc.get("description") or "").lower()
                notes_norm = (inc.get("notes") or "").strip().lower()
                if notes_norm and notes_norm == desc_norm:
                    inc["notes"] = None
                matched = True
                break
            if not matched:
                incidents.append(raw_inc)

    for period, notes in trailing_notes.items():
        if not notes:
            continue
        sess = session_by_period(day, period)
        if not sess:
            continue
        combined = " ".join(notes)
        detail = pct_detail_from_text(combined)
        if detail and period == "PM" and sess.get("feelings"):
            sess["feelings_detail"] = detail
        cleaned = PCT_GREEN.sub("", combined).strip()
        for part in re.findall(r"\(([^)]+)\)", cleaned):
            part = part.strip()
            if part:
                append_session_note(sess, part)

    dedupe_incidents(day)
    for sess in day.get("sessions", []):
        compact_session_notes(sess)


def sync_early_day_body(day: dict, day_entry: dict) -> None:
    """5/23–5/25: feelings on date line or following body."""
    if session_by_period(day, "AM"):
        return
    whole = session_by_period(day, "day")
    if not whole:
        return
    text = day_entry.get("rest") or ""
    for kind, block in split_day_blocks(day_entry):
        if kind == "body":
            text += " " + block
    apply_feelings_to_session(whole, text)


def main():
    raw_text = RAW.read_text()
    data = json.loads(STRUCTURED.read_text())
    raw_days = {d["date"]: d for d in parse_raw_days(raw_text)}
    evenings = {}

    for day_entry in parse_raw_days(raw_text):
        for kind, text in split_day_blocks(day_entry):
            if kind == "Evening":
                feelings, detail = parse_feelings(text)
                evenings[day_entry["date"]] = {
                    "feelings": feelings,
                    "feelings_detail": detail,
                }

    dates_in_raw = sorted(raw_days.keys())
    if dates_in_raw:
        data["meta"]["log_start"] = dates_in_raw[0]
        data["meta"]["log_end"] = dates_in_raw[-1]

    for day in data["days"]:
        date = day["date"]
        entry = raw_days.get(date)
        if not entry:
            continue

        blocks = split_day_blocks(entry)
        if date in evenings:
            upsert_evening_session(day, evenings[date])
        reorder_sessions(day)
        sync_early_day_body(day, entry)
        sync_day_from_raw(day, blocks)

        for sess in day.get("sessions", []):
            compact_session_notes(sess)
            if sess.get("period") == "PM":
                notes = sess.get("session_notes") or ""
                if notes.startswith("No GREEN"):
                    sess["session_notes"] = None

    data["meta"]["log_period_note"] = (
        "Log AM / Evening / PM in the raw file. AM block = morning routine + color (dashboard Afternoon). "
        "Evening = end-of-day color only. PM = evening routine + color (next calendar day dashboard Morning)."
    )

    STRUCTURED.write_text(json.dumps(data, indent=2) + "\n")
    print(f"Updated {STRUCTURED.name} from {RAW.name} ({len(raw_days)} days)")


if __name__ == "__main__":
    main()
