# AtlaZ

**Brownfield Intelligence — turning a legacy codebase into an evidence-cited knowledge graph.**

AtlaZ ingests an arbitrary repository and reverse-engineers what it can honestly answer about
the product: its business rules, capabilities, technical architecture, data model, API surface,
security controls, and functional behavior — all grounded in code, never invented. Every fact is
tagged with a confidence tier (`extractable` / `inferable` / `external_only`) and carries evidence
back to a file, line, and commit. Where the codebase genuinely can't answer a question — market
strategy, pricing rationale, why the product exists — AtlaZ says so explicitly instead of guessing.

This implements the AtlaZ HLD v2 / LLD v2 design (see `docs/` if present, or the original design
documents) — a 9-agent extraction pipeline across four domains, a single consolidated
human-in-the-loop review gate, a Neo4j knowledge graph, and a 5-mode reasoning layer for Q&A,
enhancement guidance, modernization planning, drift detection, and product-understanding synthesis.

## Architecture at a glance

```
repo path
   │
   ▼
Ingestion ──▶ Language Detection + Parser Registry (native AST / tree-sitter / heuristic fallback)
   │
   ▼
LangGraph orchestrator
   ├─ Domain C  FRD Extraction (function signatures + test assertions)
   ├─ Domain D  HLD Builder, LLD Parser, Data Model Extractor, API Contract Parser, Security Scanner
   ├─ Domain B  Capability Clustering, Business Rule Extraction, Domain Glossary
   ├─ Domain A  Business Case Gap Detector (structurally cannot fabricate a conclusion)
   └─ collect ──▶ [flagged items?] ──▶ HITL gate (Streamlit, or auto-resolve if disabled)
                                            │
                                            ▼
                                   Neo4j knowledge graph
                                            │
                                            ▼
                              Reasoning Agent (Q&A / enhancement /
                              modernization / drift / product synthesis)
```

Domain D is built in full depth (it's the highest-confidence tier and everything else is checked
against it); Domains A, B, and C each ship the agent(s) with the strongest evidence trail.
Domain E (infra/ops) is out of scope for this build — see the roadmap in the design docs.

## Project layout

```
src/atlaz/
  shared/          Tier, Evidence, PipelineConfig — used by every layer
  llm/             Pluggable LLMClient (mock / anthropic / openai / any OpenAI-compatible endpoint)
  ingestion/       RepoIngestor — file walk, language tagging, manifest/config/readme detection
  parsing/         LanguageDetector, ParserRegistry, 3-tier AST parsing (native/tree-sitter/heuristic)
  agents/
    domain_a/      Business Case Gap Detector
    domain_b/      Capability Clustering, Business Rule Extraction, Domain Glossary
    domain_c/      FRD Extraction
    domain_d/      HLD Builder, LLD Parser, Data Model Extractor, API Contract Parser, Security Scanner
  hitl/            ReviewGate, auto-resolve policy, conflict detection, Streamlit review app
  graph_store/     Neo4j schema, GraphNode/GraphEdge translation, Neo4jWriter
  orchestration/   LangGraph state graph, node wiring, checkpoint serialization allowlist
  reasoning/       ReasoningAgent (5 modes), read-only Cypher safety guard
  cli.py           `atlaz run|resume|review|ask`
tests/
  unit/            Mirrors src/, no external services required (MockLLMClient, injected fakes)
  integration/     Runs against a real Neo4j (auto-skips if unreachable); self-cleaning
```

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # defaults to LLM_PROVIDER=mock, HITL_ENABLED=true

docker compose up -d   # starts Neo4j on bolt://localhost:7687 (neo4j/password)

pytest                 # unit tests always run; integration tests auto-skip without Neo4j

atlaz run .             # extract knowledge from this repo (or point at any other repo path)
```

If `HITL_ENABLED=true` and something gets flagged (a low-confidence finding, a rule/entity
conflict, or the Domain A gap that's flagged on every run), `atlaz run` pauses and prints a
`thread_id`. Review it with:

```bash
atlaz review <thread_id>     # opens the Streamlit review UI
# or, to skip a human reviewer and apply the documented auto-resolve policy:
atlaz resume <thread_id>
```

Once the graph is populated:

```bash
atlaz ask "What does this product do?" --mode product_synthesis
atlaz ask "Where does intent diverge from implementation?" --mode drift
```

## Configuration

All runtime behavior is environment-driven (`.env`, see `.env.example`):

| Variable | Purpose |
|---|---|
| `HITL_ENABLED` | `true` pauses at the review gate; `false` applies the auto-resolve policy inline |
| `CONFIDENCE_THRESHOLD` | Findings below this confidence are flagged for review |
| `LLM_PROVIDER` | `mock` \| `anthropic` \| `openai` \| `custom` (any OpenAI-compatible endpoint via `LLM_BASE_URL`) |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Provider credentials/endpoint — never touch agent code |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Knowledge graph connection |
| `CHECKPOINT_DB_PATH` | SQLite file LangGraph uses to persist paused runs across process boundaries |

Swapping the LLM provider or turning HITL on/off never requires a code change — only `.env`.

## Design notes and deliberate deviations from the LLD

A few implementation choices diverge from the letter of the design documents; each is called out
in a docstring at the point of the decision, and summarized here:

- **JS/TS parsing uses tree-sitter, not Babel** (`parsing/parsers/tree_sitter_ast.py`) — avoids a
  Node.js toolchain dependency in an otherwise Python-only pipeline. Tagged `GRAMMAR_AST`, one
  tier below native AST, so the confidence-tiering discipline stays honest about the trade-off.
- **Evidence is stored as a JSON property on each finding's own node**, not as separate `Evidence`
  graph nodes (`graph_store/graph_builder.py`) — every fact is exactly as traceable, without one
  extra node per citation for high-volume corners like business rules and glossary terms.
- **Node execution order is dependency-respecting, not a literal parallel fan-out**
  (`orchestration/nodes.py`) — Domain A's naming-pattern signal needs Domain B's glossary, which
  needs Domain D's data entities; the LLD's own build-sequencing table already implies this chain.

## Known limitations

- Capability naming, architecture-style inference, and narrative synthesis are only as good as the
  configured LLM provider — `LLM_PROVIDER=mock` (the default) produces structurally valid but
  placeholder text, by design, so the pipeline is fully testable without API credentials.
- BRD extraction (Domain B) and PRD inference (Domain C) are architecture-only, not built —
  a question that touches either surfaces as an explicit gap, never a guess.
- Domain E (infrastructure, ops, test coverage, release history) is fully descoped.
