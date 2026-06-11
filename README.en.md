# sysmap-local

[中文](./README.md) · **English**

A **fully local** pipeline that turns "drive a browser to analyze a logged-in
system's architecture" into a queryable **knowledge graph**. No cloud
Claude/GPT required — it runs on a local model (GLM / Qwen on Ollama) with
almost no quality loss.

It produces 6 maps and fuses them into one queryable knowledge graph:
1. Feature map  2. Route map  3. API map  4. Permission map
5. Admin / management map  6. File-handling map

---

## Design: why local can still be 100%

**The graph structure (nodes + edges) is built deterministically by code — no
model in the loop.** A model is used only for two optional things: naming the
communities and summarizing a subgraph at query time.

```
your logged-in Chrome
       │ read-only CDP (browser-harness, local)
       ▼
[A] crawl.py ── pure code, no LLM ──►  <out>/raw/*.md   (6 human-readable maps)
       │                            +  graphify-out/graph.json (deterministic graph)
       │   1) parse every same-origin JS bundle: mine the SPA router table + /api endpoints (with method)
       │   2) GET-navigate each discovered route: capture runtime XHR/Fetch + 401/403 + DOM controls
       │   3) assemble routes/APIs/features/permissions/admin/files straight into graph.json
       ▼
[B] graphify cluster-only ──► community detection (deterministic) + naming (local model, optional) + report + HTML
```

**Key insight**: sysmap's six maps are already structured data, so the graph is
assembled by code — **there is no LLM extraction step**, hence no "model
compresses a long list" loss. This means:

- **Local graph = cloud graph**: structure comes from code, independent of which
  model you use. All 27 APIs and 11 routes are present; the model only affects how
  nice the community names read.
- **Deeper recon**: not just `<a>` links — it statically parses JS bundles to mine
  SPA routes and endpoints (login/upload/query/bugs/user-management…), and
  GET-drives each route to record real runtime 401/403 signals.
- **Reproducible / zero exfiltration**: deterministic script, no randomness; the
  logged-in system's data is processed only on your machine.

### What already exists
- `browser-harness` → reused as the read-only CDP recon driver. It is **already
  local** — nothing to replace.
- `graphify` (installed via `uv tool`) → **already ships an `ollama` backend**
  (plus openai/deepseek/gemini/claude-cli/azure/bedrock). Localizing is mostly
  "orchestration + configuration", not a rewrite.
- `sysmap_local.py` (added by this repo) = replaces the orchestration agent that
  was previously cloud Claude, with deterministic Python that chains A→B and
  defaults to local Ollama.

---

## Why graph construction dropped the LLM (benchmarked on a test range)

An early version used an LLM to "extract" the graph from the maps. A test-range
benchmark exposed how unreliable that is — **same maps, only the backend swapped**:

| Graph build | Nodes | Edges | Result |
|---|---|---|---|
| LLM extract · chat model glm-4.7-flash | 6 | **0** | ❌ collapses each file into a mega-node, loses all relations |
| LLM extract · code model qwen2.5-coder:7b | 11→7 | 16→6 | ⚠️ ok on small input, **compresses large input (27 APIs)** |
| LLM extract · cloud Claude | 12 | 17 | ✅ good, but still model-dependent and not local |
| **deterministic assembly (current)** | **61** | **93** | ✅ 1:1 with the maps — all 27 APIs / 11 routes present |

Takeaway: the maps are already structured data; asking a model to "extract" them
only adds compression/hallucination/randomness. Now `crawl.py` **assembles
graph.json directly**, so graph structure no longer depends on a model — local and
cloud produce identical output. The model (default `qwen2.5-coder:7b`) is only used
for **community naming** and **query synthesis**; with it offline you still get the
full graph (communities fall back to `Community N`).

---

## Dependencies

| Component | Role | Required? |
|---|---|---|
| [`browser-harness`](https://github.com/browser-use/browser-harness) | Read-only CDP control of your logged-in Chrome | **required** |
| `graphify` + the `[ollama]` extra | Clustering / report / HTML / query (the graph itself is built by crawl.py) | **required** |
| `ollama` + a local model | **Community naming + query synthesis only** (graph structure does not depend on it) | optional |

> Nodes and edges are generated deterministically, so **you get the full graph
> even with Ollama offline** (community names fall back to `Community N`). For
> naming/synthesis, the default model is `qwen2.5-coder:7b`.

---

## Installation

```bash
# 1) Clone this repo
git clone https://github.com/1lkla/sysmap.git
cd sysmap

# 2) Install graphify WITH the [ollama] extra (else the ollama backend errors: missing openai)
uv tool install "graphifyy[ollama]"   # recommended; or: pip install "graphifyy[ollama]"

# 3) Install browser-harness (read-only CDP control of your logged-in Chrome)
#    https://github.com/browser-use/browser-harness (see its install.md)
#    Confirm it's on $PATH:
which browser-harness

# 4) Install Ollama + pull the default code/extraction model
brew install ollama                 # or install Ollama.app
ollama serve &
ollama pull qwen2.5-coder:7b       # default model (code/structured extraction; ~matches cloud Claude)

# 5) Sanity check: confirm all three are ready
which graphify browser-harness ollama
```

No extra Python dependencies — the orchestrator uses only the standard library
(`urllib` / `subprocess` / `argparse`). Python 3.9+ is enough.

---

## Usage

```bash
# 0) Make sure Ollama is up (Ollama.app, or:)
ollama serve &

# 1) Log into the target system in your own Chrome; stop on a content page

# 2) Build the graph (read-only recon → local graph build)
python3 sysmap_local.py build https://your-app/dashboard --max 60
#   or: ./run.sh build https://your-app/dashboard --max 60

# 3) Ask the graph (pure graph retrieval)
python3 sysmap_local.py query "Which routes call file-handling APIs?"

# 3b) Let the local model summarize the retrieved subgraph into an answer
python3 sysmap_local.py query "Which admin features are admin-only?" --synthesize
```

Build artifacts land in `./sysmap-out/raw/graphify-out/`:
- `graph.html` — interactive knowledge graph, open in a browser
- `GRAPH_REPORT.md` — audit report: God Nodes / cross-community links / suggested questions
- `graph.json` — raw graph data, GraphRAG-ready
- `../network.jsonl` — raw network capture (reference)

### Common flags
- `--max N` route crawl cap (default 40)
- `--out DIR` output directory (default `./sysmap-out`)
- `--backend NAME` switch graphify backend: `ollama` (default) / `openai` / `deepseek` / `gemini` / `claude-cli`
- `--model NAME` local model name (default `qwen2.5-coder:7b`)
- `--ollama-base URL` override `OLLAMA_BASE_URL` (e.g. point at LM Studio's OpenAI-compatible port)

### Using LM Studio instead of Ollama
LM Studio exposes an OpenAI-compatible endpoint (default `http://localhost:1234/v1`). Two ways:
```bash
# Keep the ollama backend, just point base_url at it (simplest)
python3 sysmap_local.py build <url> --ollama-base http://localhost:1234/v1 --model <lmstudio-model>
# Or use the openai backend
OPENAI_BASE_URL=http://localhost:1234/v1 OPENAI_API_KEY=lm-studio \
  python3 sysmap_local.py build <url> --backend openai --model <lmstudio-model>
```

---

## Safety
- Recon is **read-only**: GET navigations + DOM reads only; it never clicks
  state-changing controls (delete / submit / save).
- Run it only against systems you **own or are authorized** to assess.
- If it hits a login wall it stops and tells you — it **never** enters credentials.

---

## Files
- `crawl.py` — read-only recon (emits the 6 maps as explicit-relationship markdown)
- `sysmap_local.py` — deterministic orchestrator (replaces the cloud agent)
- `run.sh` — convenience entrypoint
