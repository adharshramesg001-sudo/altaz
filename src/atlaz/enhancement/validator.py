"""Deterministic, LLM-free post-generation checks on drafted file
modifications -- mirrors Brownfield's `ValidationAgent` (syntax check +
naive security regex scan, no test execution, no "build"), so a proposal
surfaces obvious breakage before a human reviews it rather than only
after. Heuristic by design, same as Brownfield's: the brace-balance and
regex checks are not real parsers and can both miss real issues and flag
non-issues (braces inside a string literal, a secret-shaped test fixture).
"""

from __future__ import annotations

import re

from atlaz.enhancement.models import FileModification, FileValidation

_BRACE_EXTENSIONS = {".js", ".jsx", ".ts", ".tsx", ".java", ".cs", ".go", ".c", ".cpp", ".h", ".swift", ".kt"}
_BRACE_PAIRS = {"(": ")", "[": "]", "{": "}"}

_SQL_CONCAT_RE = re.compile(r"""(SELECT|INSERT|UPDATE|DELETE)[^"'\n]*["']\s*\+\s*\w""", re.IGNORECASE)
_SECRET_RE = re.compile(r"""(?i)(api[_-]?key|secret|password|token)\s*[:=]\s*["'][A-Za-z0-9+/_\-]{8,}["']""")


class ValidationAgent:
    def run(self, modifications: list[FileModification]) -> list[FileValidation]:
        return [self._validate_one(mod) for mod in modifications]

    def _validate_one(self, mod: FileModification) -> FileValidation:
        warnings: list[str] = []
        syntax_valid = True

        suffix = _suffix(mod.file_path)
        if suffix == ".py":
            syntax_valid, error = _check_python_syntax(mod.modified_content)
            if not syntax_valid:
                warnings.append(f"Syntax error: {error}")
        elif suffix in _BRACE_EXTENSIONS:
            syntax_valid, detail = _check_brace_balance(mod.modified_content)
            if not syntax_valid:
                warnings.append(f"Unbalanced braces/brackets/parens: {detail}")

        security_issues = []
        if _SQL_CONCAT_RE.search(mod.modified_content):
            security_issues.append("Possible SQL built via string concatenation -- use parameterized queries.")
        if _SECRET_RE.search(mod.modified_content):
            security_issues.append("Possible hardcoded secret/credential in source.")

        return FileValidation(
            file_path=mod.file_path,
            syntax_valid=syntax_valid,
            warnings=warnings,
            security_issues=security_issues,
        )


def _suffix(file_path: str) -> str:
    idx = file_path.rfind(".")
    return file_path[idx:].lower() if idx != -1 else ""


def _check_python_syntax(content: str) -> tuple[bool, str]:
    try:
        compile(content, "<modified>", "exec")
        return True, ""
    except SyntaxError as exc:
        return False, str(exc)


def _check_brace_balance(content: str) -> tuple[bool, str]:
    closing = set(_BRACE_PAIRS.values())
    stack: list[str] = []
    for ch in content:
        if ch in _BRACE_PAIRS:
            stack.append(_BRACE_PAIRS[ch])
        elif ch in closing and (not stack or stack.pop() != ch):
            return False, f"unexpected '{ch}'"
    if stack:
        return False, f"missing '{stack[-1]}'"
    return True, ""
