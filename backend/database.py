from sqlalchemy import create_engine, event, Column, Integer, String, Text, DateTime, Date, Boolean, Index, ForeignKey, Float, Table, text, JSON
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker, relationship, backref
from sqlalchemy.sql import func
from datetime import datetime, timezone
import os
from dotenv import load_dotenv

load_dotenv()

# Helper function for SQLAlchemy default values
def utc_now():
    return datetime.now(timezone.utc)

# Get the project root directory (one level up from backend)
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_DB_PATH = os.path.join(PROJECT_ROOT, "eng_dashboard.db")

# Use absolute path to ensure we're pointing to project root database
DATABASE_URL = os.getenv("DATABASE_URL", f"sqlite:///{DEFAULT_DB_PATH}")


# Configure SQLite with timeout for concurrent access
if "sqlite" in DATABASE_URL:
    engine = create_engine(
        DATABASE_URL,
        connect_args={
            "check_same_thread": False,
            "timeout": 30  # 30 second timeout for database locks
        }
    )

    @event.listens_for(engine, "connect")
    def _set_sqlite_pragma(dbapi_connection, connection_record):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA synchronous=NORMAL")
        cursor.close()
else:
    engine = create_engine(DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()

# Junction table for many-to-many Entry-Collection relationship
entry_collections = Table('entry_collections', Base.metadata,
    Column('entry_id', Integer, ForeignKey('entries.id'), primary_key=True),
    Column('collection_id', Integer, ForeignKey('collections.id'), primary_key=True),
    Column('added_at', DateTime, default=utc_now)
)

# Junction table for many-to-many Entry-Tag relationship (normalized tags)
entry_tags = Table('entry_tags', Base.metadata,
    Column('entry_id', Integer, ForeignKey('entries.id', ondelete='CASCADE'), primary_key=True),
    Column('tag_id', Integer, ForeignKey('tags.id', ondelete='CASCADE'), primary_key=True),
    Column('created_at', DateTime, default=utc_now)
)

class Entry(Base):
    __tablename__ = "entries"

    id = Column(Integer, primary_key=True, index=True)
    date = Column(DateTime, default=utc_now, index=True)
    source_type = Column(String, index=True)  # slack, confluence, onedrive, manual, web, slash_command
    title = Column(String)
    summary = Column(Text)
    url = Column(String)
    content = Column(Text)
    tags = Column(String)  # comma-separated tags
    ai_summary = Column(Text)
    due_date = Column(DateTime, index=True)  # For slash command todos and reminders
    priority = Column(String, default="medium")  # high, medium, low
    entry_type = Column(String, default="entry", index=True)  # entry, todo, reminder, meeting
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    is_favorite = Column(Boolean, default=False)
    is_archived = Column(Boolean, default=False, index=True)
    
    __table_args__ = (
        Index('ix_entries_date_source', 'date', 'source_type'),
        Index('ix_entries_fulltext', 'title', 'summary', 'content'),
    )
    
    # Relationships to structured data
    todos = relationship("Todo", back_populates="source_entry", cascade="all, delete-orphan")
    reminders = relationship("Reminder", back_populates="source_entry", cascade="all, delete-orphan")
    decisions = relationship("Decision", back_populates="source_entry", cascade="all, delete-orphan")
    key_info = relationship("KeyInfo", back_populates="source_entry", cascade="all, delete-orphan")
    unified_todos = relationship("UnifiedTodo", back_populates="source_entry", cascade="all, delete-orphan")
    
    # Many-to-many relationship with Collections
    collections = relationship("Collection", secondary=entry_collections, back_populates="entries")

    # Many-to-many relationship with Tags (normalized)
    tag_objects = relationship("Tag", secondary=entry_tags, back_populates="entries")

# New structured tables for intelligent extraction
class Todo(Base):
    __tablename__ = "todos"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    due_date = Column(DateTime, index=True)
    priority = Column(String, default="medium")  # high, medium, low
    status = Column(String, default="pending")  # pending, in_progress, completed, cancelled
    project = Column(String)
    assignee = Column(String)  # Who this is assigned to
    completed = Column(Boolean, default=False)
    completed_at = Column(DateTime)
    source_entry_id = Column(Integer, ForeignKey("entries.id"))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship to Entry
    source_entry = relationship("Entry", back_populates="todos")

class Reminder(Base):
    __tablename__ = "reminders"

    id = Column(Integer, primary_key=True, index=True)
    what = Column(String, nullable=False)
    description = Column(Text)
    remind_at = Column(DateTime, index=True)
    notification_sent = Column(Boolean, default=False)
    completed = Column(Boolean, default=False)
    snoozed_until = Column(DateTime)
    is_recurring = Column(Boolean, default=False)
    recurring_pattern = Column(String)  # daily, weekly, monthly, yearly
    recurring_interval = Column(Integer, default=1)  # every N days/weeks/months
    last_reminded = Column(DateTime)
    next_remind_at = Column(DateTime, index=True)
    priority = Column(String, default="medium")  # high, medium, low
    source_entry_id = Column(Integer, ForeignKey("entries.id"))
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship to Entry
    source_entry = relationship("Entry", back_populates="reminders")


class UnifiedTodo(Base):
    """
    SINGLE SOURCE OF TRUTH for all tasks, actions, decisions, and reminders.

    Consolidates: todos, suggested_actions, decisions, reminders, commitments.
    NO MORE SILOS - everything goes here.

    Item types:
    - todo: General task (manual or extracted)
    - action: AI-suggested or extracted action items
    - decision: Decisions made (status=completed when logged)
    - reminder: Time-triggered notification
    - commitment: Promise made/received (has direction: to_me/by_me)
    - follow_up: Generic follow-up item
    """
    __tablename__ = "unified_todos"

    id = Column(Integer, primary_key=True, index=True)

    # Core fields
    title = Column(String, nullable=False)
    description = Column(Text)

    # Type discrimination
    item_type = Column(String, default="todo", index=True)  # todo, reminder, commitment, action_item, decision_review, follow_up

    # Timing
    due_date = Column(DateTime, index=True)
    remind_at = Column(DateTime, index=True)  # For reminders - when to notify

    # Ownership & relationships
    owner = Column(String, index=True)  # Who's responsible (you or someone else)
    assignee = Column(String, index=True)  # Who it's assigned to (if different from owner)
    related_person = Column(String, index=True)  # Person it relates to
    direction = Column(String)  # "to_me" (they owe you) or "by_me" (you owe them) - for commitments
    recipient = Column(String)  # Who the commitment is to

    # Organization
    priority = Column(String, default="medium")  # high, medium, low, urgent
    urgency = Column(String)  # high, medium, low - for actions (maps from suggested_actions)
    project = Column(String, index=True)
    tags = Column(JSON, default=list)  # Flexible tagging
    related_epic = Column(String)  # Jira epic key if related

    # AI/extraction metadata
    confidence = Column(Float)  # AI confidence score (0-1)
    decision_date = Column(DateTime)  # For decisions - when it was made

    # Status
    status = Column(String, default="pending", index=True)  # pending, in_progress, completed, cancelled, snoozed
    completed = Column(Boolean, default=False, index=True)
    completed_at = Column(DateTime)
    completion_notes = Column(Text)
    snoozed_until = Column(DateTime)

    # Recurrence (for reminders)
    is_recurring = Column(Boolean, default=False)
    recurring_pattern = Column(String)  # daily, weekly, monthly, yearly
    recurring_interval = Column(Integer, default=1)  # every N days/weeks/months
    next_occurrence = Column(DateTime)

    # Notification tracking
    notification_sent = Column(Boolean, default=False)
    last_reminded = Column(DateTime)
    follow_up_count = Column(Integer, default=0)

    # Source tracking - where did this come from?
    source_type = Column(String, index=True)  # entry, meeting, nlp_detected, manual, migration
    source_id = Column(Integer)  # ID in source table (polymorphic reference)
    source_table = Column(String)  # Which table: entries, meeting_outcomes, commitments, etc.
    source_context = Column(String)  # Human-readable context (meeting name, etc.)
    source_entry_id = Column(Integer, ForeignKey("entries.id"))  # Direct FK to entries if applicable

    # Metadata
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship to Entry
    source_entry = relationship("Entry", back_populates="unified_todos")

    __table_args__ = (
        Index('ix_unified_todos_due_date_status', 'due_date', 'status'),
        Index('ix_unified_todos_type_status', 'item_type', 'status'),
        Index('ix_unified_todos_owner_status', 'owner', 'status'),
    )


class Decision(Base):
    __tablename__ = "decisions"
    
    id = Column(Integer, primary_key=True, index=True)
    statement = Column(Text, nullable=False)
    owner = Column(String)
    decision_date = Column(DateTime, default=utc_now)
    source_entry_id = Column(Integer, ForeignKey("entries.id"))
    created_at = Column(DateTime, default=utc_now)
    
    # Relationship to Entry
    source_entry = relationship("Entry", back_populates="decisions")

class KeyInfo(Base):
    __tablename__ = "key_info"
    
    id = Column(Integer, primary_key=True, index=True)
    fact = Column(Text, nullable=False)
    tags = Column(String)  # JSON string of tags
    source_entry_id = Column(Integer, ForeignKey("entries.id"))
    created_at = Column(DateTime, default=utc_now)
    
    # Relationship to Entry
    source_entry = relationship("Entry", back_populates="key_info")

class Source(Base):
    __tablename__ = "sources"
    
    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, index=True)  # slack, confluence, onedrive, web, file, etc.
    title = Column(String)
    url = Column(String)
    ref = Column(String)  # external reference ID
    tags = Column(String)  # JSON string of tags
    created_at = Column(DateTime, default=utc_now)

class AIConversation(Base):
    __tablename__ = "ai_conversations"
    
    id = Column(Integer, primary_key=True, index=True)
    entry_ids = Column(String)  # comma-separated entry IDs
    prompt = Column(Text)
    response = Column(Text)
    model = Column(String)  # gpt-4, claude, etc.
    created_at = Column(DateTime, default=utc_now)

class Collection(Base):
    __tablename__ = "collections"
    
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    parent_id = Column(Integer, ForeignKey("collections.id"), nullable=True)
    description = Column(Text)
    color = Column(String)  # Hex color for UI (#FF5733)
    icon = Column(String)   # Icon identifier (folder, project, etc.)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    
    # Self-referential relationship for nested folders
    children = relationship("Collection", backref=backref("parent", remote_side=[id]))
    
    # Many-to-many relationship with Entries
    entries = relationship("Entry", secondary=entry_collections, back_populates="collections")
    
    __table_args__ = (
        Index('ix_collections_parent_name', 'parent_id', 'name'),
    )


class Tag(Base):
    """Normalized tag for efficient tag-based queries"""
    __tablename__ = "tags"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), unique=True, nullable=False, index=True)  # Lowercase, hyphenated
    display_name = Column(String(100), nullable=False)  # Human-readable form
    description = Column(String(500))
    color = Column(String(7), default='#3b82f6')  # Hex color
    icon = Column(String(50), default='tag')
    tag_type = Column(String(20), default='manual')  # manual, auto, smart, system
    is_system = Column(Boolean, default=False)
    usage_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Many-to-many relationship with Entries
    entries = relationship("Entry", secondary=entry_tags, back_populates="tag_objects")

    __table_args__ = (
        Index('ix_tags_name_lower', func.lower(name)),
    )


class AlertRule(Base):
    """Configurable alert rules for proactive monitoring"""
    __tablename__ = "alert_rules"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True)  # e.g., "critical_security_vuln"
    display_name = Column(String, nullable=False)  # e.g., "Critical Security Vulnerability"
    description = Column(Text)
    alert_type = Column(String, nullable=False, index=True)  # security, delivery, dora, capacity
    severity = Column(String, default="high")  # critical, high, medium, low
    enabled = Column(Boolean, default=True)
    threshold_value = Column(Float)  # Numeric threshold if applicable
    threshold_operator = Column(String)  # gt, lt, eq, gte, lte, change_pct
    check_interval_minutes = Column(Integer, default=30)  # How often to check
    cooldown_minutes = Column(Integer, default=240)  # Min time between alerts of same type
    email_enabled = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship to alerts
    alerts = relationship("Alert", back_populates="rule", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_alert_rules_type', 'alert_type'),
        Index('ix_alert_rules_enabled', 'enabled'),
    )


class Alert(Base):
    """Triggered alerts history"""
    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, index=True)
    rule_id = Column(Integer, ForeignKey("alert_rules.id"), nullable=False)
    triggered_at = Column(DateTime, default=utc_now, index=True)
    severity = Column(String, nullable=False)  # critical, high, medium, low
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    details = Column(Text)  # JSON with additional context
    source_identifier = Column(String, index=True)  # e.g., epic key, snyk org, team name
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime)
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime)
    acknowledged_by = Column(String)
    resolved = Column(Boolean, default=False)
    resolved_at = Column(DateTime)

    # Relationship to rule
    rule = relationship("AlertRule", back_populates="alerts")

    __table_args__ = (
        Index('ix_alerts_triggered_at', 'triggered_at'),
        Index('ix_alerts_severity', 'severity'),
        Index('ix_alerts_acknowledged', 'acknowledged'),
        Index('ix_alerts_resolved', 'resolved'),
    )


class AlertMetricSnapshot(Base):
    """Historical metric snapshots for trend detection"""
    __tablename__ = "alert_metric_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    metric_name = Column(String, nullable=False, index=True)  # e.g., "snyk_critical_count", "dora_lead_time"
    metric_value = Column(Float, nullable=False)
    team = Column(String, index=True)  # Team identifier if team-specific
    captured_at = Column(DateTime, default=utc_now, index=True)
    extra_data = Column(Text)  # JSON for additional context

    __table_args__ = (
        Index('ix_metric_snapshots_name_time', 'metric_name', 'captured_at'),
        Index('ix_metric_snapshots_team_time', 'team', 'captured_at'),
    )


# =============================================================================
# STRATEGIC PLANNING MODELS
# =============================================================================

class TeamVelocity(Base):
    """Historical team velocity tracking for capacity forecasting"""
    __tablename__ = "team_velocity"

    id = Column(Integer, primary_key=True, index=True)
    team = Column(String, nullable=False, index=True)
    sprint_name = Column(String)  # e.g., "Sprint 23.4"
    sprint_start = Column(Date, nullable=False)
    sprint_end = Column(Date, nullable=False)
    story_points_committed = Column(Float, default=0)
    story_points_completed = Column(Float, default=0)
    epics_completed = Column(Integer, default=0)
    bugs_fixed = Column(Integer, default=0)
    team_size = Column(Integer)  # Number of devs this sprint
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_velocity_team_sprint', 'team', 'sprint_start'),
    )


class TeamPTO(Base):
    """PTO and holidays for capacity planning"""
    __tablename__ = "team_pto"

    id = Column(Integer, primary_key=True, index=True)
    team = Column(String, nullable=False, index=True)
    member_name = Column(String, nullable=False)
    start_date = Column(Date, nullable=False, index=True)
    end_date = Column(Date, nullable=False)
    pto_type = Column(String, default="pto")  # pto, sick, holiday, training
    notes = Column(String)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_pto_team_dates', 'team', 'start_date', 'end_date'),
    )


class TeamHeadcount(Base):
    """Team headcount and open positions tracking"""
    __tablename__ = "team_headcount"

    id = Column(Integer, primary_key=True, index=True)
    team = Column(String, nullable=False, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)
    current_headcount = Column(Integer, nullable=False)
    approved_headcount = Column(Integer)  # Target headcount
    open_positions = Column(Integer, default=0)
    positions_in_pipeline = Column(Integer, default=0)  # Candidates interviewing
    expected_hire_date = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_headcount_team_date', 'team', 'snapshot_date'),
    )


class EpicComplexity(Base):
    """Epic complexity estimates for forecasting"""
    __tablename__ = "epic_complexity"

    id = Column(Integer, primary_key=True, index=True)
    epic_key = Column(String, nullable=False, unique=True, index=True)
    team = Column(String, nullable=False, index=True)
    title = Column(String)
    complexity = Column(String, default="medium")  # xs, small, medium, large, xl
    story_point_estimate = Column(Float)
    estimated_sprints = Column(Float)  # How many sprints to complete
    confidence = Column(String, default="medium")  # low, medium, high
    risks = Column(Text)  # JSON array of risk factors
    dependencies_json = Column(Text)  # JSON array of dependency epic keys
    target_quarter = Column(String)  # e.g., "Q1 2025"
    predicted_completion = Column(Date)
    actual_completion = Column(Date)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_epic_complexity_team', 'team'),
        Index('ix_epic_complexity_quarter', 'target_quarter'),
    )


class InvestmentCategory(Base):
    """Work categorization for investment tracking"""
    __tablename__ = "investment_categories"

    id = Column(Integer, primary_key=True, index=True)
    epic_key = Column(String, nullable=False, unique=True, index=True)
    team = Column(String, nullable=False, index=True)
    title = Column(String)
    category = Column(String, nullable=False)  # new_feature, maintenance, tech_debt, platform
    subcategory = Column(String)  # More specific categorization
    quarter = Column(String, nullable=False, index=True)  # e.g., "Q4 2024"
    story_points = Column(Float, default=0)
    capex_opex = Column(String)  # capex, opex
    business_value = Column(String)  # high, medium, low
    strategic_alignment = Column(String)  # JSON array of strategic themes
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_investment_team_quarter', 'team', 'quarter'),
        Index('ix_investment_category', 'category'),
    )


class InvestmentTrend(Base):
    """Quarterly investment distribution snapshots"""
    __tablename__ = "investment_trends"

    id = Column(Integer, primary_key=True, index=True)
    team = Column(String, nullable=False, index=True)
    quarter = Column(String, nullable=False, index=True)  # e.g., "Q4 2024"
    new_feature_pct = Column(Float, default=0)
    maintenance_pct = Column(Float, default=0)
    tech_debt_pct = Column(Float, default=0)
    platform_pct = Column(Float, default=0)
    new_feature_points = Column(Float, default=0)
    maintenance_points = Column(Float, default=0)
    tech_debt_points = Column(Float, default=0)
    platform_points = Column(Float, default=0)
    total_points = Column(Float, default=0)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_investment_trend_team_quarter', 'team', 'quarter'),
    )


class EpicDependency(Base):
    """Cross-team and external dependencies"""
    __tablename__ = "epic_dependencies"

    id = Column(Integer, primary_key=True, index=True)
    source_epic = Column(String, nullable=False, index=True)  # Epic that depends on something
    source_team = Column(String, nullable=False)
    target_epic = Column(String, index=True)  # Epic it depends on (null for external)
    target_team = Column(String)  # Team that owns the dependency
    dependency_type = Column(String, nullable=False)  # blocks, depends_on, related
    external_type = Column(String)  # platform, infra, vendor, other_domain
    external_description = Column(String)  # Description for external deps
    status = Column(String, default="open")  # open, in_progress, resolved, blocked
    priority = Column(String, default="medium")  # critical, high, medium, low
    due_date = Column(Date)
    resolved_date = Column(Date)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_dependency_source', 'source_epic'),
        Index('ix_dependency_target', 'target_epic'),
        Index('ix_dependency_status', 'status'),
        Index('ix_dependency_teams', 'source_team', 'target_team'),
    )


class OKR(Base):
    """Objectives and Key Results"""
    __tablename__ = "okrs"

    id = Column(Integer, primary_key=True, index=True)
    quarter = Column(String, nullable=False, index=True)  # e.g., "Q1 2025"
    team = Column(String, index=True)  # Null for company-level OKRs
    objective = Column(Text, nullable=False)
    objective_owner = Column(String)
    status = Column(String, default="on_track")  # on_track, at_risk, off_track, achieved
    overall_progress = Column(Float, default=0)  # 0-100 calculated from key results
    parent_okr_id = Column(Integer, ForeignKey("okrs.id"))  # For cascading OKRs
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    key_results = relationship("KeyResult", back_populates="okr", cascade="all, delete-orphan")
    children = relationship("OKR", backref=backref("parent", remote_side=[id]))

    __table_args__ = (
        Index('ix_okr_quarter_team', 'quarter', 'team'),
        Index('ix_okr_status', 'status'),
    )


class KeyResult(Base):
    """Key Results for OKRs"""
    __tablename__ = "key_results"

    id = Column(Integer, primary_key=True, index=True)
    okr_id = Column(Integer, ForeignKey("okrs.id"), nullable=False, index=True)
    description = Column(Text, nullable=False)
    metric_type = Column(String)  # percentage, number, boolean, milestone
    target_value = Column(Float)
    current_value = Column(Float, default=0)
    unit = Column(String)  # %, count, etc.
    lower_is_better = Column(Boolean, default=False)  # True for metrics like CFR, vulnerabilities
    baseline_value = Column(Float)  # Starting point for "lower is better" calculations
    progress = Column(Float, default=0)  # 0-100
    status = Column(String, default="on_track")  # on_track, at_risk, off_track, achieved
    owner = Column(String)
    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship
    okr = relationship("OKR", back_populates="key_results")

    __table_args__ = (
        Index('ix_kr_okr', 'okr_id'),
    )


class EpicOKRLink(Base):
    """Link epics to Key Results for automatic progress tracking"""
    __tablename__ = "epic_okr_links"

    id = Column(Integer, primary_key=True, index=True)
    epic_key = Column(String, nullable=False, index=True)
    key_result_id = Column(Integer, ForeignKey("key_results.id"), nullable=False, index=True)
    contribution_weight = Column(Float, default=1.0)  # How much this epic contributes
    epic_status = Column(String)  # Cached epic status
    epic_progress = Column(Float, default=0)  # Cached epic progress (0-100)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_epic_okr_epic', 'epic_key'),
        Index('ix_epic_okr_kr', 'key_result_id'),
    )


# =============================================================================
# ENGINEER ACTIVITY METRICS
# =============================================================================

class EngineerMonthlyMetrics(Base):
    """
    Monthly metrics per engineer for fair performance tracking.

    Captures throughput, efficiency, collaboration, and consistency metrics
    that are harder to game than simple MR counts.
    """
    __tablename__ = "engineer_monthly_metrics"

    id = Column(Integer, primary_key=True, index=True)

    # Identity
    gitlab_username = Column(String, nullable=False, index=True)
    engineer_name = Column(String)
    team = Column(String, nullable=False, index=True)

    # Period (month granularity for 2-sprint comparison)
    period_year = Column(Integer, nullable=False, index=True)
    period_month = Column(Integer, nullable=False, index=True)  # 1-12

    # THROUGHPUT METRICS
    mrs_merged = Column(Integer, default=0)
    mrs_opened = Column(Integer, default=0)
    lines_added = Column(Integer, default=0)  # Context only, not for ranking
    lines_removed = Column(Integer, default=0)
    files_changed = Column(Integer, default=0)
    commits_count = Column(Integer, default=0)
    avg_mr_size = Column(String)  # S/M/L/XL based on lines changed

    # EFFICIENCY METRICS (in hours)
    avg_cycle_time_hours = Column(Float)  # first commit → merged (TRUE cycle time)
    avg_coding_time_hours = Column(Float)  # first commit → MR opened
    avg_review_time_hours = Column(Float)  # MR opened → merged
    avg_time_to_first_review_hours = Column(Float)  # MR opened → first comment/approval
    rework_rate = Column(Float)  # % commits after first review
    median_cycle_time_hours = Column(Float)  # Median for outlier resistance

    # COLLABORATION METRICS
    reviews_given = Column(Integer, default=0)  # MRs reviewed for others
    review_comments_given = Column(Integer, default=0)
    avg_review_turnaround_hours = Column(Float)  # When they review others
    cross_team_mrs = Column(Integer, default=0)  # MRs outside their primary repo

    # CONSISTENCY METRICS
    active_days = Column(Integer, default=0)  # Days with MRs merged (legacy)
    commit_active_days = Column(Integer, default=0)  # Days with commits pushed
    review_active_days = Column(Integer, default=0)  # Days with reviews given
    total_active_days = Column(Integer, default=0)  # Union of all activity types
    working_days_in_period = Column(Integer, default=0)  # Total working days
    activity_rate = Column(Float, default=0)  # total_active_days / working_days
    burst_score = Column(Float)  # 0=steady, 1=all work on last day
    sprint_distribution = Column(Text)  # JSON: [early%, mid%, late%]

    # CALCULATED SCORES (0-100 scale, normalized within team)
    throughput_score = Column(Float)
    efficiency_score = Column(Float)
    collaboration_score = Column(Float)
    consistency_score = Column(Float)
    balanced_score = Column(Float)  # Weighted combination

    # COMPLEXITY METRICS (captures MR difficulty beyond line count)
    avg_files_per_mr = Column(Float)  # File breadth - more files = architectural work
    avg_discussions_received = Column(Float)  # Discussion depth on authored MRs
    avg_reviewers_per_mr = Column(Float)  # Review complexity
    complexity_score = Column(Float)  # Composite 0-100 (file breadth 25%, discussion 25%, review rounds 20%, cycle time 15%, size 15%)
    
    # ENHANCED COMPLEXITY METRICS (4-dimension framework)
    complexity_size_score = Column(Float)       # Size dimension (0-100): LOC + files
    complexity_cognitive_score = Column(Float)  # Cognitive dimension (0-100): directories, cross-module, file types
    complexity_review_score = Column(Float)     # Review effort dimension (0-100): reviewers, discussions, iterations
    complexity_risk_score = Column(Float)       # Risk dimension (0-100): breaking, migrations, deps, security
    complexity_tier = Column(String)            # Tier: trivial, simple, moderate, complex, highly_complex
    
    # Cognitive breakdown
    avg_unique_directories = Column(Float)      # Average unique directories per MR
    avg_unique_file_types = Column(Float)       # Average unique file extensions per MR
    cross_module_mr_count = Column(Integer, default=0)  # MRs touching multiple modules
    
    # Risk breakdown
    breaking_change_count = Column(Integer, default=0)   # MRs with breaking changes
    migration_count = Column(Integer, default=0)         # MRs with migrations
    dependency_change_count = Column(Integer, default=0) # MRs updating dependencies
    security_change_count = Column(Integer, default=0)   # MRs touching security code
    
    # Detailed breakdown JSON for drill-down
    complexity_breakdown = Column(Text)  # JSON: full ComplexityBreakdown.to_dict()

    # ABANDONED MR METRICS (visibility only, not for scoring)
    mrs_abandoned = Column(Integer, default=0)  # Closed without merge
    abandonment_rate = Column(Float)  # abandoned / (merged + abandoned)
    abandoned_time_hours = Column(Float)  # Total time wasted on abandoned MRs

    # REVIEW QUALITY METRICS (distinguishes engaged vs rubber-stamp reviewers)
    comments_per_review = Column(Float)  # review_comments_given / reviews_given
    reviews_leading_to_changes = Column(Integer, default=0)  # Reviews that led to commits

    # REVIEW STYLE METRICS (for review style analysis view)
    formal_reviews = Column(Integer, default=0)  # MRs where explicitly requested as reviewer
    approve_only_reviews = Column(Integer, default=0)  # Reviews with 0 comments
    engaged_reviews = Column(Integer, default=0)  # Reviews with 1+ comments
    review_engagement_rate = Column(Float)  # engaged / formal * 100
    own_mr_comments = Column(Integer, default=0)  # Comments on own MRs (responding to feedback)

    # MR detail for drill-down (JSON array of MR summaries)
    mr_details = Column(Text)  # JSON: [{iid, title, cycle_time, size, repo}...]

    # Sync metadata
    last_synced_at = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_engineer_metrics_user_period', 'gitlab_username', 'period_year', 'period_month', unique=True),
        Index('ix_engineer_metrics_team_period', 'team', 'period_year', 'period_month'),
        Index('ix_engineer_metrics_balanced_score', 'balanced_score'),
    )


# =============================================================================
# JIRA CACHE MODELS
# =============================================================================

class JiraEpicCache(Base):
    """Cached Jira epic data for fast queries without API calls"""
    __tablename__ = "jira_epic_cache"

    id = Column(Integer, primary_key=True, index=True)
    epic_key = Column(String, nullable=False, unique=True, index=True)  # e.g., "PLAT-123"
    project_key = Column(String, nullable=False, index=True)  # e.g., "PLAT"
    team = Column(String, nullable=False, index=True)  # Commercial team name
    summary = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, nullable=False, index=True)  # e.g., "In Progress", "Done"
    status_category = Column(String)  # "To Do", "In Progress", "Done"
    priority = Column(String)  # e.g., "High", "Medium", "Low"
    assignee = Column(String)
    reporter = Column(String)
    labels = Column(Text)  # JSON array of labels
    components = Column(Text)  # JSON array of components
    fix_versions = Column(Text)  # JSON array of fix versions
    progress_percent = Column(Float, default=0)  # 0-100
    story_points = Column(Float)
    original_estimate_hours = Column(Float)
    time_spent_hours = Column(Float)
    remaining_estimate_hours = Column(Float)
    child_issues_total = Column(Integer, default=0)
    child_issues_done = Column(Integer, default=0)
    created_date = Column(DateTime)
    updated_date = Column(DateTime)
    due_date = Column(Date)
    resolution_date = Column(DateTime)
    sprint_name = Column(String)
    epic_link = Column(String)  # Parent epic if this is a child
    url = Column(String)  # Direct link to Jira
    raw_json = Column(Text)  # Full JSON response for advanced queries
    last_synced_at = Column(DateTime, default=utc_now, index=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_jira_cache_team_status', 'team', 'status'),
        Index('ix_jira_cache_project_status', 'project_key', 'status'),
        Index('ix_jira_cache_synced', 'last_synced_at'),
    )


class JiraSprintCache(Base):
    """Cached sprint data for velocity tracking"""
    __tablename__ = "jira_sprint_cache"

    id = Column(Integer, primary_key=True, index=True)
    sprint_id = Column(Integer, unique=True, index=True)
    sprint_name = Column(String, nullable=False)
    board_id = Column(Integer)
    board_name = Column(String)
    team = Column(String, index=True)
    state = Column(String)  # active, closed, future
    start_date = Column(DateTime)
    end_date = Column(DateTime)
    complete_date = Column(DateTime)
    goal = Column(Text)
    issues_total = Column(Integer, default=0)
    issues_completed = Column(Integer, default=0)
    story_points_committed = Column(Float, default=0)
    story_points_completed = Column(Float, default=0)
    # Stories-only metrics for normalized comparison
    stories_committed = Column(Integer, default=0)
    stories_completed = Column(Integer, default=0)
    stories_points_committed = Column(Float, default=0)
    stories_points_completed = Column(Float, default=0)
    # Track source of commitment data
    # "velocity_report" = from Jira Velocity Report API (true commitment)
    # "estimated" = calculated from team's average velocity
    # "fallback" = committed = completed (no real data)
    commitment_source = Column(String, default="fallback")
    last_synced_at = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)

    # MR metrics (synced from GitLab, aligned with sprint dates)
    mrs_merged = Column(Integer, default=0)  # Total MRs during sprint
    effective_engineers = Column(Integer, default=0)  # Team size minus TLs/Architects
    mr_per_engineer = Column(Float, default=0)  # mrs_merged / effective_engineers
    mr_last_synced_at = Column(DateTime)  # When MR data was last fetched

    __table_args__ = (
        Index('ix_sprint_team_state', 'team', 'state'),
    )


class JiraSyncLog(Base):
    """Audit log for Jira sync operations"""
    __tablename__ = "jira_sync_log"

    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String, nullable=False)  # epics, sprints, full
    started_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime)
    status = Column(String, default="running")  # running, success, failed
    items_synced = Column(Integer, default=0)
    items_created = Column(Integer, default=0)
    items_updated = Column(Integer, default=0)
    items_failed = Column(Integer, default=0)
    error_message = Column(Text)
    details = Column(Text)  # JSON with additional sync details

    __table_args__ = (
        Index('ix_sync_log_type_status', 'sync_type', 'status'),
    )


class AIAnalysisCache(Base):
    """Cache for AI-generated analysis to reduce API calls"""
    __tablename__ = "ai_analysis_cache"

    id = Column(Integer, primary_key=True, index=True)
    analysis_type = Column(String, nullable=False)  # velocity, epic, etc.
    entity_key = Column(String, nullable=False)  # team name, epic key, etc.
    analysis_text = Column(Text, nullable=False)
    metrics_json = Column(Text)  # JSON with metrics used for analysis
    provider = Column(String)  # openai, anthropic
    model = Column(String)  # gpt-4o-mini, claude-3-5-haiku, etc.
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_ai_cache_type_key', 'analysis_type', 'entity_key', unique=True),
    )


class EcosystemMetricsCache(Base):
    """Cache for ecosystem metrics to reduce API latency (24h TTL)"""
    __tablename__ = "ecosystem_metrics_cache"

    id = Column(Integer, primary_key=True, index=True)
    cache_key = Column(String, nullable=False, unique=True, index=True)  # e.g., "combined_2025-04-01_2025-12-22"
    metrics_json = Column(Text, nullable=False)  # Full JSON response
    expires_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_ecosystem_cache_key', 'cache_key', unique=True),
    )


# =============================================================================
# MEETING OUTCOMES & COMMITMENT TRACKING
# =============================================================================

class MeetingOutcome(Base):
    """Captured outcomes from meetings - decisions, action items, blockers"""
    __tablename__ = "meeting_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    meeting_title = Column(String, nullable=False)
    meeting_date = Column(DateTime, nullable=False, index=True)
    participants = Column(Text)  # JSON array of participant names

    # Capture metadata
    capture_method = Column(String, nullable=False)  # voice, transcript, bullets, quick
    raw_input = Column(Text)  # Original input (transcript, voice transcription, etc.)

    # Extracted outcomes (all JSON arrays)
    decisions = Column(Text)  # JSON: [{statement, owner, affects_epic, confidence}]
    action_items = Column(Text)  # JSON: [{task, owner, due_date, priority}]
    blockers_identified = Column(Text)  # JSON: [{blocker, team, epic_key, severity}]
    scope_changes = Column(Text)  # JSON: [{change, epic_key, impact, approved_by}]
    escalations = Column(Text)  # JSON: [{issue, escalate_to, urgency, context}]
    key_points = Column(Text)  # JSON: [{point, speaker, importance}]

    # AI processing metadata
    ai_model = Column(String)  # Model used for extraction
    extraction_confidence = Column(Float)  # 0-1 confidence score

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    commitments = relationship("Commitment", back_populates="meeting_outcome", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_meeting_outcomes_date', 'meeting_date'),
    )


class Commitment(Base):
    """Track commitments made by people - promises to deliver something by a date"""
    __tablename__ = "commitments"

    id = Column(Integer, primary_key=True, index=True)
    meeting_outcome_id = Column(Integer, ForeignKey("meeting_outcomes.id"), index=True)

    # Who and what
    owner = Column(String, nullable=False, index=True)  # Person who made the commitment
    description = Column(Text, nullable=False)  # What they committed to
    due_date = Column(Date, index=True)  # When it's due

    # Classification
    direction = Column(String, nullable=False)  # "to_me" (they promised you) or "by_me" (you promised them)
    recipient = Column(String)  # Who the commitment is to
    priority = Column(String, default="medium")  # high, medium, low
    related_epic = Column(String)  # Epic key if related to Jira work

    # Status tracking
    status = Column(String, default="pending", index=True)  # pending, in_progress, completed, overdue, cancelled
    completed_at = Column(DateTime)
    completion_notes = Column(Text)

    # Reminders
    reminder_sent = Column(Boolean, default=False)
    reminder_sent_at = Column(DateTime)
    follow_up_count = Column(Integer, default=0)  # How many times we've followed up

    # Source tracking
    source = Column(String, default="meeting")  # meeting, slack, manual

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship
    meeting_outcome = relationship("MeetingOutcome", back_populates="commitments")

    __table_args__ = (
        Index('ix_commitments_owner_status', 'owner', 'status'),
        Index('ix_commitments_due_date', 'due_date'),
        Index('ix_commitments_direction', 'direction'),
        Index('ix_commitments_status_due', 'status', 'due_date'),  # For filtered+sorted queries
    )


# =============================================================================
# 1:1 & PEOPLE DEVELOPMENT MODELS
# =============================================================================

class DirectReport(Base):
    """Track direct reports and their development"""
    __tablename__ = "direct_reports"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, unique=True, index=True)
    email = Column(String)
    role = Column(String)  # "Dev Manager", "Principal Engineer", etc.
    teams_managed = Column(Text)  # JSON array of team names

    # 1:1 settings
    one_on_one_frequency = Column(String, default="weekly")  # weekly, bi-weekly, monthly
    one_on_one_day = Column(String)  # Monday, Tuesday, etc.
    one_on_one_duration_minutes = Column(Integer, default=30)

    # Career development
    current_level = Column(String)  # IC5, M2, etc.
    target_level = Column(String)
    development_focus = Column(Text)  # JSON array of focus areas
    strengths = Column(Text)  # JSON array
    growth_areas = Column(Text)  # JSON array
    career_aspirations = Column(Text)

    # Performance tracking
    last_performance_review = Column(Date)
    next_performance_review = Column(Date)
    performance_rating = Column(String)  # "Exceptional", "Strong", etc.

    # Succession planning
    succession_readiness = Column(String)  # "Ready now", "1-2 years", "2-3 years"
    succession_notes = Column(Text)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    one_on_ones = relationship("OneOnOne", back_populates="direct_report", cascade="all, delete-orphan")
    development_goals = relationship("DevelopmentGoal", back_populates="direct_report", cascade="all, delete-orphan")
    performance_notes = relationship("PerformanceNote", back_populates="direct_report", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_direct_reports_role', 'role'),
    )


class OneOnOne(Base):
    """Track 1:1 meeting outcomes"""
    __tablename__ = "one_on_ones"

    id = Column(Integer, primary_key=True, index=True)
    direct_report_id = Column(Integer, ForeignKey("direct_reports.id"), nullable=False, index=True)
    meeting_outcome_id = Column(Integer, ForeignKey("meeting_outcomes.id"))

    meeting_date = Column(DateTime, nullable=False, index=True)
    duration_minutes = Column(Integer)
    was_held = Column(Boolean, default=True)  # False if cancelled/rescheduled
    cancellation_reason = Column(String)

    # Discussion topics - JSON: [{topic, category, notes}]
    # Categories: "team_health", "career", "blockers", "wins", "personal", "feedback", "projects"
    topics_discussed = Column(Text)

    # Action items (links to commitments)
    action_items_json = Column(Text)  # JSON array for quick access

    # Mood/engagement signals
    energy_level = Column(String)  # "high", "medium", "low"
    engagement_level = Column(String)  # "engaged", "neutral", "disengaged"
    mood_notes = Column(Text)

    # Follow-ups
    follow_up_needed = Column(Boolean, default=False)
    follow_up_topic = Column(String)

    # AI-generated insights
    ai_summary = Column(Text)
    ai_insights = Column(Text)  # JSON array of detected patterns

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    direct_report = relationship("DirectReport", back_populates="one_on_ones")
    meeting_outcome = relationship("MeetingOutcome", foreign_keys=[meeting_outcome_id])

    __table_args__ = (
        Index('ix_one_on_ones_report_date', 'direct_report_id', 'meeting_date'),
        Index('ix_one_on_ones_follow_up', 'follow_up_needed'),  # For filtering follow-up queries
    )


class DevelopmentGoal(Base):
    """Career development goals for direct reports"""
    __tablename__ = "development_goals"

    id = Column(Integer, primary_key=True, index=True)
    direct_report_id = Column(Integer, ForeignKey("direct_reports.id"), nullable=False, index=True)

    goal = Column(Text, nullable=False)
    category = Column(String)  # "technical", "leadership", "communication", "domain"
    target_date = Column(Date)
    status = Column(String, default="active")  # "active", "completed", "deferred", "cancelled"

    # Progress tracking
    progress_percent = Column(Float, default=0)
    milestones = Column(Text)  # JSON: [{milestone, completed, date}]
    evidence = Column(Text)  # JSON: [{description, date, type}]

    # Review tracking
    last_discussed = Column(Date)
    discussion_notes = Column(Text)  # JSON array of discussion summaries

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship
    direct_report = relationship("DirectReport", back_populates="development_goals")

    __table_args__ = (
        Index('ix_dev_goals_report_status', 'direct_report_id', 'status'),
    )


class PerformanceNote(Base):
    """Ongoing performance observations for review prep"""
    __tablename__ = "performance_notes"

    id = Column(Integer, primary_key=True, index=True)
    direct_report_id = Column(Integer, ForeignKey("direct_reports.id"), nullable=False, index=True)

    observation_date = Column(Date, nullable=False, index=True)
    category = Column(String)  # "win", "concern", "feedback_given", "feedback_received", "growth_moment"
    description = Column(Text, nullable=False)
    context = Column(String)  # Where observed: "1:1", "meeting", "project", "slack"

    # For review prep
    include_in_review = Column(Boolean, default=True)
    review_period = Column(String)  # "H1 2025", "H2 2025"

    # Source linkage
    source_entry_id = Column(Integer, ForeignKey("entries.id"))
    source_one_on_one_id = Column(Integer, ForeignKey("one_on_ones.id"))

    created_at = Column(DateTime, default=utc_now)

    # Relationship
    direct_report = relationship("DirectReport", back_populates="performance_notes")

    __table_args__ = (
        Index('ix_perf_notes_report_date', 'direct_report_id', 'observation_date'),
        Index('ix_perf_notes_category', 'category'),
        Index('ix_perf_notes_review_period', 'review_period'),
    )


class DecisionOutcome(Base):
    """Track decision quality - was the decision good/bad/neutral after 30 days?"""
    __tablename__ = "decision_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    decision_id = Column(Integer, ForeignKey("decisions.id"), index=True)
    meeting_outcome_id = Column(Integer, ForeignKey("meeting_outcomes.id"), index=True)

    # The decision being tracked
    decision_statement = Column(Text, nullable=False)
    decision_date = Column(DateTime, nullable=False)
    decision_owner = Column(String)

    # Decision Intelligence fields (Module 2)
    decision_type = Column(String, index=True)  # hiring, architecture, process, priority, resource, vendor, team, other
    context = Column(Text)  # JSON: situation, constraints, stakeholders, urgency
    alternatives_considered = Column(Text)  # JSON: [{alternative, pros, cons, why_rejected}]
    confidence_level = Column(String)  # high, medium, low - how confident at decision time
    reversibility = Column(String)  # easy, moderate, difficult, irreversible
    impact_scope = Column(String)  # individual, team, domain, org
    embedding = Column(Text)  # JSON: vector embedding for semantic similarity

    # Outcome tracking
    review_due_date = Column(Date, index=True)  # When to review (typically decision_date + 30 days)
    outcome = Column(String)  # good, bad, neutral, too_early, superseded
    outcome_notes = Column(Text)  # What happened as a result
    reviewed_at = Column(DateTime)

    # Learning
    lessons_learned = Column(Text)  # What we learned from this decision
    would_decide_differently = Column(Boolean)
    pattern_id = Column(Integer, ForeignKey("decision_patterns.id"), nullable=True, index=True)  # Linked pattern if one was identified

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    pattern = relationship("DecisionPattern", back_populates="decisions")
    reviews = relationship("DecisionReview", back_populates="decision_outcome")

    __table_args__ = (
        Index('ix_decision_outcomes_review_due', 'review_due_date'),
        Index('ix_decision_outcomes_outcome', 'outcome'),
        Index('ix_decision_outcomes_type', 'decision_type'),
    )


class DecisionPattern(Base):
    """Learned patterns from decision outcomes - success/failure patterns"""
    __tablename__ = "decision_patterns"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)  # Short name for the pattern
    pattern_type = Column(String, nullable=False, index=True)  # success, failure, warning
    decision_type = Column(String, index=True)  # hiring, architecture, etc. - which decisions this applies to

    # Pattern definition
    description = Column(Text, nullable=False)  # What this pattern represents
    conditions = Column(Text)  # JSON: conditions that identify this pattern
    indicators = Column(Text)  # JSON: early warning signs or positive signals

    # Pattern effectiveness
    recommendation = Column(Text)  # What to do when this pattern is detected
    example_decisions = Column(Text)  # JSON: list of decision_outcome_ids that exemplify this pattern
    success_rate = Column(Float)  # Percentage of good outcomes when pattern is followed/avoided
    sample_size = Column(Integer, default=0)  # Number of decisions used to calculate success_rate
    confidence = Column(String)  # high, medium, low - based on sample_size

    # Playbook integration
    is_playbook = Column(Boolean, default=False)  # Promoted to a reusable playbook
    playbook_content = Column(Text)  # Markdown content for the playbook

    # Metadata
    source = Column(String, default="learned")  # learned, manual, imported
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    decisions = relationship("DecisionOutcome", back_populates="pattern")

    __table_args__ = (
        Index('ix_decision_patterns_type_active', 'pattern_type', 'is_active'),
    )


class DecisionReview(Base):
    """Scheduled decision reviews with status tracking"""
    __tablename__ = "decision_reviews"

    id = Column(Integer, primary_key=True, index=True)
    decision_outcome_id = Column(Integer, ForeignKey("decision_outcomes.id"), nullable=False, index=True)

    # Review scheduling
    review_type = Column(String, nullable=False)  # 30_day, 90_day, annual, ad_hoc
    scheduled_date = Column(Date, nullable=False, index=True)
    reminder_sent = Column(Boolean, default=False)
    reminder_sent_at = Column(DateTime)

    # Review completion
    status = Column(String, default="pending", index=True)  # pending, in_progress, completed, skipped
    completed_at = Column(DateTime)
    reviewer_notes = Column(Text)

    # Review findings
    outcome_confirmed = Column(Boolean)  # Was the initial outcome assessment correct?
    new_insights = Column(Text)  # Any new learnings from this review
    pattern_suggested = Column(Text)  # Suggested pattern based on this review

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship to parent decision outcome (enables eager loading)
    decision_outcome = relationship("DecisionOutcome", back_populates="reviews")

    __table_args__ = (
        Index('ix_decision_reviews_scheduled', 'scheduled_date', 'status'),
    )


# =============================================================================
# STAKEHOLDER & INFLUENCE MAPPING (Module 3)
# =============================================================================

class Stakeholder(Base):
    """Key stakeholders - VPs, peers, cross-functional partners"""
    __tablename__ = "stakeholders"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False, index=True)
    email = Column(String)
    title = Column(String)  # VP Engineering, Product Director, etc.
    organization = Column(String)  # Their org/department
    company = Column(String, default="")  # Set via config at creation time

    # Relationship metadata
    relationship_type = Column(String, index=True)  # peer, superior, subordinate, cross-functional, external
    importance = Column(String, default="medium", index=True)  # critical, high, medium, low
    influence_level = Column(String)  # high, medium, low - their organizational influence
    relationship_strength = Column(String, default="neutral")  # strong, good, neutral, weak, strained

    # Engagement preferences
    preferred_channel = Column(String)  # email, slack, meeting, async
    communication_style = Column(String)  # direct, diplomatic, data-driven, relationship-first
    timezone = Column(String)

    # Goals and context
    their_goals = Column(Text)  # What they're trying to achieve
    how_we_help = Column(Text)  # How Ecosystem can help them
    how_they_help = Column(Text)  # How they can help Ecosystem
    topics_of_interest = Column(Text)  # JSON: topics they care about
    notes = Column(Text)  # General notes about the relationship

    # Tracking
    last_interaction_date = Column(Date)
    interaction_frequency_target = Column(Integer, default=30)  # Days between interactions
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    interactions = relationship("StakeholderInteraction", back_populates="stakeholder", cascade="all, delete-orphan")
    commitments = relationship("StakeholderCommitment", back_populates="stakeholder", cascade="all, delete-orphan")

    __table_args__ = (
        Index('ix_stakeholder_importance_active', 'importance', 'is_active'),
    )


class StakeholderInteraction(Base):
    """Track interactions with stakeholders"""
    __tablename__ = "stakeholder_interactions"

    id = Column(Integer, primary_key=True, index=True)
    stakeholder_id = Column(Integer, ForeignKey("stakeholders.id"), nullable=False, index=True)

    # Interaction details
    interaction_date = Column(DateTime, nullable=False, index=True)
    interaction_type = Column(String, nullable=False)  # meeting, email, slack, call, social
    channel = Column(String)  # 1:1, group_meeting, email_thread, slack_dm, etc.
    initiated_by = Column(String)  # me, them, mutual

    # Content
    summary = Column(Text)  # What was discussed
    topics = Column(Text)  # JSON: list of topics covered
    sentiment = Column(String)  # positive, neutral, negative
    outcome = Column(String)  # productive, neutral, challenging

    # Follow-ups
    action_items = Column(Text)  # JSON: action items from this interaction
    follow_up_needed = Column(Boolean, default=False)
    follow_up_date = Column(Date)

    # Context linking
    meeting_outcome_id = Column(Integer, ForeignKey("meeting_outcomes.id"), nullable=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=True)

    created_at = Column(DateTime, default=utc_now)

    # Relationships
    stakeholder = relationship("Stakeholder", back_populates="interactions")

    __table_args__ = (
        Index('ix_stakeholder_interaction_date', 'stakeholder_id', 'interaction_date'),
    )


class StakeholderCommitment(Base):
    """Track commitments exchanged with stakeholders"""
    __tablename__ = "stakeholder_commitments"

    id = Column(Integer, primary_key=True, index=True)
    stakeholder_id = Column(Integer, ForeignKey("stakeholders.id"), nullable=False, index=True)

    # Commitment details
    direction = Column(String, nullable=False)  # to_them, from_them
    description = Column(Text, nullable=False)
    context = Column(Text)  # Why this commitment was made

    # Tracking
    made_date = Column(Date, nullable=False)
    due_date = Column(Date, index=True)
    status = Column(String, default="pending", index=True)  # pending, in_progress, completed, overdue, cancelled
    completed_date = Column(Date)

    # Outcome
    was_met = Column(Boolean)  # Was the commitment fulfilled?
    outcome_notes = Column(Text)

    # Importance
    priority = Column(String, default="medium")  # high, medium, low
    is_visible = Column(Boolean, default=True)  # Track in dashboards

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    stakeholder = relationship("Stakeholder", back_populates="commitments")

    __table_args__ = (
        Index('ix_commitment_status_due', 'status', 'due_date'),
        Index('ix_commitment_direction', 'direction', 'status'),
    )


class InfluenceSnapshot(Base):
    """Periodic snapshots of influence dynamics for visualization"""
    __tablename__ = "influence_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(Date, nullable=False, index=True)

    # Influence map data
    stakeholder_data = Column(Text)  # JSON: stakeholder positions, connections, influence scores
    relationship_health = Column(Text)  # JSON: overall health metrics per stakeholder
    influence_changes = Column(Text)  # JSON: changes since last snapshot

    # Key metrics
    total_stakeholders = Column(Integer)
    critical_relationships = Column(Integer)
    relationships_needing_attention = Column(Integer)
    pending_commitments_to_them = Column(Integer)
    pending_commitments_from_them = Column(Integer)

    # AI insights
    ai_insights = Column(Text)  # JSON: AI-generated insights about the influence map
    recommended_actions = Column(Text)  # JSON: suggested actions

    created_at = Column(DateTime, default=utc_now)


# =============================================================================
# TEAM HEALTH & CULTURE (Module 4)
# =============================================================================

class TeamPulse(Base):
    """Lightweight pulse checks on team health - workload, morale, clarity, support"""
    __tablename__ = "team_pulses"

    id = Column(Integer, primary_key=True, index=True)
    team_name = Column(String, nullable=False, index=True)
    pulse_date = Column(Date, nullable=False, index=True)
    source = Column(String, default="direct")  # direct, 1on1_extraction, survey, observation

    # Core pulse metrics (1-5 scale)
    workload_score = Column(Float)  # 1=overwhelmed, 5=comfortable
    morale_score = Column(Float)  # 1=low, 5=high
    clarity_score = Column(Float)  # 1=confused, 5=clear direction
    support_score = Column(Float)  # 1=unsupported, 5=well-supported
    collaboration_score = Column(Float)  # 1=siloed, 5=collaborative

    # Overall
    overall_health = Column(Float)  # Average of scores
    trend = Column(String)  # improving, stable, declining

    # Context
    notes = Column(Text)  # Observations or comments
    concerns = Column(Text)  # JSON: list of specific concerns raised
    wins = Column(Text)  # JSON: list of recent wins/positives
    blockers = Column(Text)  # JSON: list of blockers

    # Extraction context
    one_on_one_id = Column(Integer, ForeignKey("one_on_ones.id"), nullable=True)
    entry_id = Column(Integer, ForeignKey("entries.id"), nullable=True)

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_team_pulse_team_date', 'team_name', 'pulse_date'),
    )


class TeamSentimentTrend(Base):
    """Weekly aggregated sentiment per team for trend analysis"""
    __tablename__ = "team_sentiment_trends"

    id = Column(Integer, primary_key=True, index=True)
    team_name = Column(String, nullable=False, index=True)
    week_start = Column(Date, nullable=False, index=True)  # Monday of the week

    # Aggregated scores (averages from pulses)
    avg_workload = Column(Float)
    avg_morale = Column(Float)
    avg_clarity = Column(Float)
    avg_support = Column(Float)
    avg_collaboration = Column(Float)
    overall_score = Column(Float)

    # Trend analysis
    week_over_week_change = Column(Float)  # Percentage change from previous week
    trend_direction = Column(String)  # improving, stable, declining
    consecutive_decline_weeks = Column(Integer, default=0)

    # Data quality
    pulse_count = Column(Integer, default=0)  # Number of pulses this week
    data_confidence = Column(String)  # high, medium, low based on pulse_count

    # AI analysis
    ai_summary = Column(Text)  # AI-generated summary of the week
    key_themes = Column(Text)  # JSON: main themes identified
    recommended_actions = Column(Text)  # JSON: suggested actions

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_sentiment_trend_team_week', 'team_name', 'week_start'),
    )


class AttritionSignal(Base):
    """Track attrition risk signals for individuals or teams"""
    __tablename__ = "attrition_signals"

    id = Column(Integer, primary_key=True, index=True)
    signal_date = Column(Date, nullable=False, index=True)

    # Target
    target_type = Column(String, nullable=False)  # individual, team
    target_name = Column(String, nullable=False, index=True)  # Person name or team name
    team_name = Column(String, index=True)  # Team they're on (for individuals)

    # Signal details
    signal_type = Column(String, nullable=False, index=True)  # disengagement, burnout, conflict, external_offer, etc.
    signal_strength = Column(String, nullable=False)  # high, medium, low
    confidence = Column(Float)  # 0-1 confidence in the signal

    # Evidence
    description = Column(Text, nullable=False)  # What was observed
    evidence = Column(Text)  # JSON: supporting evidence points
    source = Column(String)  # 1on1, observation, pulse, calendar_pattern, etc.

    # Risk assessment
    risk_level = Column(String, index=True)  # critical, high, medium, low
    time_sensitivity = Column(String)  # immediate, short_term, medium_term

    # Actions
    recommended_actions = Column(Text)  # JSON: suggested interventions
    action_taken = Column(Text)  # What was done
    action_date = Column(Date)

    # Resolution
    status = Column(String, default="active", index=True)  # active, monitoring, resolved, false_positive
    resolution_notes = Column(Text)
    resolved_date = Column(Date)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_attrition_signal_status_risk', 'status', 'risk_level'),
    )


class EngagementIndicator(Base):
    """Track engagement indicators - meeting participation, initiatives, activity"""
    __tablename__ = "engagement_indicators"

    id = Column(Integer, primary_key=True, index=True)
    indicator_date = Column(Date, nullable=False, index=True)
    team_name = Column(String, nullable=False, index=True)

    # Meeting engagement
    meeting_attendance_rate = Column(Float)  # Percentage attending scheduled meetings
    meeting_participation_score = Column(Float)  # Active participation vs passive (1-5)
    camera_on_rate = Column(Float)  # For remote teams

    # Initiative indicators
    initiatives_started = Column(Integer, default=0)  # New ideas, projects proposed
    cross_team_collaborations = Column(Integer, default=0)
    process_improvements = Column(Integer, default=0)

    # Communication indicators
    slack_activity_level = Column(String)  # high, medium, low, declining
    documentation_contributions = Column(Integer, default=0)
    knowledge_sharing_events = Column(Integer, default=0)  # Demos, presentations

    # Development indicators
    learning_activities = Column(Integer, default=0)  # Training, certifications
    mentoring_activities = Column(Integer, default=0)

    # Overall assessment
    engagement_score = Column(Float)  # Calculated overall score (1-5)
    trend = Column(String)  # improving, stable, declining

    notes = Column(Text)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_engagement_team_date', 'team_name', 'indicator_date'),
    )


# =============================================================================
# INTELLIGENCE SYNTHESIS & PREDICTIVE ALERTING
# =============================================================================

class WeeklyMetrics(Base):
    """Weekly aggregated metrics for trend analysis and synthesis"""
    __tablename__ = "weekly_metrics"

    id = Column(Integer, primary_key=True, index=True)
    week_start = Column(Date, nullable=False, index=True)  # Monday of the week
    week_end = Column(Date, nullable=False)

    # Productivity metrics
    meeting_hours = Column(Float, default=0)
    meeting_count = Column(Integer, default=0)
    focus_blocks_count = Column(Integer, default=0)  # Blocks of 2+ hours without meetings
    focus_hours = Column(Float, default=0)
    entries_created = Column(Integer, default=0)
    todos_created = Column(Integer, default=0)
    todos_completed = Column(Integer, default=0)
    completion_rate = Column(Float, default=0)  # todos_completed / todos_due * 100

    # Commitment metrics
    commitments_made = Column(Integer, default=0)
    commitments_received = Column(Integer, default=0)
    commitments_completed = Column(Integer, default=0)
    commitments_overdue = Column(Integer, default=0)
    commitment_completion_rate = Column(Float, default=0)

    # Decision metrics
    decisions_logged = Column(Integer, default=0)
    decisions_reviewed = Column(Integer, default=0)
    decision_quality_score = Column(Float)  # Average outcome score

    # Meeting outcomes
    meetings_with_outcomes = Column(Integer, default=0)
    action_items_extracted = Column(Integer, default=0)
    blockers_identified = Column(Integer, default=0)

    # Team health (from Jira cache)
    epics_completed = Column(Integer, default=0)
    epics_stale = Column(Integer, default=0)  # >7 days without update
    epics_blocked = Column(Integer, default=0)

    # Security metrics (from Snyk)
    critical_vulns = Column(Integer, default=0)
    high_vulns = Column(Integer, default=0)
    vulns_fixed = Column(Integer, default=0)

    # Calculated trends (vs previous week)
    meeting_hours_trend = Column(Float)  # +/- percentage
    focus_hours_trend = Column(Float)
    completion_rate_trend = Column(Float)

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_weekly_metrics_week', 'week_start'),
    )


class SearchAnalytics(Base):
    """Track search patterns for attention analysis"""
    __tablename__ = "search_analytics"

    id = Column(Integer, primary_key=True, index=True)
    searched_at = Column(DateTime, default=utc_now, index=True)
    query = Column(String, nullable=False)
    query_normalized = Column(String, index=True)  # Lowercase, stemmed for clustering
    search_type = Column(String)  # keyword, semantic, hybrid, graph
    results_count = Column(Integer, default=0)
    clicked_result_id = Column(Integer)  # Which result was clicked, if any

    # Topic extraction
    extracted_topics = Column(Text)  # JSON array of detected topics
    intent = Column(String)  # question, lookup, research, action

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_search_analytics_date', 'searched_at'),
        Index('ix_search_analytics_normalized', 'query_normalized'),
    )


class TopicCluster(Base):
    """Detected topic clusters from search patterns and knowledge graph"""
    __tablename__ = "topic_clusters"
    __table_args__ = (
        Index('ix_topic_clusters_trend', 'trend'),
        {'extend_existing': True}
    )

    id = Column(Integer, primary_key=True, index=True)
    cluster_name = Column(String, nullable=False, index=True)
    keywords = Column(Text)  # JSON array of keywords in this cluster
    search_count = Column(Integer, default=0)
    first_seen = Column(DateTime, default=utc_now)
    last_seen = Column(DateTime, default=utc_now)
    trend = Column(String, default="stable")  # emerging, growing, stable, declining

    # Additional columns from entry_relationships_model
    entry_ids = Column(JSON)  # List of entry IDs in this cluster
    centroid_entry_id = Column(Integer, ForeignKey("entries.id"))  # Most representative entry
    size = Column(Integer)
    coherence_score = Column(Float)  # Measure of how well-defined the cluster is

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship to centroid entry
    centroid_entry = relationship("Entry", foreign_keys=[centroid_entry_id], backref="centered_clusters")


class PredictiveAlert(Base):
    """Triggered predictive alerts - pattern-based early warnings"""
    __tablename__ = "predictive_alerts"

    id = Column(Integer, primary_key=True, index=True)
    triggered_at = Column(DateTime, default=utc_now, index=True)

    # Alert classification
    alert_type = Column(String, nullable=False, index=True)  # productivity, commitment, delivery, security, capacity
    severity = Column(String, default="medium")  # critical, high, medium, low

    # Alert content
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    recommended_action = Column(Text)

    # Pattern that triggered it
    pattern_name = Column(String, index=True)  # Name of the rule that fired
    pattern_details = Column(Text)  # JSON with pattern match details
    confidence = Column(Float, default=0.7)  # 0-1 confidence in the prediction

    # Related entities
    related_person = Column(String)  # Person involved, if any
    related_epic = Column(String)  # Epic key, if any
    related_team = Column(String)  # Team, if any

    # Status
    surfaced_in_briefing = Column(Boolean, default=False)
    surfaced_at = Column(DateTime)
    acknowledged = Column(Boolean, default=False)
    acknowledged_at = Column(DateTime)
    action_taken = Column(Text)  # What action was taken
    outcome = Column(String)  # Was the prediction accurate? accurate, false_positive, prevented

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_predictive_alerts_type', 'alert_type'),
        Index('ix_predictive_alerts_triggered', 'triggered_at'),
        Index('ix_predictive_alerts_acknowledged', 'acknowledged'),
    )


class IntelligenceSynthesis(Base):
    """Weekly intelligence synthesis reports"""
    __tablename__ = "intelligence_synthesis"

    id = Column(Integer, primary_key=True, index=True)
    week_start = Column(Date, nullable=False, index=True)
    generated_at = Column(DateTime, default=utc_now)

    # Report sections (all JSON)
    productivity_signals = Column(Text)  # Meeting hours, focus time, completion rate
    attention_patterns = Column(Text)  # Top research topics, emerging clusters
    risk_signals = Column(Text)  # Overdue commitments, stale epics, security
    recommended_actions = Column(Text)  # Prioritized action list
    cross_domain_insights = Column(Text)  # Correlated patterns

    # Full report
    full_report_markdown = Column(Text)  # Complete synthesis in markdown

    # Distribution
    emailed = Column(Boolean, default=False)
    emailed_at = Column(DateTime)

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_intelligence_synthesis_week', 'week_start'),
    )


# =============================================================================
# PROACTIVE ACTIONS ENGINE
# =============================================================================

class SuggestedAction(Base):
    """Proactive action suggestions generated from various sources"""
    __tablename__ = "suggested_actions"

    id = Column(Integer, primary_key=True, index=True)

    # Action classification
    action_type = Column(String, nullable=False, index=True)  # create_todo, draft_message, block_calendar, follow_up, schedule_meeting, send_reminder
    title = Column(String, nullable=False)
    description = Column(Text)
    urgency = Column(String, default="medium", index=True)  # critical, high, medium, low

    # Source of the action
    source_type = Column(String, nullable=False, index=True)  # commitment, meeting, pattern, predictive_alert, calendar, overdue_todo
    source_id = Column(Integer)  # Reference to source record (commitment_id, meeting_outcome_id, etc.)
    source_context = Column(Text)  # JSON with additional context about the source

    # Related entities
    related_person = Column(String, index=True)  # Person involved, if any
    related_epic = Column(String)  # Epic key, if any
    related_entry_id = Column(Integer, ForeignKey("entries.id"))  # Related PA entry

    # Action execution payload
    action_template = Column(Text)  # JSON with parameters for execution (message draft, todo title, calendar block details, etc.)

    # Status tracking
    status = Column(String, default="pending", index=True)  # pending, snoozed, completed, dismissed, expired
    snoozed_until = Column(DateTime)
    completed_at = Column(DateTime)
    dismissed_at = Column(DateTime)

    # User feedback for learning
    user_feedback = Column(String)  # clicked, dismissed, snoozed, helpful, not_helpful
    feedback_notes = Column(Text)

    # Scheduling
    surface_after = Column(DateTime, default=utc_now)  # When to show this action (for scheduling)
    expires_at = Column(DateTime)  # Action expires after this time
    recurring = Column(Boolean, default=False)  # Does this action recur?
    recurring_pattern = Column(String)  # daily, weekly, etc.

    # Metrics
    confidence = Column(Float, default=0.7)  # 0-1 confidence this action is relevant
    priority_score = Column(Float)  # Calculated priority for sorting

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationship
    related_entry = relationship("Entry", foreign_keys=[related_entry_id])

    __table_args__ = (
        Index('ix_suggested_actions_status_urgency', 'status', 'urgency'),
        Index('ix_suggested_actions_source', 'source_type', 'source_id'),
        Index('ix_suggested_actions_surface', 'surface_after'),
        Index('ix_suggested_actions_person', 'related_person'),
    )


# =============================================================================
# UNIFIED SEARCH TABLES
# =============================================================================

class SkillChunk(Base):
    """Parsed skill knowledge chunks for semantic search"""
    __tablename__ = "skill_chunks"

    id = Column(Integer, primary_key=True, index=True)
    skill_name = Column(String, nullable=False, index=True)
    skill_command = Column(String)  # e.g. "/director-morning"
    description = Column(Text)
    section = Column(String)  # Section header within the skill
    category = Column(String, index=True)  # director, personal_assistant, opex, general
    content = Column(Text, nullable=False)
    file_path = Column(String)
    content_hash = Column(String)  # For change detection
    indexed_at = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_skill_chunks_name_section', 'skill_name', 'section'),
    )


class Embedding(Base):
    """Vector embeddings storage for semantic search.

    source_type values:
    - 'entry': entries
    - 'skill': Skill knowledge chunks (source_id -> skill_chunks.id)
    - 'qa': Q&A learning pairs (source_id -> qa_pairs.id)
    - 'correction': Correction learner (source_id -> corrections.id)
    """
    __tablename__ = "embeddings"

    id = Column(Integer, primary_key=True, index=True)
    source_type = Column(String, nullable=False, index=True)  # 'entry', 'skill', 'qa', 'correction'
    source_id = Column(Integer, nullable=False, index=True)  # ID in source table
    chunk_index = Column(Integer, default=0)  # For multi-chunk documents
    chunk_text = Column(Text)  # The text that was embedded
    embedding = Column(Text)  # JSON-encoded vector (portable across SQLite versions)
    embedding_model = Column(String, default="text-embedding-3-small")
    chunk_metadata = Column(Text)  # JSON metadata (section headers, content type, etc.)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_embeddings_source', 'source_type', 'source_id'),
        Index('ix_embeddings_chunk', 'source_type', 'source_id', 'chunk_index', unique=True),
    )


# =============================================================================
# SAVED SEARCHES
# =============================================================================

class SavedSearch(Base):
    """Saved search queries for quick access"""
    __tablename__ = "saved_searches"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    query = Column(String)  # Search query text
    filters = Column(Text)  # JSON string with filter parameters
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    last_used_at = Column(DateTime)  # Track usage for sorting
    use_count = Column(Integer, default=0)  # Track how many times used

    __table_args__ = (
        Index('ix_saved_searches_name', 'name'),
    )


# =============================================================================
# ENTRY TEMPLATES
# =============================================================================

class EntryTemplate(Base):
    """Templates for creating entries with predefined structure"""
    __tablename__ = "entry_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    title_template = Column(String)  # Template for title (supports variables)
    content_template = Column(Text)  # Template for content
    summary_template = Column(Text)  # Template for summary
    tags = Column(String)  # Default tags
    source_type = Column(String, default="manual")  # Default source type
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    use_count = Column(Integer, default=0)  # Track usage

    __table_args__ = (
        Index('ix_entry_templates_name', 'name'),
    )


# =============================================================================
# CONVERSATIONS
# =============================================================================

class Conversation(Base):
    """Conversation sessions for multi-turn AI interactions"""
    __tablename__ = "conversations"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, index=True, nullable=False)
    title = Column(String)  # Auto-generated from first question
    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    # Relationships
    messages = relationship("ConversationMessage", back_populates="conversation", cascade="all, delete-orphan", order_by="ConversationMessage.created_at")

    __table_args__ = (
        Index('ix_conversations_session', 'session_id'),
        Index('ix_conversations_updated', 'updated_at'),
    )


class ConversationMessage(Base):
    """Messages within a conversation"""
    __tablename__ = "conversation_messages"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    role = Column(String, nullable=False)  # 'user' or 'assistant'
    content = Column(Text, nullable=False)
    sources = Column(JSON)  # Store source metadata as JSON
    query_intent = Column(JSON)  # Store query classification info
    sql_queries_used = Column(JSON)  # Store SQL queries if any
    skills_executed = Column(JSON)  # Store executed skills if any
    created_at = Column(DateTime, default=utc_now, index=True)

    # Relationships
    conversation = relationship("Conversation", back_populates="messages")

    __table_args__ = (
        Index('ix_conversation_messages_conversation', 'conversation_id', 'created_at'),
    )


# =============================================================================
# ACTION EXECUTION LOGGING
# =============================================================================

class ActionLog(Base):
    """
    Log of executed actions from the cmd+k interface.

    Tracks slash command executions, skill invocations, and entity mutations
    for history, debugging, and user visibility.
    """
    __tablename__ = "action_logs"

    id = Column(Integer, primary_key=True, index=True)

    # Action identification
    action_type = Column(String, nullable=False, index=True)  # 'command' | 'skill' | 'mutation'
    action_name = Column(String, nullable=False, index=True)  # '/morning' | 'team-sync' | 'todo'

    # Input context
    input_query = Column(Text)  # Original user query that triggered this action
    arguments = Column(Text)  # Parsed arguments for the action
    classification_confidence = Column(Float)  # How confident we were this was the right action

    # Execution result
    result = Column(Text)  # Output from execution (truncated if too long)
    status = Column(String, nullable=False, default="pending", index=True)  # success, error, cancelled, timeout, pending
    error_message = Column(Text)  # Error details if failed

    # Timing
    executed_at = Column(DateTime, default=utc_now, index=True)
    duration_ms = Column(Integer)  # Execution time in milliseconds

    # Metadata
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_action_logs_type_status', 'action_type', 'status'),
        Index('ix_action_logs_executed', 'executed_at'),
        Index('ix_action_logs_name', 'action_name'),
    )


# =============================================================================
# AGENT PLANNING & GOALS
# =============================================================================

class AgentPlan(Base):
    """Plan for multi-step autonomous execution."""
    __tablename__ = "agent_plans"

    id = Column(Integer, primary_key=True, index=True)
    goal = Column(Text, nullable=False)
    status = Column(String, default="pending", index=True)  # pending | running | completed | failed
    context_snapshot = Column(JSON)
    auto_execute_threshold = Column(String, default="medium")

    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    steps = relationship(
        "AgentPlanStep",
        back_populates="plan",
        cascade="all, delete-orphan",
        order_by="AgentPlanStep.step_index",
    )

    __table_args__ = ()


class AgentPlanStep(Base):
    """Individual step within an agent plan."""
    __tablename__ = "agent_plan_steps"

    id = Column(Integer, primary_key=True, index=True)
    plan_id = Column(Integer, ForeignKey("agent_plans.id", ondelete="CASCADE"), index=True)
    step_index = Column(Integer, nullable=False)
    title = Column(String, nullable=False)
    action_type = Column(String)  # command | skill | mutation | insight
    action_name = Column(String)
    arguments = Column(Text)
    risk_level = Column(String, default="medium")
    status = Column(String, default="pending", index=True)  # pending | running | completed | failed | blocked
    result_summary = Column(Text)
    error_message = Column(Text)
    output_json = Column(JSON)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    plan = relationship("AgentPlan", back_populates="steps")
    outcomes = relationship(
        "AgentOutcome",
        back_populates="plan_step",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index('ix_agent_plan_steps_plan', 'plan_id', 'step_index'),
    )


class AgentOutcome(Base):
    """Outcome log for plan steps."""
    __tablename__ = "agent_outcomes"

    id = Column(Integer, primary_key=True, index=True)
    plan_step_id = Column(Integer, ForeignKey("agent_plan_steps.id", ondelete="CASCADE"), index=True)
    action_type = Column(String)
    action_name = Column(String)
    status = Column(String, default="pending")
    success = Column(Boolean, default=False)
    duration_ms = Column(Integer)
    output_summary = Column(Text)
    error_message = Column(Text)
    metadata_json = Column(JSON)
    created_at = Column(DateTime, default=utc_now, index=True)

    plan_step = relationship("AgentPlanStep", back_populates="outcomes")

    __table_args__ = ()


class Goal(Base):
    """User or system-defined goals."""
    __tablename__ = "goals"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    description = Column(Text)
    status = Column(String, default="active", index=True)  # active | paused | completed
    priority = Column(String, default="medium", index=True)
    target_date = Column(DateTime)
    progress = Column(Integer, default=0)  # 0-100
    source = Column(String, default="user")  # user | system

    created_at = Column(DateTime, default=utc_now, index=True)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    updates = relationship(
        "GoalUpdate",
        back_populates="goal",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index('ix_goals_status_priority', 'status', 'priority'),
    )


class GoalUpdate(Base):
    """Progress updates for goals."""
    __tablename__ = "goal_updates"

    id = Column(Integer, primary_key=True, index=True)
    goal_id = Column(Integer, ForeignKey("goals.id", ondelete="CASCADE"), index=True)
    update_type = Column(String, default="note")  # note | progress | status
    note = Column(Text)
    progress_delta = Column(Integer, default=0)
    created_at = Column(DateTime, default=utc_now, index=True)

    goal = relationship("Goal", back_populates="updates")

    __table_args__ = (
        Index('ix_goal_updates_goal', 'goal_id', 'created_at'),
    )


# =============================================================================
# SKILL EVOLUTION SYSTEM
# =============================================================================

class SkillExecution(Base):
    """
    Tracks every skill/command execution for learning and evolution.

    This enables:
    - Success rate tracking per skill
    - Duration analysis for performance optimization
    - Usage pattern detection
    - Automatic staleness detection for unused skills
    """
    __tablename__ = "skill_executions"

    id = Column(Integer, primary_key=True, index=True)

    # Skill identification
    skill_name = Column(String, nullable=False, index=True)  # e.g., 'pa-meeting', 'director-weekly'
    skill_type = Column(String, default='command')  # 'command' | 'skill' | 'meta'
    skill_path = Column(String)  # Full path to the skill file

    # Execution context
    executed_at = Column(DateTime, default=utc_now, index=True)
    duration_ms = Column(Integer)  # Execution time in milliseconds
    arguments_used = Column(Text)  # Arguments passed to the skill

    # Outcome
    completed_successfully = Column(Boolean, default=True)
    error_message = Column(Text)
    output_summary = Column(Text)  # Brief summary of what was produced

    # User behavior signals (implicit feedback)
    user_continued_session = Column(Boolean)  # Did user keep working after?
    user_gave_correction = Column(Boolean, default=False)  # Did user correct output?
    follow_up_skill = Column(String)  # What skill was used next?

    # Version tracking
    skill_version = Column(String)  # Version at time of execution

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_skill_exec_name_date', 'skill_name', 'executed_at'),
        Index('ix_skill_exec_success', 'skill_name', 'completed_successfully'),
    )


class SkillFeedback(Base):
    """
    Explicit user feedback on skill behavior.

    Categories:
    - output_format: Wrong format, layout, structure
    - missing_data: Expected data not included
    - wrong_logic: Incorrect behavior or logic
    - ux: Usability issues (confusing, too slow, etc.)
    - enhancement: Feature requests
    """
    __tablename__ = "skill_feedback"

    id = Column(Integer, primary_key=True, index=True)

    # Skill identification
    skill_name = Column(String, nullable=False, index=True)
    skill_version = Column(String)  # Version at time of feedback

    # Feedback categorization
    feedback_type = Column(String, nullable=False, index=True)  # 'correction' | 'suggestion' | 'complaint' | 'praise'
    affected_aspect = Column(String, index=True)  # 'output_format' | 'missing_data' | 'wrong_logic' | 'ux' | 'enhancement'
    severity = Column(String, default='medium')  # 'low' | 'medium' | 'high' | 'critical'

    # Feedback content
    user_feedback = Column(Text, nullable=False)  # What user said
    context = Column(Text)  # What was happening when feedback was given
    expected_behavior = Column(Text)  # What user expected
    actual_behavior = Column(Text)  # What actually happened

    # AI analysis
    suggested_fix = Column(Text)  # AI-generated suggested fix
    related_code_section = Column(Text)  # Which part of skill needs change
    confidence = Column(Float)  # AI confidence in the suggestion

    # Resolution tracking
    addressed = Column(Boolean, default=False, index=True)
    addressed_in_version = Column(String)
    addressed_at = Column(DateTime)

    # Linking to execution
    execution_id = Column(Integer, ForeignKey('skill_executions.id'))

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_skill_feedback_unaddressed', 'skill_name', 'addressed'),
        Index('ix_skill_feedback_type', 'feedback_type', 'affected_aspect'),
    )


class SkillVersion(Base):
    """
    Version control for skill files.

    Stores full content of each version for:
    - Instant rollback capability
    - A/B comparison between versions
    - Performance tracking per version
    - Change history visualization
    """
    __tablename__ = "skill_versions"

    id = Column(Integer, primary_key=True, index=True)

    # Skill identification
    skill_name = Column(String, nullable=False, index=True)
    skill_path = Column(String)

    # Version info
    version_number = Column(String, nullable=False)  # Semantic version: 1.0.0, 1.0.1, etc.
    version_type = Column(String, default='patch')  # 'major' | 'minor' | 'patch'

    # Content
    content = Column(Text, nullable=False)  # Full skill file content
    content_hash = Column(String)  # Hash for quick comparison

    # Change details
    change_summary = Column(Text)  # Human-readable summary
    change_reason = Column(String)  # 'feedback' | 'suggestion' | 'manual' | 'auto_evolve'
    diff_from_previous = Column(Text)  # Diff against previous version

    # Performance metrics (collected after deployment)
    success_rate = Column(Float)  # Success rate for this version
    avg_execution_time_ms = Column(Float)  # Average execution time
    feedback_count = Column(Integer, default=0)  # Total feedback received
    negative_feedback_count = Column(Integer, default=0)  # Negative feedback count

    # Status
    is_active = Column(Boolean, default=True, index=True)  # Currently deployed version
    rolled_back_at = Column(DateTime)
    rolled_back_reason = Column(Text)

    # Related suggestion that prompted this version
    suggestion_id = Column(Integer, ForeignKey('skill_suggestions.id'))

    created_at = Column(DateTime, default=utc_now)
    created_by = Column(String, default='system')  # 'system' | 'user' | 'auto_evolve'

    __table_args__ = (
        Index('ix_skill_version_active', 'skill_name', 'is_active'),
        Index('ix_skill_version_number', 'skill_name', 'version_number'),
    )


class SkillSuggestion(Base):
    """
    AI-generated improvement suggestions for skills.

    Evidence sources:
    - feedback: Aggregated from multiple user feedback items
    - execution_pattern: Detected from execution metrics
    - api_change: External API changed, skill needs update
    - dependency: Dependency skill changed
    - enhancement: Proactive improvement opportunity
    """
    __tablename__ = "skill_suggestions"

    id = Column(Integer, primary_key=True, index=True)

    # Skill identification
    skill_name = Column(String, nullable=False, index=True)
    current_version = Column(String)  # Version this suggestion applies to

    # Suggestion type
    suggestion_type = Column(String, nullable=False, index=True)  # 'fix' | 'enhancement' | 'refactor' | 'deprecation'
    priority = Column(String, default='medium')  # 'low' | 'medium' | 'high' | 'critical'

    # Evidence
    evidence_source = Column(String, nullable=False)  # 'feedback' | 'execution_pattern' | 'api_change' | 'dependency' | 'enhancement'
    evidence_summary = Column(Text)  # Summary of evidence supporting this suggestion
    evidence_count = Column(Integer, default=1)  # Number of supporting data points

    # The suggestion itself
    title = Column(String, nullable=False)  # Brief title
    description = Column(Text)  # Detailed description
    proposed_diff = Column(Text)  # Proposed changes in diff format
    proposed_content = Column(Text)  # Full proposed new content

    # AI analysis
    confidence_score = Column(Float)  # 0.0-1.0 confidence in this suggestion
    impact_assessment = Column(Text)  # Expected impact of applying this
    risk_assessment = Column(Text)  # Potential risks

    # Related feedback (if applicable)
    related_feedback_ids = Column(String)  # Comma-separated feedback IDs

    # Approval workflow
    status = Column(String, default='pending', index=True)  # 'pending' | 'approved' | 'rejected' | 'applied' | 'expired'
    reviewed_at = Column(DateTime)
    reviewed_by = Column(String)
    rejection_reason = Column(Text)

    # Application tracking
    applied_at = Column(DateTime)
    applied_version = Column(String)  # Version created when applied

    # Timing
    created_at = Column(DateTime, default=utc_now)
    expires_at = Column(DateTime)  # Suggestions can expire if not acted upon

    __table_args__ = (
        Index('ix_skill_suggestion_pending', 'skill_name', 'status'),
        Index('ix_skill_suggestion_priority', 'priority', 'status'),
    )


# =============================================================================
# RAG FEEDBACK
# =============================================================================

class RAGFeedback(Base):
    """
    User feedback on RAG system responses.

    Collects:
    - Explicit feedback (thumbs up/down, ratings)
    - Implicit signals (copy, retry, correction)
    - Quality metrics for continuous improvement
    """
    __tablename__ = "rag_feedback"

    id = Column(Integer, primary_key=True, index=True)

    # Query identification
    query_hash = Column(String, index=True)  # Hash of original question
    question = Column(Text, nullable=False)  # The question asked
    answer = Column(Text)  # The answer generated

    # Source information
    source_count = Column(Integer, default=0)  # Number of sources used
    source_types = Column(String)  # Comma-separated source types
    model_used = Column(String)  # Model that generated the answer

    # User feedback
    rating = Column(Integer)  # 1-5 star rating or -1/0/1 for down/neutral/up
    feedback_type = Column(String, index=True)  # 'explicit' | 'implicit'
    feedback_text = Column(Text)  # Optional user comment
    correction = Column(Text)  # User-provided correction

    # Computed quality metrics (at time of generation)
    confidence_score = Column(Float)  # System confidence
    source_confidence = Column(Float)  # Source-based confidence
    faithfulness_score = Column(Float)  # From verification
    relevance_score = Column(Float)  # From verification

    # Query metadata
    intent_type = Column(String)  # structured, semantic, hybrid, skill
    matched_domains = Column(String)  # Comma-separated domains

    # Timing
    response_time_ms = Column(Integer)  # Time to generate response
    created_at = Column(DateTime, default=utc_now, index=True)

    # Session context
    session_id = Column(String, index=True)  # Link to conversation if any
    conversation_message_id = Column(Integer)  # Link to specific message

    __table_args__ = (
        Index('ix_rag_feedback_query', 'query_hash'),
        Index('ix_rag_feedback_rating', 'rating'),
        Index('ix_rag_feedback_created', 'created_at'),
    )


# =============================================================================
# AI NEWSLETTER SYSTEM
# =============================================================================

class NewsletterItem(Base):
    """
    Tracked newsletter items to prevent duplicates and enable history.
    Each item represents a news article, release, or post from any source.
    """
    __tablename__ = "newsletter_items"

    id = Column(Integer, primary_key=True, index=True)
    url_hash = Column(String(64), unique=True, nullable=False, index=True)  # SHA256 of URL for dedup
    url = Column(String(2048), nullable=False)
    title = Column(String(500), nullable=False)
    source = Column(String(100), nullable=False, index=True)  # e.g., "reddit_localllama", "github_cursor"
    source_type = Column(String(50), nullable=False)  # rss, github, reddit, nitter, scrape, x_bookmark
    category = Column(String(50), index=True)  # tools, research, industry, tutorials
    published_at = Column(DateTime, index=True)
    fetched_at = Column(DateTime, default=utc_now, index=True)
    content_raw = Column(Text)  # Original content/description
    content_summary = Column(Text)  # AI-generated summary
    relevance_score = Column(Float, default=0.5)  # AI-assigned relevance (0-1)
    included_in_newsletter = Column(DateTime)  # When included in a newsletter edition
    extra_data = Column(JSON)  # Extra fields (author, tags, score, etc.)

    __table_args__ = (
        Index('ix_newsletter_items_source_date', 'source', 'published_at'),
        Index('ix_newsletter_items_category_date', 'category', 'fetched_at'),
    )


class NewsletterEdition(Base):
    """
    Generated newsletter editions - one per day.
    Tracks what was generated, where it was saved, and if email was sent.
    """
    __tablename__ = "newsletter_editions"

    id = Column(Integer, primary_key=True, index=True)
    edition_date = Column(Date, unique=True, nullable=False, index=True)
    generated_at = Column(DateTime, default=utc_now)
    item_count = Column(Integer, default=0)
    file_path = Column(String(500))  # Path to Obsidian file
    email_sent = Column(Boolean, default=False)
    email_sent_at = Column(DateTime)
    email_recipients = Column(String)  # Comma-separated recipients
    categories = Column(JSON)  # {"tools": 5, "research": 3, ...}
    sources_fetched = Column(JSON)  # {"reddit": 10, "github": 3, "rss": 15, ...}
    errors = Column(JSON)  # Any source fetch errors

    __table_args__ = (
        Index('ix_newsletter_editions_date', 'edition_date'),
    )


class XNewsletterItem(Base):
    """
    X.com newsletter items with deep analysis and GitHub repos.
    Tracks tweets from X Intelligence with enhanced metadata.
    """
    __tablename__ = "x_newsletter_items"

    id = Column(Integer, primary_key=True, index=True)
    tweet_id = Column(String(64), unique=True, index=True)  # X.com tweet ID
    tweet_url = Column(String(2048), nullable=False)

    # Author info
    author_handle = Column(String(100), index=True)
    author_name = Column(String(200))

    # Content
    content = Column(Text)
    title = Column(String(500))  # Truncated content for display

    # Engagement metrics
    likes = Column(Integer, default=0)
    retweets = Column(Integer, default=0)
    replies = Column(Integer, default=0)
    engagement_score = Column(Float, default=0)

    # Source info
    source_type = Column(String(50))  # bookmark, profile, search, network

    # Deep analysis (stored as JSON)
    deep_analysis = Column(JSON)  # {"summary": "...", "key_insights": [...], "why_it_matters": "...", etc.}

    # GitHub repos (stored as JSON array)
    github_repos = Column(JSON)  # [{"url": "...", "stars": 1000, "language": "Python", ...}]

    # Topics extracted
    topics = Column(JSON)  # ["ai-agents", "coding-tools", ...]

    # Newsletter inclusion
    included_date = Column(Date, index=True)  # Date when included in newsletter
    newsletter_edition_id = Column(Integer, ForeignKey("newsletter_editions.id"))

    # Timestamps
    tweet_published_at = Column(DateTime)
    fetched_at = Column(DateTime, default=utc_now)
    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_x_newsletter_items_author', 'author_handle'),
        Index('ix_x_newsletter_items_included', 'included_date'),
        Index('ix_x_newsletter_items_engagement', 'engagement_score'),
    )


# =============================================================================
# SUPER SMART AGENT - INTELLIGENCE & MEMORY MODELS
# =============================================================================

class Experience(Base):
    """
    Episodic memory: Learn from past decisions and their outcomes.
    "Last time we had this situation, X happened when we did Y."
    """
    __tablename__ = "experiences"

    id = Column(Integer, primary_key=True, index=True)
    experience_type = Column(String, nullable=False, index=True)  # decision, escalation, conflict, delivery_issue, team_change, incident
    situation_summary = Column(Text, nullable=False)  # What was the situation
    context_snapshot = Column(Text)  # JSON: State when it happened (metrics, team status, etc.)

    # What happened
    action_taken = Column(Text)  # What you did
    outcome = Column(Text)  # What happened as a result
    outcome_rating = Column(Integer)  # 1-10: How well it worked
    learnings = Column(Text)  # What was learned

    # Classification
    tags = Column(String)  # Comma-separated tags for searching
    team = Column(String, index=True)  # Team if team-specific
    people_involved = Column(String)  # Comma-separated names
    related_decision_id = Column(Integer, ForeignKey("decisions.id"))
    related_epic_key = Column(String)  # If related to a Jira epic

    # For semantic search
    embedding_id = Column(String)  # Reference to ChromaDB embedding

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_experiences_type', 'experience_type'),
        Index('ix_experiences_team', 'team'),
        Index('ix_experiences_created', 'created_at'),
    )


class UserPreference(Base):
    """
    Semantic memory: Track what the user cares about based on engagement.
    System learns to prioritize content matching user's interests.
    """
    __tablename__ = "user_preferences"

    id = Column(Integer, primary_key=True, index=True)
    preference_type = Column(String, nullable=False, index=True)  # topic, metric, team, person, command
    preference_key = Column(String, nullable=False)  # The specific item (e.g., "security", "velocity")

    # Engagement tracking
    engagement_count = Column(Integer, default=0)  # How often user queries this
    last_engaged = Column(DateTime)

    # Weights
    explicit_weight = Column(Float)  # User-set importance (0-1), null if not set
    calculated_weight = Column(Float, default=0.5)  # System-calculated from engagement

    # Context
    context_notes = Column(Text)  # Why this matters to the user

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_preferences_type_key', 'preference_type', 'preference_key', unique=True),
        Index('ix_preferences_weight', 'calculated_weight'),
    )


class DetectedPattern(Base):
    """
    Procedural memory: Patterns detected in data that suggest action.
    "When X happens followed by Y, Z usually occurs."
    """
    __tablename__ = "detected_patterns"

    id = Column(Integer, primary_key=True, index=True)
    pattern_type = Column(String, nullable=False, index=True)  # velocity_decline, communication_gap, risk_indicator, burnout_signal
    pattern_name = Column(String, nullable=False)  # Human-readable name
    pattern_description = Column(Text, nullable=False)  # Full description

    # Detection
    detection_logic = Column(Text)  # Description or SQL/query for detection
    trigger_conditions = Column(Text)  # JSON: Conditions that trigger this pattern
    frequency = Column(String, default="daily")  # daily, weekly, on_trigger, real_time

    # Confidence
    confidence_score = Column(Float, default=0.5)  # 0-1 based on historical accuracy
    times_detected = Column(Integer, default=0)
    times_accurate = Column(Integer, default=0)  # Times prediction was correct
    last_detected = Column(DateTime)

    # Response
    recommended_action = Column(Text)  # What to do when detected
    severity = Column(String, default="medium")  # low, medium, high, critical

    # Active/inactive
    is_active = Column(Boolean, default=True)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_patterns_type', 'pattern_type'),
        Index('ix_patterns_active', 'is_active'),
    )


class Prediction(Base):
    """
    Track predictions and their accuracy to improve over time.
    Used to verify prediction quality and tune the system.
    """
    __tablename__ = "predictions"

    id = Column(Integer, primary_key=True, index=True)
    prediction_type = Column(String, nullable=False, index=True)  # meeting_topic, stakeholder_question, risk, daily_need
    prediction_context = Column(Text)  # What triggered this prediction

    # The prediction
    predicted_value = Column(Text, nullable=False)  # What was predicted
    confidence = Column(Float)  # 0-1 confidence score
    reasoning = Column(Text)  # Why this was predicted

    # Verification
    actual_value = Column(Text)  # What actually happened (filled later)
    was_accurate = Column(Boolean)  # True/False/Null (unverified)
    accuracy_notes = Column(Text)  # Notes on why accurate/inaccurate

    # Linkage
    related_event_id = Column(Integer)  # Calendar event, meeting, etc.
    related_person = Column(String)

    created_at = Column(DateTime, default=utc_now)
    verified_at = Column(DateTime)

    __table_args__ = (
        Index('ix_predictions_type', 'prediction_type'),
        Index('ix_predictions_verified', 'was_accurate'),
        Index('ix_predictions_created', 'created_at'),
    )


class StakeholderExpectation(Base):
    """
    Track what stakeholders expect from you.
    Powers question prediction and proactive updates.
    """
    __tablename__ = "stakeholder_expectations"

    id = Column(Integer, primary_key=True, index=True)
    stakeholder_name = Column(String, nullable=False, index=True)

    # The expectation
    expectation = Column(Text, nullable=False)  # What they expect
    category = Column(String)  # delivery, communication, quality, innovation, people

    # Source
    source = Column(String, default="inferred")  # stated, inferred, feedback
    source_context = Column(Text)  # Where this expectation came from

    # Status
    priority = Column(Integer, default=5)  # 1-10, higher = more important
    status = Column(String, default="active")  # active, met, unmet, outdated
    last_addressed = Column(DateTime)  # When we last addressed this

    # Tracking
    times_asked_about = Column(Integer, default=0)  # How often they bring this up

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_stakeholder_exp_name', 'stakeholder_name'),
        Index('ix_stakeholder_exp_status', 'status'),
        Index('ix_stakeholder_exp_priority', 'priority'),
    )


class RelationshipHealth(Base):
    """
    Track relationship health with key people.
    "You haven't talked to X in Y days"
    """
    __tablename__ = "relationship_health"

    id = Column(Integer, primary_key=True, index=True)
    person_name = Column(String, nullable=False, unique=True, index=True)

    # Relationship type
    relationship_type = Column(String)  # direct_report, peer, stakeholder, skip_level, external
    team = Column(String)  # Their team if applicable
    role = Column(String)  # Their role

    # Interaction tracking
    last_interaction = Column(DateTime)  # Last time any interaction
    last_1on1 = Column(DateTime)  # Last 1:1 meeting
    last_meaningful_conversation = Column(DateTime)  # Last substantive discussion

    # Targets
    target_interaction_frequency_days = Column(Integer, default=14)  # How often you should interact
    target_1on1_frequency_days = Column(Integer)  # How often 1:1s should happen

    # Health score (calculated)
    health_score = Column(Integer)  # 0-100, based on frequency vs target
    health_trend = Column(String)  # improving, stable, declining

    # Context
    current_concerns = Column(Text)  # Any concerns about this relationship
    notes = Column(Text)  # General notes

    # Topics to remember
    important_topics = Column(Text)  # JSON: Topics to remember for this person
    open_commitments_to = Column(Text)  # JSON: Things you owe them
    open_commitments_from = Column(Text)  # JSON: Things they owe you

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_relationship_person', 'person_name'),
        Index('ix_relationship_type', 'relationship_type'),
        Index('ix_relationship_health', 'health_score'),
    )


class ActionDraft(Base):
    """
    Prepared actions awaiting approval.
    System drafts actions, user approves before execution.
    """
    __tablename__ = "action_drafts"

    id = Column(Integer, primary_key=True, index=True)
    action_type = Column(String, nullable=False, index=True)  # jira_ticket, email, meeting, slack_message, reminder, follow_up

    # Source of the draft
    source_type = Column(String)  # meeting, alert, pattern, user_request, prediction
    source_id = Column(Integer)  # ID of source (meeting_outcome_id, alert_id, etc.)
    source_context = Column(Text)  # Context about why this was drafted

    # The draft
    draft_title = Column(String)  # Brief title
    draft_content = Column(Text, nullable=False)  # JSON: Full draft details

    # Confidence
    confidence_score = Column(Float)  # 0-1 how confident system is
    reasoning = Column(Text)  # Why this action was suggested

    # Status
    status = Column(String, default="pending", index=True)  # pending, approved, rejected, executed, expired

    # Approval
    presented_at = Column(DateTime)  # When shown to user
    approved_at = Column(DateTime)
    rejected_at = Column(DateTime)
    rejection_reason = Column(Text)

    # Execution
    executed_at = Column(DateTime)
    execution_result = Column(Text)  # JSON: Result of execution
    execution_error = Column(Text)  # Error if failed

    # Expiration
    expires_at = Column(DateTime)  # When this draft becomes stale

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_drafts_type', 'action_type'),
        Index('ix_drafts_status', 'status'),
        Index('ix_drafts_created', 'created_at'),
    )


class MeetingPrepCache(Base):
    """
    Pre-generated meeting preparation briefs.
    Generated 30 minutes before meetings for quick access.
    """
    __tablename__ = "meeting_prep_cache"

    id = Column(Integer, primary_key=True, index=True)
    calendar_event_id = Column(String, nullable=False, unique=True, index=True)  # External calendar event ID

    # Meeting info
    meeting_title = Column(String)
    meeting_time = Column(DateTime, index=True)
    participants = Column(Text)  # JSON array
    meeting_type = Column(String)  # 1on1, team_sync, stakeholder, external

    # Prep content (all JSON)
    last_meeting_summary = Column(Text)  # Summary of last meeting with same participants
    open_commitments = Column(Text)  # JSON: Commitments involving these participants
    pending_decisions = Column(Text)  # JSON: Decisions pending with these people
    predicted_topics = Column(Text)  # JSON: What will likely be discussed
    predicted_questions = Column(Text)  # JSON: What they might ask
    talking_points = Column(Text)  # JSON: Suggested talking points
    recent_context = Column(Text)  # JSON: Recent relevant changes/updates
    relationship_notes = Column(Text)  # JSON: Relationship health for each participant

    # Historical context
    similar_meetings = Column(Text)  # JSON: Similar past meetings and what worked

    # Metadata
    generated_at = Column(DateTime, default=utc_now)
    generation_time_ms = Column(Integer)  # How long generation took

    # Feedback
    was_useful = Column(Boolean)  # User feedback
    feedback_notes = Column(Text)

    __table_args__ = (
        Index('ix_meeting_prep_time', 'meeting_time'),
        Index('ix_meeting_prep_event', 'calendar_event_id'),
    )


class AgentSession(Base):
    """
    Persistent Claude agent sessions, surviving server restarts.
    Replaces in-memory ClaudeSession dict in claude_agent_service.py.
    """
    __tablename__ = "agent_sessions"

    id = Column(Integer, primary_key=True, index=True)
    session_id = Column(String, unique=True, nullable=False, index=True)
    channel = Column(String, nullable=False, default="cli")       # cli, web, slack
    status = Column(String, nullable=False, default="active")     # active, completed, expired, error
    message_count = Column(Integer, default=0)
    total_cost_usd = Column(Float, default=0.0)
    total_input_tokens = Column(Integer, default=0)
    total_output_tokens = Column(Integer, default=0)
    subagents_used = Column(Text)       # JSON list: ["delivery", "security"]
    fallback_count = Column(Integer, default=0)
    last_query = Column(Text)
    model_used = Column(String)
    error_message = Column(Text)
    created_at = Column(DateTime, default=utc_now, nullable=False)
    last_activity = Column(DateTime, default=utc_now, nullable=False)
    completed_at = Column(DateTime)

    __table_args__ = (
        Index('ix_agent_sessions_channel_status', 'channel', 'status'),
    )

    def to_dict(self):
        return {
            "session_id": self.session_id,
            "channel": self.channel,
            "status": self.status,
            "message_count": self.message_count,
            "total_cost_usd": self.total_cost_usd,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "last_activity": self.last_activity.isoformat() if self.last_activity else None,
        }


class AgentTask(Base):
    """
    Track multi-agent orchestration tasks.
    Records which agents were involved and their contributions.
    """
    __tablename__ = "agent_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_id = Column(String, unique=True, index=True)  # UUID for tracking

    # Task info
    user_query = Column(Text, nullable=False)  # Original user query
    task_type = Column(String)  # analysis, action, prediction, synthesis

    # Orchestration
    agents_involved = Column(Text)  # JSON: ["delivery", "people", "security"]
    routing_reasoning = Column(Text)  # Why these agents were chosen

    # Agent contributions (JSON)
    agent_insights = Column(Text)  # JSON: {agent: insight} for each agent
    cross_domain_connections = Column(Text)  # JSON: Connections found across domains
    conflicts_detected = Column(Text)  # JSON: Any conflicting insights

    # Final response
    synthesized_response = Column(Text)  # Final response to user
    recommended_actions = Column(Text)  # JSON: Actions recommended
    confidence_score = Column(Float)  # Overall confidence

    # Performance
    total_time_ms = Column(Integer)  # Total processing time
    agent_times = Column(Text)  # JSON: {agent: time_ms}

    # Feedback
    user_satisfaction = Column(Integer)  # 1-5 if provided
    feedback_notes = Column(Text)

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_agent_tasks_type', 'task_type'),
        Index('ix_agent_tasks_created', 'created_at'),
    )


class DailyContext(Base):
    """
    Daily context snapshot for proactive intelligence.
    Generated each morning with predictions and priorities.
    """
    __tablename__ = "daily_context"

    id = Column(Integer, primary_key=True, index=True)
    context_date = Column(Date, unique=True, nullable=False, index=True)

    # Schedule context
    meetings_today = Column(Text)  # JSON: Today's meetings with prep status
    high_priority_meetings = Column(Text)  # JSON: Meetings needing extra attention

    # What changed overnight
    changes_overnight = Column(Text)  # JSON: Significant changes since yesterday
    new_alerts = Column(Text)  # JSON: Alerts triggered overnight

    # Predictions for today
    predicted_needs = Column(Text)  # JSON: What you'll likely need today
    predicted_risks = Column(Text)  # JSON: Risks that might materialize
    predicted_questions = Column(Text)  # JSON: Questions stakeholders might ask

    # Priorities
    suggested_priorities = Column(Text)  # JSON: What to focus on today
    deferred_items = Column(Text)  # JSON: Items that can wait

    # Relationship alerts
    relationship_alerts = Column(Text)  # JSON: People you should reach out to

    # Open items
    open_commitments = Column(Text)  # JSON: Commitments due soon
    overdue_items = Column(Text)  # JSON: Items past due
    pending_decisions = Column(Text)  # JSON: Decisions needing attention

    # Generated content
    morning_brief = Column(Text)  # Full morning brief text

    # Domain health & risk (written by AgentOrchestrator)
    health_snapshot = Column(Text)    # JSON: Domain health scores
    critical_items = Column(Text)     # JSON: Critical risks
    priorities = Column(Text)         # JSON: Top priorities

    generated_at = Column(DateTime, default=utc_now)

    # Feedback
    accuracy_score = Column(Float)  # How accurate predictions were (EOD review)
    feedback_notes = Column(Text)

    __table_args__ = (
        Index('ix_daily_context_date', 'context_date'),
    )


class ScheduledTask(Base):
    """
    Log of scheduled task executions.
    Tracks automated jobs run by the ProactiveScheduler.
    """
    __tablename__ = "scheduled_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_type = Column(String, nullable=False, index=True)  # daily_context, meeting_prep, etc.
    status = Column(String, nullable=False)  # completed, failed, skipped
    message = Column(Text)
    data = Column(Text)  # JSON: Task-specific data
    duration_ms = Column(Integer)
    executed_at = Column(DateTime, default=utc_now, index=True)

    __table_args__ = (
        Index('ix_scheduled_tasks_type_date', 'task_type', 'executed_at'),
    )


class NotificationLog(Base):
    """
    Log of notifications sent by the system.

    Stores all notifications so they can be retrieved via API,
    ensuring notifications work in any environment (Cursor, Claude Code, etc.)
    """
    __tablename__ = "notification_logs"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String, nullable=False)
    message = Column(Text, nullable=False)
    priority = Column(String, default="normal", index=True)  # normal, high, urgent
    category = Column(String, default="scheduler", index=True)  # scheduler, reminder, alert, etc.
    sent_at = Column(DateTime, default=utc_now, index=True)
    read_at = Column(DateTime, nullable=True, index=True)
    # Track which delivery method succeeded (terminal-notifier, osascript, plyer, email, file)
    delivery_method = Column(String, nullable=True)

    __table_args__ = (
        Index('ix_notification_logs_category_date', 'category', 'sent_at'),
        Index('ix_notification_logs_unread', 'read_at'),
    )


class QAPair(Base):
    """
    Q&A Learning System: Store question-answer pairs from Claude Code conversations.
    Enables semantic search to surface relevant past Q&A as context for future sessions.
    """
    __tablename__ = "qa_pairs"

    id = Column(Integer, primary_key=True, index=True)
    question = Column(Text, nullable=False)
    answer = Column(Text, nullable=False)

    # Context & classification
    source = Column(String, default="claude_code")  # claude_code, manual, import
    session_id = Column(String, index=True)  # Track conversation session
    category = Column(String, index=True)  # jira, teams, architecture, process, technical
    topics = Column(String)  # Comma-separated topic tags
    skills_used = Column(String)  # Comma-separated skills/commands used
    context_snapshot = Column(Text)  # JSON: State when captured (files open, project, etc.)

    # Feedback & verification
    feedback_score = Column(Integer)  # 1-5 rating from user
    is_verified = Column(Boolean, default=False)  # User confirmed as accurate
    was_useful = Column(Boolean)  # Thumbs up/down
    feedback_notes = Column(Text)  # User notes on quality

    # Usage tracking
    retrieval_count = Column(Integer, default=0)  # Times surfaced in search
    last_retrieved = Column(DateTime)  # Last time surfaced

    # Semantic search
    embedding_id = Column(String, unique=True, index=True)  # ChromaDB document reference (unique to prevent duplicates)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)

    __table_args__ = (
        Index('ix_qa_pairs_category', 'category'),
        Index('ix_qa_pairs_session', 'session_id'),
        Index('ix_qa_pairs_created', 'created_at'),
        Index('ix_qa_pairs_feedback', 'feedback_score'),
    )


# =========================================================================
# SELF-EVOLUTION LEARNING MODELS
# =========================================================================

class FeedbackSignal(Base):
    """
    Auto-detected feedback signals from user messages.
    Enables learning without explicit rating requests.
    """
    __tablename__ = "feedback_signals"

    id = Column(Integer, primary_key=True, index=True)

    # Signal detection
    signal_type = Column(String, nullable=False, index=True)  # positive, negative, correction, clarification
    signal_phrase = Column(String, nullable=False)  # The detected phrase ("perfect", "wrong", etc.)
    confidence = Column(Float, default=1.0)  # Detection confidence (0-1)

    # Context
    user_message = Column(Text, nullable=False)  # Full user message containing signal
    session_id = Column(String, index=True)  # Conversation session

    # Linked Q&A (if applicable)
    qa_pair_id = Column(Integer, ForeignKey("qa_pairs.id"), index=True)

    # Auto-rating derived from signal
    implied_rating = Column(Integer)  # 1-5 rating implied by signal

    # Processing
    processed = Column(Boolean, default=False)  # Whether feedback was applied
    processed_at = Column(DateTime)

    created_at = Column(DateTime, default=utc_now)


class Correction(Base):
    """
    Captures when user corrects Claude's response.
    Critical for learning from mistakes.
    """
    __tablename__ = "corrections"

    id = Column(Integer, primary_key=True, index=True)

    # Original response that was wrong
    original_response = Column(Text, nullable=False)
    original_response_summary = Column(String)  # Short summary of what was wrong

    # User's correction
    correction_text = Column(Text, nullable=False)  # What user said to correct
    correct_answer = Column(Text)  # The correct information (extracted)

    # Context
    question = Column(Text)  # Original question if available
    session_id = Column(String, index=True)
    qa_pair_id = Column(Integer, ForeignKey("qa_pairs.id"), index=True)

    # Classification
    error_type = Column(String, index=True)  # factual, incomplete, wrong_tool, misunderstood, etc.
    category = Column(String, index=True)  # jira, teams, technical, etc.

    # Embedding for similarity search
    embedding_id = Column(String, unique=True, index=True)  # ChromaDB reference

    # Learning application
    applied_to_qa = Column(Boolean, default=False)  # Whether Q&A was updated
    created_pattern = Column(Boolean, default=False)  # Whether error pattern was created

    created_at = Column(DateTime, default=utc_now)


class ErrorPattern(Base):
    """
    Tracks repeated errors to prevent recurrence.
    Aggregates similar corrections into actionable patterns.
    """
    __tablename__ = "error_patterns"

    id = Column(Integer, primary_key=True, index=True)

    # Pattern definition
    pattern_name = Column(String, nullable=False)  # e.g., "Klaviyo team misattribution"
    pattern_description = Column(Text)  # What the error pattern is

    # Trigger conditions
    trigger_keywords = Column(String)  # Comma-separated keywords that trigger this pattern
    trigger_category = Column(String, index=True)  # Category where this error occurs

    # Correct behavior
    correct_behavior = Column(Text, nullable=False)  # What Claude should do instead
    example_correct_response = Column(Text)  # Example of correct response

    # Statistics
    occurrence_count = Column(Integer, default=1)  # How many times this error occurred
    last_occurred = Column(DateTime)
    prevented_count = Column(Integer, default=0)  # How many times pattern prevented error

    # Status
    is_active = Column(Boolean, default=True)  # Whether to check for this pattern
    confidence = Column(Float, default=0.5)  # Confidence this is a real pattern (increases with occurrences)

    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class LearningEvent(Base):
    """
    Tracks all learning events for audit and analysis.
    Central log of what the system has learned.
    """
    __tablename__ = "learning_events"

    id = Column(Integer, primary_key=True, index=True)

    # Event type
    event_type = Column(String, nullable=False, index=True)  # feedback_signal, correction, pattern_created, qa_updated

    # Source
    source_table = Column(String)  # feedback_signals, corrections, etc.
    source_id = Column(Integer)  # ID in source table

    # What was learned
    learning_summary = Column(Text, nullable=False)  # Human-readable summary

    # Impact
    affected_qa_ids = Column(String)  # Comma-separated QA IDs affected
    affected_patterns = Column(String)  # Comma-separated pattern IDs affected

    # Metadata
    session_id = Column(String, index=True)

    created_at = Column(DateTime, default=utc_now)


# =========================================================================
# PHASE 3 & 4 MODELS
# =========================================================================

class RecurringPlanTemplate(Base):
    """
    Templates for recurring plans (daily standups, weekly reports, etc.).
    Feature: A7 - Recurring Plan Templates
    """
    __tablename__ = "recurring_plan_templates"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String, nullable=False)
    goal_template = Column(String, nullable=False)  # Template with {date} placeholder
    frequency = Column(String, nullable=False)  # daily, weekly, monthly
    day_of_week = Column(Integer)  # 0-6 for weekly (0=Monday)
    day_of_month = Column(Integer)  # 1-31 for monthly
    hour = Column(Integer, default=9)  # Hour to create plan
    is_active = Column(Boolean, default=True)
    last_run = Column(DateTime)
    extra_context = Column(Text)  # JSON for additional context
    created_at = Column(DateTime, default=utc_now)
    updated_at = Column(DateTime, default=utc_now, onupdate=utc_now)


class DoraMetricsSnapshot(Base):
    """
    Snapshot of DORA metrics for trend analysis.
    Feature: D4 - DORA Metrics Dashboard
    """
    __tablename__ = "dora_metrics_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    snapshot_date = Column(DateTime, default=utc_now, index=True)
    team = Column(String, index=True)  # NULL for overall metrics
    deployment_frequency = Column(Float)  # Deployments per day
    lead_time_hours = Column(Float)  # Average lead time in hours
    change_failure_rate = Column(Float)  # Percentage (0.0-1.0)
    mttr_hours = Column(Float)  # Mean time to restore in hours
    metrics_json = Column(Text)  # Full metrics as JSON
    created_at = Column(DateTime, default=utc_now)


# =============================================================================
# GITLAB INTELLIGENCE TABLES (Super-Agent Integration)
# =============================================================================

class GitLabRepo(Base):
    """
    Repository metadata synced from gitlab-analysis codebase.db.
    Enables unified queries combining Jira epics with code health metrics.
    """
    __tablename__ = "gitlab_repos"

    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(String, unique=True, nullable=False, index=True)  # team/repo format
    name = Column(String, nullable=False)
    team = Column(String, nullable=False, index=True)
    team_display = Column(String)

    # Code metrics
    primary_language = Column(String, index=True)
    total_files = Column(Integer, default=0)
    total_lines = Column(Integer, default=0)
    code_lines = Column(Integer, default=0)

    # Quality indicators
    has_tests = Column(Boolean, default=False)
    has_ci = Column(Boolean, default=False)
    doc_score = Column(Integer, default=0)
    has_api_docs = Column(Boolean, default=False)

    # Cleanup tracking
    is_orphaned = Column(Boolean, default=False, index=True)
    orphan_action = Column(String)  # archive, delete, maintain
    orphan_reason = Column(String)

    # Languages and frameworks (JSON arrays)
    languages = Column(Text)  # JSON: [{"language": "Python", "version": "3.11", "lines": 5000}]
    frameworks = Column(Text)  # JSON: [{"framework": "FastAPI", "version": "0.109"}]

    # Risk metrics (computed)
    bus_factor = Column(Integer)  # Number of key contributors
    knowledge_risk = Column(String)  # low, medium, high, critical
    last_commit_date = Column(DateTime)
    days_since_commit = Column(Integer)

    # Sync metadata
    synced_at = Column(DateTime, default=utc_now)
    source_updated_at = Column(DateTime)

    __table_args__ = (
        Index('ix_gitlab_repos_team_orphan', 'team', 'is_orphaned'),
        Index('ix_gitlab_repos_language', 'primary_language'),
    )


class GitLabMetrics(Base):
    """
    Daily aggregated DevOps metrics per team, synced from gitlab-analysis.
    Used for DORA calculations and trend analysis.
    """
    __tablename__ = "gitlab_metrics"

    id = Column(Integer, primary_key=True, index=True)
    team = Column(String, nullable=False, index=True)
    metric_date = Column(Date, nullable=False, index=True)

    # Pipeline metrics
    pipeline_runs = Column(Integer, default=0)
    pipeline_success = Column(Integer, default=0)
    pipeline_failed = Column(Integer, default=0)
    avg_duration_seconds = Column(Float)

    # DORA-style metrics
    merge_requests_merged = Column(Integer, default=0)
    avg_mr_cycle_time_hours = Column(Float)  # Lead time for changes
    failed_pipeline_recovery_hours = Column(Float)  # MTTR proxy

    # Computed DORA scores
    deployment_frequency = Column(Float)  # Deploys per day
    lead_time_hours = Column(Float)
    change_failure_rate = Column(Float)  # 0.0-1.0
    mttr_hours = Column(Float)
    dora_level = Column(String)  # elite, high, medium, low

    # Sync metadata
    synced_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_gitlab_metrics_team_date', 'team', 'metric_date', unique=True),
    )


class GitLabEngineer(Base):
    """
    Engineer mapping for GitLab-to-Jira correlation.
    Links GitLab usernames to Jira account IDs for activity attribution.
    """
    __tablename__ = "gitlab_engineers"

    id = Column(Integer, primary_key=True, index=True)
    gitlab_username = Column(String, unique=True, nullable=False, index=True)
    gitlab_email = Column(String)
    jira_account_id = Column(String, index=True)
    display_name = Column(String, nullable=False)
    team = Column(String, nullable=False, index=True)
    role = Column(String)  # developer, lead, etc.

    # Activity stats (computed)
    total_mrs = Column(Integer, default=0)
    total_commits = Column(Integer, default=0)
    repos_contributed = Column(Integer, default=0)
    last_activity_date = Column(DateTime)

    # Sync metadata
    synced_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_gitlab_engineers_team', 'team'),
    )


class GitLabMRActivity(Base):
    """
    MR activity timeline for epic-MR correlation.
    Links merge requests to Jira tickets and epics.
    """
    __tablename__ = "gitlab_mr_activity"

    id = Column(Integer, primary_key=True, index=True)
    mr_iid = Column(Integer, nullable=False)
    repo_id = Column(String, nullable=False, index=True)  # team/repo format
    title = Column(String, nullable=False)
    description = Column(Text)
    source_branch = Column(String)
    author_username = Column(String, nullable=False, index=True)
    state = Column(String, nullable=False)  # merged, opened, closed

    # Timestamps
    created_at = Column(DateTime, nullable=False)
    merged_at = Column(DateTime, index=True)
    web_url = Column(String)

    # Jira correlation (extracted from branch/title/description)
    jira_tickets = Column(Text)  # JSON array of ticket keys ["PLAT-123", "PLAT-456"]
    epic_keys = Column(Text)  # JSON array of linked epic keys

    # Metrics
    lines_added = Column(Integer)
    lines_removed = Column(Integer)
    files_changed = Column(Integer)
    cycle_time_hours = Column(Float)  # Time from first commit to merge

    # Sync metadata
    synced_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_gitlab_mr_repo_iid', 'repo_id', 'mr_iid', unique=True),
        Index('ix_gitlab_mr_author', 'author_username'),
        Index('ix_gitlab_mr_merged', 'merged_at'),
    )


class GitLabPackage(Base):
    """
    Package/dependency information extracted from repositories.
    Enables queries like "Which repos use express?" or "Find all Django versions".
    """
    __tablename__ = "gitlab_packages"

    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(String, nullable=False, index=True)  # team/repo format
    package = Column(String, nullable=False, index=True)  # Package name (e.g., "express", "django")
    language = Column(String, nullable=False, index=True)  # Python, JavaScript, Java, etc.
    version = Column(String)  # Version constraint (e.g., "^4.18.0", ">=3.2,<4.0")
    version_resolved = Column(String)  # Resolved/actual version if known
    is_dev = Column(Boolean, default=False)  # Dev dependency
    is_internal = Column(Boolean, default=False)  # Internal/private package
    source_file = Column(String)  # requirements.txt, package.json, pom.xml, etc.

    # Sync metadata
    synced_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_gitlab_packages_repo_package', 'repo_id', 'package', unique=True),
        Index('ix_gitlab_packages_package_lang', 'package', 'language'),
    )


class GitLabVersion(Base):
    """
    Language and framework version tracking with EOL risk assessment.
    Enables queries like "Which repos are on Python 3.8?" or "Find EOL risk repos".
    """
    __tablename__ = "gitlab_versions"

    id = Column(Integer, primary_key=True, index=True)
    repo_id = Column(String, nullable=False, index=True)  # team/repo format
    team = Column(String, nullable=False, index=True)

    # Version info
    type = Column(String, nullable=False, index=True)  # "language" or "framework"
    name = Column(String, nullable=False, index=True)  # Python, Node, Spring Boot, etc.
    current_version = Column(String, nullable=False)  # Current version in repo
    latest_version = Column(String)  # Latest available version (if known)

    # Status
    version_status = Column(String)  # "current", "outdated", "eol", "unknown"
    is_eol = Column(Boolean, default=False, index=True)  # End of life flag
    eol_date = Column(Date)  # When version reaches/reached EOL
    risk_level = Column(String, default="low")  # low, medium, high, critical

    # Detection source
    source_file = Column(String)  # .python-version, package.json, pom.xml, etc.

    # Sync metadata
    synced_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_gitlab_versions_repo_type_name', 'repo_id', 'type', 'name', unique=True),
        Index('ix_gitlab_versions_team_eol', 'team', 'is_eol'),
        Index('ix_gitlab_versions_name_version', 'name', 'current_version'),
    )


class GitLabSyncLog(Base):
    """
    Track sync operations from gitlab-analysis codebase.db to PA.
    """
    __tablename__ = "gitlab_sync_logs"

    id = Column(Integer, primary_key=True, index=True)
    sync_type = Column(String, nullable=False, index=True)  # repos, metrics, engineers, mrs
    started_at = Column(DateTime, default=utc_now)
    completed_at = Column(DateTime)
    status = Column(String, default="running")  # running, completed, failed
    records_synced = Column(Integer, default=0)
    records_updated = Column(Integer, default=0)
    records_created = Column(Integer, default=0)
    error_message = Column(Text)
    duration_seconds = Column(Float)

    __table_args__ = (
        Index('ix_gitlab_sync_type_date', 'sync_type', 'started_at'),
    )


class EpicMRCorrelation(Base):
    """
    Links Jira epics to GitLab MRs for velocity and progress tracking.
    Enables questions like "What MRs contributed to epic PLAT-123?"
    """
    __tablename__ = "epic_mr_correlations"

    id = Column(Integer, primary_key=True, index=True)
    epic_key = Column(String, nullable=False, index=True)
    ticket_key = Column(String, nullable=False, index=True)  # Child ticket
    mr_id = Column(Integer, ForeignKey("gitlab_mr_activity.id"), index=True)

    # Attribution
    author_username = Column(String, index=True)
    team = Column(String, index=True)

    # Metrics
    lines_changed = Column(Integer)
    files_changed = Column(Integer)
    merged_at = Column(DateTime)

    # Confidence in correlation
    correlation_method = Column(String)  # branch_name, commit_message, mr_title
    confidence = Column(Float, default=1.0)  # 0.0-1.0

    created_at = Column(DateTime, default=utc_now)

    __table_args__ = (
        Index('ix_epic_mr_epic_ticket', 'epic_key', 'ticket_key'),
    )


class PredictiveRiskScore(Base):
    """
    Unified risk scoring combining Jira, GitLab, Snyk, and activity signals.
    Enables predictive alerts for at-risk epics and teams.
    """
    __tablename__ = "predictive_risk_scores"

    id = Column(Integer, primary_key=True, index=True)
    entity_type = Column(String, nullable=False, index=True)  # epic, team, repo
    entity_id = Column(String, nullable=False, index=True)  # epic key, team name, repo_id

    # Overall score
    risk_score = Column(Float, nullable=False)  # 0-100
    risk_level = Column(String, nullable=False)  # low, medium, high, critical
    confidence = Column(Float)  # 0.0-1.0

    # Component scores (weighted inputs)
    jira_velocity_score = Column(Float)  # From sprint velocity trends
    dora_score = Column(Float)  # From GitLab DORA metrics
    security_score = Column(Float)  # From Snyk vulnerability data
    knowledge_risk_score = Column(Float)  # From bus factor/contributor analysis
    activity_score = Column(Float)  # From recent activity patterns

    # Prediction outputs
    predicted_completion_date = Column(Date)  # For epics
    days_at_risk = Column(Integer)  # Days since risk elevated
    trend = Column(String)  # improving, stable, degrading

    # Context
    risk_factors = Column(Text)  # JSON: list of contributing factors
    recommended_actions = Column(Text)  # JSON: suggested interventions
    last_alert_sent = Column(DateTime)

    # Metadata
    calculated_at = Column(DateTime, default=utc_now, index=True)
    valid_until = Column(DateTime)  # When score needs recalculation

    __table_args__ = (
        Index('ix_risk_score_entity', 'entity_type', 'entity_id'),
        Index('ix_risk_score_level', 'risk_level'),
    )


class ConversationMemory(Base):
    """
    Persistent memories extracted from conversations before context compaction.
    Inspired by OpenClaw's pre-compaction memory flush pattern.
    """
    __tablename__ = "conversation_memories"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    memory_type = Column(String, nullable=False, index=True)  # fact, decision, action_item, preference, insight
    content = Column(Text, nullable=False)
    importance = Column(Float, default=0.5)  # 0.0-1.0 importance score
    source_message_range = Column(String)  # "msg_id_start:msg_id_end" range that produced this memory
    is_active = Column(Boolean, default=True)  # Can be deactivated without deletion
    metadata_json = Column(Text)  # JSON: extra context (people, teams, topics)
    created_at = Column(DateTime, default=utc_now, index=True)
    expires_at = Column(DateTime)  # Optional expiry for time-bound memories

    conversation = relationship("Conversation", backref=backref("memories", cascade="all, delete-orphan"))

    __table_args__ = (
        Index('ix_conv_mem_type_active', 'conversation_id', 'memory_type', 'is_active'),
    )


class ConversationSummary(Base):
    """
    Compacted summaries of older conversation messages.
    Implements sliding window context management.
    """
    __tablename__ = "conversation_summaries"

    id = Column(Integer, primary_key=True, index=True)
    conversation_id = Column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False, index=True)
    summary_text = Column(Text, nullable=False)
    messages_summarized = Column(Integer, nullable=False)  # Count of messages summarized
    first_message_id = Column(Integer)  # ID of first message in summarized range
    last_message_id = Column(Integer)  # ID of last message in summarized range
    token_count_before = Column(Integer)  # Token count of original messages
    token_count_after = Column(Integer)  # Token count of summary
    compression_ratio = Column(Float)  # token_count_after / token_count_before
    created_at = Column(DateTime, default=utc_now, index=True)

    conversation = relationship("Conversation", backref=backref("summaries", cascade="all, delete-orphan"))


def init_fts5_tables():
    """
    Initialize FTS5 virtual tables for full-text search.
    FTS5 provides native BM25 ranking for fast, relevant keyword search.
    """
    with engine.connect() as conn:
        # FTS5 for entries table
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS entries_fts USING fts5(
                title,
                summary,
                content,
                tags,
                content='entries',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """))

        # Triggers to keep entries_fts in sync with entries
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS entries_ai AFTER INSERT ON entries BEGIN
                INSERT INTO entries_fts(rowid, title, summary, content, tags)
                VALUES (new.id, new.title, new.summary, new.content, new.tags);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS entries_ad AFTER DELETE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, summary, content, tags)
                VALUES ('delete', old.id, old.title, old.summary, old.content, old.tags);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS entries_au AFTER UPDATE ON entries BEGIN
                INSERT INTO entries_fts(entries_fts, rowid, title, summary, content, tags)
                VALUES ('delete', old.id, old.title, old.summary, old.content, old.tags);
                INSERT INTO entries_fts(rowid, title, summary, content, tags)
                VALUES (new.id, new.title, new.summary, new.content, new.tags);
            END
        """))

        # FTS5 for skill_chunks table
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS skill_chunks_fts USING fts5(
                skill_name,
                description,
                section,
                content,
                content='skill_chunks',
                content_rowid='id',
                tokenize='porter unicode61'
            )
        """))

        # Triggers to keep skill_chunks_fts in sync
        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS skill_chunks_ai AFTER INSERT ON skill_chunks BEGIN
                INSERT INTO skill_chunks_fts(rowid, skill_name, description, section, content)
                VALUES (new.id, new.skill_name, new.description, new.section, new.content);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS skill_chunks_ad AFTER DELETE ON skill_chunks BEGIN
                INSERT INTO skill_chunks_fts(skill_chunks_fts, rowid, skill_name, description, section, content)
                VALUES ('delete', old.id, old.skill_name, old.description, old.section, old.content);
            END
        """))

        conn.execute(text("""
            CREATE TRIGGER IF NOT EXISTS skill_chunks_au AFTER UPDATE ON skill_chunks BEGIN
                INSERT INTO skill_chunks_fts(skill_chunks_fts, rowid, skill_name, description, section, content)
                VALUES ('delete', old.id, old.skill_name, old.description, old.section, old.content);
                INSERT INTO skill_chunks_fts(rowid, skill_name, description, section, content)
                VALUES (new.id, new.skill_name, new.description, new.section, new.content);
            END
        """))

        # FTS5 for qa_pairs table (hybrid search support)
        # Using standalone FTS (no content= sync) for reliability.
        # Rebuilt from qa_pairs on every startup via rebuild_fts_index("qa").
        # Drop old content-synced version if it exists (migration).
        try:
            conn.execute(text("DROP TRIGGER IF EXISTS qa_ai"))
            conn.execute(text("DROP TRIGGER IF EXISTS qa_ad"))
            conn.execute(text("DROP TRIGGER IF EXISTS qa_au"))
            conn.execute(text("DROP TABLE IF EXISTS qa_fts"))
        except Exception:
            pass
        conn.execute(text("""
            CREATE VIRTUAL TABLE IF NOT EXISTS qa_fts USING fts5(
                question,
                answer,
                category,
                topics,
                tokenize='unicode61'
            )
        """))

        conn.commit()


def _migrate_add_columns():
    """Add columns that were added after initial table creation.

    SQLAlchemy create_all() only creates new tables, not new columns on
    existing tables.  This helper bridges the gap with safe ALTER TABLE
    statements (SQLite ignores 'IF NOT EXISTS' on columns, so we catch
    OperationalError for duplicates).
    """
    migrations = [
        ("daily_context", "health_snapshot", "TEXT"),
        ("daily_context", "critical_items", "TEXT"),
        ("daily_context", "priorities", "TEXT"),
        # Memory eviction support - access tracking and archival
        ("qa_pairs", "last_accessed_at", "DATETIME"),
        ("qa_pairs", "is_archived", "BOOLEAN DEFAULT 0"),
        ("experiences", "last_accessed_at", "DATETIME"),
        ("experiences", "is_archived", "BOOLEAN DEFAULT 0"),
        ("corrections", "is_archived", "BOOLEAN DEFAULT 0"),
        # Source tracking for commitments
        ("commitments", "source", "VARCHAR DEFAULT 'meeting'"),
    ]
    with engine.connect() as conn:
        for table, column, col_type in migrations:
            try:
                conn.execute(text(
                    f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"
                ))
            except Exception:
                pass  # Column already exists
        conn.commit()


def init_db():
    try:
        Base.metadata.create_all(bind=engine)
    except Exception as e:
        # Handle "index already exists" errors from SQLite when re-running create_all
        if "already exists" in str(e):
            import logging as _logging
            _logging.getLogger(__name__).warning(
                f"Schema partially applied (some indexes already exist, continuing): {e}"
            )
            # Create tables individually with checkfirst=True
            for table in Base.metadata.sorted_tables:
                try:
                    table.create(bind=engine, checkfirst=True)
                except Exception:
                    pass
        else:
            raise
    _migrate_add_columns()
    # Initialize FTS5 virtual tables (must be done with raw SQL)
    init_fts5_tables()
    # Note: FTS rebuild removed from startup for performance.
    # Use POST /api/search/reindex to rebuild manually when needed.


def rebuild_fts_index(table: str = "all"):
    """
    Rebuild FTS5 index from source table.
    Use after bulk imports or if index gets out of sync.

    Args:
        table: 'entries', 'qa', 'skills', or 'all'
    """
    with engine.connect() as conn:
        if table in ("entries", "all"):
            # Clear and rebuild entries FTS
            conn.execute(text("DELETE FROM entries_fts"))
            conn.execute(text("""
                INSERT INTO entries_fts(rowid, title, summary, content, tags)
                SELECT id, title, summary, content, tags FROM entries
            """))

        if table in ("qa", "all"):
            # Clear and rebuild qa FTS (standalone table, no content sync)
            try:
                conn.execute(text("DELETE FROM qa_fts"))
                conn.execute(text("""
                    INSERT INTO qa_fts(rowid, question, answer, category, topics)
                    SELECT id,
                           COALESCE(question, ''),
                           COALESCE(answer, ''),
                           COALESCE(category, ''),
                           COALESCE(topics, '')
                    FROM qa_pairs
                """))
            except Exception:
                pass  # qa_fts may not exist yet

        if table in ("skills", "all"):
            try:
                conn.execute(text("DELETE FROM skill_chunks_fts"))
                conn.execute(text("""
                    INSERT INTO skill_chunks_fts(rowid, skill_name, description, section, content)
                    SELECT id,
                           COALESCE(skill_name, ''),
                           COALESCE(description, ''),
                           COALESCE(section, ''),
                           COALESCE(content, '')
                    FROM skill_chunks
                """))
            except Exception:
                pass  # skill_chunks_fts may not exist yet

        conn.commit()


# =============================================================================
# BACKGROUND TASK TRACKING
# =============================================================================

class BackgroundTask(Base):
    """
    Track background tasks spawned by subagents.

    Supports long-running tasks that run asynchronously and notify
    the user when complete via their specified channel.
    """
    __tablename__ = "background_tasks"

    id = Column(Integer, primary_key=True, index=True)
    task_description = Column(Text, nullable=False)
    status = Column(String, default="pending", nullable=False, index=True)  # pending, running, completed, failed
    channel = Column(String, nullable=False)  # Callback channel: slack, email, webhook, etc.
    channel_target = Column(String)  # Channel-specific target (e.g., Slack channel ID, email address)

    # Execution metadata
    subagent_name = Column(String)  # Which subagent is handling this
    model = Column(String)  # Model used for execution
    timeout_seconds = Column(Integer, default=300)  # Max execution time

    # Results
    result_summary = Column(Text)  # Short summary for notification
    result_full = Column(Text)  # Full result/output
    error_message = Column(Text)  # Error details if failed
    cost_usd = Column(Float)  # Estimated API cost

    # Timing
    created_at = Column(DateTime, default=utc_now, nullable=False)
    started_at = Column(DateTime)
    completed_at = Column(DateTime)

    # Tracking
    progress_percent = Column(Integer, default=0)  # 0-100
    progress_message = Column(String)  # Current step description

    __table_args__ = (
        Index('ix_background_tasks_status', 'status'),
        Index('ix_background_tasks_channel', 'channel'),
        Index('ix_background_tasks_created', 'created_at'),
    )


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()