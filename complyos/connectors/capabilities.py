"""Connector capability metadata for ComplyOS profiles."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True)
class ConnectorCapability:
    """Static capability summary for a supported or planned connector."""

    name: str
    display_name: str
    profile: str
    status: str
    auth: str
    supports_users: bool
    supports_courses: bool
    supports_assignments: bool
    supports_learning_records: bool
    supports_due_dates: bool
    supports_exemptions: bool
    supports_scores: bool
    supports_expiry: bool
    docs_url: str

    def to_dict(self) -> dict[str, str | bool]:
        """Return a JSON-serializable representation."""
        return asdict(self)


_CAPABILITIES: tuple[ConnectorCapability, ...] = (
    ConnectorCapability(
        name="csv",
        display_name="CSV Files",
        profile="both",
        status="supported",
        auth="none",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="./examples/csv",
    ),
    ConnectorCapability(
        name="document_upload",
        display_name="Document Upload",
        profile="both",
        status="supported",
        auth="none",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="./docs/document-ingest-v0.md",
    ),
    ConnectorCapability(
        name="workday",
        display_name="Workday Learning",
        profile="workforce",
        status="supported",
        auth="basic-auth",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=False,
        supports_scores=True,
        supports_expiry=False,
        docs_url="https://community.workday.com/api",
    ),
    ConnectorCapability(
        name="cornerstone",
        display_name="Cornerstone OnDemand",
        profile="workforce",
        status="supported",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://csod.dev/",
    ),
    ConnectorCapability(
        name="successfactors",
        display_name="SAP SuccessFactors Learning",
        profile="workforce",
        status="supported",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://api.sap.com/",
    ),
    ConnectorCapability(
        name="docebo",
        display_name="Docebo",
        profile="workforce",
        status="planned",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://www.docebo.com/knowledge-base/docebo-api/",
    ),
    ConnectorCapability(
        name="absorb",
        display_name="Absorb LMS",
        profile="workforce",
        status="planned",
        auth="api-key",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://support.absorblms.com/hc/en-us/articles/360053648653-Absorb-API",
    ),
    ConnectorCapability(
        name="litmos",
        display_name="Litmos",
        profile="workforce",
        status="planned",
        auth="api-key",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=False,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://support.litmos.com/hc/en-us/sections/360005029314-API",
    ),
    ConnectorCapability(
        name="learnupon",
        display_name="LearnUpon",
        profile="workforce",
        status="planned",
        auth="basic-auth",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=False,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://docs.learnupon.com/",
    ),
    ConnectorCapability(
        name="talentlms",
        display_name="TalentLMS",
        profile="workforce",
        status="planned",
        auth="api-key",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=False,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://www.talentlms.com/pages/docs/TalentLMS-API-Documentation.pdf",
    ),
    ConnectorCapability(
        name="oracle-learning-cloud",
        display_name="Oracle Learning Cloud",
        profile="workforce",
        status="planned",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=True,
        docs_url="https://docs.oracle.com/en/cloud/saas/human-resources/",
    ),
    ConnectorCapability(
        name="canvas",
        display_name="Canvas LMS",
        profile="campus",
        status="supported",
        auth="token",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=False,
        docs_url="https://canvas.instructure.com/doc/api/",
    ),
    ConnectorCapability(
        name="brightspace",
        display_name="D2L Brightspace",
        profile="campus",
        status="supported",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        # Final-grade pulls carry completion + score, but no per-item due date
        # or exemption flag, and Brightspace has no native recertification field.
        supports_due_dates=False,
        supports_exemptions=False,
        supports_scores=True,
        supports_expiry=False,
        docs_url="https://docs.valence.desire2learn.com/",
    ),
    ConnectorCapability(
        name="blackboard",
        display_name="Blackboard Learn",
        profile="campus",
        status="supported",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        # Gradebook columns carry grading.due; grades carry score + exempt flag.
        # Blackboard has no native recertification/expiry field.
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=False,
        docs_url="https://developer.anthology.com/",
    ),
    ConnectorCapability(
        name="moodle",
        display_name="Moodle",
        profile="campus",
        status="supported",
        auth="token",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        # Course-completion pulls give a completed flag + timestamp only: no due
        # date, exemption, score, or recertification field on that path.
        supports_due_dates=False,
        supports_exemptions=False,
        supports_scores=False,
        supports_expiry=False,
        docs_url="https://moodledev.io/docs/apis/webservice",
    ),
    ConnectorCapability(
        name="schoology",
        display_name="Schoology",
        profile="campus",
        status="planned",
        auth="oauth1",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=True,
        supports_scores=True,
        supports_expiry=False,
        docs_url="https://developers.schoology.com/api-documentation/rest-api-v1",
    ),
    ConnectorCapability(
        name="google-classroom",
        display_name="Google Classroom",
        profile="campus",
        status="planned",
        auth="oauth2",
        supports_users=True,
        supports_courses=True,
        supports_assignments=True,
        supports_learning_records=True,
        supports_due_dates=True,
        supports_exemptions=False,
        supports_scores=True,
        supports_expiry=False,
        docs_url="https://developers.google.com/classroom/reference/rest",
    ),
)

_VALID_PROFILES = ("all", "workforce", "campus")


def list_connector_capabilities(profile: str | None = None) -> list[ConnectorCapability]:
    """List connector capabilities, optionally filtered by profile."""
    normalized = "all" if profile is None else profile.strip().lower()
    if normalized not in _VALID_PROFILES:
        valid = ", ".join(_VALID_PROFILES)
        raise ValueError(f"Unknown connector profile '{profile}'. Valid profiles: {valid}")
    if normalized == "all":
        return list(_CAPABILITIES)
    return [item for item in _CAPABILITIES if item.profile in {normalized, "both"}]


def get_connector_capability(name: str) -> ConnectorCapability:
    """Return a connector capability by name or raise a useful error."""
    normalized = name.lower()
    for item in _CAPABILITIES:
        if item.name == normalized:
            return item
    known = ", ".join(item.name for item in _CAPABILITIES)
    raise ValueError(f"Unknown connector capability '{name}'. Known connectors: {known}")
