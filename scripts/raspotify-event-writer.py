#!/usr/bin/env python3
import fcntl
import json
import os
import tempfile
import time
from pathlib import Path


STATE_FILE = Path(os.environ.get("SPOTIFY_NOW_PLAYING_STATE_FILE", "/run/raspotify/now-playing.json"))
LOCK_FILE = STATE_FILE.with_suffix(".lock")


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


def env_flag(name: str) -> bool:
    return (os.environ.get(name) or "").strip().lower() in {"true", "1", "yes", "on"}


def write_state(state: dict) -> None:
    # A unique temp file per process so concurrent writers never share one.
    fd, tmp_name = tempfile.mkstemp(dir=STATE_FILE.parent, prefix=".now-playing.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(json.dumps(state, ensure_ascii=False, separators=(",", ":")) + "\n")
        os.chmod(tmp_name, 0o644)
        os.replace(tmp_name, STATE_FILE)
    except BaseException:
        try:
            os.unlink(tmp_name)
        except FileNotFoundError:
            pass
        raise


def apply_event(state: dict, event: str, now_ms: int) -> dict:
    state["last_event"] = event
    state["updated_at_ms"] = now_ms

    track_id = os.environ.get("TRACK_ID")
    if track_id:
        state["track_id"] = track_id

    if event == "track_changed":
        artists = split_list(os.environ.get("ARTISTS"))
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
                "album_art": first_cover(),
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
    elif event == "repeat_changed":
        if env_flag("REPEAT_TRACK"):
            state["repeat_state"] = "track"
        elif env_flag("REPEAT"):
            state["repeat_state"] = "context"
        else:
            state["repeat_state"] = "off"
    elif event in {"stopped", "session_disconnected"}:
        state.update({"empty": True, "playing": False, "message": "Nothing is playing."})
    elif event == "end_of_track":
        state["playing"] = False

    return state


def main() -> None:
    event = os.environ.get("PLAYER_EVENT", "")
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # librespot spawns one process per event and events often arrive together
    # (track_changed + playing). Serialize the read-modify-write cycle.
    with open(LOCK_FILE, "a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = apply_event(read_state(), event, int(time.time() * 1000))
        write_state(state)


if __name__ == "__main__":
    main()
