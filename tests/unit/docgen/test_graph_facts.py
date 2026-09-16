from atlaz.docgen.graph_facts import fetch_project_facts


def test_every_query_is_scoped_to_repo_id():
    seen_params = []

    def fake_runner(cypher, params):
        seen_params.append(params)
        if "Repository" in cypher:
            return [{"repo_id": "repo-1", "name": "Repo One", "primary_languages": ["python"]}]
        return []

    fetch_project_facts(fake_runner, thread_id="t1", repo_id="repo-1")

    assert seen_params  # at least one query ran
    assert all(p.get("repo_id") == "repo-1" for p in seen_params)


def test_missing_repository_node_falls_back_to_repo_id():
    facts = fetch_project_facts(lambda cypher, params: [], thread_id="t1", repo_id="repo-2")
    assert facts.repository.repo_id == "repo-2"
    assert facts.repository.name == "repo-2"


def test_capability_facts_pick_up_feature_edges():
    def fake_runner(cypher, params):
        if "BusinessCapability" in cypher and "HAS_FEATURE" in cypher:
            return [{"capability": "Billing", "feature_id": "feature::Billing"}]
        if "BusinessCapability" in cypher:
            return [{"capability_id": "Billing", "name": "Billing", "confidence": 0.9, "cohesion_score": 0.5, "member_modules": ["a.py"], "needs_review": False}]
        return []

    facts = fetch_project_facts(fake_runner, thread_id="t1", repo_id="repo-1")
    assert len(facts.capabilities) == 1
    assert facts.capabilities[0].feature_ids == ["feature::Billing"]


def test_workflow_steps_are_ordered():
    def fake_runner(cypher, params):
        if "HAS_STEP" in cypher:
            return [
                {"workflow_id": "w1", "step_name": "step_a", "seq": 0},
                {"workflow_id": "w1", "step_name": "step_b", "seq": 1},
            ]
        if cypher.startswith("MATCH (w:Workflow"):
            return [{"workflow_id": "w1", "name": "w1", "confidence": 0.5}]
        return []

    facts = fetch_project_facts(fake_runner, thread_id="t1", repo_id="repo-1")
    assert facts.workflows[0].steps == ["step_a", "step_b"]
