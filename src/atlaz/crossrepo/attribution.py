"""Small helpers shared by both `atlaz.crossrepo.matcher` (sync calls) and
`atlaz.crossrepo.pubsub_service` (async messaging), kept in one place so the
two scanning paths stay consistent rather than drifting apart.
"""

from __future__ import annotations

import re

_SEPARATORS = re.compile(r"[-_\s]")


def normalize_name(name: str) -> str:
    return _SEPARATORS.sub("", name).lower()


def owning_service(file_path: str | None, service_files: dict[str, list[str]]) -> str | None:
    """Attributes a piece of scan evidence to the `Service` (component) that
    owns it, via a repo's own `service_files` map
    (`atlaz.docgen.models.ProjectFacts.service_files`, service name -> file
    paths). A signal found in a file outside any known component is dropped
    consistently rather than guessed."""
    if not file_path:
        return None
    for service, paths in service_files.items():
        if file_path in paths:
            return service
    return None
