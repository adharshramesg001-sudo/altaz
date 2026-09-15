"""Auto-Resolve Fallback Policy (LLD Section 10.3, `hitl_enabled = false`).

Turning HITL off removes the human step, not the honesty guarantee: this
policy never picks a side on a conflict and never silently drops a
low-confidence finding -- it writes everything, correctly labeled, so the
reasoning layer can still tell the truth about what's uncertain.
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
        elif item.kind == ReviewItemKind.CONFLICT:
            # Both sides written, linked by conflicts_with, with no side preferred.
            # `resolved_value` still carries the ConflictCandidate (not None) so the
            # graph writer can record both sides -- "no side preferred" describes the
            # resolution note, not an absence of data to write.
            resolved.append(
                ReviewResolution(
                    item_id=item.item_id,
                    action=ReviewAction.RESOLVE_CONFLICT,
                    resolved_value=item.subject,
                    reviewer=AUTO_RESOLVE_REVIEWER,
                    resolution_note="left unresolved -- no side preferred",
                )
            )
    return resolved
