"""Checkpoint (de)serialization allowlist.

LangGraph's default `JsonPlusSerializer` currently warns-but-allows any
dataclass/enum it doesn't recognize when reconstructing checkpointed state
(see the "Deserializing unregistered type ... This will be blocked in a
future version" warning); a future release blocks it outright unless the
type is explicitly allowlisted. `PipelineState` is built entirely out of
this project's own dataclasses and enums, so every one of them needs to be
in this list -- otherwise a resumed run (the entire point of checkpointing
across the HITL pause) would start silently dropping fields the moment
LangGraph tightens this default.
"""

from __future__ import annotations

from langgraph.checkpoint.serde.jsonplus import JsonPlusSerializer

from atlaz.agents.domain_a.gap_detector import CandidateSignal, GapFinding
from atlaz.agents.domain_b.business_rule_extractor import BusinessRule
from atlaz.agents.domain_b.capability_clustering import CapabilityCluster
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.domain_c.frd_extractor import FunctionalRequirement
from atlaz.agents.domain_d.api_contract_parser import APIContract
from atlaz.agents.domain_d.data_model_extractor import DataEntity, EntityRelationship, FieldInfo
from atlaz.agents.domain_d.hld_builder import Component, ComponentDiagram, DependsOnEdge
from atlaz.agents.domain_d.lld_parser import LLDEntry
from atlaz.agents.domain_d.security_control_scanner import SecurityControl
from atlaz.graph_store.schema import EdgeType, GraphEdge, GraphNode, NodeLabel
from atlaz.hitl.conflict_detection import ConflictCandidate
from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution
from atlaz.ingestion.models import FileRecord, RepoInventory
from atlaz.parsing.models import (
    CallEdge,
    ClassDef,
    CommentRecord,
    DecoratorUse,
    FieldSpec,
    FunctionDef,
    ImportEdge,
    ParamSpec,
    ParseDepth,
    ParsedModule,
)
from atlaz.shared.evidence import Evidence
from atlaz.shared.tier import Tier

ALLOWED_CHECKPOINT_TYPES = [
    FileRecord,
    RepoInventory,
    ParseDepth,
    FieldSpec,
    ClassDef,
    ParamSpec,
    FunctionDef,
    ImportEdge,
    CallEdge,
    DecoratorUse,
    CommentRecord,
    ParsedModule,
    Tier,
    Evidence,
    CandidateSignal,
    GapFinding,
    CapabilityCluster,
    BusinessRule,
    GlossaryTerm,
    FunctionalRequirement,
    Component,
    ComponentDiagram,
    DependsOnEdge,
    LLDEntry,
    FieldInfo,
    EntityRelationship,
    DataEntity,
    APIContract,
    SecurityControl,
    ReviewItemKind,
    ReviewAction,
    ReviewItem,
    ReviewResolution,
    ConflictCandidate,
    NodeLabel,
    EdgeType,
    GraphNode,
    GraphEdge,
]


def build_checkpoint_serializer() -> JsonPlusSerializer:
    return JsonPlusSerializer(allowed_msgpack_modules=ALLOWED_CHECKPOINT_TYPES)
