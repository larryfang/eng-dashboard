"""
Jira Report Router

API endpoints for generating Jira ecosystem progress reports:
- POST /api/jira/report/generate — generate and send the report
- GET  /api/jira/report/preview  — preview HTML without sending
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/jira/report", tags=["jira-report"])


def get_ecosystem_db():
    from backend.database_domain import get_ecosystem_session
    yield from get_ecosystem_session()


class GenerateRequest(BaseModel):
    to: str = ""  # Set JIRA_REPORT_RECIPIENT in .env, or pass explicitly
    include_pulse: bool = True


@router.post("/generate")
async def generate_report(body: GenerateRequest, db: Session = Depends(get_ecosystem_db)):
    """Generate and send the Jira ecosystem progress report."""
    try:
        from backend.services.jira_report_service import JiraReportService

        service = JiraReportService(db=db)
        result = service.generate_and_send(to=body.to, include_pulse=body.include_pulse)

        if not result.get("success"):
            raise HTTPException(status_code=500, detail=result.get("error", "Unknown error"))

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error generating Jira report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))



@router.get("/markdown")
async def markdown_report(
    include_pulse: bool = Query(True),
    db: Session = Depends(get_ecosystem_db),
):
    """Return the Jira report as markdown for embedding in documents (e.g. pre-read).

    Matches the full content of the email report:
    - Team summary table
    - WIP epic progress with done/total child counts
    - Per-team: pulse, active items table, ready backlog count
    """
    try:
        from backend.services.jira_report_service import JiraReportService

        service = JiraReportService(db=db)
        teams_data = service.fetch_active_issues()
        wip_epics = service.fetch_wip_epics()

        if not teams_data and not wip_epics:
            return {"markdown": "_No active Jira data found._", "teams": 0, "total_items": 0}

        # Pre-generate pulses
        team_pulses: dict = {}
        if include_pulse:
            for team, issues_by_type in teams_data.items():
                try:
                    team_pulses[team] = service.generate_team_pulse(team, issues_by_type)
                except Exception:
                    all_issues = [i for v in issues_by_type.values() for i in v]
                    team_pulses[team] = service._fallback_pulse(team, all_issues)

        # Fetch epic child counts for progress
        child_counts: dict = {}
        if wip_epics:
            all_epic_keys = [e["key"] for epics in wip_epics.values() for e in epics]
            child_counts = service.fetch_epic_child_counts(all_epic_keys)

        lines = []

        # ── Team Summary ─────────────────────────────────────
        lines.append("### Epic Status by Team")
        lines.append("")
        lines.append("| Team | Active WIP | Breakdown |")
        lines.append("|------|-----------|-----------|")
        for team in sorted(teams_data.keys()):
            types = teams_data[team]
            count = sum(len(v) for v in types.values())
            breakdown = ", ".join(
                f"{len(v)} {t}"
                for t, v in sorted(types.items(), key=lambda x: -len(x[1]))
            )
            lines.append(f"| **{team}** | {count} | {breakdown} |")
        lines.append("")

        # ── WIP Epic Progress ────────────────────────────────
        if wip_epics:
            total_epics = sum(len(v) for v in wip_epics.values())
            lines.append(f"### WIP Epics ({total_epics} total)")
            lines.append("")
            for team in sorted(wip_epics.keys()):
                epics = wip_epics[team]
                lines.append(f"**{team}** ({len(epics)} epics)")
                lines.append("")
                lines.append("| Epic | Summary | Progress | Issues |")
                lines.append("|------|---------|----------|--------|")
                for epic in epics:
                    key = epic["key"]
                    url = epic["url"]
                    summary = epic["summary"]
                    if len(summary) > 60:
                        summary = summary[:57] + "…"
                    cc = child_counts.get(key, {"done": 0, "total": 0})
                    done, total = cc["done"], cc["total"]
                    pct = f"{done / total * 100:.0f}%" if total > 0 else "—"
                    lines.append(f"| [{key}]({url}) | {summary} | {pct} | {done}/{total} |")
                lines.append("")

        # ── Per-Team Detail ──────────────────────────────────
        for team in sorted(teams_data.keys()):
            types = teams_data[team]
            all_issues = [i for issues in types.values() for i in issues]

            epics = [i for i in all_issues if i["issue_type"] == "Epic"]
            ready_items = [i for i in all_issues if i["status"] in ("Ready for Development", "Ready")]
            active_items = [
                i for i in all_issues
                if i["issue_type"] != "Epic" and i["status"] not in ("Ready for Development", "Ready")
            ]
            active_items.sort(key=lambda x: x["assignee"])

            lines.append(f"#### {team} — {len(all_issues)} Active Items")
            lines.append("")

            # Pulse
            pulse = team_pulses.get(team, "")
            if pulse:
                lines.append(f"> 🔍 **Team Pulse:** {pulse}")
                lines.append("")

            # Epics inline (if any appear in active issues fetch)
            if epics:
                lines.append(f"**Epics ({len(epics)})**")
                lines.append("")
                lines.append("| Key | Summary | Status | Assignee |")
                lines.append("|-----|---------|--------|----------|")
                for e in epics:
                    lines.append(f"| {e['key']} | {e['summary']} | {e['status']} | {e['assignee']} |")
                lines.append("")

            # Active items
            if active_items:
                lines.append(f"**Items Actively Moving ({len(active_items)})**")
                lines.append("")
                lines.append("| Key | Type | Summary | Status | Assignee | Days | Parent |")
                lines.append("|-----|------|---------|--------|----------|------|--------|")
                for item in active_items:
                    days = item.get("days_in_status", 0)
                    days_str = f"🔴 {days}d" if days >= 14 else f"🟠 {days}d" if days >= 7 else f"🟡 {days}d" if days >= 3 else f"🟢 {days}d"
                    summary = item["summary"]
                    if len(summary) > 50:
                        summary = summary[:47] + "…"
                    lines.append(
                        f"| {item['key']} | {item['issue_type']} | {summary} "
                        f"| {item['status']} | {item['assignee']} | {days_str} | {item.get('parent', '')} |"
                    )
                lines.append("")

            # Ready backlog
            if ready_items:
                lines.append(f"**Ready for Development Backlog: {len(ready_items)} items**")
                lines.append("")

        total_items = sum(sum(len(v) for v in t.values()) for t in teams_data.values())
        all_teams = sorted(set(list(teams_data.keys()) + list(wip_epics.keys())))
        md = "\n".join(lines)
        return {
            "markdown": md,
            "teams": len(all_teams),
            "total_items": total_items,
            "wip_epics": sum(len(v) for v in wip_epics.values()),
        }
    except Exception as e:
        logger.error(f"Error generating markdown report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/preview", response_class=HTMLResponse)
async def preview_report(
    include_pulse: bool = Query(True),
    db: Session = Depends(get_ecosystem_db),
):
    """Preview the Jira report as HTML without sending."""
    try:
        from backend.services.jira_report_service import JiraReportService

        service = JiraReportService(db=db)
        teams_data = service.fetch_active_issues()

        if not teams_data:
            return HTMLResponse("<h1>No data</h1><p>No active Jira issues found.</p>")

        team_pulses = {}
        if include_pulse:
            for team, types in teams_data.items():
                try:
                    team_pulses[team] = service.generate_team_pulse(team, types)
                except Exception:
                    all_issues = [i for issues in types.values() for i in issues]
                    team_pulses[team] = service._fallback_pulse(team, all_issues)

        html = service.render_html_report(teams_data, team_pulses)
        return HTMLResponse(html)
    except Exception as e:
        logger.error(f"Error previewing Jira report: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
