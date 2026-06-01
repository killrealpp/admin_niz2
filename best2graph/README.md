# best2graph

Graphify workspace for the `best2` code map.

This folder is a developer tool, not the project knowledge base:

- `best2obs/` remains the long-term project memory and should not be replaced by Graphify.
- `best2info/` remains the client-facing knowledge base for Telegram answers.
- `best2graph/graphify-out/` stores the generated code graph.

## Files

- `.venv/` - isolated Python environment with `graphifyy`.
- `graphify-out/graph.json` - machine-readable graph.
- `graphify-out/GRAPH_REPORT.md` - generated graph report.
- `graphify-out/graph.html` - interactive graph view.
- `graphify-out/GRAPH_TREE.html` - collapsible file/symbol tree.
- `update_graph.ps1` - rebuilds the graph safely.

## Update

From the project root:

```powershell
.\best2graph\update_graph.ps1
```

The script reads `OPENROUTER_API_KEY`, `OPENROUTER_BASE_URL` and `OPENAI_MODEL`
from the root `.env`, passes them only to the Graphify process, and does not
print secrets.

The scan excludes:

- `.env`
- `.venv/`
- `best2graph/`
- `best2obs/`
- `logs/`
- `*.log`
- `__pycache__/`

## Query Examples

```powershell
.\best2graph\.venv\Scripts\graphify.exe query "Where is availability checked?" --graph .\best2graph\graphify-out\graph.json --budget 1200
.\best2graph\.venv\Scripts\graphify.exe explain "payment_service.py" --graph .\best2graph\graphify-out\graph.json
.\best2graph\.venv\Scripts\graphify.exe path "message_handler.py" "payment_service.py" --graph .\best2graph\graphify-out\graph.json
```

Do not run `graphify codex install` unless you intentionally want Graphify to
edit the root `AGENTS.md`.
