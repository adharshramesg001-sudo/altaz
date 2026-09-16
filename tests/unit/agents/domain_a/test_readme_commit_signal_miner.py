from atlaz.agents.domain_a.readme_commit_signal_miner import ReadmeCommitSignalMiner
from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.ingestion.repo_ingestor import RepoIngestor
from atlaz.parsing.models import ClassDef, FieldSpec, ParseDepth, ParsedModule
from atlaz.shared.evidence import Evidence


def test_no_signal_when_repo_is_empty(tmp_path):
    inventory = RepoIngestor().ingest(str(tmp_path))
    signals = ReadmeCommitSignalMiner().run(inventory, parsed=[])
    assert signals == []


def test_readme_rationale_language_becomes_a_candidate_signal(tmp_path):
    (tmp_path / "README.md").write_text("This tool exists to help teams because manual audits were too slow.")
    inventory = RepoIngestor().ingest(str(tmp_path))

    signals = ReadmeCommitSignalMiner().run(inventory, parsed=[])

    readme_signals = [s for s in signals if s.source_kind == "readme"]
    assert readme_signals
    assert "because" in readme_signals[0].text.lower()


def test_billing_structure_is_surfaced_as_raw_signal_not_a_conclusion(tmp_path):
    module = ParsedModule(
        file_path="billing/plans.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        classes=[
            ClassDef(
                qualified_name="billing.plans.PlanTier",
                name="PlanTier",
                line_start=1,
                line_end=5,
                fields=[FieldSpec(name="pricing_tier", value_expr="'gold'", line=2)],
            )
        ],
    )
    inventory = RepoIngestor().ingest(str(tmp_path))

    signals = ReadmeCommitSignalMiner().run(inventory, parsed=[module])

    billing_signals = [s for s in signals if s.source_kind == "billing_structure"]
    assert billing_signals
    # raw evidence only -- never phrased as a strategy conclusion
    assert "pricing strategy" not in billing_signals[0].text.lower()


def test_glossary_terms_feed_naming_pattern_signals(tmp_path):
    glossary = [
        GlossaryTerm(term="settlement", occurrence_count=5, source_kinds=["class_name"], evidence=[Evidence(file="a.py", line=1)])
    ]
    inventory = RepoIngestor().ingest(str(tmp_path))

    signals = ReadmeCommitSignalMiner().run(inventory, parsed=[], glossary=glossary)

    naming_signals = [s for s in signals if s.source_kind == "naming_pattern"]
    assert any(s.text == "settlement" for s in naming_signals)


def test_commit_messages_are_scanned(tmp_path):
    import subprocess

    subprocess.run(["git", "init"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "a@b.com"], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "a"], cwd=tmp_path, check=True, capture_output=True)
    (tmp_path / "a.txt").write_text("x")
    subprocess.run(["git", "add", "."], cwd=tmp_path, check=True, capture_output=True)
    subprocess.run(
        ["git", "commit", "-m", "add retry because the upstream API is flaky"],
        cwd=tmp_path, check=True, capture_output=True,
    )
    inventory = RepoIngestor().ingest(str(tmp_path))

    signals = ReadmeCommitSignalMiner().run(inventory, parsed=[])

    commit_signals = [s for s in signals if s.source_kind == "commit_message"]
    assert commit_signals
    assert commit_signals[0].evidence.commit
