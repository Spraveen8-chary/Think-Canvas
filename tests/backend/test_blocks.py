import pytest

from backend.services import blocks, rag


def clean(obj):
    return blocks.sanitize(obj)


def test_extract_json_from_fenced_reply():
    assert blocks.extract_json('Here:\n```json\n{"a": 1}\n```')["a"] == 1
    with pytest.raises(ValueError):
        blocks.extract_json("no json here")


def test_text_markdown_removed_and_limited():
    out = clean({"blocks": [{"t": "text", "text": "**hi** `x`" + "a" * 2000}]})["blocks"][0]
    assert out["text"].startswith("hi x") and len(out["text"]) <= 700


def test_unknown_and_empty_blocks_dropped():
    assert clean({"blocks": [{"t": "script"}, {"t": "text", "text": "  "}, "x", None]})["blocks"] == []


def test_plot_expression_is_checked():
    ok = clean({"blocks": [{"t": "plot", "f": ["sin(x)", "__import__('os')", "x;rm"], "x": [0, 6]}]})["blocks"][0]
    assert ok["f"] == ["sin(x)"] and ok["x"] == [0.0, 6.0]
    assert clean({"blocks": [{"t": "plot", "f": ["alert(1);"]}]})["blocks"] == []


def test_chart_needs_matching_numbers():
    c = clean({"blocks": [{"t": "chart", "kind": "pie", "labels": ["a", "b", "c"], "values": [1, "x", 3]}]})["blocks"][0]
    assert c["labels"] == ["a", "c"] and c["values"] == [1.0, 3.0]
    assert clean({"blocks": [{"t": "chart", "kind": "pie", "labels": ["a"], "values": [-1]}]})["blocks"] == []


def test_flow_edges_must_reference_nodes():
    f = clean({"blocks": [{"t": "flow", "nodes": [["a", "Start", "oval"], ["b", "End"]], "edges": [["a", "b", "go"], ["a", "zzz"]]}]})["blocks"][0]
    assert f["edges"] == [["a", "b", "go"]] and f["nodes"][1][2] == "box"
    assert clean({"blocks": [{"t": "flow", "nodes": [["a", "only one"]]}]})["blocks"] == []


def test_draw_shapes_validated_and_size_clamped():
    d = clean({"blocks": [{"t": "draw", "w": 99999, "h": 10, "s": [["circle", 10, 10, 5], ["circle", 1, 2], ["rect", "a", 1, 2, 3], ["text", 5, 5, "hi"]]}]})["blocks"][0]
    assert d["w"] == 700 and d["h"] == 120 and len(d["s"]) == 2


def test_anim_checks_targets_and_motion_types():
    a = clean({"blocks": [{"t": "anim", "o": [
        {"id": "sun", "type": "circle", "cx": 100, "cy": 100, "r": 10, "fill": "#f90"},
        {"id": "p", "type": "circle", "cx": 150, "cy": 100, "r": 4, "fill": "red; x"}],
        "m": [{"type": "orbit", "target": "p", "center": "sun", "rx": 50, "ry": 50, "ms": 2000},
              {"type": "orbit", "target": "ghost", "center": "sun", "rx": 5, "ry": 5, "ms": 1000},
              {"type": "eval", "target": "p", "ms": 1000}]}]})["blocks"][0]
    assert len(a["m"]) == 1 and a["m"][0]["center"] == "sun" and "fill" not in a["o"][1]


def test_at_most_four_blocks_and_lookup_passthrough():
    r = clean({"read": "q", "lookup": "force mass", "blocks": [{"t": "text", "text": str(i)} for i in range(9)]})
    assert len(r["blocks"]) == 4 and r["lookup"] == "force mass"


def test_chunking_keeps_page_numbers():
    pages = [(1, "alpha " * 300), (2, "beta " * 50)]
    chunks = rag.chunk_pages(pages)
    assert {c["page"] for c in chunks} == {1, 2} and all(len(c["text"]) <= rag.CHUNK_CHARS for c in chunks)


def test_prompt_is_built_from_parts_so_requests_only_pay_for_what_they_use():
    from backend.services import prompts

    base = prompts.system_prompt(animation=False)
    full = prompts.system_prompt(animation=True, can_lookup=True)
    assert '"t":"anim"' not in base and '"t":"anim"' in full
    assert len(full) > len(base) + 400                                   # the animation spec is the costly part
    assert "excerpts" in prompts.system_prompt(has_excerpts=True) and "lookup" in full
    assert not prompts.wants_animation("plot sin x", False)
    assert prompts.wants_animation("animate the earth orbiting the sun", False)
    assert prompts.wants_animation("", True)                             # a picture's question is unknown: keep the spec
