#!/usr/bin/env python3
"""
Jira Report Service - Comprehensive Jira ecosystem progress report.

Generates a styled HTML email report of all active WIP items across
all configured Jira projects, grouped by team with AI-powered team pulse summaries.

Usage:
    from backend.services.jira_report_service import JiraReportService
    
    service = JiraReportService()
    result = service.generate_and_send(to="")
"""

import logging
import os
from collections import defaultdict
from datetime import datetime
from html import escape
from typing import Any, Dict, List, Optional, Union

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# Statuses to exclude from the report
EXCLUDED_STATUSES = {
    "Done", "Closed", "Cancelled", "To Do", "Open", "Backlog", "Waiting", "Archived",
}

# Status category mappings for CSS classes
STATUS_CSS = {
    "In Progress": "in-progress",
    "In Development": "in-progress",
    "Peer Review": "review",
    "In Review": "review",
    "Waiting for Review": "review",
    "Code Review": "review",
    "In QA": "qa",
    "QA": "qa",
    "Ready for QA": "qa",
    "In Deployment": "deploy",
    "Ready For Deploy": "deploy",
    "Deploy": "deploy",
    "On Hold": "on-hold",
    "Ready": "ready",
    "Ready for Development": "ready",
}

# Status ordering for sorting (lower = higher in report)
STATUS_ORDER = {
    "Ready For Deploy": 0, "In Deployment": 0, "Deploy": 0,
    "In QA": 1, "QA": 1, "Ready for QA": 1,
    "Peer Review": 2, "In Review": 2, "Waiting for Review": 2, "Code Review": 2,
    "In Progress": 3, "In Development": 3,
    "On Hold": 4,
    "Ready": 5, "Ready for Development": 5,
}

# Team emoji mapping (keys are team names as returned by project_to_team config)
TEAM_EMOJI: dict = {}


def _status_css_class(status: str) -> str:
    return STATUS_CSS.get(status, "in-progress")


def _status_sort_key(status: str) -> int:
    return STATUS_ORDER.get(status, 3)


class JiraReportService:
    """Generates and sends comprehensive Jira ecosystem progress reports."""

    def __init__(self, db=None):
        self.db = db
        self._jira = None
        self._email = None

    @property
    def jira(self):
        if self._jira is None:
            from backend.services.jira_api_service import JiraAPIService
            self._jira = JiraAPIService()
        return self._jira

    @property
    def email_service(self):
        if self._email is None:
            from backend.services.email_service import EmailService
            self._email = EmailService()
        return self._email

    def fetch_active_issues(self, projects: Optional[List[str]] = None) -> Dict[str, Dict[str, List]]:
        """
        Fetch and group active WIP issues by team -> issue type.
        
        Returns:
            {team_name: {issue_type: [issue_dict, ...]}}
        """
        from backend.services.jira_api_service import get_project_to_team

        if not self.jira.is_configured:
            logger.warning("Jira not configured")
            return {}

        project_to_team = get_project_to_team()
        if projects is None:
            projects = list(project_to_team.keys())

        if not projects:
            logger.warning("No projects configured")
            return {}

        # Build JQL
        quoted = ", ".join(f'"{p}"' for p in projects)
        excluded = ", ".join(f'"{s}"' for s in EXCLUDED_STATUSES)
        jql = f"project in ({quoted}) AND status not in ({excluded}) ORDER BY project ASC, status ASC, updated DESC"

        logger.info(f"Fetching active issues: {jql}")
        raw_issues = self.jira.search_all_issues(
            jql,
            fields=["summary", "status", "assignee", "issuetype", "project", "updated", "parent",
                    "created", "statuscategorychangedate"],
            max_total=1000,
        )

        # Group by team -> issue type
        teams_data: Dict[str, Dict[str, List]] = defaultdict(lambda: defaultdict(list))

        for issue in raw_issues:
            fields = issue.get("fields", {})
            project_key = fields.get("project", {}).get("key", "UNKNOWN")
            team = project_to_team.get(project_key, project_key)
            issue_type = fields.get("issuetype", {}).get("name", "Unknown")
            status = fields.get("status", {}).get("name", "Unknown")

            assignee_obj = fields.get("assignee")
            assignee = assignee_obj.get("displayName", "Unassigned") if assignee_obj else "Unassigned"

            parent_obj = fields.get("parent")
            parent_key = parent_obj.get("key", "") if parent_obj else ""

            updated_raw = fields.get("updated", "")
            try:
                updated_dt = datetime.fromisoformat(updated_raw.replace("Z", "+00:00").split("+")[0])
                updated = updated_dt.strftime("%Y-%m-%d")
            except Exception:
                updated = updated_raw[:10] if updated_raw else ""

            # Days in current work cycle: use statuscategorychangedate (when ticket entered
            # "In Progress" category), falling back to created date.
            now = datetime.utcnow()
            days_in_status = 0
            for date_field in ("statuscategorychangedate", "created"):
                raw = fields.get(date_field, "")
                if raw:
                    try:
                        dt = datetime.fromisoformat(raw.replace("Z", "+00:00").split("+")[0])
                        days_in_status = (now - dt).days
                        break
                    except Exception:
                        pass

            teams_data[team][issue_type].append({
                "key": issue.get("key", ""),
                "summary": fields.get("summary", ""),
                "status": status,
                "assignee": assignee,
                "updated": updated,
                "parent": parent_key,
                "issue_type": issue_type,
                "days_in_status": days_in_status,
            })

        return dict(teams_data)

    def generate_team_pulse(self, team: str, issues_by_type: Dict[str, List]) -> str:
        """Use LLM to generate a brief team pulse summary."""
        # Flatten all issues
        all_issues = []
        for issues in issues_by_type.values():
            all_issues.extend(issues)

        if not all_issues:
            return "No active items."

        # Build context for LLM
        issue_lines = []
        for item in all_issues:
            line = f"- {item['key']} ({item['issue_type']}): {item['summary']} | Status: {item['status']} | Assignee: {item['assignee']}"
            if item.get("parent"):
                line += f" | Parent: {item['parent']}"
            issue_lines.append(line)

        issue_text = "\n".join(issue_lines)

        system_prompt = "You are a concise engineering manager writing team status updates."
        user_prompt = (
            f"Given these active Jira items for team {team}, write a 2-3 sentence summary of "
            f"who's actively working on what, what's in which pipeline stage, and any observations. "
            f"Be specific with names and ticket references. Keep it factual, no opinions. "
            f"Format: '{{Person}} is working on {{what}} ({{status}}). {{Person2}} has {{what}} ({{status}})...'\n\n"
            f"{issue_text}"
        )

        try:
            from backend.services.llm_helpers import get_llm_plugin
            from backend.plugins.llm.base import ChatMessage

            llm = get_llm_plugin()
            if llm is None:
                raise RuntimeError("LLM not available")

            resp = llm.chat(
                [ChatMessage(role="system", content=system_prompt),
                 ChatMessage(role="user", content=user_prompt)],
                max_tokens=500,
            )
            return resp.content.strip()
        except Exception as e:
            logger.warning(f"LLM unavailable for team pulse ({team}): {e}")
            return self._fallback_pulse(team, all_issues)

    def _fallback_pulse(self, team: str, issues: List[Dict]) -> str:
        """Generate a simple fallback pulse when LLM is unavailable."""
        by_person: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
        for item in issues:
            by_person[item["assignee"]][item["status"]] += 1

        parts = []
        for person, statuses in sorted(by_person.items()):
            status_parts = [f"{count} {status}" for status, count in statuses.items()]
            parts.append(f"{person}: {', '.join(status_parts)}")
        return ". ".join(parts) + "."

    def fetch_wip_epics(self) -> Dict[str, List[Dict]]:
        """
        Fetch WIP epics from ecosystem.db, grouped by team.

        Returns:
            {team_name: [epic_dict, ...]}  sorted by team then epic key
        """
        from sqlalchemy import text

        if self.db is None:
            from backend.database_domain import create_ecosystem_session
            self.db = create_ecosystem_session()

        rows = self.db.execute(text("""
            SELECT key, team, summary, status, url
            FROM jira_epics
            WHERE status_category = 'In Progress'
            ORDER BY team, key
        """)).fetchall()

        epics_by_team: Dict[str, List[Dict]] = defaultdict(list)
        for r in rows:
            jira_url = os.getenv("JIRA_URL", "").rstrip("/")
            url = r.url or (f"{jira_url}/browse/{r.key}" if jira_url else "")
            team = r.team or "Unknown"
            epics_by_team[team].append({
                "key": r.key,
                "summary": r.summary or "",
                "url": url,
            })

        return dict(epics_by_team)

    def fetch_epic_child_counts(self, epic_keys: List[str]) -> Dict[str, Dict[str, int]]:
        """
        Fetch done/total child issue counts for a batch of epic keys via live Jira API.

        Returns:
            {epic_key: {"done": int, "total": int}}
        """
        if not epic_keys:
            return {}

        counts: Dict[str, Dict[str, int]] = {k: {"done": 0, "total": 0} for k in epic_keys}
        epic_key_set = set(epic_keys)

        # Jira limits JQL length, process in batches of 50
        chunk_size = 50
        for i in range(0, len(epic_keys), chunk_size):
            chunk = epic_keys[i : i + chunk_size]
            quoted = ", ".join(f'"{k}"' for k in chunk)
            jql = (
                f'issueType != Epic AND '
                f'("Epic Link" in ({quoted}) OR parent in ({quoted}))'
            )
            try:
                issues = self.jira.search_all_issues(
                    jql,
                    fields=["status", "parent", "customfield_10014"],
                    max_total=2000,
                )
                for issue in issues:
                    fields = issue.get("fields", {})

                    # Resolve parent epic — check parent field first, then Epic Link custom field
                    parent_key = None
                    parent_obj = fields.get("parent") or {}
                    pk = parent_obj.get("key", "")
                    if pk in epic_key_set:
                        parent_key = pk
                    if not parent_key:
                        epic_link = fields.get("customfield_10014") or ""
                        if epic_link in epic_key_set:
                            parent_key = epic_link

                    if not parent_key:
                        continue

                    counts[parent_key]["total"] += 1
                    status_cat = (fields.get("status") or {}).get("statusCategory", {}).get("key", "")
                    status_name = (fields.get("status") or {}).get("name", "")
                    if status_cat == "done" or status_name in ("Done", "Closed"):
                        counts[parent_key]["done"] += 1

            except Exception as e:
                logger.warning(f"Failed to fetch child counts (chunk {i}): {e}")

        return counts

    def _render_epic_progress_section(
        self,
        epics_by_team: Dict[str, List[Dict]],
        child_counts: Dict[str, Dict[str, int]],
    ) -> str:
        """Render the WIP Epics progress HTML section."""
        total_epics = sum(len(v) for v in epics_by_team.values())
        if not total_epics:
            return ""

        def _progress_color(pct: float) -> str:
            if pct == 0:
                return "#9ca3af"      # gray
            if pct < 20:
                return "#ef4444"      # red
            if pct < 50:
                return "#f97316"      # orange
            if pct < 75:
                return "#eab308"      # yellow
            return "#22c55e"          # green

        def _progress_bar(pct: float) -> str:
            color = _progress_color(pct)
            bar_width = max(0, min(100, int(pct)))
            return (
                f'<div style="display:inline-flex;align-items:center;gap:6px;">'
                f'<div style="background:#e5e7eb;border-radius:4px;height:8px;width:100px;overflow:hidden;">'
                f'<div style="background:{color};height:8px;width:{bar_width}px;border-radius:4px;"></div>'
                f'</div>'
                f'<span style="font-size:12px;color:#666;min-width:34px;">{pct:.0f}%</span>'
                f'</div>'
            )

        team_blocks = []
        for team in sorted(epics_by_team.keys()):
            epics = epics_by_team[team]
            emoji = TEAM_EMOJI.get(team, "📋")

            rows_html = ""
            for epic in epics:
                key = epic["key"]
                cc = child_counts.get(key, {"done": 0, "total": 0})
                done, total = cc["done"], cc["total"]
                pct = (done / total * 100) if total > 0 else 0.0

                summary = epic["summary"]
                summary_display = (summary[:55] + "…") if len(summary) > 55 else summary
                url = escape(epic["url"])

                rows_html += (
                    f'<tr>'
                    f'<td style="white-space:nowrap;">'
                    f'<a href="{url}" style="color:#2563eb;text-decoration:none;font-weight:600;">'
                    f'{escape(key)}</a></td>'
                    f'<td style="color:#374151;">{escape(summary_display)}</td>'
                    f'<td>{_progress_bar(pct)}</td>'
                    f'<td style="text-align:center;color:#6b7280;font-size:13px;">{done}/{total}</td>'
                    f'</tr>\n'
                )

            team_blocks.append(
                f'<tr style="background:#f3f4f6;">'
                f'<td colspan="4" style="padding:8px 12px;font-weight:700;color:#1a1a2e;">'
                f'{emoji} {escape(team)} ({len(epics)} epics)</td></tr>\n'
                + rows_html
            )

        return (
            f'<div class="section">'
            f'<h2 style="margin-top:0;color:#d97706;">🚧 Work In Progress Epics ({total_epics} total)</h2>'
            f'<table>'
            f'<tr><th>Epic</th><th>Summary</th><th>Progress</th><th>Issues</th></tr>\n'
            + "".join(team_blocks)
            + f'</table>'
            f'</div>\n'
        )

    def render_html_report(self, teams_data: Dict[str, Dict[str, List]], team_pulses: Dict[str, str], epic_section: str = "") -> str:
        """Render the full HTML email report."""
        now = datetime.now()
        date_str = now.strftime("%A, %d %B %Y")

        total_items = sum(
            len(issues) for types in teams_data.values() for issues in types.values()
        )

        # Build summary rows
        summary_rows = []
        for team in sorted(teams_data.keys()):
            types = teams_data[team]
            count = sum(len(v) for v in types.values())
            breakdown_parts = []
            type_counts = sorted(
                [(t, len(v)) for t, v in types.items()],
                key=lambda x: -x[1],
            )
            for t, c in type_counts:
                breakdown_parts.append(f"{c} {t}")
            summary_rows.append(
                f'<tr><td><strong>{escape(team)}</strong></td>'
                f'<td>{count}</td>'
                f'<td>{", ".join(breakdown_parts)}</td></tr>'
            )

        # Build per-team sections
        team_sections = []
        for team in sorted(teams_data.keys()):
            types = teams_data[team]
            all_issues = []
            for issues in types.values():
                all_issues.extend(issues)

            team_count = len(all_issues)
            emoji = TEAM_EMOJI.get(team, "📋")

            # Team pulse
            pulse = team_pulses.get(team, "")
            pulse_html = ""
            if pulse:
                pulse_html = (
                    f'<div style="background: #eef2ff; border-left: 4px solid #4f46e5; '
                    f'padding: 12px 16px; margin: 10px 0 20px; border-radius: 0 6px 6px 0; font-size: 13px;">'
                    f'<strong>🔍 Team Pulse:</strong> {escape(pulse)}</div>'
                )

            # Separate epics vs active items vs ready backlog
            epics = [i for i in all_issues if i["issue_type"] == "Epic"]
            ready_items = [i for i in all_issues if i["status"] in ("Ready for Development", "Ready")]
            active_items = [
                i for i in all_issues
                if i["issue_type"] != "Epic" and i["status"] not in ("Ready for Development", "Ready")
            ]

            # Sort active items by status priority
            active_items.sort(key=lambda x: (_status_sort_key(x["status"]), x["assignee"]))

            section = f'<h2>{emoji} {escape(team)} — {team_count} Active Items</h2>\n'
            section += pulse_html

            # Epics table
            if epics:
                section += f'<h3>Epics ({len(epics)})</h3>\n'
                section += '<table><tr><th>Key</th><th>Summary</th><th>Status</th><th>Assignee</th></tr>\n'
                for e in epics:
                    badge = f'<span class="badge {_status_css_class(e["status"])}">{escape(e["status"])}</span>'
                    section += (
                        f'<tr><td>{escape(e["key"])}</td>'
                        f'<td>{escape(e["summary"])}</td>'
                        f'<td>{badge}</td>'
                        f'<td>{escape(e["assignee"])}</td></tr>\n'
                    )
                section += '</table>\n'

            # Active items table
            if active_items:
                section += f'<h3>Items Actively Moving ({len(active_items)})</h3>\n'
                section += '<table><tr><th>Key</th><th>Type</th><th>Summary</th><th>Status</th><th>Assignee</th><th>Days</th><th>Parent</th></tr>\n'
                for item in active_items:
                    badge = f'<span class="badge {_status_css_class(item["status"])}">{escape(item["status"])}</span>'
                    days = item.get("days_in_status", 0)
                    if days < 3:
                        day_color = "#22c55e"   # green — fresh
                    elif days < 7:
                        day_color = "#eab308"   # yellow — moderate
                    elif days < 14:
                        day_color = "#f97316"   # orange — slow
                    else:
                        day_color = "#ef4444"   # red — blocked/stale
                    day_badge = (
                        f'<span style="background:{day_color}22;color:{day_color};'
                        f'font-weight:700;padding:2px 7px;border-radius:4px;font-size:12px;">'
                        f'{days}d</span>'
                    )
                    section += (
                        f'<tr><td>{escape(item["key"])}</td>'
                        f'<td>{escape(item["issue_type"])}</td>'
                        f'<td>{escape(item["summary"])}</td>'
                        f'<td>{badge}</td>'
                        f'<td>{escape(item["assignee"])}</td>'
                        f'<td style="text-align:center;">{day_badge}</td>'
                        f'<td>{escape(item.get("parent", ""))}</td></tr>\n'
                    )
                section += '</table>\n'

            # Ready backlog count
            if ready_items:
                section += (
                    f'<h3>Ready for Development Backlog: {len(ready_items)} items</h3>\n'
                    f'<p style="color: #666;">Items in "Ready for Development" or "Ready" status.</p>\n'
                )

            team_sections.append(section)

        html = f"""<html>
<head>
<style>
  body {{ font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #333; line-height: 1.6; max-width: 900px; margin: 0 auto; padding: 20px; }}
  h1 {{ color: #1a1a2e; border-bottom: 2px solid #e94560; padding-bottom: 8px; }}
  h2 {{ color: #1a1a2e; margin-top: 30px; border-bottom: 1px solid #ddd; padding-bottom: 5px; }}
  h3 {{ color: #555; margin-top: 20px; }}
  table {{ border-collapse: collapse; width: 100%; margin: 15px 0; font-size: 13px; }}
  th {{ background: #1a1a2e; color: white; padding: 10px 12px; text-align: left; }}
  td {{ padding: 8px 12px; border-bottom: 1px solid #eee; }}
  tr:hover {{ background: #f8f8f8; }}
  .badge {{ display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 11px; font-weight: 600; }}
  .in-progress {{ background: #dbeafe; color: #1e40af; }}
  .review {{ background: #fef3c7; color: #92400e; }}
  .qa {{ background: #d1fae5; color: #065f46; }}
  .ready {{ background: #f3f4f6; color: #374151; }}
  .on-hold {{ background: #fee2e2; color: #991b1b; }}
  .deploy {{ background: #ede9fe; color: #5b21b6; }}
  .section {{ background: #f9fafb; border: 1px solid #e5e7eb; border-radius: 8px; padding: 20px; margin: 20px 0; }}
</style>
</head>
<body>

<h1>🏗️ Ecosystem Jira Progress Report</h1>
<p style="color: #666;">Generated: {date_str} · Active WIP items only (excluding Waiting, Archived, Backlog, To Do, Done, Closed, Cancelled)</p>

<div class="section">
<h2 style="margin-top:0;">📊 Team Summary</h2>
<table>
<tr><th>Team</th><th>Active WIP</th><th>Breakdown</th></tr>
{"".join(summary_rows)}
</table>
</div>

{epic_section}

{"".join(team_sections)}

<hr style="margin: 30px 0;">
<p style="color: #999; font-size: 12px;">Auto-generated from Jira REST API · {date_str} · Excludes: Waiting, Archived, Backlog, To Do, Done, Closed, Cancelled</p>

</body>
</html>"""
        return html

    def generate_and_send(
        self,
        to: Union[str, List[str]],
        include_pulse: bool = True,
    ) -> Dict[str, Any]:
        """Full pipeline: fetch → analyze → render → send."""
        try:
            # Fetch
            teams_data = self.fetch_active_issues()
            if not teams_data:
                return {"success": False, "error": "No data fetched from Jira"}

            total_items = sum(
                len(issues) for types in teams_data.values() for issues in types.values()
            )

            # Generate pulses
            team_pulses = {}
            if include_pulse:
                for team, types in teams_data.items():
                    try:
                        team_pulses[team] = self.generate_team_pulse(team, types)
                    except Exception as e:
                        logger.warning(f"Pulse generation failed for {team}: {e}")
                        all_issues = [i for issues in types.values() for i in issues]
                        team_pulses[team] = self._fallback_pulse(team, all_issues)

            # Fetch WIP epics + child progress counts
            epics_by_team = self.fetch_wip_epics()
            epic_section = ""
            if epics_by_team:
                all_epic_keys = [
                    e["key"] for epics in epics_by_team.values() for e in epics
                ]
                child_counts = self.fetch_epic_child_counts(all_epic_keys)
                epic_section = self._render_epic_progress_section(epics_by_team, child_counts)

            # Render
            html = self.render_html_report(teams_data, team_pulses, epic_section)

            # Send
            now = datetime.now()
            subject = f"🏗️ Ecosystem Jira Progress Report — {now.strftime('%d %B %Y')}"

            result = self.email_service.send(
                to=to,
                subject=subject,
                html=html,
                tags=["jira-report", "automation"],
            )

            total_epics = sum(len(v) for v in epics_by_team.values())
            if result.success:
                return {
                    "success": True,
                    "message_id": result.message_id,
                    "teams": len(teams_data),
                    "total_items": total_items,
                    "wip_epics": total_epics,
                }
            else:
                return {"success": False, "error": result.error}

        except Exception as e:
            logger.error(f"Jira report generation failed: {e}", exc_info=True)
            return {"success": False, "error": str(e)}
