#!/usr/bin/env python3
import json
import os
import time
from pathlib import Path


STATE_FILE = Path(os.environ.get("SPOTIFY_NOW_PLAYING_STATE_FILE", "/run/raspotify/now-playing.json"))


def read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def split_list(value: str | None) -> list[str]:
    if not value:
        return []
    return [item.strip() for item in value.splitlines() if item.strip()]


def first_cover() -> str | None:
    covers = split_list(os.environ.get("COVERS"))
    return covers[0] if covers else None


def write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n")
    tmp.chmod(0o644)
    tmp.replace(STATE_FILE)


event = os.environ.get("PLAYER_EVENT", "")
now_ms = int(time.time() * 1000)
state = read_state()

state["last_event"] = event
state["updated_at_ms"] = now_ms

track_id = os.environ.get("TRACK_ID")
if track_id:
    state["track_id"] = track_id

if event == "track_changed":
    artists = split_list(os.environ.get("ARTISTS"))
    album_art = first_cover()
    state.update(
        {
            "configured": True,
            "empty": False,
            "playing": bool(state.get("playing")),
            "progress_ms": 0,
            "position_updated_at_ms": now_ms,
            "duration_ms": int(os.environ.get("DURATION_MS") or 0),
            "track": os.environ.get("NAME") or "Unknown track",
            "artist": ", ".join(artists) or "Unknown artist",
            "album": os.environ.get("ALBUM") or "",
            "album_art": album_art,
        }
    )
elif event in {"playing", "paused", "seeked", "position_correction"}:
    if event == "playing":
        state["playing"] = True
        state["empty"] = False
    elif event == "paused":
        state["playing"] = False
        state["empty"] = False

    if "POSITION_MS" in os.environ:
        state["progress_ms"] = int(os.environ.get("POSITION_MS") or 0)
        state["position_updated_at_ms"] = now_ms
    if "DURATION_MS" in os.environ:
        state["duration_ms"] = int(os.environ.get("DURATION_MS") or 0)
elif event in {"stopped", "stop", "session_disconnected"}:
    state.update({"empty": True, "playing": False, "message": "Nothing is playing."})
elif event == "end_of_track":
    state["playing"] = False

write_state(state)
