from pathlib import Path

from atlaz.agents.domain_d.data_model_extractor import DataModelExtractor
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.parsing.parser_registry import ParserRegistry
from atlaz.parsing.pipeline import parse_inventory

ORM_SOURCE = '''
class Base:
    pass


class Order(Base):
    id: int
    customer_id: int = ForeignKey("customer.id")
    total: float


class NotAModel:
    id: int
'''


def test_extracts_orm_entities_and_foreign_key_relationship(tmp_path: Path):
    (tmp_path / "models.py").write_text(ORM_SOURCE)
    inventory = RepoIngestor().ingest(str(tmp_path))
    parsed = parse_inventory(inventory, ParserRegistry())

    entities = DataModelExtractor().run(inventory, parsed)

    names = {e.entity_name for e in entities}
    assert "Order" in names
    assert "NotAModel" not in names

    order = next(e for e in entities if e.entity_name == "Order")
    assert order.source_kind == "orm_model"
    assert order.tier.value == "extractable"
    assert order.confidence == 1.0
    field_names = {f.name for f in order.fields}
    assert {"id", "customer_id", "total"} <= field_names

    assert len(order.relationships) == 1
    rel = order.relationships[0]
    assert rel.from_entity == "Order"
    assert rel.to_entity == "customer"
    assert rel.kind == "foreign_key"


def test_extracts_entities_from_raw_sql_migration(tmp_path: Path):
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "0001_init.sql").write_text(
        "CREATE TABLE customers (\n"
        "    id INTEGER PRIMARY KEY,\n"
        "    email VARCHAR(255)\n"
        ");\n"
    )
    inventory = RepoIngestor().ingest(str(tmp_path))
    parsed = parse_inventory(inventory, ParserRegistry())

    entities = DataModelExtractor().run(inventory, parsed)

    customers = next(e for e in entities if e.entity_name == "customers")
    assert customers.source_kind == "raw_sql_schema"
    field_names = {f.name for f in customers.fields}
    assert "id" in field_names
    assert "email" in field_names

    required_by_name = {f.name: f.required for f in customers.fields}
    assert required_by_name["id"] is True  # PRIMARY KEY
    assert required_by_name["email"] is False  # no NOT NULL/PRIMARY KEY


REQUIRED_FIELD_SOURCE = '''
class Base:
    pass


class UserProfile(Base):
    id: int
    nickname: Optional[str] = None
    email: str = Field(...)
    bio: str = Column(String, nullable=True)
    age: int = Column(Integer, nullable=False)
    country: str = "US"
'''


def test_infers_required_and_optional_fields_from_annotations_and_kwargs(tmp_path: Path):
    (tmp_path / "models.py").write_text(REQUIRED_FIELD_SOURCE)
    inventory = RepoIngestor().ingest(str(tmp_path))
    parsed = parse_inventory(inventory, ParserRegistry())

    entities = DataModelExtractor().run(inventory, parsed)
    profile = next(e for e in entities if e.entity_name == "UserProfile")
    required_by_name = {f.name: f.required for f in profile.fields}

    assert required_by_name["id"] is True  # bare annotation, no default -> required
    assert required_by_name["nickname"] is False  # Optional[...] with default None
    assert required_by_name["email"] is True  # Field(...) ellipsis -> explicitly required
    assert required_by_name["bio"] is False  # nullable=True
    assert required_by_name["age"] is True  # nullable=False
    assert required_by_name["country"] is False  # plain literal default
