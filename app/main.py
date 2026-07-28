import base64
import json
import os
import time
from pathlib import Path
from typing import Any

import httpx
from fastapi import FastAPI, Query
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

SPOTIFY_TOKEN_URL = "https://accounts.spotify.com/api/token"
SPOTIFY_PLAYER_URL = "https://api.spotify.com/v1/me/player"
STATIC_DIR = os.environ.get("STATIC_DIR", "/opt/spotify-now-playing/app/static")
LOCAL_STATE_FILE = Path(os.environ.get("SPOTIFY_NOW_PLAYING_STATE_FILE", "/run/raspotify/now-playing.json"))
LOCAL_STATE_MAX_AGE_SECONDS = int(os.environ.get("SPOTIFY_NOW_PLAYING_STATE_MAX_AGE_SECONDS", "21600"))

app = FastAPI(title="Spotify Now Playing")

_access_token: str | None = None
_access_token_expires_at = 0.0


def credentials_configured() -> bool:
    return all(
        os.environ.get(name)
        for name in (
            "SPOTIFY_CLIENT_ID",
            "SPOTIFY_CLIENT_SECRET",
            "SPOTIFY_REFRESH_TOKEN",
        )
    )


async def refresh_access_token(force: bool = False) -> str | None:
    global _access_token, _access_token_expires_at

    if not credentials_configured():
        return None

    now = time.time()
    if not force and _access_token and now < (_access_token_expires_at - 60):
        return _access_token

    client_id = os.environ["SPOTIFY_CLIENT_ID"]
    client_secret = os.environ["SPOTIFY_CLIENT_SECRET"]
    refresh_token = os.environ["SPOTIFY_REFRESH_TOKEN"]
    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.post(
            SPOTIFY_TOKEN_URL,
            data={"grant_type": "refresh_token", "refresh_token": refresh_token},
            headers={"Authorization": f"Basic {basic}"},
        )

    if response.status_code != 200:
        return None

    payload = response.json()
    _access_token = payload["access_token"]
    _access_token_expires_at = now + int(payload.get("expires_in", 3600))
    return _access_token


def image_url(item: dict[str, Any]) -> str | None:
    images = item.get("album", {}).get("images", [])
    if not images:
        return None
    largest = max(images, key=lambda image: int(image.get("width") or 0) * int(image.get("height") or 0))
    return largest.get("url")


def has_stale_progress(payload: dict[str, Any], item: dict[str, Any]) -> bool:
    duration = int(item.get("duration_ms") or 0)
    progress = int(payload.get("progress_ms") or 0)

    if duration <= 0:
        return False

    return progress < -5000 or progress > duration + 60000


def normalized_progress(payload: dict[str, Any], item: dict[str, Any]) -> int:
    duration = int(item.get("duration_ms") or 0)
    progress = int(payload.get("progress_ms") or 0)

    if duration <= 0:
        return max(0, progress)

    if 0 <= progress <= duration:
        return progress

    if payload.get("is_playing"):
        return progress % duration

    return max(0, min(duration, progress))


def empty_response(message: str, configured: bool = True) -> JSONResponse:
    return JSONResponse(
        {
            "configured": configured,
            "empty": True,
            "playing": False,
            "message": message,
        },
        headers={"Cache-Control": "no-store"},
    )


def local_state_response() -> JSONResponse | None:
    try:
        stat = LOCAL_STATE_FILE.stat()
    except FileNotFoundError:
        return None
    except OSError:
        return None

    if time.time() - stat.st_mtime > LOCAL_STATE_MAX_AGE_SECONDS:
        return None

    try:
        state = json.loads(LOCAL_STATE_FILE.read_text())
    except Exception:
        return None

    if state.get("empty"):
        return empty_response(state.get("message") or "Nothing is playing.")

    if not state.get("track") and not state.get("track_id"):
        return None

    now_ms = int(time.time() * 1000)
    duration_ms = int(state.get("duration_ms") or 0)
    progress_ms = int(state.get("progress_ms") or 0)
    updated_at_ms = int(state.get("position_updated_at_ms") or state.get("updated_at_ms") or now_ms)

    if state.get("playing") and duration_ms:
        progress_ms += now_ms - updated_at_ms

    if duration_ms:
        progress_ms = max(0, min(duration_ms, progress_ms))
    else:
        progress_ms = max(0, progress_ms)

    return JSONResponse(
        {
            "configured": True,
            "playing": bool(state.get("playing")),
            "empty": False,
            "progress_ms": progress_ms,
            "raw_progress_ms": int(state.get("progress_ms") or 0),
            "duration_ms": duration_ms,
            "track": state.get("track") or "Unknown track",
            "artist": state.get("artist") or "Unknown artist",
            "album": state.get("album") or "",
            "album_art": state.get("album_art"),
            "track_id": state.get("track_id"),
            "device": "Canton RC-L",
            "repeat_state": state.get("repeat_state") or "off",
            "server_time_ms": now_ms,
            "source": "raspotify-event",
        },
        headers={"Cache-Control": "no-store"},
    )


def serialize_player(payload: dict[str, Any]) -> dict[str, Any]:
    item = payload.get("item") or {}
    album = item.get("album") or {}
    artists = item.get("artists") or []
    artist_names = ", ".join(a.get("name", "") for a in artists if a.get("name"))
    duration_ms = int(item.get("duration_ms") or 0)
    progress_ms = normalized_progress(payload, item)

    return {
        "configured": True,
        "playing": bool(payload.get("is_playing")),
        "empty": False,
        "progress_ms": progress_ms,
        "raw_progress_ms": payload.get("progress_ms") or 0,
        "duration_ms": duration_ms,
        "track": item.get("name") or "Unknown track",
        "artist": artist_names or "Unknown artist",
        "album": album.get("name") or "Unknown album",
        "album_art": image_url(item),
        "track_id": item.get("id"),
        "device": (payload.get("device") or {}).get("name"),
        "repeat_state": payload.get("repeat_state") or "off",
        "server_time_ms": int(time.time() * 1000),
    }


async def spotify_request(method: str, path: str, **kwargs: Any) -> JSONResponse:
    if not credentials_configured():
        return JSONResponse({"ok": False, "message": "Spotify API credentials are not configured."}, status_code=400)

    token = await refresh_access_token()
    if not token:
        return JSONResponse({"ok": False, "message": "Could not refresh Spotify access token."}, status_code=502)

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.request(
            method,
            f"{SPOTIFY_PLAYER_URL}{path}",
            headers={"Authorization": f"Bearer {token}"},
            **kwargs,
        )
        if response.status_code == 401:
            token = await refresh_access_token(force=True)
            response = await client.request(
                method,
                f"{SPOTIFY_PLAYER_URL}{path}",
                headers={"Authorization": f"Bearer {token}"},
                **kwargs,
            )

    if response.status_code in (200, 202, 204):
        return JSONResponse({"ok": True}, headers={"Cache-Control": "no-store"})

    message = "Spotify control request failed."
    try:
        error = response.json().get("error", {})
        message = error.get("message") or message
    except Exception:
        pass

    if response.status_code == 403:
        message = "Controls need a new Spotify refresh token with user-modify-playback-state."
    elif response.status_code == 404:
        message = "No active Spotify device is available."

    return JSONResponse({"ok": False, "message": message}, status_code=response.status_code, headers={"Cache-Control": "no-store"})


@app.get("/api/current")
async def current_playback() -> JSONResponse:
    local_response = local_state_response()
    if local_response is not None:
        return local_response

    if not credentials_configured():
        return empty_response("Spotify API credentials are not configured.", configured=False)

    token = await refresh_access_token()
    if not token:
        response = empty_response("Could not refresh Spotify access token.", configured=False)
        response.status_code = 502
        return response

    async with httpx.AsyncClient(timeout=10) as client:
        response = await client.get(
            SPOTIFY_PLAYER_URL,
            headers={"Authorization": f"Bearer {token}"},
            params={"additional_types": "track,episode"},
        )

        if response.status_code == 401:
            token = await refresh_access_token(force=True)
            response = await client.get(
                SPOTIFY_PLAYER_URL,
                headers={"Authorization": f"Bearer {token}"},
                params={"additional_types": "track,episode"},
            )

    if response.status_code == 204:
        return empty_response("Nothing is playing.")

    if response.status_code != 200:
        return JSONResponse(
            {
                "configured": True,
                "empty": True,
                "playing": False,
                "message": f"Spotify API returned HTTP {response.status_code}.",
            },
            status_code=502,
            headers={"Cache-Control": "no-store"},
        )

    payload = response.json()
    if not payload or not payload.get("item"):
        return empty_response("Nothing is playing.")

    if has_stale_progress(payload, payload["item"]):
        return empty_response("Spotify returned stale playback state. Re-select Canton RC-L in Spotify.")

    return JSONResponse(serialize_player(payload), headers={"Cache-Control": "no-store"})


@app.put("/api/play")
async def play() -> JSONResponse:
    return await spotify_request("PUT", "/play")


@app.put("/api/pause")
async def pause() -> JSONResponse:
    return await spotify_request("PUT", "/pause")


@app.post("/api/next")
async def next_track() -> JSONResponse:
    return await spotify_request("POST", "/next")


@app.post("/api/previous")
async def previous_track() -> JSONResponse:
    return await spotify_request("POST", "/previous")


@app.put("/api/seek")
async def seek(position_ms: int = Query(ge=0)) -> JSONResponse:
    return await spotify_request("PUT", "/seek", params={"position_ms": position_ms})


@app.put("/api/repeat")
async def repeat(state: str = Query(pattern="^(off|context|track)$")) -> JSONResponse:
    return await spotify_request("PUT", "/repeat", params={"state": state})


@app.get("/health")
async def health() -> dict[str, bool]:
    return {"ok": True}


app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
