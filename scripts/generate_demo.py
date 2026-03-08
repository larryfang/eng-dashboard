#!/usr/bin/env python3
"""
Generate a demo database with realistic mock data for eng-dashboard.

Creates:
  - config/domains/nexus-tech.yaml  (copied from organization.demo.yaml)
  - data/domains/nexus-tech.db      (populated SQLite database)
  - data/active_domain.txt          (set to nexus-tech)

Usage:
  uv run python scripts/generate_demo.py
"""

import sys
import json
import shutil
import random
from pathlib import Path
from datetime import datetime, timedelta, date, timezone

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy.orm import sessionmaker
from backend.database_domain import init_domain_db, get_domain_engine
from backend.models_domain import (
    RefTeam, RefMember, MRActivity, TeamMetrics, JiraEpic,
    JiraChildEpic, SyncStatus, SyncRunHistory, EngineerStats,
    PortService, AlertTriageState,
)

DOMAIN_SLUG = "nexus-tech"
NOW = datetime.now(timezone.utc)
TODAY = date.today()

random.seed(42)  # Reproducible demo data


# =============================================================================
# Team & engineer definitions
# =============================================================================

TEAMS = [
    {
        "slug": "atlas",
        "key": "ATLAS",
        "name": "Platform Infrastructure",
        "scrum_name": "Atlas",
        "jira_project": "ATLAS",
        "gitlab_path": "nexus/platform/core",
        "headcount": 5,
        "em_name": "Sarah Chen",
        "em_email": "sarah.chen@nexus-tech.io",
        "products": ["Cloud Platform", "CI/CD Pipeline", "Internal Developer Tools"],
        # Performance profile: elite
        "mr_rate": 1.2,  # multiplier on base MR rate
        "dora_profile": "elite",
    },
    {
        "slug": "horizon",
        "key": "HRZ",
        "name": "Product Frontend",
        "scrum_name": "Horizon",
        "jira_project": "HRZ",
        "gitlab_path": "nexus/frontend/web",
        "headcount": 4,
        "em_name": "Marcus Rivera",
        "em_email": "marcus.rivera@nexus-tech.io",
        "products": ["Customer Dashboard", "Design System", "Mobile Web"],
        "mr_rate": 1.0,
        "dora_profile": "high",
    },
    {
        "slug": "forge",
        "key": "FRG",
        "name": "Core API Services",
        "scrum_name": "Forge",
        "jira_project": "FRG",
        "gitlab_path": "nexus/services/api",
        "headcount": 5,
        "em_name": "Priya Patel",
        "em_email": "priya.patel@nexus-tech.io",
        "products": ["REST API Gateway", "Authentication Service", "Billing Engine"],
        "mr_rate": 0.85,
        "dora_profile": "medium",
    },
    {
        "slug": "sentinel",
        "key": "SNT",
        "name": "Security & DevOps",
        "scrum_name": "Sentinel",
        "jira_project": "SNT",
        "gitlab_path": "nexus/security",
        "headcount": 4,
        "em_name": "James Okonkwo",
        "em_email": "james.okonkwo@nexus-tech.io",
        "products": ["Security Scanner", "Infrastructure as Code", "Monitoring Stack"],
        "mr_rate": 0.6,  # declining team — triggers alerts
        "dora_profile": "declining",
    },
]

ENGINEERS = [
    # Atlas — high performers
    {"username": "sarah.chen",    "name": "Sarah Chen",    "team": "atlas",    "role": "TL",       "activity": 0.9},
    {"username": "alex.kumar",    "name": "Alex Kumar",    "team": "atlas",    "role": "senior",   "activity": 1.3},
    {"username": "lisa.park",     "name": "Lisa Park",     "team": "atlas",    "role": "engineer", "activity": 1.1},
    {"username": "tom.wilson",    "name": "Tom Wilson",    "team": "atlas",    "role": "engineer", "activity": 0.8},
    {"username": "nina.volkov",   "name": "Nina Volkov",   "team": "atlas",    "role": "engineer", "activity": 1.0},
    # Horizon
    {"username": "marcus.rivera", "name": "Marcus Rivera", "team": "horizon",  "role": "TL",       "activity": 0.7},
    {"username": "emma.jones",    "name": "Emma Jones",    "team": "horizon",  "role": "senior",   "activity": 1.2},
    {"username": "kai.tanaka",    "name": "Kai Tanaka",    "team": "horizon",  "role": "engineer", "activity": 1.0},
    {"username": "sofia.reyes",   "name": "Sofia Reyes",   "team": "horizon",  "role": "engineer", "activity": 0.9},
    # Forge
    {"username": "priya.patel",   "name": "Priya Patel",   "team": "forge",    "role": "TL",       "activity": 0.6},
    {"username": "david.kim",     "name": "David Kim",     "team": "forge",    "role": "senior",   "activity": 1.1},
    {"username": "rachel.green",  "name": "Rachel Green",  "team": "forge",    "role": "engineer", "activity": 0.9},
    {"username": "omar.hassan",   "name": "Omar Hassan",   "team": "forge",    "role": "engineer", "activity": 0.0},  # quiet — no MRs
    {"username": "yuki.sato",     "name": "Yuki Sato",     "team": "forge",    "role": "qa",       "activity": 0.3, "exclude": True},
    # Sentinel — declining, one departed
    {"username": "james.okonkwo", "name": "James Okonkwo", "team": "sentinel", "role": "TL",       "activity": 0.5},
    {"username": "anna.schmidt",  "name": "Anna Schmidt",  "team": "sentinel", "role": "senior",   "activity": 0.7},
    {"username": "leo.garcia",    "name": "Leo Garcia",    "team": "sentinel", "role": "engineer", "activity": 0.0},  # quiet — no MRs
    {"username": "mei.lin",       "name": "Mei Lin",       "team": "sentinel", "role": "engineer", "activity": 0.0, "departed": True},
]

# Realistic MR title templates per team focus area
MR_TITLES = {
    "atlas": [
        "Add Kubernetes pod autoscaling for {service}",
        "Fix Terraform state drift in {env} environment",
        "Migrate CI pipeline from Jenkins to GitLab CI",
        "Add Prometheus alerting rules for memory pressure",
        "Refactor Helm chart values for multi-region deploy",
        "Fix flaky integration test in pipeline stage 3",
        "Add Datadog APM instrumentation to {service}",
        "Upgrade PostgreSQL driver to support connection pooling",
        "Implement blue-green deployment for {service}",
        "Add circuit breaker pattern to external API calls",
        "Fix DNS resolution timeout in service mesh",
        "Add Grafana dashboard for deployment frequency",
        "Optimize Docker image size for {service}",
        "Add health check endpoints to all microservices",
        "Fix SSL certificate rotation in {env} cluster",
    ],
    "horizon": [
        "Implement responsive data table component",
        "Add dark mode toggle to design system",
        "Fix accessibility issue in navigation dropdown",
        "Migrate from Redux to Zustand for state management",
        "Add skeleton loading states to dashboard cards",
        "Fix layout shift on mobile viewport",
        "Implement WebSocket real-time notifications",
        "Add E2E tests for onboarding flow",
        "Refactor chart components to use Recharts v3",
        "Fix date picker timezone handling",
        "Add keyboard navigation to command palette",
        "Implement lazy loading for route chunks",
        "Fix CSS specificity issue in button variants",
        "Add Storybook stories for form components",
        "Optimize bundle size by tree-shaking lodash",
    ],
    "forge": [
        "Add rate limiting to public API endpoints",
        "Fix N+1 query in user permissions endpoint",
        "Implement OAuth2 PKCE flow for mobile clients",
        "Add pagination to /api/v2/transactions",
        "Fix race condition in billing webhook handler",
        "Migrate authentication to JWT RS256 signing",
        "Add OpenAPI schema validation middleware",
        "Fix timeout in batch export endpoint",
        "Implement idempotency keys for payment API",
        "Add Redis caching for session lookups",
        "Fix CORS headers for partner integrations",
        "Add audit logging for admin operations",
        "Optimize database connection pool settings",
        "Fix decimal precision in invoice calculations",
        "Add gRPC gateway for internal service calls",
    ],
    "sentinel": [
        "Add Trivy container scanning to CI pipeline",
        "Fix false positive in SAST rule for SQL injection",
        "Implement secret rotation for API keys",
        "Add RBAC policy for production namespace",
        "Fix Vault token renewal in sidecar injector",
        "Migrate WAF rules to new CloudFlare format",
        "Add dependency vulnerability scanning for Python",
        "Fix TLS 1.3 configuration in ingress controller",
        "Implement SOC2 compliance logging",
        "Add network policy for pod-to-pod encryption",
        "Fix security group rules for RDS access",
        "Add DAST scanning for staging environment",
        "Implement CSP headers for web applications",
        "Fix IAM role trust policy for cross-account access",
        "Add PII detection rules to data pipeline",
    ],
}

ENVS = ["staging", "production", "dev"]
SERVICES = ["api-gateway", "auth-service", "billing-engine", "user-service", "notification-service"]

JIRA_EPICS_DATA = [
    # Atlas — mostly healthy
    {"key": "ATLAS-101", "team": "atlas", "summary": "Multi-region deployment support",       "status": "In Progress", "cat": "In Progress", "priority": "High",    "progress": 0.72, "total": 18, "done": 13, "days_ago_updated": 2,  "due_offset": 30},
    {"key": "ATLAS-102", "team": "atlas", "summary": "Kubernetes 1.29 cluster upgrade",       "status": "In Progress", "cat": "In Progress", "priority": "Highest", "progress": 0.45, "total": 11, "done": 5,  "days_ago_updated": 1,  "due_offset": 14},
    {"key": "ATLAS-103", "team": "atlas", "summary": "Observability stack consolidation",     "status": "Done",        "cat": "Done",        "priority": "Medium",  "progress": 1.0,  "total": 8,  "done": 8,  "days_ago_updated": 10, "due_offset": -5},
    {"key": "ATLAS-104", "team": "atlas", "summary": "CI pipeline performance optimization",  "status": "To Do",       "cat": "To Do",       "priority": "Medium",  "progress": 0.0,  "total": 6,  "done": 0,  "days_ago_updated": 3,  "due_offset": 45},
    # Horizon — one stale
    {"key": "HRZ-201",   "team": "horizon", "summary": "Design system v3 migration",          "status": "In Progress", "cat": "In Progress", "priority": "High",    "progress": 0.60, "total": 15, "done": 9,  "days_ago_updated": 1,  "due_offset": 21},
    {"key": "HRZ-202",   "team": "horizon", "summary": "Mobile-first responsive overhaul",    "status": "In Progress", "cat": "In Progress", "priority": "High",    "progress": 0.33, "total": 12, "done": 4,  "days_ago_updated": 15, "due_offset": 7},  # STALE
    {"key": "HRZ-203",   "team": "horizon", "summary": "Accessibility audit remediation",     "status": "In Progress", "cat": "In Progress", "priority": "Highest", "progress": 0.80, "total": 10, "done": 8,  "days_ago_updated": 2,  "due_offset": 10},
    {"key": "HRZ-204",   "team": "horizon", "summary": "Performance monitoring dashboard",    "status": "Done",        "cat": "Done",        "priority": "Medium",  "progress": 1.0,  "total": 7,  "done": 7,  "days_ago_updated": 20, "due_offset": -15},
    # Forge — two stale
    {"key": "FRG-301",   "team": "forge", "summary": "API v2 rate limiting and throttling",    "status": "In Progress", "cat": "In Progress", "priority": "High",    "progress": 0.50, "total": 14, "done": 7,  "days_ago_updated": 12, "due_offset": 5},  # STALE
    {"key": "FRG-302",   "team": "forge", "summary": "Payment gateway PCI compliance",        "status": "In Progress", "cat": "In Progress", "priority": "Highest", "progress": 0.25, "total": 20, "done": 5,  "days_ago_updated": 18, "due_offset": -3},  # STALE & overdue
    {"key": "FRG-303",   "team": "forge", "summary": "GraphQL API layer",                     "status": "To Do",       "cat": "To Do",       "priority": "Medium",  "progress": 0.0,  "total": 10, "done": 0,  "days_ago_updated": 5,  "due_offset": 60},
    {"key": "FRG-304",   "team": "forge", "summary": "Webhook delivery reliability",          "status": "In Progress", "cat": "In Progress", "priority": "High",    "progress": 0.67, "total": 9,  "done": 6,  "days_ago_updated": 1,  "due_offset": 14},
    # Sentinel
    {"key": "SNT-401",   "team": "sentinel", "summary": "SOC2 Type II compliance automation", "status": "In Progress", "cat": "In Progress", "priority": "Highest", "progress": 0.35, "total": 20, "done": 7,  "days_ago_updated": 3,  "due_offset": 30},
    {"key": "SNT-402",   "team": "sentinel", "summary": "Zero-trust network architecture",    "status": "In Progress", "cat": "In Progress", "priority": "High",    "progress": 0.20, "total": 15, "done": 3,  "days_ago_updated": 8,  "due_offset": 45},
    {"key": "SNT-403",   "team": "sentinel", "summary": "Secret management overhaul",         "status": "Done",        "cat": "Done",        "priority": "High",    "progress": 1.0,  "total": 8,  "done": 8,  "days_ago_updated": 25, "due_offset": -20},
    {"key": "SNT-404",   "team": "sentinel", "summary": "Container image hardening",          "status": "To Do",       "cat": "To Do",       "priority": "Medium",  "progress": 0.0,  "total": 6,  "done": 0,  "days_ago_updated": 4,  "due_offset": 35},
]

PORT_SERVICES_DATA = [
    {"id": "api-gateway",          "title": "API Gateway",           "team": "forge",    "lang": "Go",         "ver": "Go 1.22",       "crit": "Tier 1", "public": True},
    {"id": "auth-service",         "title": "Authentication Service","team": "forge",    "lang": "Python",     "ver": "Python 3.12",   "crit": "Tier 1", "public": True},
    {"id": "billing-engine",       "title": "Billing Engine",        "team": "forge",    "lang": "Java",       "ver": "Java 21",       "crit": "Tier 1", "public": False},
    {"id": "user-service",         "title": "User Service",          "team": "forge",    "lang": "Python",     "ver": "Python 3.12",   "crit": "Tier 2", "public": False},
    {"id": "web-dashboard",        "title": "Customer Dashboard",    "team": "horizon",  "lang": "TypeScript", "ver": "Node 20",       "crit": "Tier 1", "public": True},
    {"id": "design-system",        "title": "Design System",         "team": "horizon",  "lang": "TypeScript", "ver": "Node 20",       "crit": "Tier 3", "public": False},
    {"id": "ci-orchestrator",      "title": "CI Orchestrator",       "team": "atlas",    "lang": "Python",     "ver": "Python 3.12",   "crit": "Tier 2", "public": False},
    {"id": "deploy-controller",    "title": "Deploy Controller",     "team": "atlas",    "lang": "Go",         "ver": "Go 1.22",       "crit": "Tier 1", "public": False},
    {"id": "monitoring-collector",  "title": "Monitoring Collector",  "team": "atlas",    "lang": "Go",         "ver": "Go 1.22",       "crit": "Tier 2", "public": False},
    {"id": "security-scanner",     "title": "Security Scanner",      "team": "sentinel", "lang": "Python",     "ver": "Python 3.11",   "crit": "Tier 2", "public": False},
    {"id": "vault-proxy",          "title": "Vault Proxy",           "team": "sentinel", "lang": "Go",         "ver": "Go 1.22",       "crit": "Tier 1", "public": False},
    {"id": "notification-service", "title": "Notification Service",  "team": "forge",    "lang": "Python",     "ver": "Python 3.12",   "crit": "Tier 2", "public": False},
]


# =============================================================================
# Helpers
# =============================================================================

def rand_dt(start: datetime, end: datetime) -> datetime:
    """Random datetime between start and end."""
    delta = end - start
    secs = random.randint(0, int(delta.total_seconds()))
    return start + timedelta(seconds=secs)


def is_workday(d: date) -> bool:
    return d.weekday() < 5


def team_for(slug: str) -> dict:
    return next(t for t in TEAMS if t["slug"] == slug)


# =============================================================================
# Generators
# =============================================================================

def generate_ref_teams(session):
    """Seed reference teams."""
    for t in TEAMS:
        session.add(RefTeam(
            slug=t["slug"], key=t["key"], name=t["name"],
            scrum_name=t["scrum_name"], jira_project=t["jira_project"],
            gitlab_path=t["gitlab_path"], headcount=t["headcount"],
            em_name=t["em_name"], em_email=t["em_email"],
            products=json.dumps(t["products"]),
        ))
    session.commit()
    print(f"  ref_teams: {len(TEAMS)} teams")


def generate_ref_members(session):
    """Seed reference members."""
    for eng in ENGINEERS:
        t = team_for(eng["team"])
        session.add(RefMember(
            gitlab_username=eng["username"], name=eng["name"],
            email=f"{eng['username']}@nexus-tech.io",
            role=eng["role"], team_slug=eng["team"],
            team_display=t["name"], em_name=t["em_name"],
            em_email=t["em_email"], jira_project=t["jira_project"],
            gitlab_path=t["gitlab_path"],
            exclude_from_metrics=eng.get("exclude", False),
            departed=eng.get("departed", False),
        ))
    session.commit()
    print(f"  ref_members: {len(ENGINEERS)} engineers")


def generate_mr_activity(session):
    """Generate ~300 MRs over 90 days with realistic patterns."""
    start_date = NOW - timedelta(days=90)
    mr_count = 0
    mr_iid_counter = {}  # per repo

    for eng in ENGINEERS:
        if eng.get("departed") or eng["activity"] == 0.0:
            continue

        team = team_for(eng["team"])
        repo_id = team["gitlab_path"]
        base_mrs = int(25 * eng["activity"] * team["mr_rate"])

        for _ in range(base_mrs):
            created = rand_dt(start_date, NOW - timedelta(hours=2))
            # Skip weekends ~80% of the time
            if not is_workday(created.date()) and random.random() < 0.8:
                continue

            mr_iid_counter.setdefault(repo_id, 0)
            mr_iid_counter[repo_id] += 1
            iid = mr_iid_counter[repo_id]

            # State distribution: 72% merged, 18% opened (still open), 10% closed
            roll = random.random()
            if roll < 0.72:
                state = "merged"
                cycle_hours = random.uniform(2, 72)
                merged = created + timedelta(hours=cycle_hours)
                if merged > NOW:
                    merged = NOW - timedelta(hours=1)
                    cycle_hours = (merged - created).total_seconds() / 3600
            elif roll < 0.90:
                state = "opened"
                merged = None
                cycle_hours = None
            else:
                state = "closed"
                merged = None
                cycle_hours = None

            # Title
            title_template = random.choice(MR_TITLES[eng["team"]])
            title = title_template.format(
                service=random.choice(SERVICES),
                env=random.choice(ENVS),
            )

            # Branch name from title
            branch = "feature/" + title[:40].lower().replace(" ", "-").replace("/", "-").rstrip("-")

            # Jira ticket reference (~60% of MRs)
            jira_tickets = None
            epic_keys = None
            if random.random() < 0.6:
                ticket_num = random.randint(100, 500)
                jira_tickets = json.dumps([f"{team['key']}-{ticket_num}"])
                # Link to a team epic ~40% of the time
                team_epics = [e["key"] for e in JIRA_EPICS_DATA if e["team"] == eng["team"]]
                if team_epics and random.random() < 0.4:
                    epic_keys = json.dumps([random.choice(team_epics)])

            lines_added = random.randint(5, 500)
            lines_removed = random.randint(0, int(lines_added * 0.6))
            files_changed = random.randint(1, min(20, max(1, lines_added // 20)))

            session.add(MRActivity(
                mr_iid=iid, repo_id=repo_id, title=title,
                source_branch=branch, author_username=eng["username"],
                author_team=eng["team"], state=state,
                created_at=created, merged_at=merged,
                web_url=f"https://gitlab.com/{repo_id}/-/merge_requests/{iid}",
                jira_tickets=jira_tickets, epic_keys=epic_keys,
                lines_added=lines_added, lines_removed=lines_removed,
                files_changed=files_changed, cycle_time_hours=cycle_hours,
            ))
            mr_count += 1

    session.commit()
    print(f"  mr_activity: {mr_count} merge requests")


def generate_team_metrics(session):
    """Generate daily DORA metrics for 90 days per team."""
    profiles = {
        "elite":     {"df": (3.0, 5.0), "lt": (4, 18),   "cfr": (0.01, 0.04), "mttr": (0.3, 1.0)},
        "high":      {"df": (1.5, 3.5), "lt": (12, 36),  "cfr": (0.03, 0.08), "mttr": (0.5, 2.0)},
        "medium":    {"df": (0.8, 2.0), "lt": (24, 72),  "cfr": (0.05, 0.12), "mttr": (1.0, 4.0)},
        "declining": {"df": (0.3, 1.5), "lt": (36, 120), "cfr": (0.08, 0.20), "mttr": (2.0, 8.0)},
    }
    dora_levels = {"elite": "Elite", "high": "High", "medium": "Medium", "declining": "Low"}

    count = 0
    for team in TEAMS:
        p = profiles[team["dora_profile"]]
        for day_offset in range(90):
            d = TODAY - timedelta(days=89 - day_offset)
            if not is_workday(d):
                continue

            # Sentinel declining: degrade over time
            decay = 1.0
            if team["dora_profile"] == "declining" and day_offset > 45:
                decay = 0.6 + 0.4 * ((90 - day_offset) / 45)

            df = random.uniform(*p["df"]) * decay
            lt = random.uniform(*p["lt"]) / decay
            cfr = random.uniform(*p["cfr"]) / decay
            mttr = random.uniform(*p["mttr"]) / decay

            pipeline_runs = random.randint(8, 30)
            failed = int(pipeline_runs * cfr)
            success = pipeline_runs - failed
            mrs_merged = max(0, int(df * random.uniform(0.8, 1.2)))

            session.add(TeamMetrics(
                team=team["slug"], metric_date=d,
                pipeline_runs=pipeline_runs, pipeline_success=success,
                pipeline_failed=failed,
                avg_duration_seconds=random.uniform(120, 600),
                mrs_merged=mrs_merged,
                avg_cycle_time_hours=lt * random.uniform(0.8, 1.2),
                deployment_frequency=df,
                lead_time_hours=lt,
                change_failure_rate=cfr,
                mttr_hours=mttr,
                dora_level=dora_levels[team["dora_profile"]],
            ))
            count += 1

    session.commit()
    print(f"  team_metrics: {count} daily records")


def generate_jira_epics(session):
    """Populate Jira epic cache."""
    for epic in JIRA_EPICS_DATA:
        t = team_for(epic["team"])
        updated = NOW - timedelta(days=epic["days_ago_updated"])
        due = TODAY + timedelta(days=epic["due_offset"])
        assignee = t["em_name"]

        session.add(JiraEpic(
            key=epic["key"], project=t["jira_project"], team=epic["team"],
            summary=epic["summary"], status=epic["status"],
            status_category=epic["cat"], priority=epic["priority"],
            assignee=assignee,
            url=f"https://nexus-tech.atlassian.net/browse/{epic['key']}",
            progress_percent=epic["progress"],
            child_issues_total=epic["total"], child_issues_done=epic["done"],
            updated_date=updated, due_date=due,
        ))

        # Generate child issues for each epic
        for i in range(epic["total"]):
            child_num = int(epic["key"].split("-")[1]) * 100 + i + 1
            child_key = f"{t['jira_project']}-{child_num}"
            session.add(JiraChildEpic(
                child_key=child_key, epic_key=epic["key"],
            ))

    session.commit()
    print(f"  jira_epics: {len(JIRA_EPICS_DATA)} epics with child issues")


def generate_sync_status(session):
    """Mark all sections as successfully synced."""
    sections = [
        ("engineers", 30), ("engineers", 60), ("engineers", 90),
        ("team_metrics", 30), ("team_metrics", 60), ("team_metrics", 90),
        ("jira_epics", 0),
        ("repos", 0),
        ("dora", 30), ("dora", 60), ("dora", 90),
    ]
    for section, days in sections:
        session.add(SyncStatus(
            section=section, period_days=days, status="success",
            last_synced_at=NOW - timedelta(minutes=random.randint(5, 120)),
            next_sync_at=NOW + timedelta(hours=1),
            records_synced=random.randint(10, 200),
            duration_seconds=random.uniform(2.0, 30.0),
        ))

    # Add sync history entries
    for section, days in sections:
        session.add(SyncRunHistory(
            section=section, period_days=days,
            trigger_source="scheduled", status="success",
            records_synced=random.randint(10, 200),
            started_at=NOW - timedelta(minutes=random.randint(60, 180)),
            finished_at=NOW - timedelta(minutes=random.randint(5, 59)),
            duration_seconds=random.uniform(2.0, 30.0),
        ))

    session.commit()
    print(f"  sync_status: {len(sections)} sections marked as synced")


def generate_engineer_stats(session):
    """Generate cached engineer stats for 30/60/90 day periods."""
    count = 0
    for eng in ENGINEERS:
        if eng.get("departed"):
            continue
        for period in [30, 60, 90]:
            base_commits = int(40 * eng["activity"] * (period / 30))
            base_reviews = int(15 * eng["activity"] * (period / 30))
            session.add(EngineerStats(
                username=eng["username"], period_days=period,
                commit_count=max(0, base_commits + random.randint(-5, 10)),
                review_count=max(0, base_reviews + random.randint(-3, 5)),
            ))
            count += 1
    session.commit()
    print(f"  engineer_stats: {count} cached stat records")


def generate_port_services(session):
    """Populate Port.io service catalog."""
    for svc in PORT_SERVICES_DATA:
        session.add(PortService(
            id=svc["id"], title=svc["title"],
            department="Engineering", system="Nexus Platform",
            domain="nexus-tech", team=svc["team"],
            language=svc["lang"], language_version=svc["ver"],
            url=f"https://gitlab.com/nexus/{svc['id']}",
            description=f"{svc['title']} — part of the Nexus platform",
            service_criticality=svc["crit"],
            publicly_exposed=svc["public"],
        ))
    session.commit()
    print(f"  port_services: {len(PORT_SERVICES_DATA)} services")


def generate_alert_states(session):
    """Pre-seed some alert triage states for demo."""
    alerts = [
        # Quiet engineer alerts
        {"key": "quiet_omar.hassan", "type": "quiet_engineer", "etype": "engineer",
         "ekey": "omar.hassan", "status": "open", "note": "On extended leave?"},
        {"key": "quiet_leo.garcia", "type": "quiet_engineer", "etype": "engineer",
         "ekey": "leo.garcia", "status": "acknowledged",
         "note": "Checked — working on internal documentation sprint"},
        # Team trend alert
        {"key": "trend_sentinel_w10", "type": "team_trend", "etype": "team",
         "ekey": "sentinel", "status": "open",
         "note": "MR volume dropped 35% after Mei Lin's departure"},
        # Stale epic
        {"key": "stale_FRG-302", "type": "stale_epic", "etype": "epic",
         "ekey": "FRG-302", "status": "open",
         "note": "PCI compliance blocked on vendor response"},
    ]
    for a in alerts:
        session.add(AlertTriageState(
            alert_key=a["key"], alert_type=a["type"],
            entity_type=a["etype"], entity_key=a["ekey"],
            status=a["status"], note=a.get("note"),
        ))
    session.commit()
    print(f"  alert_triage_state: {len(alerts)} demo alerts")


# =============================================================================
# Main
# =============================================================================

def main():
    print("=" * 60)
    print("  Generating Demo Data for eng-dashboard")
    print("=" * 60)

    # 1. Copy demo config → config/domains/
    src = ROOT / "config" / "organization.demo.yaml"
    dst_dir = ROOT / "config" / "domains"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / f"{DOMAIN_SLUG}.yaml"
    shutil.copy2(src, dst)
    print(f"\n1. Config: {dst}")

    # 2. Set active domain
    data_dir = ROOT / "data"
    data_dir.mkdir(exist_ok=True)
    (data_dir / "active_domain.txt").write_text(DOMAIN_SLUG)
    print(f"2. Active domain: {DOMAIN_SLUG}")

    # 3. Create database with all tables
    (data_dir / "domains").mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "domains" / f"{DOMAIN_SLUG}.db"
    if db_path.exists():
        db_path.unlink()
        print(f"3. Removed existing DB: {db_path}")

    init_domain_db(DOMAIN_SLUG)
    engine = get_domain_engine(DOMAIN_SLUG)
    Session = sessionmaker(bind=engine)
    session = Session()
    print(f"4. Database created: {db_path}")

    # 4. Populate all tables
    print("\n5. Populating tables:")
    generate_ref_teams(session)
    generate_ref_members(session)
    generate_mr_activity(session)
    generate_team_metrics(session)
    generate_jira_epics(session)
    generate_sync_status(session)
    generate_engineer_stats(session)
    generate_port_services(session)
    generate_alert_states(session)

    session.close()

    print("\n" + "=" * 60)
    print("  Demo data generated successfully!")
    print(f"  DB: {db_path}")
    print(f"  Config: {dst}")
    print("")
    print("  Start the dashboard:")
    print("    ./start.sh")
    print(f"    Open http://localhost:5174")
    print("=" * 60)


if __name__ == "__main__":
    main()
