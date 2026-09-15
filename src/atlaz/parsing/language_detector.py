"""LanguageDetector (LLD Section 4.1).

Produces a per-language file count, not a single guess -- a polyglot repo is
parsed as one inventory with multiple active parsers, not forced into a
single-language assumption. Manifest/build files are the highest-confidence
signal and are weighted accordingly.
"""

from __future__ import annotations

from collections import Counter

from atlaz.ingestion.models import RepoInventory

MANIFEST_LANGUAGE_HINTS: dict[str, str] = {
    "package.json": "javascript",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "setup.py": "python",
    "go.mod": "go",
    "pom.xml": "java",
    "build.gradle": "java",
    "cargo.toml": "rust",
    "gemfile": "ruby",
    "composer.json": "php",
}

_MANIFEST_WEIGHT = 25  # a manifest hit outweighs a handful of stray same-extension files


class LanguageDetector:
    def detect(self, inventory: RepoInventory) -> dict[str, int]:
        counts: Counter[str] = Counter()

        for file_record in inventory.files:
            if file_record.language:
                counts[file_record.language] += 1

        for manifest_path in inventory.manifest_paths:
            filename = manifest_path.rsplit("/", 1)[-1].lower()
            hinted = MANIFEST_LANGUAGE_HINTS.get(filename)
            if hinted:
                counts[hinted] += _MANIFEST_WEIGHT

        return dict(counts.most_common())

    def primary_language(self, inventory: RepoInventory) -> str | None:
        counts = self.detect(inventory)
        if not counts:
            return None
        return max(counts, key=counts.get)
