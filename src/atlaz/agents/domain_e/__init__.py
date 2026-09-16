"""Domain E -- Engineering & Ops (LLD Section 7.5, descoped).

Architecturally represented, not executed in this build cycle: every agent
below is a fixed `false` in `capability_registry.yaml`, so
`domain_orchestrator` never dispatches a `Send()` task for this domain. This
package exists so "not built" is a runtime fact the capability registry
enforces (LLD Design Principle #9), not only a diagram annotation --
`atlaz.orchestration.capability_registry.validate_capability_registry`
would raise if any of these were ever flipped to `true` without a matching
node actually being registered.

Planned, not implemented:
- `infra_iac_parser`: infra-as-code (Terraform/Kubernetes/Dockerfiles).
- `test_coverage_analyzer`: coverage mining from test runs/CI artifacts.
- `git_pr_history_miner`: PR/commit history as a signal source.
"""
