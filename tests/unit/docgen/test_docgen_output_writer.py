import json

from atlaz.docgen.models import ProjectFacts, RepositoryFact
from atlaz.docgen.output_writer import write_documents


def test_writes_hld_lld_and_manifest_under_project_id(tmp_path):
    facts = ProjectFacts(thread_id="t1", repository=RepositoryFact(repo_id="r1", name="demo"))

    run_dir = write_documents(tmp_path, "proj-42", "t1", "# HLD content", "# LLD content", facts)

    assert run_dir.parent == tmp_path / "proj-42" / "docs"
    assert (run_dir / "HLD.md").read_text() == "# HLD content"
    assert (run_dir / "LLD.md").read_text() == "# LLD content"

    manifest = json.loads((run_dir / "manifest.json").read_text())
    assert manifest["project_id"] == "proj-42"
    assert manifest["thread_id"] == "t1"
    assert manifest["repository"]["name"] == "demo"


def test_never_touches_the_ingested_repo(tmp_path):
    """The output lives under output_root/<project_id>/, never anywhere
    derived from the ingested repo's own path -- same propose-only
    discipline as atlaz.enhancement."""
    facts = ProjectFacts(thread_id="t1", repository=RepositoryFact(repo_id="r1", name="demo"))
    run_dir = write_documents(tmp_path, "proj-42", "t1", "hld", "lld", facts)
    assert str(run_dir).startswith(str(tmp_path))
