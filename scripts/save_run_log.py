"""
save_run_log.py
===============
Erfasst die Ergebnisse eines Workflow-Durchlaufs und speichert sie
in docs/run_history.json fuer die Actions-Archivseite.

Wird nach allen anderen Steps ausgefuehrt.
"""

import json
import os
from datetime import datetime
from pathlib import Path

DATA_PATH = Path("docs/data.json")
HISTORY_PATH = Path("docs/run_history.json")
MAX_HISTORY = 90  # Maximal 90 Eintraege behalten (~3 Monate)


def load_history():
    if HISTORY_PATH.exists():
        try:
            with open(HISTORY_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return []
    return []


def build_run_entry():
    entry = {
        "timestamp": datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "run_id": os.environ.get("GITHUB_RUN_ID", ""),
        "run_url": "",
        "trigger": os.environ.get("GITHUB_EVENT_NAME", "unknown"),
        "status": "ok",
        "fetch": {},
        "gemini": {},
    }

    # Link zu GitHub Actions
    repo = os.environ.get("GITHUB_REPOSITORY", "")
    run_id = os.environ.get("GITHUB_RUN_ID", "")
    if repo and run_id:
        entry["run_url"] = f"https://github.com/{repo}/actions/runs/{run_id}"

    # Stats aus data.json lesen
    if DATA_PATH.exists():
        try:
            with open(DATA_PATH, encoding="utf-8") as f:
                data = json.load(f)

            statements = data.get("statements", [])
            entry["fetch"]["total_statements"] = len(statements)

            # Gemini-Stats (falls vorhanden)
            gs = data.get("gemini_stats") or {}
            if gs:
                entry["gemini"] = {
                    "cached": sum(1 for s in statements if s.get("gemini_status") == "cached"),
                    "processed": sum(1 for s in statements if s.get("gemini_status") == "processed"),
                    "pending": sum(1 for s in statements if s.get("gemini_status") == "pending"),
                    "filtered_out": len(data.get("gemini_filtered_out", [])),
                }

            # Neue vs. gecachte Eintraege zaehlen
            cached_count = sum(1 for s in statements if s.get("gemini_status") == "cached")
            entry["fetch"]["from_cache"] = cached_count
            entry["fetch"]["new"] = len(statements) - cached_count

        except Exception as e:
            entry["status"] = f"error: {e}"
    else:
        entry["status"] = "error: data.json nicht gefunden"

    return entry


def main():
    print("=== Run-Log speichern ===")

    history = load_history()
    new_entry = build_run_entry()
    history.append(new_entry)

    # Auf MAX_HISTORY begrenzen (aelteste entfernen)
    if len(history) > MAX_HISTORY:
        history = history[-MAX_HISTORY:]

    with open(HISTORY_PATH, "w", encoding="utf-8") as f:
        json.dump(history, f, ensure_ascii=False, indent=2)

    total = new_entry.get("fetch", {}).get("total_statements", "?")
    new = new_entry.get("fetch", {}).get("new", "?")
    pending = new_entry.get("gemini", {}).get("pending", 0)

    print(f"  Eintraege: {total} (davon {new} neu, {pending} pending)")
    print(f"  Run-ID: {new_entry['run_id']}")
    print(f"  Historie: {len(history)} Eintraege gespeichert")
    print("=== Fertig ===")


if __name__ == "__main__":
    main()
