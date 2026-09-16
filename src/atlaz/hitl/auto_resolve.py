"""Auto-Resolve Fallback Policy for the three-tier HITL gate (`hitl_enabled
= false`) -- gap confirmations and low-confidence findings only. Cross-
domain conflict auto-resolution is a separate policy now, see
`atlaz.orchestration.dispute_resolution`.

Turning HITL off removes the human step, not the honesty guarantee: this
policy never silently drops a low-confidence finding -- it writes
everything, correctly labeled, so the reasoning layer can still tell the
truth about what's uncertain.
"""

from __future__ import annotations

from atlaz.hitl.models import ReviewAction, ReviewItem, ReviewItemKind, ReviewResolution

AUTO_RESOLVE_REVIEWER = "auto-resolve-policy"


def auto_resolve(flagged: list[ReviewItem]) -> list[ReviewResolution]:
    resolved: list[ReviewResolution] = []
    for item in flagged:
        if item.kind == ReviewItemKind.GAP_CONFIRMATION:
            # Written as an open, unfilled gap node -- never fabricated.
            resolved.append(
                ReviewResolution(
                    item_id=item.item_id,
                    action=ReviewAction.REJECT,  # "reject" here means "leave open," not "discard"
                    resolved_value=None,
                    reviewer=AUTO_RESOLVE_REVIEWER,
                    resolution_note="unknown -- not extractable from code",
                )
            )
        elif item.kind == ReviewItemKind.LOW_CONFIDENCE_FINDING:
            # Written to the graph, but flagged for any downstream query.
            resolved.append(
                ReviewResolution(
                    item_id=item.item_id,
                    action=ReviewAction.ACCEPT,
                    resolved_value=item.subject,
                    reviewer=AUTO_RESOLVE_REVIEWER,
                    resolution_note="accepted as-is; needs_review=true",
                )
            )
    return resolved
