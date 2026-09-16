"""README/Commit Signal Miner Agent (LLD Section 7.1).

First of Domain A's two nodes: gathers raw candidate signals -- README
rationale language, commit messages, code comments, naming conventions,
billing-structure hints -- and hands them to `gap_detector` (LLD Section
7.1's second node) to route. This agent never concludes anything about
*why* the product exists; every `CandidateSignal` is the raw hint itself,
each with `evidence` pointing at the exact README line, commit hash, or
comment that produced it.

Split out of the prior single-node `BusinessCaseGapDetector` per the new
LLD's two-node Domain A subgraph (§7.1); `gap_detector.py` now only
consumes `domain_a.signals`, it no longer gathers them itself.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass

from atlaz.agents.domain_b.domain_glossary import GlossaryTerm
from atlaz.agents.shared.identifiers import identifier_matches_any
from atlaz.ingestion.models import RepoInventory
from atlaz.parsing.models import ParsedModule
from atlaz.shared.evidence import Evidence

RATIONALE_PATTERNS = re.compile(
    r"\b(because|this exists to|workaround for|the reason|in order to|so that)\b", re.IGNORECASE
)
BILLING_IDENTIFIER_WORDS = frozenset(
    {"plan", "tier", "subscription", "billing", "entitlement", "feature", "flag", "gate", "pricing"}
)
_COMMIT_LOG_WINDOW = 50
_COMMIT_SEPARATOR = "\x1f"


@dataclass(slots=True)
class CandidateSignal:
    source_kind: str  # "readme" | "commit_message" | "comment" | "naming_pattern" | "billing_structure"
    text: str
    evidence: Evidence


class ReadmeCommitSignalMiner:
    def run(
        self,
        inventory: RepoInventory,
        parsed: list[ParsedModule],
        glossary: list[GlossaryTerm] | None = None,
    ) -> list[CandidateSignal]:
        signals: list[CandidateSignal] = []
        signals.extend(self._scan_readmes(inventory))
        signals.extend(self._scan_commit_messages(inventory))
        signals.extend(self._scan_comments(parsed))
        signals.extend(self._scan_naming_and_glossary(glossary or []))
        signals.extend(self._scan_billing_structure(parsed))
        return signals

    def _scan_readmes(self, inventory: RepoInventory) -> list[CandidateSignal]:
        signals = []
        for readme_path in inventory.readme_paths:
            try:
                with open(inventory.abs_path(readme_path), encoding="utf-8", errors="ignore") as fh:
                    content = fh.read()
            except OSError:
                continue
            for match in RATIONALE_PATTERNS.finditer(content):
                line = content.count("\n", 0, match.start()) + 1
                snippet = content[max(0, match.start() - 40) : match.end() + 80].strip()
                signals.append(
                    CandidateSignal(source_kind="readme", text=snippet, evidence=Evidence(file=readme_path, line=line))
                )
            if content.strip() and not signals:
                first_line = content.strip().splitlines()[0]
                signals.append(
                    CandidateSignal(source_kind="readme", text=first_line, evidence=Evidence(file=readme_path, line=1))
                )
        return signals

    def _scan_commit_messages(self, inventory: RepoInventory) -> list[CandidateSignal]:
        try:
            result = subprocess.run(
                ["git", "log", f"-n{_COMMIT_LOG_WINDOW}", f"--format=%H{_COMMIT_SEPARATOR}%s %b"],
                cwd=inventory.repo_root,
                capture_output=True,
                text=True,
                timeout=10,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if result.returncode != 0:
            return []

        signals = []
        for line in result.stdout.splitlines():
            if _COMMIT_SEPARATOR not in line:
                continue
            commit_sha, message = line.split(_COMMIT_SEPARATOR, 1)
            message = message.strip()
            if not message or not RATIONALE_PATTERNS.search(message):
                continue
            signals.append(
                CandidateSignal(
                    source_kind="commit_message",
                    text=message,
                    evidence=Evidence(commit=commit_sha, note="commit message"),
                )
            )
        return signals

    def _scan_comments(self, parsed: list[ParsedModule]) -> list[CandidateSignal]:
        signals = []
        for module in parsed:
            for comment in module.comments:
                if RATIONALE_PATTERNS.search(comment.text):
                    signals.append(
                        CandidateSignal(
                            source_kind="comment", text=comment.text, evidence=Evidence(file=module.file_path, line=comment.line)
                        )
                    )
        return signals

    def _scan_naming_and_glossary(self, glossary: list[GlossaryTerm]) -> list[CandidateSignal]:
        signals = []
        top_terms = sorted(glossary, key=lambda t: t.occurrence_count, reverse=True)[:10]
        for term in top_terms:
            evidence = term.evidence[0] if term.evidence else Evidence.gap()
            signals.append(CandidateSignal(source_kind="naming_pattern", text=term.term, evidence=evidence))
        return signals

    def _scan_billing_structure(self, parsed: list[ParsedModule]) -> list[CandidateSignal]:
        signals = []
        for module in parsed:
            for cls in module.classes:
                if identifier_matches_any(cls.name, BILLING_IDENTIFIER_WORDS):
                    signals.append(
                        CandidateSignal(
                            source_kind="billing_structure",
                            text=f"class {cls.name}",
                            evidence=Evidence(file=module.file_path, line=cls.line_start),
                        )
                    )
                for f in cls.fields:
                    if identifier_matches_any(f.name, BILLING_IDENTIFIER_WORDS):
                        signals.append(
                            CandidateSignal(
                                source_kind="billing_structure",
                                text=f"{cls.name}.{f.name}" + (f" = {f.value_expr}" if f.value_expr else ""),
                                evidence=Evidence(file=module.file_path, line=f.line or cls.line_start),
                            )
                        )
        return signals
