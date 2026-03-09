"""
ORM models for the domain-scoped SQLite database (ecosystem.db).

Tables:
  Reference (seeded from organization.yaml):
    ref_teams    - team config
    ref_members  - engineer roster

  Transactional (synced from GitLab/Jira):
    mr_activity   - MR events per engineer
    team_metrics  - daily DORA/pipeline metrics per team
    jira_epics    - Jira epic cache
    engineer_stats - cached commit + review counts per engineer per period

  Sync & cache control:
    sync_status   - per-section sync state and TTL
    section_cache - cached API payloads per section+period
"""
from datetime import datetime, timezone
from sqlalchemy import (
    Column, Integer, String, Text, DateTime, Date,
    Boolean, Float, Index, UniqueConstraint
)
from backend.database_domain import DomainBase


def utc_now():
    return datetime.now(timezone.utc)


# =============================================================================
# REFERENCE TABLES  (seeded from organization.yaml, re-seeded on config change)
# =============================================================================

class RefTeam(DomainBase):
    """Canonical team registry for this domain."""
    __tablename__ = "ref_teams"

    id = Column(Integer, primary_key=True)
    slug        = Column(String, nullable=False, unique=True)
    key         = Column(String, nullable=False)
    name        = Column(String, nullable=False)
    scrum_name  = Column(String)
    jira_project= Column(String)
    gitlab_path = Column(String)
    headcount   = Column(Integer, default=0)
    em_name     = Column(String)
    em_email    = Column(String)
    products    = Column(Text)                             # JSON array
    git_provider= Column(String, default="gitlab")
    updated_at  = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_ref_teams_slug", "slug", unique=True),
        Index("ix_ref_teams_key", "key"),
        {"extend_existing": True},
    )


class RefMember(DomainBase):
    """
    Engineer roster for this domain.

    This is the authoritative source for team membership.
    Team is determined by this table, NOT by which repo an MR was opened in.
    """
    __tablename__ = "ref_members"

    id              = Column(Integer, primary_key=True)
    gitlab_username = Column(String, nullable=False, unique=True)
    name            = Column(String, nullable=False)
    email           = Column(String)
    role            = Column(String, default="engineer")
    team_slug       = Column(String, nullable=False, index=True)
    team_display    = Column(String)
    em_name         = Column(String)
    em_email        = Column(String)
    jira_project    = Column(String)
    jira_account_id = Column(String)
    gitlab_path     = Column(String)
    exclude_from_metrics = Column(Boolean, default=False)
    departed        = Column(Boolean, default=False)
    updated_at      = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_ref_members_team", "team_slug"),
        Index("ix_ref_members_username", "gitlab_username", unique=True),
        {"extend_existing": True},
    )


# =============================================================================
# TRANSACTIONAL TABLES  (synced from GitLab / Jira)
# =============================================================================

class MRActivity(DomainBase):
    """MR activity — attributed to the engineer, not the repo's team."""
    __tablename__ = "mr_activity"

    id              = Column(Integer, primary_key=True)
    mr_iid          = Column(Integer, nullable=False)
    repo_id         = Column(String, nullable=False, index=True)
    title           = Column(String, nullable=False)
    description     = Column(Text)
    source_branch   = Column(String)
    author_username = Column(String, nullable=False, index=True)
    author_team     = Column(String, index=True)
    state           = Column(String, nullable=False)
    created_at      = Column(DateTime, nullable=False, index=True)
    merged_at       = Column(DateTime, index=True)
    web_url         = Column(String)
    jira_tickets    = Column(Text)
    epic_keys       = Column(Text)
    lines_added     = Column(Integer)
    lines_removed   = Column(Integer)
    files_changed   = Column(Integer)
    cycle_time_hours= Column(Float)
    provider        = Column(String, default="gitlab")
    synced_at       = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("repo_id", "mr_iid", name="uq_mr_repo_iid"),
        Index("ix_mr_author", "author_username"),
        Index("ix_mr_author_team", "author_username", "author_team"),
        Index("ix_mr_author_created", "author_username", "created_at"),
        Index("ix_mr_created", "created_at"),
        Index("ix_mr_merged", "merged_at"),
        {"extend_existing": True},
    )


class TeamMetrics(DomainBase):
    """Daily DORA / pipeline metrics per team."""
    __tablename__ = "team_metrics"

    id                  = Column(Integer, primary_key=True)
    team                = Column(String, nullable=False)
    metric_date         = Column(Date, nullable=False)
    pipeline_runs       = Column(Integer, default=0)
    pipeline_success    = Column(Integer, default=0)
    pipeline_failed     = Column(Integer, default=0)
    avg_duration_seconds= Column(Float)
    mrs_merged          = Column(Integer, default=0)
    avg_cycle_time_hours= Column(Float)
    deployment_frequency= Column(Float)
    lead_time_hours     = Column(Float)
    change_failure_rate = Column(Float)
    mttr_hours          = Column(Float)
    dora_level          = Column(String)
    synced_at           = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("team", "metric_date", name="uq_team_date"),
        Index("ix_team_metrics_team", "team"),
        Index("ix_team_metrics_date", "metric_date"),
        {"extend_existing": True},
    )


class JiraEpic(DomainBase):
    """Jira epic cache."""
    __tablename__ = "jira_epics"

    id                  = Column(Integer, primary_key=True)
    key                 = Column(String, nullable=False, unique=True, index=True)
    project             = Column(String, index=True)
    team                = Column(String)
    summary             = Column(Text)
    status              = Column(String)
    status_category     = Column(String)
    priority            = Column(String)
    assignee            = Column(String)
    url                 = Column(String)
    progress_percent    = Column(Float)
    child_issues_total  = Column(Integer)
    child_issues_done   = Column(Integer)
    updated_date        = Column(DateTime)
    due_date            = Column(Date)
    synced_at           = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index("ix_jira_epics_team", "team"),
        Index("ix_jira_epics_status", "status_category"),
        {"extend_existing": True},
    )


class JiraChildEpic(DomainBase):
    """Maps Jira child tickets (stories, tasks, bugs) to their parent epic.

    Populated during Jira epic sync by querying child issues via
    'Epic Link' (classic) and 'parent' (next-gen) fields.
    Enables the contributor endpoint to find MRs that reference
    child tickets rather than the epic key directly.
    """
    __tablename__ = "jira_child_epic"

    child_key = Column(String, primary_key=True)
    epic_key  = Column(String, nullable=False)
    synced_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index("ix_jira_child_epic_epic_key", "epic_key"),
        {"extend_existing": True},
    )


class AlertTriageState(DomainBase):
    """Persistent user triage state for active alerts in a domain."""
    __tablename__ = "alert_triage_state"

    alert_key    = Column(String, primary_key=True)
    alert_type   = Column(String, nullable=False, index=True)
    entity_type  = Column(String, nullable=False)
    entity_key   = Column(String, nullable=False, index=True)
    status       = Column(String, nullable=False, default="open")
    owner        = Column(String)
    note         = Column(Text)
    created_at   = Column(DateTime, default=utc_now)
    updated_at   = Column(DateTime, default=utc_now, onupdate=utc_now)
    resolved_at  = Column(DateTime)

    __table_args__ = (
        Index("ix_alert_triage_state_status", "status"),
        Index("ix_alert_triage_state_type_entity", "alert_type", "entity_key"),
        {"extend_existing": True},
    )


class SavedView(DomainBase):
    """Persisted UI/report presets."""
    __tablename__ = "saved_views"

    id          = Column(Integer, primary_key=True)
    name        = Column(String, nullable=False)
    view_type   = Column(String, nullable=False, index=True)
    config_json = Column(Text, nullable=False)
    created_at  = Column(DateTime, default=utc_now)
    updated_at  = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_saved_views_type_name", "view_type", "name"),
        {"extend_existing": True},
    )


class ExecutiveDigest(DomainBase):
    """Scheduled executive digest definitions."""
    __tablename__ = "executive_digests"

    id              = Column(Integer, primary_key=True)
    name            = Column(String, nullable=False)
    saved_view_id   = Column(Integer, index=True)
    recipients_json = Column(Text, nullable=False, default="[]")
    include_pulse   = Column(Boolean, default=True)
    frequency       = Column(String, nullable=False, default="weekly")
    weekday         = Column(Integer)
    hour_utc        = Column(Integer, nullable=False, default=8)
    active          = Column(Boolean, default=True)
    last_run_at     = Column(DateTime)
    next_run_at     = Column(DateTime, index=True)
    created_at      = Column(DateTime, default=utc_now)
    updated_at      = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index("ix_executive_digests_active_next", "active", "next_run_at"),
        {"extend_existing": True},
    )


class ExecutiveDigestRun(DomainBase):
    """Stored digest generations and delivery outcomes."""
    __tablename__ = "executive_digest_runs"

    id             = Column(Integer, primary_key=True)
    digest_id      = Column(Integer, nullable=False, index=True)
    status         = Column(String, nullable=False, default="generated")
    delivery_state = Column(String, nullable=False, default="stored_only")
    recipient_count= Column(Integer, default=0)
    subject        = Column(String)
    report_markdown= Column(Text)
    report_html    = Column(Text)
    error_message  = Column(Text)
    generated_at   = Column(DateTime, default=utc_now, index=True)

    __table_args__ = (
        Index("ix_executive_digest_runs_digest_generated", "digest_id", "generated_at"),
        {"extend_existing": True},
    )


class SyncRunHistory(DomainBase):
    """Append-only sync audit trail."""
    __tablename__ = "sync_run_history"

    id               = Column(Integer, primary_key=True)
    section          = Column(String, nullable=False, index=True)
    period_days      = Column(Integer, nullable=False, default=0)
    trigger_source   = Column(String, nullable=False, default="manual")
    status           = Column(String, nullable=False, default="syncing")
    records_synced   = Column(Integer, default=0)
    error_message    = Column(Text)
    started_at       = Column(DateTime, default=utc_now, index=True)
    finished_at      = Column(DateTime)
    duration_seconds = Column(Float)

    __table_args__ = (
        Index("ix_sync_run_history_section_started", "section", "started_at"),
        {"extend_existing": True},
    )


# =============================================================================
# SYNC & CACHE CONTROL
# =============================================================================

class SyncStatus(DomainBase):
    """
    Per-section sync tracking.

    section values: engineers, team_metrics, jira_epics, repos, dora
    period_days values: 30, 60, 90  (0 = all-time / not period-specific)
    status values: idle, syncing, success, error
    """
    __tablename__ = "sync_status"

    id              = Column(Integer, primary_key=True)
    section         = Column(String, nullable=False)
    period_days     = Column(Integer, nullable=False, default=0)
    status          = Column(String, default="idle")
    last_synced_at  = Column(DateTime, index=True)
    next_sync_at    = Column(DateTime)
    records_synced  = Column(Integer, default=0)
    error_message   = Column(Text)
    duration_seconds= Column(Float)

    __table_args__ = (
        UniqueConstraint("section", "period_days", name="uq_sync_section_period"),
        Index("ix_sync_status_section", "section"),
        {"extend_existing": True},
    )


class EngineerStats(DomainBase):
    """
    Cached commit + review counts per engineer per period.

    Populated by POST /engineers/{username}/sync.
    Read by GET /engineers/{username} to avoid live GitLab calls on every page load.
    Keyed by (username, period_days) — one row per engineer per period window.
    """
    __tablename__ = "engineer_stats"

    id              = Column(Integer, primary_key=True)
    username        = Column(String, nullable=False, index=True)
    period_days     = Column(Integer, nullable=False)
    commit_count    = Column(Integer, default=0)
    review_count    = Column(Integer, default=0)
    cached_at       = Column(DateTime, default=utc_now)

    __table_args__ = (
        UniqueConstraint("username", "period_days", name="uq_engineer_stats_username_period"),
        {"extend_existing": True},
    )


class PortService(DomainBase):
    """
    Cached Port.io service catalog.

    Synced via POST /api/port/sync; read by GET /api/port/services.
    Keyed on the Port entity identifier.
    """
    __tablename__ = "port_services"

    id                  = Column(String, primary_key=True)
    title               = Column(String, nullable=False)
    department          = Column(String)
    system              = Column(String)
    domain              = Column(String)        # resolved via service→system→team→domain
    team                = Column(String, index=True)  # Port team identifier from relations.team
    language            = Column(String)
    language_version    = Column(String)        # e.g. "Java 17", "Python 3.11" (scanned via GitLab API)
    url                 = Column(String)
    description         = Column(Text)
    service_criticality = Column(String)
    publicly_exposed    = Column(Boolean, default=False)
    synced_at           = Column(DateTime, default=utc_now)

    __table_args__ = {"extend_existing": True}


class SectionCache(DomainBase):
    """
    Cached API responses per section + period.

    The dashboard first checks here; if expired or missing, triggers a sync.
    payload_json holds the full API response so the frontend never waits for
    a live API call unless explicitly requesting a refresh.
    """
    __tablename__ = "section_cache"

    id          = Column(Integer, primary_key=True)
    section     = Column(String, nullable=False)
    period_days = Column(Integer, nullable=False)
    cache_key   = Column(String, nullable=False, unique=True, index=True)
    payload_json= Column(Text, nullable=False)
    cached_at   = Column(DateTime, default=utc_now)
    expires_at  = Column(DateTime, nullable=False, index=True)
    record_count= Column(Integer, default=0)

    __table_args__ = (
        UniqueConstraint("section", "period_days", name="uq_cache_section_period"),
        Index("ix_section_cache_expires", "expires_at"),
        {"extend_existing": True},
    )
