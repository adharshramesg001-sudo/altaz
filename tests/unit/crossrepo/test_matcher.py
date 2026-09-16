from atlaz.crossrepo.matcher import correlate
from atlaz.crossrepo.models import OutboundCallSignal
from atlaz.docgen.models import ApiFact, ProjectFacts, RepositoryFact, ServiceFact
from atlaz.shared.evidence import Evidence


def _facts(repo_id, name, services=None, apis=None, service_files=None):
    return ProjectFacts(
        thread_id=f"t-{repo_id}",
        repository=RepositoryFact(repo_id=repo_id, name=name),
        services=services or [],
        apis=apis or [],
        service_files=service_files or {},
    )


def test_correlate_matches_single_service_target_by_repo_name():
    source = _facts(
        "repo-a", "order-consumer", service_files={"consumer": ["client.py"]}
    )
    target = _facts("repo-b", "payment-service", services=[ServiceFact(service_id="s1", name="payment-service")])
    signal = OutboundCallSignal(host="payment-service", path="", evidence=Evidence(file="client.py", line=4))

    candidates = correlate(source, [signal], target, target_declared_names=set())

    assert len(candidates) == 1
    c = candidates[0]
    assert c.source_repo_id == "repo-a"
    assert c.source_service == "consumer"
    assert c.target_repo_id == "repo-b"
    assert c.target_service == "payment-service"
    assert c.matched_on == "service_name_only"
    assert c.confidence == 0.55


def test_correlate_boosts_confidence_on_route_overlap():
    source = _facts("repo-a", "checkout", service_files={"checkout": ["client.py"]})
    target = _facts(
        "repo-b",
        "order-service",
        services=[ServiceFact(service_id="s1", name="order-service")],
        apis=[ApiFact(api_id="a1", route="/api/orders", method="GET")],
    )
    signal = OutboundCallSignal(host="order-service", path="/api/orders", evidence=Evidence(file="client.py", line=1))

    candidates = correlate(source, [signal], target, target_declared_names=set())

    assert candidates[0].confidence == 0.85
    assert candidates[0].matched_on == "service_name_and_route"


def test_correlate_drops_unmatched_host():
    source = _facts("repo-a", "checkout", service_files={"checkout": ["client.py"]})
    target = _facts("repo-b", "order-service", services=[ServiceFact(service_id="s1", name="order-service")])
    signal = OutboundCallSignal(host="stripe.com", evidence=Evidence(file="client.py", line=1))

    assert correlate(source, [signal], target, target_declared_names=set()) == []


def test_correlate_drops_signal_with_unattributable_file():
    source = _facts("repo-a", "checkout", service_files={"checkout": ["client.py"]})
    target = _facts("repo-b", "order-service", services=[ServiceFact(service_id="s1", name="order-service")])
    signal = OutboundCallSignal(host="order-service", evidence=Evidence(file="unknown.py", line=1))

    assert correlate(source, [signal], target, target_declared_names=set()) == []


def test_correlate_requires_specific_component_when_target_has_multiple_services():
    source = _facts("repo-a", "checkout", service_files={"checkout": ["client.py"]})
    target = _facts(
        "repo-b",
        "monorepo",
        services=[ServiceFact(service_id="s1", name="orders"), ServiceFact(service_id="s2", name="payments")],
    )
    signal = OutboundCallSignal(host="monorepo", evidence=Evidence(file="client.py", line=1))

    assert correlate(source, [signal], target, target_declared_names=set()) == []
