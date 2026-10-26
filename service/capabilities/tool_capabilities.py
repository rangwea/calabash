"""Declarative optional capabilities, checked before any tool code executes."""

import re
from dataclasses import dataclass

from service.capabilities.capability_manifest import PACK_IDS, VERSION, version_key
from service.capabilities.capability_packs import official_manager
from service.tools.tool_metadata import parse_tool_metadata

_REQUIREMENT = re.compile(rf"(?P<id>[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+)(?:\s*>=\s*(?P<version>{VERSION}))?")


@dataclass(frozen=True)
class Requirement:
    id: str
    minimum: str | None = None

    @property
    def label(self):
        return self.id + (f">={self.minimum}" if self.minimum else "")


@dataclass(frozen=True)
class CapabilityIssue:
    requirement: Requirement
    reason: str
    installed: str | None = None


class ToolCapabilityError(ValueError):
    def __init__(self, requirements=(), issues=(), *, invalid=False):
        self.requirements = tuple(requirements)
        self.issues = tuple(issues)
        self.invalid = invalid
        super().__init__("Invalid tool capability declaration" if invalid else "Tool capabilities are not ready")


def parse_requirements(content: str) -> tuple[Requirement, ...]:
    value = parse_tool_metadata(content).get("requires", "")
    if not value:
        return ()
    if len(value) > 2048:
        raise ToolCapabilityError(invalid=True)
    parts = value.split(",")
    if len(parts) > 16:
        raise ToolCapabilityError(invalid=True)
    result, seen = [], set()
    for part in parts:
        match = _REQUIREMENT.fullmatch(part.strip())
        if match is None or match["id"] in seen:
            raise ToolCapabilityError(invalid=True)
        seen.add(match["id"])
        result.append(Requirement(match["id"], match["version"]))
    return tuple(result)


def check_requirements(requirements, manager=None) -> tuple[CapabilityIssue, ...]:
    if not requirements:
        return ()
    manager = manager if manager is not None else official_manager()
    issues = []
    for requirement in requirements:
        if requirement.id not in PACK_IDS or requirement.id not in manager.selfchecks:
            issues.append(CapabilityIssue(requirement, "unsupported"))
            continue
        try:
            status = manager.status(requirement.id)
            installed = status.get("version")
            if status["state"] != "ready":
                reason = "damaged" if status["state"] == "invalid" else "missing"
                issues.append(CapabilityIssue(requirement, reason, installed))
            elif requirement.minimum and version_key(installed) < version_key(requirement.minimum):
                issues.append(CapabilityIssue(requirement, "version", installed))
        except (OSError, ValueError, KeyError, TypeError):
            issues.append(CapabilityIssue(requirement, "damaged"))
    return tuple(issues)


def require_tool_capabilities(content: str):
    requirements = parse_requirements(content)
    issues = check_requirements(requirements)
    if issues:
        raise ToolCapabilityError(requirements, issues)
