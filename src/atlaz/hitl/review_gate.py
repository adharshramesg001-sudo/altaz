"""ReviewGate (LLD Section 10.1).

`interrupt_fn` is injected rather than imported directly from LangGraph:
pausing a *running graph* only makes sense from inside a compiled graph's
node (LangGraph's `interrupt()` raises a control-flow exception the graph
runtime catches), so the orchestration layer passes its own callable when
`hitl_enabled` is true. Calling `route()` with the default (no interrupt_fn)
outside a graph context is only valid when `hitl_enabled=False`, which is
exactly the case that never needs one.
"""

from __future__ import annotations

from collections.abc import Callable

from atlaz.hitl.auto_resolve import auto_resolve
from atlaz.hitl.models import ReviewItem, ReviewResolution
from atlaz.shared.config import PipelineConfig


class ReviewGate:
    def route(
        self,
        flagged: list[ReviewItem],
        config: PipelineConfig,
        interrupt_fn: Callable[[list[ReviewItem]], list[ReviewResolution]] | None = None,
    ) -> list[ReviewResolution]:
        if not flagged:
            return []
        if config.hitl_enabled:
            if interrupt_fn is None:
                raise RuntimeError(
                    "hitl_enabled=True requires an interrupt_fn (supplied by the orchestration "
                    "graph's hitl_gate_node); ReviewGate cannot pause execution on its own."
                )
            return interrupt_fn(flagged)
        return auto_resolve(flagged)
