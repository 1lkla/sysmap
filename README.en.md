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

The pipeline splits into two stages, and **only part of the second stage uses a model**:

```
your logged-in Chrome
       │ read-only CDP (browser-harness, local)
       ▼
[A] crawl.py ── pure code, no LLM ──► <out>/raw/*.md
       │   BFS over same-origin routes + capture XHR/Fetch via CDP + read DOM controls
       │   writes the relationships as explicit sentences:
       │     "Route /x calls API GET /y"
       │     "Feature \"Export\" is available on route /x"
       │     "Route /x was denied access to API ... (permission restriction)"
       ▼
[B] graphify ── local LLM backend (ollama) ──► graph.json + graph.html + GRAPH_REPORT.md
       ├─ extract:      AST (deterministic) + semantic edge-filling/dedup (local model)
       └─ cluster-only: community detection (deterministic) + naming (local model) + report/HTML
```

**Key insight**: the hardest, most quality-critical part — reconnaissance (A) —
is deterministic code with zero model involvement; the relationships for all 6
maps are already written out as explicit English sentences. What's left for the
model (B) is just "connect already-explicit relationships into a graph, name the
communities, and summarize a subgraph at query time" — tasks a 7B–30B local
model handles reliably. Therefore:

- **Local ≠ downgraded**: the graph's skeleton comes from code, not the model.
- **Reproducible**: the orchestration is a deterministic script, with none of a
  cloud agent's randomness.
- **Zero data exfiltration**: the logged-in system's DOM / network traffic is
  processed only on your machine.

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

## Model choice matters (benchmarked on a test range)

On an authorized test range, with the **same crawl, same graphify, same
extraction prompt — only the backend swapped**:

| Backend (graph-build model) | Nodes | Edges | Graph usable? |
|---|---|---|---|
| general chat model glm-4.7-flash | 6 | **0** | ❌ collapses each file into one mega-node, loses all relations |
| **code model qwen2.5-coder:7b** (default) | 11 | **16** | ✅ properly atomized, accurate edges, ~on par with cloud |
| cloud Claude (claude-cli backend) | 12 | 17 | ✅ slightly richer (more INFERRED edges + audit metadata) |

Takeaway: **the recon stage is model-free and lossless; graph quality depends on
the extraction model.** A code/structured model (qwen2.5-coder class) pulls the
relationship edges out correctly and gets local close to cloud Claude; a general
chat/reasoning model (glm-4.x-flash class) drops every edge and the graph is
unusable. Hence the default is `qwen2.5-coder:7b`. For more power, `--backend
openai` to a larger model, or `--backend claude-cli` to use cloud Claude directly.

---

## Dependencies

| Component | Role |
|---|---|
| [`browser-harness`](https://github.com/browser-use/browser-harness) | Read-only CDP control of your logged-in Chrome |
| `graphify` + the `[ollama]` extra | Build / cluster / query; the extra ships the openai client (**required** for the ollama backend) |
| `ollama` + a **code/extraction model** | Semantic edge-filling / community naming / query synthesis |

> ⚠️ **Model choice is critical** (see above). Default is `qwen2.5-coder:7b`.
> Do **not** use a general chat/reasoning model (e.g. glm-4.x-flash) for
> extraction — benchmarks show it drops all relationship edges.

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
