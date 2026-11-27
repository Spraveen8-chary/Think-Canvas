# Think Canvas — UML Diagrams

All diagrams are strict UML 2.x monochrome (`#FFFFFF` / `#F5F5F5`, `#000000` 1px borders, Arial 12px/14px, zero shadows), traced directly to the source code in `backend/` and `frontend/`.

## Files
1. [01_use_case.drawio](01_use_case.drawio) — Use Case Diagram (`User`, `LLM Provider`, `MongoDB`)
2. [02_class_diagram.drawio](02_class_diagram.drawio) — Class Diagram (`Assistant`, `Answer`, `AuthService`, `LibraryService`, `LLMProvider`, `OpenAICompatible`, `AnthropicProvider`, `CliProvider`, `LLMReply`, `UserRepository`, `LibraryRepository`, `CanvasRepository`, `HistoryRepository`, `AssetRepository`, `Board`, `RateLimiter`)
3. [03a_seq_ask_flow.drawio](03a_seq_ask_flow.drawio) — Sequence Diagram: Pause Detection -> `/api/ask` -> `Assistant.answer()` -> Two-pass RAG Lookup -> `blocks.sanitize()` -> `HistoryRepository` -> `Board.addBlocks()`
4. [03b_seq_auth_flow.drawio](03b_seq_auth_flow.drawio) — Sequence Diagram: `/api/auth/login` -> `AuthService` -> `security.py` -> `UserRepository` -> `tc_session` Cookie
5. [03c_seq_library_rag_flow.drawio](03c_seq_library_rag_flow.drawio) — Sequence Diagram: `/api/documents` -> `LibraryService.ingest()` -> `rag.extract_pages()` / `chunk_pages()` -> `LibraryRepository.add()`
6. [04_activity_ask_workflow.drawio](04_activity_ask_workflow.drawio) — Activity Diagram: Canvas Input to AI Answer Rendering (with decision diamonds and fork/join bars)
7. [05_state_machine_canvas.drawio](05_state_machine_canvas.drawio) — State Machine Diagram: Canvas Input & AI Request Lifecycle (`Locked`, `Idle`, `Drawing / Typing`, `WaitingForPause`, `AskingAI`, `Error`)
8. [06_component_diagram.drawio](06_component_diagram.drawio) — Component Diagram (Frontend ES modules, Backend FastAPI layers, External MongoDB & AI Providers)
9. [07_deployment_diagram.drawio](07_deployment_diagram.drawio) — Deployment Diagram (`Client Workstation`, `Local Application Host 127.0.0.1` with Uvicorn `:3888` & Docker MongoDB `:27017`, `Cloud AI Provider Endpoints`)
10. [08_er_diagram.drawio](08_er_diagram.drawio) — ER Diagram (`users`, `sessions`, `canvases`, `assets`, `history`, `documents`, `chunks`)

## Exporting to PNG (2x) and SVG
1. Open any `.drawio` file in **draw.io Desktop** or **https://app.diagrams.net**.
2. To export **PNG (2x)**: `File -> Export as -> PNG...` -> set **Zoom** to `200%` -> **Export**.
3. To export **SVG**: `File -> Export as -> SVG...` -> **Export**.
