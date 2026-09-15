"""Extension -> language lookup used for the first-pass file tagging done
during ingestion (LLD Section 3: "Language is detected by extension first").

This is deliberately separate from the confidence-scored LanguageDetector in
`atlaz.parsing.language_detector` (Section 4.1): ingestion just needs a cheap
per-file label; the detector layer turns that into a repo-wide, manifest-
weighted signal used to pick parsers.
"""

from __future__ import annotations

EXTENSION_TO_LANGUAGE: dict[str, str] = {
    ".py": "python",
    ".pyi": "python",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".go": "go",
    ".java": "java",
    ".rb": "ruby",
    ".cs": "csharp",
    ".rs": "rust",
    ".php": "php",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".swift": "swift",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".hpp": "cpp",
    ".scala": "scala",
    ".sql": "sql",
    ".sh": "shell",
    ".bash": "shell",
}

SHEBANG_TO_LANGUAGE: dict[str, str] = {
    "python": "python",
    "python3": "python",
    "node": "javascript",
    "ruby": "ruby",
    "bash": "shell",
    "sh": "shell",
}


def language_for_extension(suffix: str) -> str | None:
    return EXTENSION_TO_LANGUAGE.get(suffix.lower())


def language_from_shebang(first_line: str) -> str | None:
    if not first_line.startswith("#!"):
        return None
    interpreter = first_line[2:].strip().split()[-1] if first_line[2:].strip() else ""
    interpreter_name = interpreter.rsplit("/", 1)[-1]
    return SHEBANG_TO_LANGUAGE.get(interpreter_name)
