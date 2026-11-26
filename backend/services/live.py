"""Gemini Live API service: ephemeral token minting and canvas tool-call validation."""
from datetime import datetime, timedelta, timezone
import logging

import httpx

from ..core.errors import BadRequest, RateLimited, UpstreamError
from . import blocks as block_svc

log = logging.getLogger("tc.live")

AUTH_TOKENS_URL = "https://generativelanguage.googleapis.com/v1alpha/auth_tokens"
LIVE_WS_URL = (
    "wss://generativelanguage.googleapis.com/ws/"
    "google.ai.generativelanguage.v1alpha.GenerativeService.BidiGenerateContentConstrained"
)
MAX_SESSION_S = 1800
IDLE_TIMEOUT_S = 120

CANVAS_TOOL_DECLARATIONS = [
    {
        "name": "draw_text_note",
        "description": "Write a concise text note or explanation card on the canvas.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "text": {"type": "STRING", "description": "Plain text note (max 700 chars, no markdown)"},
            },
            "required": ["text"],
        },
    },
    {
        "name": "draw_plot",
        "description": "Plot one or more mathematical functions y = f(x) on a 2D coordinate grid.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "f": {
                    "type": "ARRAY",
                    "items": {"type": "STRING"},
                    "description": "Expressions of x using + - * / ^ pi e sin cos tan sqrt abs exp ln, e.g. ['sin(x)', 'x^2']",
                },
                "x": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "[xmin, xmax], default [-10, 10]"},
                "y": {"type": "ARRAY", "items": {"type": "NUMBER"}, "description": "Optional [ymin, ymax]"},
            },
            "required": ["f"],
        },
    },
    {
        "name": "draw_chart",
        "description": "Draw a bar, line, or pie chart on the canvas.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "kind": {"type": "STRING", "enum": ["bar", "line", "pie"]},
                "labels": {"type": "ARRAY", "items": {"type": "STRING"}},
                "values": {"type": "ARRAY", "items": {"type": "NUMBER"}},
                "title": {"type": "STRING"},
            },
            "required": ["kind", "labels", "values"],
        },
    },
    {
        "name": "draw_flow",
        "description": "Draw a flowchart or system architecture diagram with automatic layout.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "dir": {"type": "STRING", "enum": ["down", "right"]},
                "nodes": {
                    "type": "ARRAY",
                    "items": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "description": "Up to 12 nodes of [id, label, shape] where shape is box, oval, or diamond",
                },
                "edges": {
                    "type": "ARRAY",
                    "items": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "description": "Edges of [from_id, to_id, optional_label]",
                },
            },
            "required": ["nodes", "edges"],
        },
    },
    {
        "name": "draw_geometry",
        "description": "Draw geometric shapes, vectors, or labeled diagrams inside a w x h card.",
        "parameters": {
            "type": "OBJECT",
            "properties": {
                "w": {"type": "NUMBER"},
                "h": {"type": "NUMBER"},
                "s": {
                    "type": "ARRAY",
                    "items": {"type": "ARRAY"},
                    "description": "Shapes: ['line',x1,y1,x2,y2], ['arrow',x1,y1,x2,y2], ['rect',x,y,w,h], ['circle',cx,cy,r], ['ellipse',cx,cy,rx,ry], ['text',x,y,'label']",
                },
            },
            "required": ["s"],
        },
    },
    {
        "name": "clear_canvas_area",
        "description": "Clear the canvas when the user explicitly asks to start fresh.",
        "parameters": {"type": "OBJECT", "properties": {}},
    },
]

_TOOL_BLOCK_MAP = {
    "draw_text_note": lambda a: {"t": "text", "text": a.get("text", "")},
    "draw_plot": lambda a: {"t": "plot", "f": a.get("f"), "x": a.get("x"), "y": a.get("y")},
    "draw_chart": lambda a: {
        "t": "chart", "kind": a.get("kind"), "labels": a.get("labels"),
        "values": a.get("values"), "title": a.get("title", ""),
    },
    "draw_flow": lambda a: {"t": "flow", "dir": a.get("dir", "down"), "nodes": a.get("nodes"), "edges": a.get("edges")},
    "draw_geometry": lambda a: {"t": "draw", "w": a.get("w", 320), "h": a.get("h", 220), "s": a.get("s")},
    "draw_animation": lambda a: {
        "t": "anim", "w": a.get("w", 400), "h": a.get("h", 260),
        "ms": a.get("ms", 4000), "o": a.get("o"), "m": a.get("m"),
    },
}


def validate_tool_block(name: str, args: dict) -> dict:
    """Validate and sanitize a Gemini Live tool call using the same rules as blocks.py."""
    if name == "clear_canvas_area":
        return {"action": "clear", "block": None}
    builder = _TOOL_BLOCK_MAP.get(name)
    if not builder or not isinstance(args, dict):
        raise BadRequest(f"Unknown or invalid canvas tool: {name}")
    sanitized = block_svc.sanitize({"blocks": [builder(args)]})
    if not sanitized["blocks"]:
        raise BadRequest(f"Invalid arguments for {name}")
    return {"action": "draw", "block": sanitized["blocks"][0]}


def _iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


async def mint_live_token(api_key: str, model: str, system_instruction: str) -> dict:
    """Mint a single-use, short-lived Gemini ephemeral token locked to our model and tools."""
    if not api_key:
        raise BadRequest("Live Session is not configured (missing GEMINI_API_KEY)")

    now = datetime.now(timezone.utc)
    payload = {
        "uses": 1,
        "expireTime": _iso_utc(now + timedelta(seconds=MAX_SESSION_S)),
        "newSessionExpireTime": _iso_utc(now + timedelta(minutes=2)),
        "liveConnectConstraints": {
            "model": model,
            "config": {
                "responseModalities": ["AUDIO"],
                "systemInstruction": {"parts": [{"text": system_instruction}]},
                "sessionResumption": {},
                "contextWindowCompression": {"slidingWindow": {}},
                "inputAudioTranscription": {},
                "outputAudioTranscription": {},
                "tools": [{"functionDeclarations": CANVAS_TOOL_DECLARATIONS}],
            },
        },
    }

    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            res = await client.post(
                AUTH_TOKENS_URL,
                headers={"x-goog-api-key": api_key, "Content-Type": "application/json"},
                json=payload,
            )
    except httpx.HTTPError as e:
        log.warning("live.token_network_error err=%s", e.__class__.__name__)
        raise UpstreamError("Could not reach Gemini Live service") from e

    if res.status_code == 429:
        raise RateLimited("Gemini Live quota reached. Try again shortly.")
    if res.status_code >= 400:
        log.warning("live.token_vendor_error status=%s", res.status_code)
        raise UpstreamError("Live Session could not be started right now")

    token_name = res.json().get("name")
    if not token_name:
        raise UpstreamError("Gemini Live service returned an invalid token")

    return {
        "token": token_name,
        "model": model,
        "ws_url": LIVE_WS_URL,
        "max_session_s": MAX_SESSION_S,
        "idle_timeout_s": IDLE_TIMEOUT_S,
    }
