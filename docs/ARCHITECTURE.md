# Architecture

## The idea in one paragraph
You write, type or import something. The browser notices you paused, cuts out just that spot, and asks the
backend. The backend asks an AI for a small JSON description of the answer ("blocks": text, plot, chart,
flowchart, drawing, animation). The browser draws those blocks on the canvas. Nothing about *where* to draw
comes from the AI, so replies stay small and cheap.

```
 Browser (frontend/)                         Python backend (backend/)                      Outside
 ┌──────────────────────┐   JSON over HTTP   ┌─────────────────────────────────────────┐
 │ board.js  canvas     │ ─────────────────► │ api/routes   (HTTP only: parse, respond)│
 │ main.js   pause logic│                    │      │ Depends() wiring (api/deps.py)    │
 │ blocks.js draws AI   │ ◄───────────────── │      ▼                                  │   ┌──────────────┐
 │           blocks     │   blocks + tokens  │ services     (the rules)                │──►│ AI provider  │
 └──────────────────────┘                    │  assistant · auth · library · blocks    │   │ OpenRouter / │
                                             │      │             └─ llm/ (strategy)   │   │ OpenAI / ... │
                                             │      ▼                                  │   └──────────────┘
                                             │ repositories (only code touching Mongo) │   ┌──────────────┐
                                             │      ▼                                  │──►│   MongoDB    │
                                             │ db.py  connection + indexes             │   └──────────────┘
                                             │ core/  config · logging · errors ·      │
                                             │        security · ratelimit · middleware│
                                             └─────────────────────────────────────────┘
```

## Layers and the one rule
**A layer only calls the layer below it.** `routes -> services -> repositories -> MongoDB`.

| Layer | Knows about | Must not know about |
|---|---|---|
| `api/routes` | HTTP: status codes, cookies, request bodies | MongoDB queries, AI vendors |
| `services` | The rules: who may log in, how to build a prompt, what a valid block is | HTTP, cookies |
| `repositories` | MongoDB collections and queries | Business rules |
| `services/llm` | One vendor's API each | Everything else |
| `core` | Cross-cutting: settings, logs, errors, security | Features |

Why: any layer can be replaced or tested alone. The tests swap the AI for a fake and MongoDB for an in-memory
database without touching the code under test.

Plain CRUD (canvases, images, history) skips the service layer on purpose: a service that only forwards
calls adds files, not clarity. A service exists where there are rules (auth, library, assistant).

## Request flow: one answer
1. `main.js`: you lift the pen. The box around your new input is remembered; a 2.5 s timer starts (cancelled if you write again).
2. Timer fires. `board.js` draws only the touched strokes/images to a small PNG (max 768 px) and gathers typed text.
3. `POST /api/ask`. Middleware: request id, origin check, security headers. Route: login check (`current_user`), per-user rate limit.
4. `Assistant.answer`: textbook search if a library is on, build a short prompt, call the provider.
5. `blocks.sanitize`: the AI's JSON is validated and clamped. Anything malformed is dropped, never trusted.
6. History row saved, one `ask.done` log line written, JSON returned.
7. `board.addBlocks` lays out and draws the blocks; the canvas auto-saves to MongoDB.

## Data model (MongoDB)
| Collection | Holds | Notes |
|---|---|---|
| `users` | name, email (unique), organisation, scrypt password hash | |
| `sessions` | SHA-256 of the login token, user, expiry | TTL index: expired sessions delete themselves |
| `canvases` | user, title, `items[]` (strokes, text, images, AI blocks) | one document per canvas, loaded and saved whole |
| `assets` | imported images (binary, shrunk in the browser) | max 3 MB, private to the owner |
| `documents` + `chunks` | a book, and its ~800-character passages | `$text` index on `chunks.text` |
| `history` | what was asked/answered, tokens used | no handwriting or image data |

Every query includes `user_id`, so one user can never read another's data (tested).

## How it reads the canvas (compared with PenEcho)
PenEcho sends an image of the surrounding canvas plus coordinates, a trail of "hotspots" and a magnified
inset, and asks the model to return commands with global coordinates (`write_text x,y`, `draw`, `plot_function`,
`animate_scene`). We kept the good ideas and dropped the expensive ones:

| Idea | PenEcho | Here |
|---|---|---|
| Find the new writing | idle timer, changed box, hotspot trail | idle timer, box of new input |
| What the model sees | wide context image up to 2048x1536, plus inset | only the touched strokes, <= 768 px, no grid, no earlier answers |
| What the model returns | commands with global coordinates (about 4096 tokens allowed) | compact blocks with no page coordinates, capped at 700 tokens |
| Where answers go | model chooses x, y | the app: right of the writing, else below, else left; never over another answer |
| Graphs | `plot_function` evaluated in the browser | same idea; own safe parser, never `eval` |
| Diagrams | `draw` command | `flow` (automatic layout from nodes and arrows) and `draw` (shapes) |
| Animation | declarative `animate_scene` | declarative `anim`: circle, rect, line, text with orbit, spin, move, pulse |

## Keeping token use low
* Typed questions send **no picture**. Only text.
* Pictures are cropped to the new input and capped at 768 px; a small crop is a few hundred tokens.
* The prompt is assembled from parts: the animation spec (~170 tokens) is sent only for motion words or when a picture is attached.
* The reply is compact JSON, capped by `MAX_OUTPUT_TOKENS`. No page coordinates.
* RAG indexes with MongoDB `$text`: zero embedding calls. A question adds only the 3 best passages, trimmed to 520 characters.
* A handwritten question needs a second (text-only) call only if the AI asks for a textbook lookup.
* No conversation history is resent. Each request stands alone.
* Per-user rate limit (`ASK_RATE_PER_MIN`) caps the cost of a bug or a user.
* Every answer shows its token count; every call logs `tokens_in` and `tokens_out`.

## Design decisions and trade-offs
* **Modular monolith, not microservices.** One process, one database. Clear internal layers give the benefits
  that matter here (testability, replaceability) without the cost of running many services.
* **Strategy pattern for AI vendors.** `LLMProvider` is one small interface. OpenAI and OpenRouter share one class
  (same wire format). Adding a vendor is one class and one line in `registry.py`.
* **Dependency injection with FastAPI `Depends`.** Routes receive repositories and services; they never build them.
* **One error shape.** Services raise `AppError` subclasses; one handler returns `{"error": {"code", "message"}}`.
* **Retries only where they help.** 429/5xx/network errors retry twice with backoff; a rejected key does not.
* **MongoDB `$text` instead of vectors.** No embedding cost and no extra service. Weaker on paraphrased questions
  than vector search; the repository's `search` is the one place to change if that becomes a problem.
* **Whole-canvas documents.** Simple and fast for a canvas of thousands of strokes. A very large canvas (tens of MB)
  would need splitting into tiles; the 16 MB MongoDB document limit is the ceiling.
* **No eval anywhere.** Plot formulas go through a hand-written parser; AI blocks are data, validated twice (server and browser).

## Security
* Passwords: salted scrypt. Login: random token in an HttpOnly, SameSite=Lax cookie; only its hash is stored.
* Cross-site writes are rejected (Origin check) and SameSite blocks cookie use from other sites.
* Content-Security-Policy, `nosniff`, `frame-ancestors 'none'`.
* Login/register and AI calls are rate-limited. Uploads are type- and size-checked.
* The server binds to 127.0.0.1.
* Secrets and content are never logged (`core/logging.py` drops sensitive field names; emails are masked).

## Running more than one server
The pieces that live in process memory are the rate limiter and the login-attempt counters. With several
servers, move them to a shared store (Redis) and put a reverse proxy with HTTPS in front (then set cookies `Secure`).
Everything else is stateless: sessions, canvases and history are in MongoDB.

## Where to change things
| I want to... | Go to |
|---|---|
| Add an AI vendor | `backend/services/llm/` (new class) and `registry.py` |
| Add a block type (e.g. a table) | `services/blocks.py` (validate), `services/prompts.py` (tell the AI), `frontend/js/blocks.js` (draw) |
| Change what the AI is told | `backend/services/prompts.py` |
| Change how passages are found | `repositories/library.py` (`search`) |
| Add a setting | `core/config.py`, then `.env.example` |

## Voice features and token flow
Long-lived vendor keys (`ASSEMBLYAI_API_KEY`, `GEMINI_API_KEY`) stay on the server in `core/config.py` and are never sent to the browser or logged.

1. **Live Speech-to-Text (`frontend/js/stt.js`, `services/stt.py`, `api/routes/stt.py`)**
   - `POST /api/stt/token` (authenticated + rate-limited) mints a short-lived AssemblyAI v3 streaming token (`expires_in_seconds=300`) and returns `{token, ws_url, expires_in}`.
   - The browser captures 16 kHz mono PCM16 via `frontend/js/pcm-worklet.js` (`AudioWorklet`) and streams ~50 ms binary frames directly to `wss://streaming.assemblyai.com/v3/ws`.
   - `frontend/js/transcript.js` keeps finalized turns (`committedText`, keyed by `turn_order`) separate from the in-progress partial (`partialText`) so text never repeats and user edits are preserved. After `STT_AUTOSUBMIT_SILENCE_MS` (default 5000 ms) of silence, it submits through the standard `POST /api/ask` flow.
   - For languages outside the 6-language streaming tier, `MediaRecorder` records audio and uploads to `POST /api/stt/transcribe`, which uses AssemblyAI `/v2/upload` + `/v2/transcript` (`language_detection: true`).

2. **Live Session Voice Tutor (`frontend/js/live.js`, `services/live.py`, `api/routes/live.py`)**
   - `POST /api/live/token` (authenticated + rate-limited) mints a single-use Gemini ephemeral token via `POST /v1alpha/auth_tokens` with `liveConnectConstraints` locking the model (`GEMINI_LIVE_MODEL`), `LIVE_TUTOR_INSTRUCTION`, `AUDIO` response modality, `sessionResumption`, `contextWindowCompression`, `inputAudioTranscription`/`outputAudioTranscription`, and canvas tool declarations.
   - The browser connects directly to `BidiGenerateContentConstrained`, streams 16 kHz PCM16 audio, plays 24 kHz PCM responses through a gapless `AudioContext` queue (flushing immediately on `interrupted`), and transparently reconnects on `goAway` using `sessionResumptionUpdate` handles.
   - Tool calls (`draw_text_note`, `draw_plot`, `draw_chart`, `draw_flow`, `draw_geometry`, `clear_canvas_area`) are validated server-side via `POST /api/live/blocks` (reusing `services/blocks.py`), rendered via `board.addBlocks`, and acknowledged with `toolResponse`. Session transcripts and drawn block kinds are saved to `history` via `POST /api/live/history`.
