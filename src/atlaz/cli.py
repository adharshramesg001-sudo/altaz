"""CLI entry point (`atlaz` console script, per pyproject.toml).

Commands:
  atlaz app
      Launches the Streamlit app -- a single scrolling page, three
      sections: Ingest, Retrieve & Document, and Modernize. Runs everything
      in-process (no Celery/API required); the three-tier HITL gate is
      always auto-resolved there, there is no separate review screen.
  atlaz run <repo_path> [--thread-id ID]
      Ingests and extracts knowledge from a repository. If HITL is enabled
      and something was flagged, the run pauses and prints the thread id
      needed to resolve it.
  atlaz resume <thread_id>
      Applies the auto-resolve policy and finishes a paused run without a
      human reviewer (equivalent to what happens automatically when
      HITL_ENABLED=false) -- useful for CI or a hands-off demo.
  atlaz ask <thread_id> "<question>" [--mode qa|enhancement|modernization|drift|product_synthesis]
      Runs one reasoning-layer query against the knowledge graph.
  atlaz enhance <thread_id> "<request>" [--save]
      Runs the targeted-change flow: finds files the knowledge graph says
      are impacted by <request>, drafts a modernization plan, generates
      modified content for each file (grounded in the file's own current
      content), validates it (syntax + basic security checks), and (with
      --save) writes it all to outputs/ -- never back into the ingested
      repo. Also available as the "Modernize" screen in the Streamlit app
      (`atlaz app`).
  atlaz migrate <thread_id> "<request>" [--save]
      Runs the full-project migration flow: pulls the *entire* knowledge
      graph (the same whole-project facts `atlaz document` uses), groups
      it into migration units (one per business capability, or per
      service/whole-project as fallbacks, plus an infra unit for
      Dockerfile/CI/IaC/manifests), drafts a migration plan (including a
      same-language vs. cross-language classification), scans dependency
      manifests and proposes + registry-verifies a replacement mapping
      (PyPI/npm), and generates fresh code per unit -- grounded only in
      what the graph says that unit does, the original file source is
      never shown to the LLM except for the infra unit (declarative
      config, shown its real current content on purpose). Validates the
      result and (with --save) writes it to outputs/ -- never back into
      the ingested repo. The CLI runs every stage automatically; the
      Streamlit app's "Full migration" mode instead pauses for human
      confirmation of the dependency mapping on a cross-language request.
  atlaz document <thread_id> <project_id> [--no-save]
      Generates a High-Level Design and Low-Level Design document from an
      already-ingested run's knowledge graph -- deterministic facts
      (services, classes, data model, API contracts, business rules,
      security controls) rendered directly from the graph, plus one
      LLM-synthesized executive summary. Saved to
      outputs/<project_id>/docs/<timestamp>/{HLD,LLD}.md unless --no-save.
  atlaz link-services <thread_id_a> <thread_id_b> [--write] [--min-confidence F]
      Scans both already-ingested repos' source for every kind of evidence
      one talks to the other, and correlates it against each repo's own
      knowledge graph:
        - synchronous: literal URLs, service-name-shaped env vars,
          docker-compose/k8s declared service names -- written as
          CALLS_SERVICE edges between the two repos' Service nodes.
        - async messaging: message-queue/event-stream call sites (Kafka,
          RabbitMQ, SQS, Azure Service Bus, Redis Streams, Google Pub/Sub)
          -- written as PUBLISHES/CONSUMES edges from each repo's owning
          Service to a shared Event node keyed by topic name (the two
          repos land on the same node without needing to be matched to
          each other explicitly).
      Prints findings by default (dry run); --write persists them,
      status="unconfirmed" -- heuristic, not HITL-reviewed yet.
  atlaz db init
      Creates the audit database (if missing), its schema, and runs Alembic
      migrations. Run this once before the first `atlaz run`. Assumes an
      editable/source checkout (resolves alembic.ini relative to this file).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.llm.client import build_llm_client
from atlaz.orchestration.runner import resume_pipeline, run_pipeline
from atlaz.reasoning.neo4j_query_runner import Neo4jReasoningStore
from atlaz.reasoning.reasoning_agent import ReasoningAgent, ReasoningMode
from atlaz.shared.config import PipelineConfig
from atlaz.shared.logging_config import configure_logging


def _cmd_run(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_env()
    result = run_pipeline(args.repo_path, config, thread_id=args.thread_id)

    if result.status == "pending_review":
        print(f"Run paused for human review. thread_id = {result.thread_id}")
        print(f"  Flagged items: {len(result.pending_items or [])}")
        print(f"  Auto-resolve and finish:  atlaz resume {result.thread_id}")
        return 0

    print(f"Run complete. thread_id = {result.thread_id}")
    print(f"  Nodes written: {len(result.state.get('graph_write_nodes', []))}")
    print(f"  Edges written: {len(result.state.get('graph_write_edges', []))}")
    return 0


def _cmd_resume(args: argparse.Namespace) -> int:
    config = PipelineConfig.from_env()
    from atlaz.orchestration.runner import get_pending_review_items

    flagged = get_pending_review_items(args.thread_id, config)
    if not flagged:
        print(f"No pending review items for thread_id={args.thread_id} (already resolved, or unknown thread).")
        return 1

    resolutions = auto_resolve(flagged)
    result = resume_pipeline(args.thread_id, resolutions, config)
    print(f"Run complete via auto-resolve. thread_id = {result.thread_id}")
    print(f"  Nodes written: {len(result.state.get('graph_write_nodes', []))}")
    print(f"  Edges written: {len(result.state.get('graph_write_edges', []))}")
    return 0


def _cmd_app(args: argparse.Namespace) -> int:
    app_path = Path(__file__).parent / "webapp" / "main.py"
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(app_path)])


def _cmd_ask(args: argparse.Namespace) -> int:
    from atlaz.audit.repository import get_run

    config = PipelineConfig.from_env()
    run = get_run(args.thread_id, config.database)
    if run is None:
        print(f"No ingestion run found for thread_id={args.thread_id!r}")
        return 1

    llm_client = build_llm_client(config.llm)
    with Neo4jReasoningStore(config.neo4j) as store:
        agent = ReasoningAgent(llm_client, store.run)
        result = agent.answer(args.question, ReasoningMode(args.mode), run.repo_id)

    print(result.answer_text)
    print(f"\nconfidence: {result.confidence:.2f}")
    if result.cited_nodes:
        print(f"cited: {', '.join(result.cited_nodes)}")
    if result.gaps_encountered:
        print("gaps encountered:")
        for gap in result.gaps_encountered:
            print(f"  - {gap}")
    return 0


def _cmd_enhance(args: argparse.Namespace) -> int:
    from atlaz.enhancement.guideline_store import (
        GuidelineRetrievalAgent,
        MilvusLiteVectorIndex,
        default_embed_fn,
    )
    from atlaz.enhancement.impact_analysis import ImpactAnalysisAgent
    from atlaz.enhancement.modifier import CodeModificationAgent
    from atlaz.enhancement.planner import PlanningAgent
    from atlaz.enhancement.service import EnhancementService
    from atlaz.enhancement.validator import ValidationAgent

    config = PipelineConfig.from_env()
    llm_client = build_llm_client(config.llm)

    guideline_agent = None
    if config.guideline_store.enabled:
        try:
            index = MilvusLiteVectorIndex(config.guideline_store.db_path, config.guideline_store.collection_name)
            guideline_agent = GuidelineRetrievalAgent(index, default_embed_fn(config.llm))
            guideline_agent.populate_default_guidelines()
        except RuntimeError as exc:
            print(f"Guideline retrieval disabled: {exc}")

    with Neo4jReasoningStore(config.neo4j) as store:
        service = EnhancementService(
            ImpactAnalysisAgent(store.run),
            CodeModificationAgent(llm_client),
            guideline_agent,
            PlanningAgent(llm_client),
            ValidationAgent(),
            output_root="outputs",
        )
        try:
            result = service.run(args.thread_id, args.request)
        except ValueError as exc:
            print(str(exc))
            return 1

    print(f"Impacted files: {len(result.impact.files)}")
    for f in result.impact.files:
        print(f"  - {f.file_path} ({f.reason})")
    if result.skipped_files:
        print(f"Skipped (not found on disk): {', '.join(result.skipped_files)}")
    if result.plan:
        print("\nModernization plan:")
        print(result.plan.summary)
    print(f"\nModifications drafted: {len(result.modifications)}")
    for validation in result.validations:
        if not validation.syntax_valid or validation.security_issues:
            print(f"  ⚠ {validation.file_path}: {', '.join(validation.warnings + validation.security_issues)}")

    if args.save:
        output_dir = service.save(result, args.request)
        print(f"Saved to: {output_dir}")
    return 0


def _cmd_migrate(args: argparse.Namespace) -> int:
    from atlaz.enhancement.guideline_store import (
        GuidelineRetrievalAgent,
        MilvusLiteVectorIndex,
        default_embed_fn,
    )
    from atlaz.enhancement.validator import ValidationAgent
    from atlaz.migration.dependency_mapper import DependencyMappingAgent
    from atlaz.migration.dependency_verifier import HttpRegistryClient
    from atlaz.migration.generator import UnitMigrationAgent
    from atlaz.migration.infra_generator import InfraMigrationAgent
    from atlaz.migration.planner import MigrationPlanningAgent
    from atlaz.migration.service import MigrationService

    config = PipelineConfig.from_env()
    llm_client = build_llm_client(config.llm)

    guideline_agent = None
    if config.guideline_store.enabled:
        try:
            index = MilvusLiteVectorIndex(config.guideline_store.db_path, config.guideline_store.collection_name)
            guideline_agent = GuidelineRetrievalAgent(index, default_embed_fn(config.llm))
            guideline_agent.populate_default_guidelines()
        except RuntimeError as exc:
            print(f"Guideline retrieval disabled: {exc}")

    with Neo4jReasoningStore(config.neo4j) as store:
        service = MigrationService(
            store.run,
            MigrationPlanningAgent(llm_client),
            UnitMigrationAgent(llm_client),
            guideline_agent,
            ValidationAgent(),
            InfraMigrationAgent(llm_client),
            DependencyMappingAgent(llm_client),
            HttpRegistryClient(),
            output_root="outputs",
        )
        try:
            result = service.run(args.thread_id, args.request)
        except ValueError as exc:
            print(str(exc))
            return 1

    print(f"Target language: {result.plan.target_language or 'unknown'} "
          f"({'same language' if result.plan.same_language else 'CROSS-LANGUAGE -- review dependency mapping below'})")
    print(f"\nMigration units: {len(result.units)}")
    for unit in result.units:
        print(f"  - [{unit.unit_type}] {unit.name}")
    print("\nMigration plan:")
    print(result.plan.summary)

    if result.dependency_mappings:
        print("\nDependency mapping:")
        for m in result.dependency_mappings:
            status = "verified" if m.verified else "UNVERIFIED"
            print(
                f"  - {m.current_name} {m.current_version} ({m.current_ecosystem}) -> "
                f"{m.target_name} {m.target_version} ({m.target_ecosystem}) [{status}] {m.justification}"
            )
            if not m.verified and m.verification_note:
                print(f"      {m.verification_note}")

    generated_files = sum(len(u.files) for u in result.generated_units)
    print(f"\nFiles generated: {generated_files}")
    for validation in result.validations:
        if not validation.syntax_valid or validation.security_issues:
            print(f"  ⚠ {validation.file_path}: {', '.join(validation.warnings + validation.security_issues)}")

    if not result.plan.same_language and result.dependency_mappings:
        print(
            "\nNote: this is a cross-language migration -- review the dependency mapping above "
            "before applying anything (the CLI runs the whole flow automatically; the Streamlit "
            "app's Modernize screen offers an interactive confirm step for this case)."
        )

    if args.save:
        output_dir = service.save(result, args.request)
        print(f"Saved to: {output_dir}")
    return 0


def _cmd_document(args: argparse.Namespace) -> int:
    from atlaz.docgen.service import DocumentationService

    config = PipelineConfig.from_env()
    llm_client = build_llm_client(config.llm)

    with Neo4jReasoningStore(config.neo4j) as store:
        service = DocumentationService(llm_client, store.run, output_root="outputs")
        try:
            result = service.run(args.thread_id, args.project_id, save=not args.no_save)
        except ValueError as exc:
            print(str(exc))
            return 1

    print(f"HLD: {len(result.hld_markdown.splitlines())} line(s)")
    print(f"LLD: {len(result.lld_markdown.splitlines())} line(s)")
    if result.output_dir:
        print(f"Saved to: {result.output_dir}")
    return 0


def _cmd_link_services(args: argparse.Namespace) -> int:
    """Detects both how repo A and repo B call each other synchronously
    (CALLS_SERVICE, via `CrossRepoLinkService`) and how each publishes/
    consumes messages asynchronously (PUBLISHES/CONSUMES onto a shared
    Event node, via `PubSubLinkService`) -- one command, since both are
    just different evidence for the same question ("how are these two
    repos coupled?"), not two things a user should have to remember to run
    separately."""
    from atlaz.crossrepo.pubsub_service import PubSubLinkService
    from atlaz.crossrepo.service import CrossRepoLinkService

    config = PipelineConfig.from_env()

    with Neo4jReasoningStore(config.neo4j) as store:
        sync_service = CrossRepoLinkService(store.run)
        pubsub_service = PubSubLinkService(store.run)
        try:
            candidates = sync_service.find_candidates(args.thread_id_a, args.thread_id_b)
            findings = pubsub_service.scan(args.thread_id_a) + pubsub_service.scan(args.thread_id_b)
        except ValueError as exc:
            print(str(exc))
            return 1

        candidates = [c for c in candidates if c.confidence >= args.min_confidence]
        candidates.sort(key=lambda c: c.confidence, reverse=True)
        findings = [f for f in findings if f.confidence >= args.min_confidence]
        findings.sort(key=lambda f: f.confidence, reverse=True)

        if not candidates and not findings:
            print("No cross-repo service links found.")
            return 0

        for c in candidates:
            evidence = c.evidence[0] if c.evidence else None
            location = f"{evidence.file}:{evidence.line}" if evidence else "?"
            print(
                f"[sync]  {c.source_repo_id}:{c.source_service} -> {c.target_repo_id}:{c.target_service} "
                f"(confidence={c.confidence:.2f}, matched_on={c.matched_on}, evidence={location})"
            )
        for f in findings:
            location = f"{f.evidence.file}:{f.evidence.line}"
            print(
                f"[async] {f.repo_id}:{f.service} {f.direction} '{f.topic}' via {f.library} "
                f"(confidence={f.confidence:.2f}, evidence={location})"
            )

        if args.write:
            written_sync = sync_service.write(candidates)
            written_async = pubsub_service.write(findings)
            print(f"Wrote {written_sync} CALLS_SERVICE edge(s), {written_async} PUBLISHES/CONSUMES edge(s).")
        else:
            print("Dry run -- re-run with --write to persist these as graph edges.")
    return 0


def _cmd_db_init(args: argparse.Namespace) -> int:
    from atlaz.audit.migrate import migrate

    migrate()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="atlaz", description="AtlaZ codebase knowledge extraction framework")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run_parser = subparsers.add_parser("run", help="Run the extraction pipeline against a repository")
    run_parser.add_argument("repo_path")
    run_parser.add_argument("--thread-id", default=None)
    run_parser.set_defaults(func=_cmd_run)

    resume_parser = subparsers.add_parser("resume", help="Auto-resolve a paused run and finish it")
    resume_parser.add_argument("thread_id")
    resume_parser.set_defaults(func=_cmd_resume)

    app_parser = subparsers.add_parser("app", help="Launch the Streamlit app (Ingest + Retrieve & Document + Modernize)")
    app_parser.set_defaults(func=_cmd_app)

    ask_parser = subparsers.add_parser("ask", help="Ask the reasoning layer a question")
    ask_parser.add_argument("thread_id")
    ask_parser.add_argument("question")
    ask_parser.add_argument(
        "--mode", default="qa", choices=[m.value for m in ReasoningMode]
    )
    ask_parser.set_defaults(func=_cmd_ask)

    enhance_parser = subparsers.add_parser(
        "enhance", help="Find impacted files and draft modifications for a change request"
    )
    enhance_parser.add_argument("thread_id")
    enhance_parser.add_argument("request")
    enhance_parser.add_argument("--save", action="store_true", help="Write results to outputs/")
    enhance_parser.set_defaults(func=_cmd_enhance)

    migrate_parser = subparsers.add_parser(
        "migrate", help="Regenerate a whole project in a new stack, grounded only in its knowledge graph"
    )
    migrate_parser.add_argument("thread_id")
    migrate_parser.add_argument("request")
    migrate_parser.add_argument("--save", action="store_true", help="Write results to outputs/")
    migrate_parser.set_defaults(func=_cmd_migrate)

    document_parser = subparsers.add_parser(
        "document", help="Generate an HLD/LLD document pair from an already-ingested run's knowledge graph"
    )
    document_parser.add_argument("thread_id")
    document_parser.add_argument("project_id")
    document_parser.add_argument("--no-save", action="store_true", help="Print lengths only; don't write to outputs/")
    document_parser.set_defaults(func=_cmd_document)

    link_services_parser = subparsers.add_parser(
        "link-services",
        help="Find (and optionally persist) cross-repo service links between two ingested runs -- "
        "both synchronous (CALLS_SERVICE) and async messaging (PUBLISHES/CONSUMES)",
    )
    link_services_parser.add_argument("thread_id_a")
    link_services_parser.add_argument("thread_id_b")
    link_services_parser.add_argument("--write", action="store_true", help="Persist findings as graph edges")
    link_services_parser.add_argument("--min-confidence", type=float, default=0.5)
    link_services_parser.set_defaults(func=_cmd_link_services)

    db_parser = subparsers.add_parser("db", help="Audit database management")
    db_subparsers = db_parser.add_subparsers(dest="db_command", required=True)
    db_init_parser = db_subparsers.add_parser("init", help="Create the database/schema and run migrations")
    db_init_parser.set_defaults(func=_cmd_db_init)

    return parser


def main() -> None:
    configure_logging()
    parser = build_parser()
    args = parser.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
