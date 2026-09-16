"""Raw source/config scan for cross-repo call evidence.

Runs directly against a repo's files on disk (no re-ingestion, no parser
reuse -- these are lightweight regex/YAML scans, matching the style of
`atlaz.agents.domain_d.api_contract_parser`'s route-decorator regexes and
its optional-PyYAML pattern).

Deliberately broad rather than tied to a specific HTTP client library: a
literal `http(s)://host[:port][/path]` is scanned wherever it appears
(source code, `docker-compose.yml`, `.env.example`, k8s manifests, ...),
since real services declare each other's location in config as often as in
call sites. Precision comes later, in `atlaz.crossrepo.matcher`, by
requiring the host to match a name the *target* repo actually declares for
itself -- an unrelated public URL (e.g. a payment gateway) never matches
anything and is dropped there, not here.
"""

from __future__ import annotations

import re
from pathlib import Path

from atlaz.ingestion.repo_ingestor import DEFAULT_IGNORE_DIRS
from atlaz.shared.evidence import Evidence

try:
    import yaml
except ImportError:  # pragma: no cover - PyYAML ships with most stacks but stay defensive
    yaml = None

from atlaz.crossrepo.models import OutboundCallSignal, PubSubSignal

_MAX_FILE_BYTES = 1_000_000
_TEXT_SUFFIXES = frozenset(
    {
        ".py", ".js", ".jsx", ".ts", ".tsx", ".go", ".java", ".rb", ".php", ".cs",
        ".yml", ".yaml", ".json", ".env", ".txt", ".cfg", ".ini", ".toml",
    }
)

_URL_LITERAL_PATTERN = re.compile(r"https?://([A-Za-z0-9_.-]+)(?::\d+)?(/[^\s\"'<>]*)?")

_ENV_VAR_PATTERNS = [
    re.compile(r"os\.environ\[\s*['\"]([A-Z][A-Z0-9_]*)['\"]\s*\]"),
    re.compile(r"os\.environ\.get\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"os\.getenv\(\s*['\"]([A-Z][A-Z0-9_]*)['\"]"),
    re.compile(r"process\.env\.([A-Z][A-Z0-9_]*)"),
]
_ENV_NAME_SUFFIXES = ("_BASE_URL", "_URL", "_HOST", "_ENDPOINT", "_SERVICE", "_API")

_COMPOSE_FILENAMES = ("docker-compose.yml", "docker-compose.yaml", "compose.yml", "compose.yaml")

# (library, direction, pattern) -- one capture group each, the topic/queue
# name. Best-effort, not exhaustive: erring toward missing a signal rather
# than asserting a wrong one, same philosophy as `_ROUTE_DECORATOR_PATTERNS`
# in `api_contract_parser.py`. Order matters only in that more specific
# patterns are listed before more general ones where two could both match
# the same line.
_PUBSUB_PATTERNS: list[tuple[str, str, re.Pattern[str]]] = [
    ("kafka", "publish", re.compile(r"\.(?:send|produce)\(\s*f?['\"]([^'\"]+)['\"]")),
    ("kafka", "consume", re.compile(r"\.subscribe\(\s*\[?\s*f?['\"]([^'\"]+)['\"]")),
    ("rabbitmq", "publish", re.compile(r"basic_publish\([^)]*routing_key\s*=\s*['\"]([^'\"]+)['\"]")),
    ("rabbitmq", "consume", re.compile(r"basic_consume\([^)]*queue\s*=\s*['\"]([^'\"]+)['\"]")),
    ("sqs", "publish", re.compile(r"send_message\([^)]*QueueUrl\s*=\s*['\"][^'\"]*/([^'\"/]+)['\"]")),
    ("sqs", "consume", re.compile(r"receive_message\([^)]*QueueUrl\s*=\s*['\"][^'\"]*/([^'\"/]+)['\"]")),
    (
        "azure_servicebus",
        "publish",
        re.compile(r"get_(?:queue|topic)_sender\([^)]*(?:queue|topic)_name\s*=\s*['\"]([^'\"]+)['\"]"),
    ),
    (
        "azure_servicebus",
        "consume",
        re.compile(r"get_(?:queue_receiver|subscription_receiver)\([^)]*(?:queue|topic)_name\s*=\s*['\"]([^'\"]+)['\"]"),
    ),
    ("redis_streams", "publish", re.compile(r"\.xadd\(\s*f?['\"]([^'\"]+)['\"]")),
    ("redis_streams", "consume", re.compile(r"\.xread(?:group)?\([^)]*['\"]([^'\"]+)['\"]\s*:")),
    ("google_pubsub", "publish", re.compile(r"topic_path\([^,]+,\s*['\"]([^'\"]+)['\"]")),
    ("google_pubsub", "consume", re.compile(r"subscription_path\([^,]+,\s*['\"]([^'\"]+)['\"]")),
]


def _iter_text_files(repo_path: str):
    root = Path(repo_path).resolve()
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _TEXT_SUFFIXES:
            continue
        if any(part in DEFAULT_IGNORE_DIRS for part in path.relative_to(root).parts):
            continue
        try:
            if path.stat().st_size > _MAX_FILE_BYTES:
                continue
        except OSError:
            continue
        yield root, path


def _relative_posix(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _strip_env_suffix(name: str) -> str:
    for suffix in _ENV_NAME_SUFFIXES:
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return name


def scan_outbound_calls(repo_path: str) -> list[OutboundCallSignal]:
    signals: list[OutboundCallSignal] = []
    for root, path in _iter_text_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel_path = _relative_posix(root, path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            for match in _URL_LITERAL_PATTERN.finditer(line):
                host, url_path = match.group(1), match.group(2) or ""
                signals.append(
                    OutboundCallSignal(
                        host=host,
                        path=url_path,
                        raw_target=match.group(0),
                        evidence=Evidence(file=rel_path, line=line_no),
                    )
                )
            for pattern in _ENV_VAR_PATTERNS:
                for match in pattern.finditer(line):
                    env_name = match.group(1)
                    host = _strip_env_suffix(env_name)
                    if host == env_name:
                        continue  # no recognized service-ish suffix -- too noisy to trust
                    signals.append(
                        OutboundCallSignal(
                            host=host,
                            raw_target=env_name,
                            evidence=Evidence(file=rel_path, line=line_no),
                        )
                    )
    return signals


def scan_pubsub_signals(repo_path: str) -> list[PubSubSignal]:
    signals: list[PubSubSignal] = []
    for root, path in _iter_text_files(repo_path):
        text = path.read_text(encoding="utf-8", errors="ignore")
        rel_path = _relative_posix(root, path)
        for line_no, line in enumerate(text.splitlines(), start=1):
            for library, direction, pattern in _PUBSUB_PATTERNS:
                match = pattern.search(line)
                if not match:
                    continue
                signals.append(
                    PubSubSignal(
                        direction=direction,
                        topic=match.group(1),
                        library=library,
                        evidence=Evidence(file=rel_path, line=line_no),
                    )
                )
    return signals


def scan_declared_service_names(repo_path: str) -> set[str]:
    if yaml is None:
        return set()
    names: set[str] = set()
    root = Path(repo_path).resolve()

    for filename in _COMPOSE_FILENAMES:
        compose_path = root / filename
        if not compose_path.is_file():
            continue
        spec = _load_yaml(compose_path)
        if isinstance(spec, dict) and isinstance(spec.get("services"), dict):
            names.update(spec["services"].keys())

    for _, path in _iter_text_files(repo_path):
        if path.suffix.lower() not in (".yml", ".yaml") or path.name in _COMPOSE_FILENAMES:
            continue
        for doc in _load_yaml_all(path):
            if isinstance(doc, dict) and doc.get("kind") == "Service":
                metadata = doc.get("metadata")
                if isinstance(metadata, dict) and isinstance(metadata.get("name"), str):
                    names.add(metadata["name"])
    return names


def _load_yaml(path: Path) -> object | None:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return yaml.safe_load(text)
    except Exception:  # noqa: BLE001 - malformed/foreign YAML must not crash the scan
        return None


def _load_yaml_all(path: Path) -> list[object]:
    try:
        text = path.read_text(encoding="utf-8", errors="ignore")
        return [doc for doc in yaml.safe_load_all(text) if doc is not None]
    except Exception:  # noqa: BLE001 - malformed/foreign YAML must not crash the scan
        return []
