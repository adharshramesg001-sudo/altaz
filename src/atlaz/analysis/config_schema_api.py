"""Config/schema/API analysis (LLD Section 5, node N8
`analyze_config_schema_api`).

Reads `file_classification` (config/build files) independently of
`symbol_table` -- runs concurrently with N6/N7 in the graph topology since
it reads a disjoint file class. Wraps the existing `DataModelExtractor`/
`APIContractParser` (originally Domain D agents in the prior design): the
new LLD places schema/API extraction in the deterministic stage, and Domain
D's `data_model_extractor`/`api_contract_parser` agents now read this
precomputed artifact instead of re-deriving it (see
`atlaz.agents.domain_d`).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from atlaz.agents.domain_d.api_contract_parser import APIContract, APIContractParser
from atlaz.agents.domain_d.data_model_extractor import DataEntity, DataModelExtractor
from atlaz.ingestion.models import RepoInventory
from atlaz.parsing.models import ParsedModule


@dataclass(slots=True)
class ConfigSchemaAPI:
    data_entities: list[DataEntity] = field(default_factory=list)
    api_contracts: list[APIContract] = field(default_factory=list)


def analyze_config_schema_api(inventory: RepoInventory, parsed: list[ParsedModule]) -> ConfigSchemaAPI:
    return ConfigSchemaAPI(
        data_entities=DataModelExtractor().run(inventory, parsed),
        api_contracts=APIContractParser().run(inventory, parsed),
    )
