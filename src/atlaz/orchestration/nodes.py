"""LangGraph node functions (LLD Section 9).

Each `make_*_node` factory closes over the config/LLM client it needs and
returns a plain `state -> partial_state_update` callable -- the shape
LangGraph nodes take. Closing over config/clients (rather than putting them
in `PipelineState`) is what keeps secrets out of the checkpoint file; see
`atlaz.orchestration.state` for the full rationale.

Node topology deviates from the LLD's literal "fan-out to five parallel
domain nodes" in one way: Domain A's naming-pattern signal needs Domain B's
glossary, and Domain B's glossary needs Domain D's data entities (LLD
Section 14's own build-sequencing table already establishes this chain --
"Domain Glossary is grouped into Day 3 ... since it depends on DataEntity
output from Domain D"). A literal parallel fan-out of A/B/C/D cannot satisfy
both dependencies at once, so this implementation runs them in the
dependency-respecting order the LLD's sequencing table implies:
parse -> domain_c (no cross-domain deps) -> domain_d -> domain_b -> domain_a
-> collect. This preserves every domain's documented behavior; it only
corrects an internal inconsistency between two sections of the same
document.
"""

from __future__ import annotations

from atlaz.agents.domain_a.gap_detector import BusinessCaseGapDetector
from atlaz.agents.domain_b.business_rule_extractor import BusinessRuleExtractor
from atlaz.agents.domain_b.capability_clustering import CapabilityClusterer
from atlaz.agents.domain_b.domain_glossary import DomainGlossaryExtractor
from atlaz.agents.domain_c.frd_extractor import FRDExtractor
from atlaz.agents.domain_d.api_contract_parser import APIContractParser
from atlaz.agents.domain_d.data_model_extractor import DataModelExtractor
from atlaz.agents.domain_d.hld_builder import HLDBuilder
from atlaz.agents.domain_d.lld_parser import LLDParser
from atlaz.agents.domain_d.security_control_scanner import SecurityControlScanner
from atlaz.graph_store import graph_builder
from atlaz.graph_store.neo4j_writer import Neo4jWriter
from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.hitl.merge import collect_flagged_items
from atlaz.hitl.models import ReviewItem, ReviewResolution
from atlaz.hitl.resolution_application import (
    apply_low_confidence_resolutions,
    conflict_resolutions,
    find_gap_resolution,
)
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.llm.client import BaseLLMClient
from atlaz.parsing.parser_registry import ParserRegistry
from atlaz.parsing.pipeline import parse_inventory
from atlaz.shared.config import PipelineConfig


def make_ingest_node(config: PipelineConfig):
    def ingest_node(state):
        inventory = RepoIngestor(ignore_dirs=frozenset(config.ignore_dirs)).ingest(state["repo_path"])
        return {"inventory": inventory}

    return ingest_node


def make_parse_node():
    def parse_node(state):
        parsed = parse_inventory(state["inventory"], ParserRegistry())
        return {"parsed_modules": parsed}

    return parse_node


def make_domain_c_node(llm_client: BaseLLMClient):
    def domain_c_node(state):
        requirements = FRDExtractor(llm_client).run(state["parsed_modules"])
        return {"domain_c": requirements}

    return domain_c_node


def make_domain_d_node(llm_client: BaseLLMClient):
    def domain_d_node(state):
        parsed = state["parsed_modules"]
        inventory = state["inventory"]
        data_model = DataModelExtractor().run(inventory, parsed)
        security = SecurityControlScanner(llm_client).run(parsed, data_model)
        return {
            "domain_d": {
                "hld": HLDBuilder(llm_client).run(parsed),
                "lld": LLDParser().run(parsed),
                "data_model": data_model,
                "api": APIContractParser().run(inventory, parsed),
                "security": security,
            }
        }

    return domain_d_node


def make_domain_b_node(llm_client: BaseLLMClient, confidence_threshold: float):
    def domain_b_node(state):
        parsed = state["parsed_modules"]
        inventory = state["inventory"]
        data_entities = state["domain_d"]["data_model"]
        return {
            "domain_b": {
                "capability_clusters": CapabilityClusterer(llm_client, confidence_threshold).run(parsed),
                "business_rules": BusinessRuleExtractor(llm_client).run(inventory),
                "glossary_terms": DomainGlossaryExtractor(llm_client).run(parsed, data_entities),
            }
        }

    return domain_b_node


def make_domain_a_node():
    def domain_a_node(state):
        finding = BusinessCaseGapDetector().run(
            state["inventory"], state["parsed_modules"], state["domain_b"]["glossary_terms"]
        )
        return {"domain_a": finding}

    return domain_a_node


def make_collect_node(confidence_threshold: float):
    def collect_node(state):
        items = collect_flagged_items(
            gap_finding=state["domain_a"],
            capability_clusters=state["domain_b"]["capability_clusters"],
            business_rules=state["domain_b"]["business_rules"],
            glossary_terms=state["domain_b"]["glossary_terms"],
            functional_requirements=state["domain_c"],
            component_diagram=state["domain_d"]["hld"],
            data_entities=state["domain_d"]["data_model"],
            api_contracts=state["domain_d"]["api"],
            security_controls=state["domain_d"]["security"],
            confidence_threshold=confidence_threshold,
        )
        return {"flagged_for_review": items}

    return collect_node


def route_after_collect(state) -> str:
    return "hitl_gate" if state["flagged_for_review"] else "prepare_graph_batch"


def make_hitl_gate_node(config: PipelineConfig, interrupt_fn):
    """`interrupt_fn` wraps LangGraph's `interrupt()` (or a test double);
    injected rather than imported here so this module -- and the ReviewGate
    it uses -- stays testable without a running graph."""

    def hitl_gate_node(state):
        flagged: list[ReviewItem] = state["flagged_for_review"]
        if config.hitl_enabled:
            resolutions: list[ReviewResolution] = interrupt_fn(flagged)
        else:
            resolutions = auto_resolve(flagged)
        return {"hitl_resolutions": resolutions}

    return hitl_gate_node


def make_prepare_graph_batch_node(confidence_threshold: float):
    def prepare_graph_batch_node(state):
        flagged: list[ReviewItem] = state.get("flagged_for_review", [])
        resolutions: list[ReviewResolution] = state.get("hitl_resolutions", [])

        clusters = apply_low_confidence_resolutions(
            state["domain_b"]["capability_clusters"], flagged, resolutions
        )
        rules = state["domain_b"]["business_rules"]  # not itself an inferable-tier corner; never filtered here
        glossary = apply_low_confidence_resolutions(state["domain_b"]["glossary_terms"], flagged, resolutions)
        requirements = apply_low_confidence_resolutions(state["domain_c"], flagged, resolutions)
        diagram_list = apply_low_confidence_resolutions([state["domain_d"]["hld"]], flagged, resolutions)
        diagram = diagram_list[0] if diagram_list else state["domain_d"]["hld"]
        data_entities = state["domain_d"]["data_model"]
        api_contracts = state["domain_d"]["api"]
        security_controls = apply_low_confidence_resolutions(state["domain_d"]["security"], flagged, resolutions)
        parsed = state["parsed_modules"]

        nodes: list = []
        edges: list = []

        nodes.extend(graph_builder.build_capability_nodes(clusters, confidence_threshold))
        nodes.extend(graph_builder.build_business_rule_nodes(rules, confidence_threshold))
        nodes.extend(graph_builder.build_glossary_term_nodes(glossary, confidence_threshold))
        nodes.extend(graph_builder.build_requirement_nodes(requirements, confidence_threshold))
        nodes.extend(graph_builder.build_module_nodes(parsed))
        nodes.extend(graph_builder.build_security_control_nodes(security_controls, confidence_threshold))
        nodes.extend(graph_builder.build_api_contract_nodes(api_contracts, confidence_threshold))

        entity_nodes, entity_edges = graph_builder.build_data_entity_nodes_and_edges(
            data_entities, confidence_threshold
        )
        nodes.extend(entity_nodes)
        edges.extend(entity_edges)

        component_nodes, component_edges = graph_builder.build_component_nodes_and_edges(diagram)
        nodes.extend(component_nodes)
        edges.extend(component_edges)

        test_case_nodes, test_case_edges = graph_builder.build_test_case_nodes_and_edges(requirements)
        nodes.extend(test_case_nodes)
        edges.extend(test_case_edges)

        edges.extend(graph_builder.build_capability_ownership_edges(clusters, data_entities, api_contracts))
        edges.extend(graph_builder.build_component_implements_capability_edges(diagram, clusters))
        edges.extend(graph_builder.build_module_implements_requirement_edges(requirements))

        gap_resolution = find_gap_resolution(flagged, resolutions)
        nodes.append(graph_builder.build_gap_node(state["domain_a"], gap_resolution))

        edges.extend(graph_builder.build_conflict_edges(conflict_resolutions(resolutions)))

        return {"graph_write_nodes": nodes, "graph_write_edges": edges}

    return prepare_graph_batch_node


def make_graph_write_node(config: PipelineConfig, writer_factory=None):
    """`writer_factory` defaults to a real `Neo4jWriter`; tests inject a
    fake to exercise the full graph topology without a live database."""
    writer_factory = writer_factory or (lambda: Neo4jWriter(config.neo4j))

    def graph_write_node(state):
        with writer_factory() as writer:
            writer.ensure_schema()
            writer.write_batch(state["graph_write_nodes"], state["graph_write_edges"])
        return {}

    return graph_write_node
