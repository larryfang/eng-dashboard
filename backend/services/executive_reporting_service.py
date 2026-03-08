"""Executive reporting helpers for saved views and scheduled digests."""

import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from backend.core.config_loader import get_config
from backend.models_domain import ExecutiveDigest, ExecutiveDigestRun, SavedView
from backend.services.email_service import get_email_service
from backend.services.jira_report_service import JiraReportService

logger = logging.getLogger(__name__)

DEFAULT_VIEW_CONFIG = {
    "include_pulse": True,
    "format": "html",
}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _load_json(raw: str | None, default: Any):
    if not raw:
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _dump_json(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"))


def serialize_saved_view(row: SavedView) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "view_type": row.view_type,
        "config": _load_json(row.config_json, dict(DEFAULT_VIEW_CONFIG)),
        "created_at": _to_iso(row.created_at),
        "updated_at": _to_iso(row.updated_at),
    }


def serialize_digest(row: ExecutiveDigest) -> dict[str, Any]:
    return {
        "id": row.id,
        "name": row.name,
        "saved_view_id": row.saved_view_id,
        "recipients": _load_json(row.recipients_json, []),
        "include_pulse": row.include_pulse,
        "frequency": row.frequency,
        "weekday": row.weekday,
        "hour_utc": row.hour_utc,
        "active": row.active,
        "last_run_at": _to_iso(row.last_run_at),
        "next_run_at": _to_iso(row.next_run_at),
        "created_at": _to_iso(row.created_at),
        "updated_at": _to_iso(row.updated_at),
    }


def serialize_digest_run(row: ExecutiveDigestRun) -> dict[str, Any]:
    return {
        "id": row.id,
        "digest_id": row.digest_id,
        "status": row.status,
        "delivery_state": row.delivery_state,
        "recipient_count": row.recipient_count,
        "subject": row.subject,
        "error_message": row.error_message,
        "generated_at": _to_iso(row.generated_at),
        "report_markdown": row.report_markdown,
        "report_html": row.report_html,
    }


def resolve_view_config(db, saved_view_id: int | None, fallback_include_pulse: bool = True) -> dict[str, Any]:
    config = dict(DEFAULT_VIEW_CONFIG)
    if saved_view_id is None:
        config["include_pulse"] = fallback_include_pulse
        return config

    row = db.query(SavedView).filter_by(id=saved_view_id).first()
    if row is None:
        config["include_pulse"] = fallback_include_pulse
        return config

    config.update(_load_json(row.config_json, {}))
    return config


def compute_next_run(
    frequency: str,
    hour_utc: int,
    weekday: int | None = None,
    from_dt: datetime | None = None,
) -> datetime:
    now = (from_dt or _utc_now()).astimezone(timezone.utc).replace(minute=0, second=0, microsecond=0)
    candidate = now.replace(hour=max(0, min(hour_utc, 23)))

    if frequency == "daily":
        if candidate <= now:
            candidate += timedelta(days=1)
        return candidate

    target_weekday = weekday if weekday is not None else 0
    days_ahead = (target_weekday - now.weekday()) % 7
    candidate = candidate + timedelta(days=days_ahead)
    if candidate <= now:
        candidate += timedelta(days=7)
    return candidate


def render_executive_report(db, include_pulse: bool = True) -> dict[str, Any]:
    service = JiraReportService(db=db)
    teams_data = service.fetch_active_issues()
    wip_epics = service.fetch_wip_epics()

    team_pulses: dict[str, str] = {}
    if include_pulse:
        for team, issues_by_type in teams_data.items():
            try:
                team_pulses[team] = service.generate_team_pulse(team, issues_by_type)
            except Exception:
                all_issues = [item for issues in issues_by_type.values() for item in issues]
                team_pulses[team] = service._fallback_pulse(team, all_issues)

    all_epic_keys = [epic["key"] for epics in wip_epics.values() for epic in epics]
    child_counts = service.fetch_epic_child_counts(all_epic_keys) if all_epic_keys else {}
    epic_section = service._render_epic_progress_section(wip_epics, child_counts) if wip_epics else ""

    html = service.render_html_report(teams_data, team_pulses, epic_section)
    markdown = _render_markdown_report(service, teams_data, wip_epics, team_pulses, child_counts)
    total_items = sum(sum(len(v) for v in types.values()) for types in teams_data.values())

    return {
        "html": html,
        "markdown": markdown,
        "summary": {
            "teams": len(sorted(set(list(teams_data.keys()) + list(wip_epics.keys())))),
            "total_items": total_items,
            "wip_epics": sum(len(v) for v in wip_epics.values()),
            "generated_at": _to_iso(_utc_now()),
        },
    }


def _render_markdown_report(service: JiraReportService, teams_data, wip_epics, team_pulses, child_counts) -> str:
    lines: list[str] = []

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
                summary = epic["summary"]
                if len(summary) > 60:
                    summary = summary[:57] + "…"
                cc = child_counts.get(key, {"done": 0, "total": 0})
                done, total = cc["done"], cc["total"]
                pct = f"{done / total * 100:.0f}%" if total > 0 else "—"
                lines.append(f"| [{key}]({epic['url']}) | {summary} | {pct} | {done}/{total} |")
            lines.append("")

    for team in sorted(teams_data.keys()):
        types = teams_data[team]
        all_issues = [item for issues in types.values() for item in issues]
        epics = [item for item in all_issues if item["issue_type"] == "Epic"]
        ready_items = [item for item in all_issues if item["status"] in ("Ready for Development", "Ready")]
        active_items = [
            item for item in all_issues
            if item["issue_type"] != "Epic" and item["status"] not in ("Ready for Development", "Ready")
        ]
        active_items.sort(key=lambda x: x["assignee"])

        lines.append(f"#### {team} — {len(all_issues)} Active Items")
        lines.append("")

        pulse = team_pulses.get(team, "")
        if pulse:
            lines.append(f"> 🔍 **Team Pulse:** {pulse}")
            lines.append("")

        if epics:
            lines.append(f"**Epics ({len(epics)})**")
            lines.append("")
            lines.append("| Key | Summary | Status | Assignee |")
            lines.append("|-----|---------|--------|----------|")
            for epic in epics:
                lines.append(f"| {epic['key']} | {epic['summary']} | {epic['status']} | {epic['assignee']} |")
            lines.append("")

        if active_items:
            lines.append(f"**Items Actively Moving ({len(active_items)})**")
            lines.append("")
            lines.append("| Key | Type | Summary | Status | Assignee | Days | Parent |")
            lines.append("|-----|------|---------|--------|----------|------|--------|")
            for item in active_items:
                days = item.get("days_in_status", 0)
                days_str = (
                    f"🔴 {days}d" if days >= 14
                    else f"🟠 {days}d" if days >= 7
                    else f"🟡 {days}d" if days >= 3
                    else f"🟢 {days}d"
                )
                summary = item["summary"]
                if len(summary) > 50:
                    summary = summary[:47] + "…"
                lines.append(
                    f"| {item['key']} | {item['issue_type']} | {summary} | "
                    f"{item['status']} | {item['assignee']} | {days_str} | {item.get('parent', '')} |"
                )
            lines.append("")

        if ready_items:
            lines.append(f"**Ready for Development Backlog: {len(ready_items)} items**")
            lines.append("")

    return "\n".join(lines)


def upsert_saved_view(db, *, name: str, view_type: str, config: dict[str, Any], view_id: int | None = None) -> SavedView:
    row = db.query(SavedView).filter_by(id=view_id).first() if view_id else None
    if row is None:
        row = SavedView(name=name.strip(), view_type=view_type, config_json=_dump_json(config))
        db.add(row)
    else:
        row.name = name.strip()
        row.view_type = view_type
        row.config_json = _dump_json(config)
        row.updated_at = _utc_now()
    db.commit()
    db.refresh(row)
    return row


def delete_saved_view(db, view_id: int) -> bool:
    row = db.query(SavedView).filter_by(id=view_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def upsert_digest(
    db,
    *,
    name: str,
    recipients: list[str],
    include_pulse: bool,
    frequency: str,
    weekday: int | None,
    hour_utc: int,
    active: bool,
    saved_view_id: int | None = None,
    digest_id: int | None = None,
) -> ExecutiveDigest:
    row = db.query(ExecutiveDigest).filter_by(id=digest_id).first() if digest_id else None
    if row is None:
        row = ExecutiveDigest(name=name.strip())
        db.add(row)

    row.name = name.strip()
    row.saved_view_id = saved_view_id
    row.recipients_json = _dump_json(sorted(set(r.strip() for r in recipients if r.strip())))
    row.include_pulse = include_pulse
    row.frequency = frequency
    row.weekday = weekday
    row.hour_utc = hour_utc
    row.active = active
    row.updated_at = _utc_now()
    row.next_run_at = compute_next_run(frequency, hour_utc, weekday) if active else None

    db.commit()
    db.refresh(row)
    return row


def delete_digest(db, digest_id: int) -> bool:
    row = db.query(ExecutiveDigest).filter_by(id=digest_id).first()
    if row is None:
        return False
    db.delete(row)
    db.commit()
    return True


def run_digest(db, digest: ExecutiveDigest) -> ExecutiveDigestRun:
    config = resolve_view_config(db, digest.saved_view_id, fallback_include_pulse=digest.include_pulse)
    report = render_executive_report(db, include_pulse=bool(config.get("include_pulse", True)))
    recipients = _load_json(digest.recipients_json, []) or get_config().get_digest_recipients()
    subject = f"{digest.name} — {_utc_now().strftime('%Y-%m-%d')}"

    email = get_email_service()
    delivery_state = "stored_only"
    status = "generated"
    error_message = None

    if recipients and email.is_configured:
        result = email.send(
            to=recipients,
            subject=subject,
            text=report["markdown"],
            html=report["html"],
        )
        if result.success:
            delivery_state = "sent"
        else:
            delivery_state = "delivery_blocked"
            error_message = result.error
            status = "generated"
    elif recipients:
        delivery_state = "delivery_blocked"
        error_message = "Email delivery is disabled; digest snapshot stored only"

    run = ExecutiveDigestRun(
        digest_id=digest.id,
        status=status,
        delivery_state=delivery_state,
        recipient_count=len(recipients),
        subject=subject,
        report_markdown=report["markdown"],
        report_html=report["html"],
        error_message=error_message,
        generated_at=_utc_now(),
    )
    db.add(run)

    digest.last_run_at = run.generated_at
    digest.next_run_at = compute_next_run(digest.frequency, digest.hour_utc, digest.weekday, from_dt=run.generated_at) if digest.active else None
    digest.updated_at = _utc_now()

    db.commit()
    db.refresh(run)
    return run


def run_due_digests(db) -> int:
    now = _utc_now()
    due = (
        db.query(ExecutiveDigest)
        .filter(
            ExecutiveDigest.active.is_(True),
            ExecutiveDigest.next_run_at.isnot(None),
            ExecutiveDigest.next_run_at <= now,
        )
        .all()
    )
    for digest in due:
        try:
            run_digest(db, digest)
        except Exception as exc:
            logger.exception("Executive digest '%s' failed", digest.name)
            run = ExecutiveDigestRun(
                digest_id=digest.id,
                status="error",
                delivery_state="error",
                recipient_count=0,
                subject=f"{digest.name} — {_utc_now().strftime('%Y-%m-%d')}",
                error_message=str(exc),
                generated_at=_utc_now(),
            )
            db.add(run)
            digest.last_run_at = now
            digest.next_run_at = compute_next_run(digest.frequency, digest.hour_utc, digest.weekday, from_dt=now)
            digest.updated_at = now
            db.commit()
    return len(due)
