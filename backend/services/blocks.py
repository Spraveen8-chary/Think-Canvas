"""Turns the model's reply into safe, bounded "blocks". Anything malformed is dropped, never trusted."""
import json
import math
import re

MAX_BLOCKS = 6
TEXT_LIMIT = 1200
EXPR_RE = re.compile(r"^[0-9a-zA-Z_+\-*/^().,\s]{1,120}$")
COLOR_RE = re.compile(r"^(#[0-9a-fA-F]{3,8}|[a-zA-Z]{3,20})$")


def extract_json(text: str) -> dict:
    """Finds the JSON object in a reply (models sometimes wrap it in a code fence)."""
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        raise ValueError("The AI did not return JSON")
    obj = json.loads(text[start:end + 1])
    if not isinstance(obj, dict):
        raise ValueError("The AI reply was not an object")
    return obj


def _num(v, lo=-1e6, hi=1e6, default=None):
    if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
        return default
    return max(lo, min(hi, float(v)))


def _clean(text, limit):
    return re.sub(r"\*\*|`", "", str(text)).strip()[:limit]


def _color(v):
    return v if isinstance(v, str) and COLOR_RE.match(v) else None


def _text(b):
    t = _clean(b.get("text", ""), TEXT_LIMIT)
    return {"t": "text", "text": t} if t else None


PLOT_WORDS = {"x", "pi", "e", "deg", "sin", "cos", "tan", "sqrt", "abs", "exp", "ln"}


def _only_x(expr):
    """A plot must be a function of x alone; any other name (y, c, a...) can't be drawn."""
    return all(w in PLOT_WORDS for w in re.findall(r"[a-zA-Z_]+", expr))


def _plot(b):
    fs = [f for f in (b.get("f") or []) if isinstance(f, str) and EXPR_RE.match(f) and _only_x(f)][:4]
    if not fs:
        return None
    x = b.get("x") or [-10, 10]
    x0, x1 = (_num(x[0], default=-10), _num(x[1], default=10)) if isinstance(x, list) and len(x) == 2 else (-10, 10)
    if x0 is None or x1 is None or x1 <= x0:
        x0, x1 = -10.0, 10.0
    out = {"t": "plot", "f": fs, "x": [x0, x1]}
    y = b.get("y")
    if isinstance(y, list) and len(y) == 2:
        y0, y1 = _num(y[0]), _num(y[1])
        if y0 is not None and y1 is not None and y1 > y0:
            out["y"] = [y0, y1]
    return out


def _chart(b):
    kind = b.get("kind") if b.get("kind") in ("bar", "line", "pie") else "bar"
    labels, values = b.get("labels"), b.get("values")
    if not isinstance(labels, list) or not isinstance(values, list):
        return None
    pairs = [(_clean(l, 24), _num(v)) for l, v in zip(labels, values)][:24]
    pairs = [(l, v) for l, v in pairs if v is not None]
    if not pairs or (kind == "pie" and any(v < 0 for _, v in pairs)):
        return None
    return {"t": "chart", "kind": kind, "labels": [p[0] for p in pairs], "values": [p[1] for p in pairs], "title": _clean(b.get("title", ""), 60)}


def _flow(b):
    nodes = []
    for n in (b.get("nodes") or [])[:12]:
        if isinstance(n, list) and len(n) >= 2:
            shape = n[2] if len(n) > 2 and n[2] in ("box", "oval", "diamond") else "box"
            nodes.append([_clean(n[0], 20), _clean(n[1], 40), shape])
    ids = {n[0] for n in nodes}
    if len(ids) < 2 or len(ids) != len(nodes):
        return None
    edges = []
    for e in (b.get("edges") or [])[:24]:
        if isinstance(e, list) and len(e) >= 2 and _clean(e[0], 20) in ids and _clean(e[1], 20) in ids:
            edges.append([_clean(e[0], 20), _clean(e[1], 20), _clean(e[2], 24) if len(e) > 2 else ""])
    return {"t": "flow", "dir": "right" if b.get("dir") == "right" else "down", "nodes": nodes, "edges": edges}


SHAPE_ARGS = {"line": 4, "arrow": 4, "rect": 4, "circle": 3, "ellipse": 4}


def _draw(b):
    w, h = _num(b.get("w"), 120, 700, 320), _num(b.get("h"), 120, 700, 220)
    shapes = []
    for s in (b.get("s") or [])[:40]:
        if not isinstance(s, list) or not s:
            continue
        kind = s[0]
        if kind == "text" and len(s) >= 4 and _num(s[1]) is not None and _num(s[2]) is not None:
            shapes.append(["text", _num(s[1]), _num(s[2]), _clean(s[3], 40)])
        elif kind in SHAPE_ARGS and len(s) == SHAPE_ARGS[kind] + 1:
            nums = [_num(v) for v in s[1:]]
            if None not in nums:
                shapes.append([kind, *nums])
    return {"t": "draw", "w": w, "h": h, "s": shapes} if shapes else None


def _points(raw, limit=40):
    """[[x, y], ...] with 2..limit numeric pairs, or None."""
    if not isinstance(raw, list):
        return None
    pts = [[_num(p[0]), _num(p[1])] for p in raw[:limit] if isinstance(p, list) and len(p) == 2]
    pts = [p for p in pts if None not in p]
    return pts if len(pts) >= 2 else None


def _anim(b):
    w, h = _num(b.get("w"), 120, 700, 400), _num(b.get("h"), 120, 700, 260)
    objs, ids, paths = [], set(), set()
    for o in (b.get("o") or [])[:24]:
        if not isinstance(o, dict) or not isinstance(o.get("id"), str) or o["id"] in ids:
            continue
        kind, out = o.get("type"), {"id": o["id"][:20], "type": o.get("type")}
        if kind == "path":                                   # a curve the AI draws once; objects can follow it
            pts = _points(o.get("points"))
            if pts:
                out["points"] = pts
                for key in ("fill", "stroke"):
                    if _color(o.get(key)):
                        out[key] = o[key]
                objs.append(out)
                ids.add(out["id"])
                paths.add(out["id"])
            continue
        fields = {"circle": ("cx", "cy", "r"), "rect": ("x", "y", "w", "h"), "line": ("x1", "y1", "x2", "y2"), "text": ("x", "y")}.get(kind)
        if not fields:
            continue
        vals = {k: _num(o.get(k)) for k in fields}
        if None in vals.values():
            continue
        out.update(vals)
        if kind == "text":
            out["text"] = _clean(o.get("text", ""), 40)
            out["size"] = _num(o.get("size"), 8, 60, 16)
        for key in ("fill", "stroke"):
            if _color(o.get(key)):
                out[key] = o[key]
        objs.append(out)
        ids.add(out["id"])
    motions = []
    for m in (b.get("m") or [])[:24]:
        if not isinstance(m, dict) or m.get("target") not in ids:
            continue
        kind, ms = m.get("type"), _num(m.get("ms"), 300, 60000)
        if ms is None:
            continue
        out = {"type": kind, "target": m["target"], "ms": ms}
        if kind == "orbit":
            c = m.get("center")
            if isinstance(c, str) and c in ids:
                out["center"] = c
            elif isinstance(c, list) and len(c) == 2 and None not in (_num(c[0]), _num(c[1])):
                out["center"] = [_num(c[0]), _num(c[1])]
            else:
                continue
            out["rx"], out["ry"] = _num(m.get("rx"), 1, 700, 50), _num(m.get("ry"), 1, 700, 50)
        elif kind == "move":
            f, t = m.get("from"), m.get("to")
            if not (isinstance(f, list) and isinstance(t, list) and len(f) == len(t) == 2 and None not in map(_num, f + t)):
                continue
            out["from"], out["to"] = [_num(f[0]), _num(f[1])], [_num(t[0]), _num(t[1])]
        elif kind == "follow":
            if m.get("along") not in paths or m["target"] in paths:
                continue
            out["along"] = m["along"]
        elif kind == "pulse":
            out["from"], out["to"] = _num(m.get("from"), 0.1, 10, 1), _num(m.get("to"), 0.1, 10, 1.3)
        elif kind != "spin":
            continue
        motions.append(out)
    if not objs:
        return None
    return {"t": "anim", "w": w, "h": h, "ms": _num(b.get("ms"), 500, 60000, 4000), "o": objs, "m": motions}


BUILDERS = {"text": _text, "plot": _plot, "chart": _chart, "flow": _flow, "draw": _draw, "anim": _anim}


def sanitize(raw: dict) -> dict:
    """Returns {"read": str, "blocks": [...], "lookup": str|None}."""
    blocks = []
    for b in raw.get("blocks") or []:
        build = BUILDERS.get(b.get("t")) if isinstance(b, dict) else None
        block = build(b) if build else None
        if block:
            blocks.append(block)
        if len(blocks) >= MAX_BLOCKS:
            break
    lookup = raw.get("lookup")
    return {
        "read": _clean(raw.get("read", ""), 200),
        "blocks": blocks,
        "lookup": _clean(lookup, 100) if isinstance(lookup, str) and lookup.strip() else None,
    }
