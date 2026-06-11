"""ComplyOS buyer profile definitions and starter config rendering."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum


class ComplyOSProfile(StrEnum):
    """Supported ComplyOS operating profiles."""

    WORKFORCE = "workforce"
    CAMPUS = "campus"


@dataclass(frozen=True)
class ProfileDefinition:
    """Terms and connector recommendations for a ComplyOS profile."""

    name: str
    display_name: str
    buyer_terms: tuple[str, ...]
    learner_term: str
    learning_item_term: str
    responsible_party_term: str
    record_term: str
    gap_term: str
    recommended_connectors: tuple[str, ...]


_WORKFORCE_PROFILE = ProfileDefinition(
    name=ComplyOSProfile.WORKFORCE.value,
    display_name="ComplyOS Workforce",
    buyer_terms=("L&D", "People Ops", "HRIS", "Security Compliance"),
    learner_term="employee",
    learning_item_term="training",
    responsible_party_term="manager",
    record_term="transcript",
    gap_term="compliance gap",
    recommended_connectors=(
        "csv",
        "workday",
        "cornerstone",
        "successfactors",
        "docebo",
        "absorb",
        "litmos",
        "learnupon",
        "talentlms",
        "oracle-learning-cloud",
    ),
)

_CAMPUS_PROFILE = ProfileDefinition(
    name=ComplyOSProfile.CAMPUS.value,
    display_name="ComplyOS Campus",
    buyer_terms=("Academic Technology", "Higher-Ed IT", "Program Compliance", "District IT"),
    learner_term="student",
    learning_item_term="course",
    responsible_party_term="advisor",
    record_term="enrollment",
    gap_term="missing requirement",
    recommended_connectors=(
        "csv",
        "canvas",
        "brightspace",
        "blackboard",
        "moodle",
        "schoology",
        "google-classroom",
    ),
)

_PROFILE_ORDER = (ComplyOSProfile.WORKFORCE.value, ComplyOSProfile.CAMPUS.value)
_PROFILE_DEFINITIONS = {
    _WORKFORCE_PROFILE.name: _WORKFORCE_PROFILE,
    _CAMPUS_PROFILE.name: _CAMPUS_PROFILE,
}


def get_profile(profile: str | ComplyOSProfile) -> ProfileDefinition:
    """Return the profile definition for a supported profile name."""
    profile_name = str(profile)
    try:
        return _PROFILE_DEFINITIONS[profile_name]
    except KeyError as exc:
        valid_profiles = ", ".join(_PROFILE_ORDER)
        raise ValueError(
            f"Unknown ComplyOS profile '{profile}'. Valid profiles: {valid_profiles}"
        ) from exc


def list_profiles() -> list[ProfileDefinition]:
    """List profile definitions in the default display order."""
    return [_PROFILE_DEFINITIONS[name] for name in _PROFILE_ORDER]


def _render_yaml_list(values: Iterable[str], indent: int = 2) -> list[str]:
    padding = " " * indent
    return [f"{padding}- {value}" for value in values]


def render_profile_config(profile: str | ComplyOSProfile) -> str:
    """Render a YAML-ish starter config for a supported profile."""
    definition = get_profile(profile)
    lines = [
        f"profile: {definition.name}",
        "connector:",
        "  type: csv",
        "  csv_dir: ./examples/csv",
        "database:",
        "  path: complyos.db",
        "terms:",
        f"  learner_term: {definition.learner_term}",
        f"  learning_item_term: {definition.learning_item_term}",
        f"  responsible_party_term: {definition.responsible_party_term}",
        f"  record_term: {definition.record_term}",
        f"  gap_term: {definition.gap_term}",
        "recommended_connectors:",
        *_render_yaml_list(definition.recommended_connectors),
        "buyer_terms:",
        *_render_yaml_list(definition.buyer_terms),
    ]
    return "\n".join(lines) + "\n"
