from atlaz.agents.domain_d.lld_parser import LLDParser
from atlaz.parsing.models import FunctionDef, ParamSpec, ParseDepth, ParsedModule
from atlaz.shared.tier import Tier


def test_lld_parser_is_pure_passthrough_with_full_confidence():
    module = ParsedModule(
        file_path="app/billing.py",
        language="python",
        parse_depth=ParseDepth.FULL_AST,
        functions=[
            FunctionDef(
                qualified_name="app.billing.compute_fee",
                name="compute_fee",
                line_start=10,
                line_end=15,
                parameters=[ParamSpec(name="amount", annotation="float")],
                return_type="float",
            )
        ],
    )

    entries = LLDParser().run([module])

    assert len(entries) == 1
    entry = entries[0]
    assert entry.tier == Tier.EXTRACTABLE
    assert entry.confidence == 1.0
    assert entry.signature == "compute_fee(amount: float) -> float"
    assert entry.evidence[0].file == "app/billing.py"
    assert entry.evidence[0].line == 10
