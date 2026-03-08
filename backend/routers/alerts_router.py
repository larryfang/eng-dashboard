"""Alerts API with unified alert feed and persistent triage state."""

import logging
import re
from datetime import datetime, timezone
from typing import Literal
from urllib.parse import quote, urlencode

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from backend.database_domain import get_ecosystem_session
from backend.models_domain import AlertTriageState
from backend.services.jira_epic_health import check_stalled_epics
from backend.services.quiet_engineer_alerts import check_quiet_engineers
from backend.services.team_trend_alerts import check_team_trends

logger = logging.getLogger(__name__)

router = APIRouter(tags=["alerts"])

_STATUS_ORDER = {"open": 0, "acknowledged": 1, "resolved": 2}
_SEVERITY_ORDER = {"critical": 0, "warning": 1}
_SLUG_RE = re.compile(r"[^a-z0-9]+")


class AlertTriageUpdateRequest(BaseModel):
    alert_key: str
    status: Literal["open", "acknowledged", "resolved"] | None = None
    owner: str | None = None
    note: str | None = None


@router.get("/api/alerts/summary")
def alerts_summary(db: Session = Depends(get_ecosystem_session)):
    source_results = _collect_alert_results(db)
    alerts = _build_unified_alerts(source_results, db)

    return {
        "generated_at": _to_iso(_utc_now()),
        "alerts": alerts,
        "team_trends": source_results["team_trends"],
        "quiet_engineers": source_results["quiet_engineers"],
        "stalled_epics": source_results["stalled_epics"],
        "summary": {
            "teams_flagged": _item_count(source_results["team_trends"]),
            "quiet_engineer_count": _item_count(source_results["quiet_engineers"]),
            "stalled_epic_count": _item_count(source_results["stalled_epics"]),
            "total_alerts": len(alerts),
            "open_count": sum(1 for alert in alerts if alert["status"] == "open"),
            "acknowledged_count": sum(1 for alert in alerts if alert["status"] == "acknowledged"),
            "resolved_count": sum(1 for alert in alerts if alert["status"] == "resolved"),
            "critical_count": sum(1 for alert in alerts if alert["severity"] == "critical"),
            "warning_count": sum(1 for alert in alerts if alert["severity"] == "warning"),
        },
    }


@router.post("/api/alerts/triage")
def update_alert_triage(
    payload: AlertTriageUpdateRequest,
    db: Session = Depends(get_ecosystem_session),
):
    source_results = _collect_alert_results(db)
    alerts = _build_unified_alerts(source_results, db)
    alert = next((item for item in alerts if item["alert_key"] == payload.alert_key), None)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found in the current alert feed")

    triage_row = _upsert_triage_state(db, alert, payload)
    return {"alert": _apply_triage_state(alert, triage_row)}


def _collect_alert_results(db: Session) -> dict[str, list[dict] | dict[str, str]]:
    return {
        "team_trends": _safe_check(check_team_trends, db, "team_trends"),
        "quiet_engineers": _safe_check(check_quiet_engineers, db, "quiet_engineers"),
        "stalled_epics": _safe_check(check_stalled_epics, db, "stalled_epics"),
    }


def _build_unified_alerts(
    source_results: dict[str, list[dict] | dict[str, str]],
    db: Session,
) -> list[dict]:
    alerts: list[dict] = []

    team_trends = source_results.get("team_trends")
    if isinstance(team_trends, list):
        alerts.extend(_normalize_team_trend_alerts(team_trends))

    quiet_engineers = source_results.get("quiet_engineers")
    if isinstance(quiet_engineers, list):
        alerts.extend(_normalize_quiet_engineer_alerts(quiet_engineers))

    stalled_epics = source_results.get("stalled_epics")
    if isinstance(stalled_epics, list):
        alerts.extend(_normalize_stalled_epic_alerts(stalled_epics))

    triage_by_key = _load_triage_rows(db, [alert["alert_key"] for alert in alerts])
    hydrated = [_apply_triage_state(alert, triage_by_key.get(alert["alert_key"])) for alert in alerts]
    hydrated.sort(
        key=lambda item: (
            _STATUS_ORDER.get(str(item["status"]), 99),
            _SEVERITY_ORDER.get(str(item["severity"]), 99),
            str(item["alert_type"]),
            str(item["entity_label"]).lower(),
        )
    )
    return hydrated


def _normalize_team_trend_alerts(items: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    for item in items:
        team_slug = _clean_text(item.get("team_slug")) or _slugify(_clean_text(item.get("team_name")))
        if not team_slug:
            continue
        team_name = _clean_text(item.get("team_name")) or team_slug
        current_mrs = _as_int(item.get("current_mrs"))
        prior_mrs = _as_int(item.get("prior_mrs"))
        drop_pct = _as_float(item.get("drop_pct")) or 0.0
        route, route_metadata = _build_route("/activity", {"team": team_slug, "days": "7", "compare": "1"})
        alerts.append(
            {
                "alert_key": f"team_trend:{team_slug}",
                "alert_type": "team_trend",
                "severity": "critical" if drop_pct >= 50 else "warning",
                "status": "open",
                "title": f"{team_name} merge request volume dropped {drop_pct:.1f}%",
                "description": (
                    f"{team_name} opened {current_mrs} merge requests in the last 7 days "
                    f"versus {prior_mrs} in the prior 7 days."
                ),
                "entity_type": "team",
                "entity_label": team_name,
                "owner": None,
                "note": None,
                "route": route,
                "route_metadata": route_metadata,
                "metric": "merge_requests_opened",
                "metadata": _compact(
                    {
                        "entity_key": team_slug,
                        "team_slug": team_slug,
                        "team_name": team_name,
                        "current_mrs": current_mrs,
                        "prior_mrs": prior_mrs,
                        "drop_pct": drop_pct,
                    }
                ),
                "updated_at": None,
                "resolved_at": None,
            }
        )
        item["alert_key"] = f"team_trend:{team_slug}"
        item["severity"] = "critical" if drop_pct >= 50 else "warning"
        item["route"] = route
        item["route_metadata"] = route_metadata
        item["entity_key"] = team_slug
    return alerts


def _normalize_quiet_engineer_alerts(items: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    for item in items:
        username = _clean_text(item.get("engineer_username"))
        if not username:
            continue
        team_slug = _clean_text(item.get("team_slug"))
        team_name = _clean_text(item.get("team_name")) or team_slug or "Unknown team"
        engineer_name = _clean_text(item.get("engineer_name")) or username
        days_since = _as_int(item.get("days_since_last_activity"))
        route, route_metadata = _build_route(f"/engineers/{quote(username)}")
        alerts.append(
            {
                "alert_key": f"quiet_engineer:{username.lower()}",
                "alert_type": "quiet_engineer",
                "severity": "critical" if days_since >= 20 else "warning",
                "status": "open",
                "title": f"{engineer_name} has been quiet for {days_since} days",
                "description": (
                    f"No merge request activity was found for {engineer_name} in the last "
                    f"{days_since} days for {team_name}."
                ),
                "entity_type": "engineer",
                "entity_label": engineer_name,
                "owner": None,
                "note": None,
                "route": route,
                "route_metadata": route_metadata,
                "metric": "days_since_last_mr",
                "metadata": _compact(
                    {
                        "entity_key": username.lower(),
                        "team_slug": team_slug,
                        "team_name": team_name,
                        "engineer_username": username,
                        "engineer_name": engineer_name,
                        "days_since_last_activity": days_since,
                    }
                ),
                "updated_at": None,
                "resolved_at": None,
            }
        )
        item["alert_key"] = f"quiet_engineer:{username.lower()}"
        item["severity"] = "critical" if days_since >= 20 else "warning"
        item["route"] = route
        item["route_metadata"] = route_metadata
        item["entity_key"] = username.lower()
    return alerts


def _normalize_stalled_epic_alerts(items: list[dict]) -> list[dict]:
    alerts: list[dict] = []
    for item in items:
        epic_key = _clean_text(item.get("epic_key"))
        if not epic_key:
            continue
        project_key = _clean_text(item.get("project")) or epic_key.split("-")[0]
        epic_name = _clean_text(item.get("epic_name")) or "Untitled epic"
        team_name = _clean_text(item.get("team_name")) or project_key or "Unknown team"
        days_stalled = _as_int(item.get("days_stalled"))
        route, route_metadata = _build_route("/activity", {"team": project_key, "epic": epic_key, "days": "90"})
        alerts.append(
            {
                "alert_key": f"stalled_epic:{epic_key}",
                "alert_type": "stalled_epic",
                "severity": "critical" if days_stalled >= 14 else "warning",
                "status": "open",
                "title": f"{epic_key} has had no Jira updates for {days_stalled} days",
                "description": (
                    f"{epic_name} has been idle in Jira for {days_stalled} days "
                    f"for {team_name}."
                ),
                "entity_type": "epic",
                "entity_label": epic_key,
                "owner": None,
                "note": None,
                "route": route,
                "route_metadata": route_metadata,
                "metric": "days_since_update",
                "metadata": _compact(
                    {
                        "entity_key": epic_key,
                        "project_key": project_key,
                        "team_name": team_name,
                        "epic_key": epic_key,
                        "epic_name": epic_name,
                        "days_stalled": days_stalled,
                        "jira_url": _clean_text(item.get("jira_url")),
                    }
                ),
                "updated_at": None,
                "resolved_at": None,
            }
        )
        item["alert_key"] = f"stalled_epic:{epic_key}"
        item["severity"] = "critical" if days_stalled >= 14 else "warning"
        item["route"] = route
        item["route_metadata"] = route_metadata
        item["entity_key"] = epic_key
    return alerts


def _load_triage_rows(db: Session, alert_keys: list[str]) -> dict[str, AlertTriageState]:
    if not alert_keys:
        return {}
    rows = (
        db.query(AlertTriageState)
        .filter(AlertTriageState.alert_key.in_(alert_keys))
        .all()
    )
    return {row.alert_key: row for row in rows}


def _upsert_triage_state(
    db: Session,
    alert: dict,
    payload: AlertTriageUpdateRequest,
) -> AlertTriageState:
    row = db.query(AlertTriageState).filter_by(alert_key=payload.alert_key).first()
    if row is None:
        row = AlertTriageState(
            alert_key=payload.alert_key,
            alert_type=str(alert["alert_type"]),
            entity_type=str(alert["entity_type"]),
            entity_key=str(alert["metadata"]["entity_key"]),
            status="open",
        )
        db.add(row)

    row.alert_type = str(alert["alert_type"])
    row.entity_type = str(alert["entity_type"])
    row.entity_key = str(alert["metadata"]["entity_key"])

    provided_fields = _model_fields_set(payload)
    if "status" in provided_fields:
        if payload.status is None:
            raise HTTPException(status_code=400, detail="status cannot be null")
        row.status = payload.status
        row.resolved_at = _utc_now() if payload.status == "resolved" else None
    if "owner" in provided_fields:
        row.owner = _clean_text(payload.owner)
    if "note" in provided_fields:
        row.note = _clean_text(payload.note)

    row.updated_at = _utc_now()
    db.commit()
    db.refresh(row)
    return row


def _apply_triage_state(alert: dict, row: AlertTriageState | None) -> dict:
    hydrated = dict(alert)
    if row is None:
        return hydrated

    hydrated["status"] = row.status
    hydrated["owner"] = row.owner
    hydrated["note"] = row.note
    hydrated["updated_at"] = _to_iso(row.updated_at)
    hydrated["resolved_at"] = _to_iso(row.resolved_at)
    return hydrated


def _safe_check(fn, db, label: str):
    try:
        return fn(db)
    except Exception as exc:
        logger.exception("Alert check '%s' failed", label)
        return {"error": str(exc)}


def _build_route(path: str, params: dict[str, str | None] | None = None) -> tuple[str, dict]:
    clean_params = {
        key: value
        for key, value in (params or {}).items()
        if value not in (None, "")
    }
    route = path
    if clean_params:
        route = f"{path}?{urlencode(clean_params)}"
    return route, {"path": path, "params": clean_params}


def _item_count(value) -> int:
    return len(value) if isinstance(value, list) else 0


def _clean_text(value) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _slugify(value: str | None) -> str | None:
    if not value:
        return None
    slug = _SLUG_RE.sub("-", value.strip().lower()).strip("-")
    return slug or None


def _compact(payload: dict) -> dict:
    return {key: value for key, value in payload.items() if value is not None}


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _as_int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _as_float(value) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _model_fields_set(model: BaseModel) -> set[str]:
    fields = getattr(model, "model_fields_set", None)
    if fields is not None:
        return set(fields)
    return set(getattr(model, "__fields_set__", set()))
