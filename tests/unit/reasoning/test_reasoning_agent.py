from atlaz.llm.client import BaseLLMClient
from atlaz.reasoning.reasoning_agent import ReasoningAgent, ReasoningMode


class ScriptedLLMClient(BaseLLMClient):
    """Returns a fixed JSON response per call, in order -- lets tests control
    exactly what Cypher/answer the LLM 'generates' without a real provider."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.prompts_seen: list[str] = []

    def complete(self, prompt: str, schema: dict | None = None) -> str:
        import json

        self.prompts_seen.append(prompt)
        return json.dumps(self.responses.pop(0))


def test_drift_mode_uses_dedicated_query_not_llm_generated_cypher():
    queries_run = []

    def fake_runner(cypher, params):
        queries_run.append(cypher)
        return [
            {
                "rule_id": "cfg::late_fee_rate",
                "rule_value": "0.05",
                "entity_name": "Plan",
                "conflict_entity_value": "0.045",
                "unresolved": True,
            }
        ]

    llm = ScriptedLLMClient([{"answer_text": "The rule and the plan disagree on the late fee rate.", "confidence": 0.9}])
    agent = ReasoningAgent(llm, fake_runner)

    result = agent.answer("Where does intent diverge from implementation?", ReasoningMode.DRIFT, "test-repo")

    assert len(queries_run) == 1
    assert "CONFLICTS_WITH" in queries_run[0]
    assert "cfg::late_fee_rate" in result.cited_nodes
    assert result.confidence == 0.9


def test_qa_mode_generates_cypher_then_synthesizes_answer():
    def fake_runner(cypher, params):
        assert cypher == "MATCH (r:BusinessRule) RETURN r.rule_id AS rule_id"
        return [{"rule_id": "cfg::max_retries"}]

    llm = ScriptedLLMClient(
        [
            {"cypher": "MATCH (r:BusinessRule) RETURN r.rule_id AS rule_id"},
            {"answer_text": "There is one business rule: cfg::max_retries.", "confidence": 0.8},
        ]
    )
    agent = ReasoningAgent(llm, fake_runner)

    result = agent.answer("What business rules exist?", ReasoningMode.QA, "test-repo")

    assert result.answer_text == "There is one business rule: cfg::max_retries."
    assert "cfg::max_retries" in result.cited_nodes


def test_unsafe_generated_cypher_is_never_executed():
    calls = []

    def fake_runner(cypher, params):
        calls.append(cypher)
        return [{"rule_id": "should-not-be-reached"}]

    llm = ScriptedLLMClient([{"cypher": "MATCH (n) DETACH DELETE n"}])
    agent = ReasoningAgent(llm, fake_runner)

    result = agent.answer("Delete everything?", ReasoningMode.QA, "test-repo")

    assert calls == []  # the unsafe query never reached the runner
    assert result.confidence == 0.0


def test_unbuilt_corner_question_surfaces_a_gap_without_fabricating():
    def fake_runner(cypher, params):
        return []

    llm = ScriptedLLMClient(
        [
            {"cypher": "MATCH (n:Requirement) RETURN n"},
            {"answer_text": "No BRD data is available; nothing else in the graph answers this either.", "confidence": 0.0},
        ]
    )
    agent = ReasoningAgent(llm, fake_runner)

    result = agent.answer("What does the BRD say about approval workflows?", ReasoningMode.QA, "test-repo")

    assert any("Business Requirements" in g for g in result.gaps_encountered)


def test_product_synthesis_uses_dedicated_query():
    queries_run = []

    def fake_runner(cypher, params):
        queries_run.append(cypher)
        return [{"capability": "Order Management", "rules": ["late fee rule"], "components": ["orders"], "vocabulary": ["order"]}]

    llm = ScriptedLLMClient([{"answer_text": "This product manages orders.", "confidence": 0.7}])
    agent = ReasoningAgent(llm, fake_runner)

    result = agent.answer("What does this product do?", ReasoningMode.PRODUCT_SYNTHESIS, "test-repo")

    assert "Capability" in queries_run[0]
    assert result.answer_text == "This product manages orders."
