"""Handwriting benchmark: small / medium / hard problems, written as pen strokes, through the REAL app.

For every case it
  1. draws the text with a handwriting font, character by character with random tilt / size / baseline / spacing,
     thins it to a one-pixel centre line and wobbles it (so it looks like pen strokes, not a font),
  2. gives those strokes to the app's real Board.snapshot() in headless Chrome: the exact picture the AI receives,
  3. sends that picture to the real POST /api/ask (login, safety rules, prompt, AI model),
  4. checks the answer against the expected result and saves the picture, what the AI read, and its answer.

Needs: Windows fonts, Google Chrome, a configured .env (an AI key and MongoDB). It starts its own server on another port with a
throw-away database. Output: docs/evidence/handwriting/ (REPORT.md, results.json, img/*.png).

Run:  .venv\\Scripts\\python tools\\handwriting_benchmark.py
Note: the strokes are synthetic (font + jitter), not a human hand. They test reading messy, tilted, wobbly writing, not every style of a real person.
"""
import base64, difflib, http.cookiejar, json, os, random, re, shutil, subprocess, sys, tempfile, time, urllib.error, urllib.request
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageOps
from websockets.sync.client import connect

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
OUT = REPO / "docs" / "evidence" / "handwriting"
PY = REPO / ".venv" / "Scripts" / "python.exe"
CHROME = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
PORT, DBG = 3998, 9334
BASE = f"http://localhost:{PORT}"
FONTS = {"a": r"C:\Windows\Fonts\segoepr.ttf", "b": r"C:\Windows\Fonts\Inkfree.ttf"}          # print-like and cursive-like
SYMBOL_FONT = r"C:\Windows\Fonts\seguisym.ttf"
SYMBOLS = set("∫→°π√≠≈")

NUM = lambda n: rf"(?<![\d.]){n}(?!\d|\.\d)"           # the number n on its own: not part of a longer number or a decimal (a full stop after it is fine)
CASES = [
    # ---- small: one step, short -------------------------------------------------------------------------------------------------
    dict(id="S1", level="small", lines=["2 + 3 = ?"], expect=[NUM(5)]),
    dict(id="S2", level="small", lines=["12 x 4 ="], expect=[NUM(48)]),
    dict(id="S3", level="small", lines=["9^2 = ?"], expect=[NUM(81)]),
    dict(id="S4", level="small", lines=["photosynthesis"], expect=[r"chlorophyll|sunlight|glucose|light energy"]),
    dict(id="S5", level="small", lines=["100 / 4 ="], expect=[NUM(25)]),
    # ---- medium: a few steps, a formula or a topic ------------------------------------------------------------------------------
    dict(id="M1", level="medium", lines=["3x + 7 = 22"], expect=[r"x\s*=\s*5(?!\d|\.\d)"]),
    dict(id="M2", level="medium", lines=["sin 30° = ?"], expect=[r"0\.5|1/2|half"]),
    dict(id="M3", level="medium", lines=["d/dx (x^3 + 2x) ="], expect=[r"3\s*x\s*\^?\s*2\s*\+\s*2"]),
    dict(id="M4", level="medium", lines=["area of circle r = 7"], expect=[r"153\.9|154|49\s*(π|pi)"]),
    dict(id="M5", level="medium", lines=["binary search code"], expect=[r"def |while |mid"]),
    dict(id="M6", level="medium", lines=["F = ma , m = 5 , a = 3"], expect=[NUM(15)]),
    # ---- hard: symbols, powers, several lines, word problems ------------------------------------------------------------------------
    dict(id="H1", level="hard", lines=["∫ x^2 dx   from 0 to 3"], expect=[NUM(9)]),
    dict(id="H2", level="hard", lines=["x^2 - 5x + 6 = 0"], expect=[r"x\s*=\s*2.*x\s*=\s*3|x\s*=\s*3.*x\s*=\s*2|2\s*(,|and|or)\s*3|3\s*(,|and|or)\s*2"]),
    dict(id="H3", level="hard", lines=["(a+b)^3 = ?"], squash=True, expect=[r"a3\+3a2b\+3ab2\+b3"]),
    dict(id="H4", level="hard", lines=["lim x→0  sin x / x"], expect=[r"(=|equals|is)\s*1(?!\d|\.\d)"]),
    dict(id="H5", level="hard", lines=["2x + y = 7", "x - y = 2"], expect=[r"x\s*=\s*3", r"y\s*=\s*1"]),
    dict(id="H6", level="hard", lines=["A ball is thrown at 20 m/s", "at 30°. Find the range."], expect=[r"35\.?\d*"]),
    dict(id="H7", level="hard", lines=["SQL: second highest", "salary from Employee"], expect=[r"(?i)select"]),
]


# ------------------------------------------------------------------ 1. handwriting -> pen strokes
def draw_handwriting(lines, font_key, seed, size=64):
    rnd = random.Random(seed)
    main = ImageFont.truetype(FONTS[font_key], size)
    sym = ImageFont.truetype(SYMBOL_FONT, size)
    W, H = 1500, 130 * len(lines) + 90
    page = Image.new("L", (W, H), 255)
    for li, line in enumerate(lines):
        x, base = 40 + rnd.uniform(0, 10), 100 + li * 125 + rnd.uniform(-4, 4)
        superscript = False
        for ch in line:
            if ch == "^":
                superscript = True
                continue
            if ch == " ":
                x += size * 0.32 + rnd.uniform(-3, 5)
                continue
            scale = (0.6 if superscript else 1.0) * rnd.uniform(0.93, 1.07)
            f = sym if ch in SYMBOLS else main
            if scale != 1.0:
                f = ImageFont.truetype(SYMBOL_FONT if ch in SYMBOLS else FONTS[font_key], max(8, int(size * scale)))
            patch = Image.new("L", (size * 2, size * 2), 255)
            ImageDraw.Draw(patch).text((size // 2, int(size * 1.3)), ch, font=f, fill=0, anchor="ls")
            patch = patch.rotate(rnd.gauss(0, 4.5), resample=Image.BICUBIC, fillcolor=255)
            dy = rnd.gauss(0, 2.5) - (size * 0.45 if superscript else 0)
            page.paste(patch, (int(x - size // 2), int(base - size * 1.3 + dy)), ImageOps.invert(patch))
            x += f.getlength(ch) + rnd.uniform(-1, 4)
            superscript = False
    return np.asarray(page) < 128


def thin(img):
    """Zhang-Suen thinning: a thick written line becomes a one-pixel centre line (what a pen path is)."""
    img = img.astype(np.uint8).copy()
    changed = True
    while changed:
        changed = False
        for step in (0, 1):
            P = np.pad(img, 1)
            p2, p3, p4, p5 = P[:-2, 1:-1], P[:-2, 2:], P[1:-1, 2:], P[2:, 2:]
            p6, p7, p8, p9 = P[2:, 1:-1], P[2:, :-2], P[1:-1, :-2], P[:-2, :-2]
            nb = p2 + p3 + p4 + p5 + p6 + p7 + p8 + p9
            seq = [p2, p3, p4, p5, p6, p7, p8, p9, p2]
            a = sum(((seq[i] == 0) & (seq[i + 1] == 1)).astype(np.uint8) for i in range(8))
            c1, c2 = ((p2 * p4 * p6 == 0), (p4 * p6 * p8 == 0)) if step == 0 else ((p2 * p4 * p8 == 0), (p2 * p6 * p8 == 0))
            m = (img == 1) & (nb >= 2) & (nb <= 6) & (a == 1) & c1 & c2
            if m.any():
                img[m] = 0
                changed = True
    return img.astype(bool)


def to_strokes(ink, seed):
    """Centre line -> pen strokes with a slow wobble (a hand does not draw perfectly straight lines)."""
    rnd = random.Random(seed)
    ph = [rnd.uniform(0, 6.28) for _ in range(4)]
    sk = thin(ink)
    ys, xs = np.nonzero(sk)
    have = set(zip(ys.tolist(), xs.tolist()))

    def wob(y, x):
        return (x + 2.4 * np.sin(y / 37 + ph[0]) + 1.2 * np.sin(y / 11 + ph[1]), y + 2.4 * np.sin(x / 41 + ph[2]) + 1.2 * np.sin(x / 13 + ph[3]))

    strokes = []
    for y, x in sorted(have):
        for dy, dx in ((0, 1), (1, 0), (1, 1), (1, -1)):
            if (y + dy, x + dx) in have:
                (x1, y1), (x2, y2) = wob(y, x), wob(y + dy, x + dx)
                strokes.append({"type": "stroke", "points": [[round(x1 + 200, 1), round(y1 + 150, 1)], [round(x2 + 200, 1), round(y2 + 150, 1)]]})
    return strokes


# ------------------------------------------------------------------ 2. helpers: server, http, chrome
class Client:
    def __init__(self):
        self.jar = http.cookiejar.CookieJar()
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def call(self, method, path, body=None, timeout=120):
        req = urllib.request.Request(BASE + path, data=json.dumps(body).encode() if body is not None else None, method=method,
                                     headers={"content-type": "application/json"} if body is not None else {})
        try:
            with self.op.open(req, timeout=timeout) as r:
                return r.status, json.loads(r.read().decode() or "{}")
        except urllib.error.HTTPError as e:
            return e.code, json.loads(e.read().decode() or "{}")

    def cookie(self):
        return next(c.value for c in self.jar if c.name == "tc_session")


class CDP:
    def __init__(self, url):
        self.ws, self.n = connect(url, max_size=None), 0

    def send(self, method, **params):
        self.n += 1
        self.ws.send(json.dumps({"id": self.n, "method": method, "params": params}))
        while True:
            m = json.loads(self.ws.recv(timeout=120))
            if m.get("id") == self.n:
                if "error" in m:
                    raise RuntimeError(f"{method}: {m['error']}")
                return m.get("result", {})

    def ev(self, expr):
        r = self.send("Runtime.evaluate", expression=expr, returnByValue=True, awaitPromise=True)
        if r.get("exceptionDetails"):
            raise RuntimeError(r["exceptionDetails"].get("exception", {}).get("description", "script error")[:300])
        return r.get("result", {}).get("value")


SNAPSHOT_JS = """(async () => {
  const { Board } = await import('/js/board.js'); const { union } = await import('/js/geometry.js');
  const c = document.createElement('canvas'); c.width = 600; c.height = 400; document.body.append(c);
  const b = new Board(c); const items = JSON.parse(%s); b.items = items;
  let box = null; for (const it of items) box = union(box, b.boxOf(it));
  const url = b.snapshot(items, box); c.remove(); return url; })()"""


# ------------------------------------------------------------------ 3. judging
def norm(s):
    return (s or "").lower().replace("²", "^2").replace("³", "^3").replace("×", "x").replace("°", "deg").replace("π", "pi")


def squash(s):
    return re.sub(r"[\s^*·]", "", norm(s))


def judge(case, read, answer):
    text = norm(answer)
    if case.get("squash"):
        text = squash(answer)
    return all(re.search(p, text, re.S) for p in case["expect"])


def read_ok(case, read):
    wrote = squash(" ".join(case["lines"]))
    got = squash(read)
    return difflib.SequenceMatcher(None, wrote, got).ratio() >= 0.72


# ------------------------------------------------------------------ main
def main():
    from pymongo import MongoClient
    from backend.core.config import get_settings

    (OUT / "img").mkdir(parents=True, exist_ok=True)
    dbname = f"tc_hw_bench_{int(time.time())}"
    env = {**os.environ, "PORT": str(PORT), "MONGODB_DB": dbname, "ASK_RATE_PER_MIN": "500", "PYTHONIOENCODING": "utf-8"}
    server = subprocess.Popen([str(PY), "-m", "backend"], cwd=REPO, env=env, stdout=open(os.path.join(tempfile.gettempdir(), "hw_bench_server.log"), "w"), stderr=subprocess.STDOUT)
    prof = tempfile.mkdtemp(prefix="hw-bench-chrome-")
    chrome = subprocess.Popen([CHROME, "--headless=new", f"--remote-debugging-port={DBG}", f"--user-data-dir={prof}", "--window-size=1200,800", "--disable-gpu", "about:blank"],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    results = []
    try:
        for _ in range(60):
            try:
                urllib.request.urlopen(BASE + "/api/config", timeout=2)
                break
            except urllib.error.HTTPError:
                break
            except Exception:
                time.sleep(0.5)
        user = Client()
        user.call("POST", "/api/auth/register", {"name": "Benchmark", "email": "bench@example.com", "password": "password123"})
        page = None
        for _ in range(40):
            try:
                page = next(t for t in json.load(urllib.request.urlopen(f"http://localhost:{DBG}/json")) if t["type"] == "page")
                break
            except Exception:
                time.sleep(0.5)
        cdp = CDP(page["webSocketDebuggerUrl"])
        cdp.send("Page.enable")
        cdp.send("Page.navigate", url=BASE + "/login.html")
        time.sleep(2)

        for case in CASES:
            for variant in ("a", "b"):
                cid = f"{case['id']}{variant}"
                seed = sum(ord(ch) for ch in cid) * 7919
                strokes = to_strokes(draw_handwriting(case["lines"], variant, seed), seed)
                url = cdp.ev(SNAPSHOT_JS % json.dumps(json.dumps(strokes)))
                png = base64.b64decode(url.split(",", 1)[1])
                (OUT / "img" / f"{cid}.png").write_bytes(png)
                t0 = time.time()
                status, res = user.call("POST", "/api/ask", {"image": url, "typed": "", "canvas_id": f"hw-{cid}", "use_library": False})
                secs = round(time.time() - t0, 1)
                answer = " ".join(b.get("text", "") for b in res.get("blocks", []) if b.get("t") == "text")
                kinds = [b["t"] for b in res.get("blocks", [])]
                ok, rok = status == 200 and not res.get("violation") and judge(case, res.get("read", ""), answer), read_ok(case, res.get("read", ""))
                results.append(dict(id=cid, level=case["level"], wrote=" / ".join(case["lines"]), read=res.get("read", ""), conf=res.get("conf"), answer=answer, kinds=kinds,
                                    correct=ok, read_ok=rok, tokens=sum((res.get("tokens") or {}).values()), seconds=secs, flag=res.get("flag"), strokes=len(strokes),
                                    image=f"img/{cid}.png", status=status))
                print(f"{'PASS' if ok else 'FAIL'} {cid:4} {case['level']:6} wrote={' / '.join(case['lines'])[:34]!r:38} read={res.get('read','')[:34]!r:38} -> {answer[:50]!r}", flush=True)
    finally:
        chrome.terminate()
        server.terminate()
        time.sleep(1)
        shutil.rmtree(prof, ignore_errors=True)
        try:
            MongoClient(get_settings().mongo_uri).drop_database(dbname)
        except Exception as e:
            print("cleanup:", e)
    write_report(results)


def write_report(results):
    (OUT / "results.json").write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")
    levels = ["small", "medium", "hard"]
    lines = ["# Handwriting benchmark: evidence", "",
             "Each case is written as **pen strokes** (handwriting font, per-character tilt/size/baseline jitter, thinned to a centre line, wobbled), turned into the picture the AI receives by the app's own `Board.snapshot()` in Chrome, then sent through the real `POST /api/ask` (login, safety rules, prompt, AI model).", "",
             "* **Answer correct**: the answer contains the expected result (checked by a pattern, e.g. `x = 5`).",
             "* **Read OK**: what the AI says it read is at least 72% similar to what was written.", "",
             "Limits: the strokes are synthetic, so this measures reading messy, tilted, wobbly writing in two styles (print-like and cursive-like), not every real person's hand. Run it again with `python tools/handwriting_benchmark.py`.", "",
             "## Summary", "", "| Level | Answer correct | Read OK | Avg tokens | Avg seconds |", "|---|---|---|---|---|"]
    tot = ok = 0
    for lv in levels:
        rs = [r for r in results if r["level"] == lv]
        if not rs:
            continue
        tot += len(rs); ok += sum(r["correct"] for r in rs)
        lines.append(f"| {lv} | **{sum(r['correct'] for r in rs)}/{len(rs)}** | {sum(r['read_ok'] for r in rs)}/{len(rs)} | {round(sum(r['tokens'] for r in rs) / len(rs))} | {round(sum(r['seconds'] for r in rs) / len(rs), 1)} |")
    lines.append(f"| **all** | **{ok}/{tot}** | {sum(r['read_ok'] for r in results)}/{tot} | {round(sum(r['tokens'] for r in results) / tot)} | {round(sum(r['seconds'] for r in results) / tot, 1)} |")
    for lv in levels:
        rs = [r for r in results if r["level"] == lv]
        lines += ["", f"## {lv.capitalize()}", "", "| Picture sent to the AI | Written | AI read | AI answer | Result |", "|---|---|---|---|---|"]
        for r in rs:
            esc = lambda t: (t or "").replace("|", "\\|").replace("\n", " ")[:170]
            lines.append(f"| <img src=\"{r['image']}\" width=\"230\"> **{r['id']}** | {esc(r['wrote'])} | {esc(r['read'])} (conf {r['conf']}) | {esc(r['answer']) or '(' + ', '.join(r['kinds']) + ')'} | {'✅' if r['correct'] else '❌'} {r['tokens']} tok, {r['seconds']} s |")
    (OUT / "REPORT.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"\n{ok}/{tot} answers correct. Report: {OUT / 'REPORT.md'}")


if __name__ == "__main__":
    main()
