# AtlaZ

**Brownfield Intelligence — turning a legacy codebase into an evidence-cited knowledge graph.**

AtlaZ ingests an arbitrary repository and reverse-engineers what it can honestly answer about
the product: its business rules, capabilities, technical architecture, data model, API surface,
security controls, and functional behavior — all grounded in code, never invented. Every fact is
tagged with a confidence tier (`extractable` / `inferable` / `external_only`) and carries evidence
back to a file, line, and commit. Where the codebase genuinely can't answer a question — market
strategy, pricing rationale, why the product exists — AtlaZ says so explicitly instead of guessing.

This implements the AtlaZ LLD (`~/Downloads/AtlaZ_LLD.md`) — a full N1-N21 LangGraph pipeline: a
deterministic ingestion/analysis stage (symbol table, call graph, data flow, config/schema/API),
a runtime-enforced capability registry, five domain subgraphs fanned out in parallel, cross-domain
conflict detection, domain-aware confidence scoring, an auto-resolve dispute policy, a
technical+business+bridge Neo4j knowledge graph, a Qdrant vector index, and a Postgres evidence
store. A two-screen Streamlit app (`atlaz app`) is the easiest way to use it end to end — ingest a
repo (local path or git URL), then ask questions and generate/download an HLD and LLD, no
configuration exposed anywhere in the UI. A FastAPI + Celery layer and a plain CLI cover
programmatic/background use of the same pipeline; a Postgres audit trail records every run's
lifecycle and every human review decision.

## Architecture at a glance

```
repo path ──▶ N1 ingest_repo (RepoIngestor + file_classification)
                    │
                    ▼
         N2 incremental? ──delta──▶ N3D fan_out_changed_files ─┐
                    │full                                       │
                    ▼                                          ▼
         N3 fan_out_files ──Send() per file──▶ N4 parse_ast (parallel)
                    │
                    ▼
         N5 build_symbol_table (fan-in)
              ├─ N6 build_call_graph ─────┐
              ├─ N7 analyze_data_flow ────┼─▶ N9 merge_dependency_graph
              └─ N8 analyze_config_schema_api ┘
                    │
                    ▼
         N10 check_capability_registry (validated against capability_registry.yaml)
                    │
                    ▼
         N10ORCH domain_orchestrator ──Send()──▶ domain_a / domain_b / domain_c / domain_d (parallel)
                    │                                    │
                    └──────────────▶ workflow_trace (B + D) ──▶ collect_domain_outputs
                                                                       │
                                          three-tier HITL gate (gap / low-confidence) ─┐
                                                                       │◀───────────────┘
                                                                       ▼
                                          N11X detect_cross_domain_conflicts
                                                                       │
                                          N12 consolidate_business_rules
                                                                       │
                                          N13 score_confidence (domain-aware weight profiles)
                                                                       │
                                    N14 dispute? ──yes──▶ N16 auto_resolve_dispute ─┐
                                          │no                                        │
                                          └──────────────▶ N15 accept_resolved ◀────┘
                                                                       │
                              N17 write_knowledge_graph ──▶ N18 write_vector_index (Qdrant)
                                                                       │
                                                        N19 write_evidence_store (Postgres)
                                                                       │
                                                   N20 more files pending? ──▶ N21 ready_for_query
```

Domain D (HLD/LLD/data model/API contracts/security) is built in full depth — it's the
highest-confidence tier (`deterministic_adjacent`, 0.85 floor) everything else is checked against.
Domain A is capped at 0.6 confidence by design (`signal_density`) — never high-confidence, always
advisory. Domain E (infra/ops) is architecturally represented but never executed — every one of
its agents is `false` in `capability_registry.yaml`, enforced at graph-compile time.

## Project layout

```
capability_registry.yaml   Which agents are implemented, checked at graph-compile time (LLD §6.1)
src/atlaz/
  shared/          Tier, Evidence, PipelineConfig (+ Neo4j/Qdrant/Celery/API/DB sub-configs)
  llm/             Pluggable LLMClient (mock / anthropic / openai / azure / any OpenAI-compatible endpoint)
  ingestion/       RepoIngestor — file walk, language tagging, manifest/config/readme detection
  parsing/         LanguageDetector, ParserRegistry, 3-tier AST parsing (native/tree-sitter/heuristic)
  analysis/        Deterministic stage (N4-N9): symbol_table, call_graph, data_flow,
                   config_schema_api, dependency_graph, file_classification
  agents/
    domain_a/      readme_commit_signal_miner, gap_detector (business case — cannot fabricate)
    domain_b/      Capability Clustering, Business Rule Extraction, Domain Glossary
    domain_c/      FRD Extraction
    domain_d/      HLD Builder, LLD Parser, Data Model Extractor, API Contract Parser, Security Scanner
    domain_e/      Descoped placeholder — every agent `false` in the capability registry
    cross_domain/  workflow_trace — walks the call graph seeded by Domain B + Domain D
  orchestration/   LangGraph state graph (graph.py), node wiring (nodes.py), capability_registry
                   loader/validator, confidence scoring, cross-domain conflict detection, dispute
                   resolution, checkpoint serialization allowlist, runner
  hitl/            Two-tier review gate (gap confirmation / low-confidence finding): ReviewGate,
                   auto-resolve policy, natural-key matching -- no UI of its own; the Streamlit
                   app always runs this auto-resolved (see `webapp/`)
  graph_store/     Neo4j schema (technical + business + bridge), GraphNode/GraphEdge translation,
                   Neo4jWriter
  vector_store/    Qdrant vector index (candidate retrieval only — every hit resolves to a real
                   Neo4j node before being trusted)
  reasoning/       ReasoningAgent (5 modes), read-only Cypher safety guard
  audit/           Postgres evidence store + audit trail: SQLAlchemy models, engine/session,
                   repository functions
  enhancement/     Retrieval + code-modification flow (impact analysis, guideline RAG, modifier) —
                   runs on-demand against an already-ingested run's graph; CLI-only, not in the app
  docgen/          HLD/LLD document generation (graph_facts, hld_generator, lld_generator,
                   output_writer, service) — also on-demand, also read-only against the graph
  webapp/          The Streamlit app: two pages, `ingest.py` and `retrieve.py`, wired together by
                   `main.py`. No configuration exposed -- everything comes from `.env`.
  worker/          Celery app + the ingestion task
  api/             FastAPI app: /ingest, /runs/{id}, /runs/{id}/resolve, /runs/{id}/documents
  cli.py           `atlaz app|run|resume|ask|enhance|document|db init`
alembic/           Audit/evidence-store database migrations (`alembic upgrade head`, or `atlaz db init`)
scripts/
  migrate_db.py    Standalone runner for `atlaz.audit.migrate.migrate()` -- no CLI/install required
tests/
  unit/            Mirrors src/, no external services required (MockLLMClient, injected fakes)
  integration/     Runs against real Neo4j/Postgres (auto-skips if unreachable); self-cleaning
```

## Quickstart

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

cp .env.example .env   # defaults to LLM_PROVIDER=mock, HITL_ENABLED=true

docker compose up -d   # starts Neo4j (bolt://localhost:7687, neo4j/password), Qdrant
                        # (http://localhost:6333), and Redis
                        # Postgres is NOT included here -- point DATABASE_URL/ADMIN_DATABASE_URL
                        # in .env at any reachable Postgres 14+; add your own docker service
                        # (postgres:16-alpine, POSTGRES_PASSWORD=postgres) if you don't have one

atlaz db init           # creates the `atlaz` database + `atlaz` schema + audit tables (idempotent)
# or, equivalently, without going through the CLI:
#   python scripts/migrate_db.py

pytest                  # unit tests always run; integration tests auto-skip without Neo4j/Postgres
```

### Option A — the Streamlit app (recommended)

```bash
atlaz app
```

Two screens, nothing to configure in the UI (LLM provider, Neo4j/Qdrant/Postgres connection, and
confidence threshold all come from `.env`, silently):

- **Ingest** — paste a local repo path or a git URL (cloned into `.atlaz/workspaces/`) and click
  *Start ingestion*. Runs the full pipeline in-process (no Celery/API needed); any low-confidence
  finding is auto-resolved and written to the graph, correctly flagged -- there's no separate
  review screen to hand off to.
- **Retrieve & Document** — pick an ingested project from a dropdown (no thread_id to copy-paste),
  ask it questions, and generate + download its HLD and LLD as markdown.

### Option B — CLI (synchronous, no API/Celery needed)

```bash
atlaz run .              # extract knowledge from this repo (or point at any other repo path)
atlaz resume <thread_id> # if HITL_ENABLED=true and something was flagged, auto-resolve and finish
atlaz ask "What does this product do?" --mode product_synthesis
atlaz ask "Where does intent diverge from implementation?" --mode drift
atlaz document <thread_id> <project_id>     # -> outputs/<project_id>/docs/<timestamp>/{HLD,LLD}.md
atlaz enhance <thread_id> "<change request>" --save
```

### Option C — API + Celery worker (background jobs, for programmatic/production use)

```bash
# terminal 1
celery -A atlaz.worker.celery_app.celery_app worker --loglevel=info

# terminal 2
uvicorn atlaz.api.main:app --host 0.0.0.0 --port 8000

# terminal 3
curl -X POST http://localhost:8000/ingest -d '{"repo_path": "/path/to/repo"}'
curl http://localhost:8000/runs/<thread_id>                                            # check status
curl -X POST http://localhost:8000/runs/<thread_id>/resolve -d '{"resolutions": []}'    # auto-resolve the rest
curl -X POST http://localhost:8000/runs/<thread_id>/documents -d '{"project_id": "my-project"}'
```

All three options pause the same way if `HITL_ENABLED=true` and something gets flagged (a
low-confidence finding, or the Domain A gap that's flagged on every run): the run reports a
`thread_id` and stops short of writing to the graph until it's resolved (`atlaz resume`, or
`POST /runs/{id}/resolve`). The Streamlit app always runs with HITL auto-resolved regardless of
`.env`, since it has no review screen -- see "Design notes" below.

### Generating an HLD/LLD document pair

`atlaz.docgen` reads an already-ingested run's knowledge graph and renders a High-Level Design and
Low-Level Design document -- every section except the HLD's one-paragraph executive summary is
rendered directly from graph facts (services, classes/methods, data model, API surface, business
rules, security controls), no LLM narration of anything that's supposed to be exact. The Streamlit
app's **Retrieve & Document** tab is the easiest way to generate and download these; `atlaz
document`/`POST /runs/{id}/documents` do the same thing for CLI/API use.

or via the API:

```bash
curl -X POST http://localhost:8000/runs/<thread_id>/documents -d '{"project_id": "my-project"}'
```

`project_id` is caller-chosen and only used to name the output folder -- it groups every
regeneration of a project's docs together regardless of which ingestion run (`thread_id`) produced
the latest version. Neo4j is one shared instance across every repo you've ever ingested; every
query `docgen` issues is scoped to the target run's `repo_id` (resolved from the Postgres audit
record), never "whatever's in the graph" -- see "Design notes" below for why that scoping exists.

## Audit database / evidence store

Every run's lifecycle (`running` → `pending_review`/`complete`/`failed`, with node/edge counts,
`run_mode`, and the capability registry snapshot in effect) and every HITL resolution is recorded
in Postgres — `atlaz.pipeline_runs` and `atlaz.hitl_resolutions` — alongside the LLD §14.4 evidence
store: `atlaz.evidence_records` (one row per citation, queryable/joinable; the graph nodes also
carry the same citations inline as `evidence_json`, for cheap reads without a round-trip here),
`atlaz.conflict_records` (every cross-domain conflict N11X detects, resolved or
`unresolved_written_both`), and `atlaz.parse_failures` (every file N4 couldn't parse). All of it
lives in its own `atlaz` schema of its own `atlaz` database, isolated from anything else that
database server hosts. This is a queryable record on top of the pipeline, not a dependency of it:
every write in `atlaz/audit/repository.py` swallows its own errors, so a Postgres outage never
breaks an ingestion run — only the record of it goes missing, logged as a warning.

`atlaz.llm_traces` is defined in the schema (LLD §14.4) but not yet populated — capturing every
agent's prompt/response pair requires instrumenting each LLM call individually, which this pass
doesn't do.

```bash
atlaz db init             # creates the database (if missing) + schema + runs Alembic migrations
python scripts/migrate_db.py   # equivalent standalone script -- same steps, no CLI required
```

`ADMIN_DATABASE_URL` (a database that already exists, e.g. the server's default `postgres`) is
used only for the one-time `CREATE DATABASE` step — Postgres can't run that inside a transaction
against the database being created. `DATABASE_URL` is what the app actually connects to
afterward. To add a migration: edit `src/atlaz/audit/models.py`, then either write a revision under
`alembic/versions/` by hand or run `alembic revision --autogenerate -m "..."` against a database
already at the previous head.

## Configuration

All runtime behavior is environment-driven (`.env`, see `.env.example`):

| Variable | Purpose |
|---|---|
| `HITL_ENABLED` | `true` pauses at the review gate; `false` applies the auto-resolve policy inline |
| `CONFIDENCE_THRESHOLD` | Findings below this confidence are flagged for review |
| `LLM_PROVIDER` | `mock` \| `anthropic` \| `openai` \| `custom` (any OpenAI-compatible endpoint via `LLM_BASE_URL`) |
| `LLM_API_KEY`, `LLM_BASE_URL`, `LLM_MODEL` | Provider credentials/endpoint — never touch agent code |
| `NEO4J_URI`, `NEO4J_USER`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | Knowledge graph connection |
| `QDRANT_ENABLED`, `QDRANT_URL`, `QDRANT_API_KEY`, `QDRANT_COLLECTION_PREFIX` | Vector index (candidate retrieval only); `enabled=false` makes `write_vector_index` a no-op |
| `CAPABILITY_REGISTRY_PATH` | Path to `capability_registry.yaml`; defaults to the repo root copy |
| `CHECKPOINT_DB_PATH` | SQLite file LangGraph uses to persist paused runs across process boundaries |
| `CELERY_BROKER_URL`, `CELERY_RESULT_BACKEND` | Redis, for background ingestion jobs |
| `API_HOST`, `API_PORT`, `API_BASE_URL` | FastAPI bind address (the Streamlit app talks to the pipeline in-process, not through this API) |
| `DATABASE_URL`, `ADMIN_DATABASE_URL`, `DB_SCHEMA` | Postgres audit trail + evidence store (see "Audit database / evidence store" above) |

Swapping the LLM provider or turning HITL on/off never requires a code change — only `.env`.

## Design notes and deliberate deviations from the LLD

A few implementation choices diverge from the letter of the LLD; each is called out in a docstring
at the point of the decision, and summarized here:

- **Domain fan-out is per-domain, not per-agent** (`orchestration/nodes.py`) —
  `domain_orchestrator` dispatches one `Send()` per enabled domain; each domain's node function is
  what enforces per-agent gating (`registry[domain][agent]`) before calling that agent's code. All
  four domains (A-D) are dispatched together so they land in the same LangGraph superstep, which is
  what lets `workflow_trace` (needs Domain B *and* Domain D) fan in correctly without a hand-rolled
  synchronization node. Trade-off: Domain A's `readme_commit_signal_miner` no longer runs strictly
  after Domain B, so its `naming_pattern` signal source (fed by the glossary) is empty in this
  ordering — documented, not silent.
- **No separate `Module` graph label** (`graph_store/schema.py`) — the LLD's `Module` (folder
  container) and `Service` (HLD-derived boundary) would be built from the exact same source in this
  codebase (`HLDBuilder`'s folder-topology grouping), so `Service` plays both roles rather than
  duplicating one real concept into two nodes.
- **`Feature` is derived 1:1 from `BusinessCapability`, not independently extracted** — no dedicated
  Feature-extraction agent exists in this build. `Workflow`/`Step` come from `workflow_trace`'s
  call-graph walk from entry points, seeded by Domain B's clusters and Domain D's HLD.
- **Incremental re-analysis is topology-only** (LLD §12) — `run_mode`/`changed_files` and the N2/N20
  nodes are wired into the graph exactly per the diagram, and a delta run correctly scopes N3D-N9 to
  `changed_files`. Diffing `dependency_graph` to selectively skip unaffected domains, and Neo4j
  bitemporal `valid_from`/`valid_to` stamping, are not implemented — a delta run re-executes every
  enabled domain, and graph writes use the same `MERGE`+`last_verified` semantics as a full run.
- **`analyze_data_flow` is scoped, not exhaustive** (`analysis/data_flow.py`) — parameter
  propagation is call-graph adjacency, not alias/taint tracking; DB read/write attribution is a
  CRUD-verb naming heuristic on a method's parent class, honestly labeled `access="unknown"` when
  it can't tell, not guessed.
- **Evidence is stored as a JSON property on each finding's own node**, not as separate `Evidence`
  graph nodes (`graph_store/graph_builder.py`) — Postgres `evidence_records` is the queryable/
  joinable source; the inline JSON is for cheap reads without a round-trip.
- **HITL resolution matching uses a `natural_key`, not object identity** (`hitl/natural_keys.py`) —
  a LangGraph checkpoint round-trip (or an HTTP API and its caller being different processes, which
  is the normal case for `/resolve`) does not preserve Python object identity.
- **Intended-vs-implemented conflicts are no longer part of the three-tier HITL queue** — the new
  LLD's N11X-N16 cross-domain conflict detection/dispute resolution is authoritative for every
  conflict type now, including the rule-vs-implementation `value_mismatch` check the prior HITL gate
  used to surface directly (see `hitl/models.py`).
- **Every graph node is stamped with `repo_id` at write time** (`Neo4jWriter.write_batch`) — Neo4j
  here is one shared instance across every repo ever ingested, and most node labels have no other
  run-scoping property. `atlaz.docgen` (and any future cross-run reader) must filter every query by
  `repo_id`, resolved from the Postgres audit record, not just query the label and hope. This was
  found by testing HLD/LLD generation against real data, not by inspection — an earlier version
  silently blended two different ingested repos' facts into one document.
- **Qdrant writes are best-effort, wrapped end to end** (`orchestration/nodes.py`'s
  `write_vector_index_node`) — an unreachable Qdrant server must never fail an otherwise-successful
  ingestion run, mirroring the audit-write swallow-and-log pattern. Construction succeeding is not
  enough to guarantee this (the client connects lazily), so the actual write call is inside the
  same guarded block, not just the client's `__init__`.
- **The Streamlit app (`webapp/`) forces `hitl_enabled=False` for every run it starts**, regardless
  of `.env` — it has exactly two screens (Ingest, Retrieve & Document) and no review screen, so a
  run started there always runs to completion; any low-confidence finding is written to the graph,
  correctly flagged, never blocked on approval. `atlaz run`/the API still honor `.env`'s
  `HITL_ENABLED` as before.
- **The old three-origin HITL queue (gap / low-confidence / conflict) is now two-origin** (gap /
  low-confidence only, see the conflicts note above) — the Streamlit `hitl/streamlit_app/` package
  from the prior design was removed rather than updated to the new schema; `webapp/` replaces it
  with a simpler, always-auto-resolved flow instead of a review UI.

## Known limitations

- Capability naming, architecture-style inference, and narrative synthesis are only as good as the
  configured LLM provider — `LLM_PROVIDER=mock` (the default) produces structurally valid but
  placeholder text, by design, so the pipeline is fully testable without API credentials. One
  consequence: `MockLLMClient` always names every capability cluster identically, which can cause
  clusters to collapse under the same natural key / graph node — a real provider naming clusters
  distinctly does not hit this.
- BRD extraction (Domain B) and PRD inference (Domain C) are architecture-only, not built — a
  question that touches either surfaces as an explicit gap, never a guess. Domain E (infrastructure,
  ops, test coverage, release history) is fully descoped, enforced by `capability_registry.yaml`.
- `atlaz.llm_traces` (evidence store) is defined but not populated yet (see "Audit database" above).
- The Streamlit app has no code-modification screen (`atlaz.enhancement`'s retrieval + code-mod
  flow) and no way to edit a low-confidence finding's content before accepting it -- both are
  CLI-only (`atlaz enhance`), by design, to keep the app to exactly two approachable screens.
- Git-URL ingestion always does a fresh shallow clone into `.atlaz/workspaces/<slug>-<uuid>/` and
  never cleans old clones up automatically -- fine for occasional use, but worth pruning by hand on
  a long-lived install that ingests many git URLs.
- File/Class/Method/Service graph nodes are still MERGE-*keyed* by path/qualified-name alone (their
  `repo_id` is a filterable property, not part of the natural key — see "Design notes" above) —
  ingesting two different repos that happen to share an identical file path still merges those two
  nodes into one, with `repo_id` simply reflecting whichever repo wrote it most recently. This was
  already true of the prior design; full multi-repo namespacing (a `repo_id`-qualified natural key)
  isn't addressed by this refactor, only the "a reader can't tell which repo a node came from at
  all" half of the problem.
- `atlaz db init` resolves `alembic.ini` relative to its own source location — it assumes an
  editable/source checkout (`pip install -e .`), not a standalone installed wheel.
