"""Gemini Live API service: ephemeral token minting and canvas tool-call validation."""
import logging

from ..core.errors import BadRequest
from . import blocks as block_svc

log = logging.getLogger("tc.live")

LIVE_WS_URL = "wss://generativelanguage.googleapis.com/ws/google.ai.generativelanguage.v1beta.GenerativeService.BidiGenerateContent"
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
                    "items": {"type": "ARRAY", "items": {"type": "STRING"}},
                    "description": "Each shape is a list of strings (numbers written as text). Shapes:['line',x1,y1,x2,y2], ['arrow',x1,y1,x2,y2], ['rect',x,y,w,h], ['circle',cx,cy,r], ['ellipse',cx,cy,rx,ry], ['text',x,y,'label']",
                },
            },
            "required": ["s"],
        },
    },
    {
        "name": "clear_canvas_area",
        "description": "Clear the canvas when the user explicitly asks to start fresh.",
    },
]

def _coerce_shapes(shapes):
    """Gemini sends shape items as strings; turn numeric ones back into numbers."""
    def num(v):
        try:
            return float(v) if isinstance(v, str) else v
        except ValueError:
            return v
    if not isinstance(shapes, list):
        return shapes
    return [[sh[0], *[num(v) for v in sh[1:]]] if isinstance(sh, list) and sh else sh for sh in shapes]


_TOOL_BLOCK_MAP = {
    "draw_text_note": lambda a: {"t": "text", "text": a.get("text", "")},
    "draw_plot": lambda a: {"t": "plot", "f": a.get("f"), "x": a.get("x"), "y": a.get("y")},
    "draw_chart": lambda a: {
        "t": "chart", "kind": a.get("kind"), "labels": a.get("labels"),
        "values": a.get("values"), "title": a.get("title", ""),
    },
    "draw_flow": lambda a: {"t": "flow", "dir": a.get("dir", "down"), "nodes": a.get("nodes"), "edges": a.get("edges")},
    "draw_geometry": lambda a: {"t": "draw", "w": a.get("w", 320), "h": a.get("h", 220), "s": _coerce_shapes(a.get("s"))},
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


def build_setup(model: str, system_instruction: str, resume_handle: str | None = None) -> dict:
    """The first message sent to Gemini Live. Built on the server so the browser cannot change it."""
    setup = {
        "model": model if model.startswith(("models/", "tunedModels/")) else f"models/{model}",   # Gemini wants the "models/" prefix
        "generationConfig": {"responseModalities": ["AUDIO"]},
        "systemInstruction": {"parts": [{"text": system_instruction}]},
        "sessionResumption": {"handle": resume_handle} if resume_handle else {},
        "contextWindowCompression": {"slidingWindow": {}},
        "inputAudioTranscription": {},
        "outputAudioTranscription": {},
        "tools": [{"functionDeclarations": CANVAS_TOOL_DECLARATIONS}],
    }
    return {"setup": setup}
