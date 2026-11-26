# Think Canvas

Write, type or import a picture on a grid canvas. When you pause, Think Canvas finds what you just added,
reads it with an AI, and puts the answer on the canvas next to it: text, a plotted graph, a chart,
a flowchart, a shape drawing, or an animation. Answers can come from your own textbooks (RAG).
Each person has their own account; canvases, images, books and history are saved in MongoDB.

Backend: Python + FastAPI. Frontend: plain JavaScript (no build step). Database: MongoDB.

## Run
```
cd d:\think-canvas
# 1. MongoDB (skip if you already run one; set MONGODB_URI in .env if it is not on port 27017)
docker run -d --name think-canvas-mongo -p 27017:27017 mongo:8

# 2. Python packages (once)
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt

# 3. start
.venv\Scripts\python -m backend         # open http://localhost:3888, create an account
```
Put your AI key in `.env` (see "Keys"). The server listens on 127.0.0.1 only.

## Using it
| Do this | What happens |
|---|---|
| Write with **Pen**, then pause | A dashed box marks what was just written; after 2.5 s the AI answers beside it. `2+2=` gets `4` |
| **Type** tool: click the canvas, type, Enter | Same, but only text is sent (no picture), so it is the cheapest way to ask |
| **Image** (or paste / drop a picture) | The AI explains the picture |
| Ask for a visual: "plot sin x and x^2", "bar chart of 3, 5, 9", "flowchart of login", "draw a right triangle", "animate the earth orbiting the sun" | The answer is drawn on the canvas |
| **Library** | Add textbooks / PDFs. Questions are answered from them, with page numbers |
| **Find my work** (or `Home`) | Jumps to your latest writing; press again for the next spot. A "Back to your work" button appears when you scroll away from everything |
| **History** | Everything you asked, with answers and token counts |
| **Mic** (Speech-to-Text) | Speak your question live (AssemblyAI); auto-sends after 5 s of silence onto the canvas |
| **Live Session** | Real-time voice tutor (Gemini Live) that answers in audio and draws visuals on the canvas |
| **Eraser** removes what it touches. **Move** (or hold Space, or scroll) pans. `Ctrl+Z` undoes | |

## Keys: the `.env` file
`LLM_PROVIDER` chooses the way to reach the AI. This project is set to **openrouter**:

| LLM_PROVIDER | Fill in |
|---|---|
| `openrouter` | `OPEN_ROUTER_API_KEY`, `OPEN_ROUTER_MODEL` (for example `openai/gpt-4o`) |
| `openai` | `OPENAI_API_KEY`, `OPENAI_MODEL`. A custom `OPENAI_BASE_URL` (Ollama, LM Studio) needs no key |
| `anthropic` | `ANTHROPIC_API_KEY`, `ANTHROPIC_MODEL` |
| `claude-cli`, `codex-cli` | nothing: log in to the `claude` / `codex` command first |

Optional voice keys:
- `ASSEMBLYAI_API_KEY`: enables **Mic** (live speech-to-text via AssemblyAI Universal-Streaming v3, plus pre-recorded fallback). Streaming supports Auto-detect across **English, Spanish, French, German, Italian, and Portuguese** (`universal-streaming-multilingual`); all other languages (Hindi, Arabic, Japanese, Korean, Mandarin, Russian, etc., up to 99 languages) automatically use the pre-recorded `/api/stt/transcribe` fallback with `language_detection`.
- `GEMINI_API_KEY` and `GEMINI_LIVE_MODEL`: enables **Live Session** voice tutor (Gemini Live API native audio + canvas tool calling).

Restart after editing `.env`. `.env` is git-ignored.

## Logs
Console and `logs/think-canvas.log` (rotated, 2 MB x 3). One line per event, with a request id:
```
13:43:40 INFO  tc.ask  [601dbfe3] ask.done user=6b03.. provider=openrouter model=openai/gpt-4o calls=1 tokens_in=609 tokens_out=48 blocks=plot ms=2908
13:43:40 INFO  tc.http [601dbfe3] http method=POST path=/api/ask status=200 ms=2926
```
Question text, handwriting, images, passwords and keys are never written to the logs. Emails are masked.

## Tests
```
.venv\Scripts\python -m pytest tests/backend     # backend (uses an in-memory database)
npm test                                         # browser logic (formula parser, flowchart layout...)
```
The RAG search test needs a real MongoDB: `set TEST_MONGODB_URI=mongodb://localhost:27017` first (it is skipped otherwise).

## Folder map
```
.env / .env.example      keys and settings
requirements.txt         Python packages
backend/
  main.py                builds the FastAPI app            <- start here
  api/                   HTTP layer: routes/, deps.py (wiring), schemas.py (request bodies)
  services/              the rules: assistant.py (one AI answer), auth_service.py, library_service.py,
                         blocks.py (checks the AI's JSON), prompts.py, rag.py (PDF -> passages)
    llm/                 AI providers: openai_compat.py (OpenAI + OpenRouter), anthropic.py, cli.py, registry.py
  repositories/          the only code that queries MongoDB
  core/                  settings, logging, errors, security, rate limits, middleware
  db.py                  MongoDB connection and indexes
frontend/
  index.html, login.html pages
  js/main.js             page logic: pause detection, asking, saving
  js/board.js            the canvas: grid, pen, eraser, text, images, pan, find-my-work
  js/blocks.js           draws plots, charts, flowcharts, shapes, animations
  js/mathexpr.js, flow.js, geometry.js    pure logic (unit-tested)
  js/api.js, auth.js, dialogs.js, sidebar.js, imaging.js
tests/                   backend/ (pytest) and frontend/ (node)
docs/ARCHITECTURE.md     design and the reasons behind it
logs/                    log files (created on first run)
```
See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for how the pieces fit together.
