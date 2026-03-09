"""
Snyk Service - Security vulnerability metrics per team.

Fetches vulnerability counts (critical/high/medium/low) from the Snyk API,
maps Snyk orgs to teams via organization.yaml, and caches results to CSV.

Adapted from the personalassistant project's snyk_service.py.
"""

import csv
import logging
import os
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).parent.parent.parent


def _get_snyk_to_team() -> Dict[str, str]:
    try:
        from backend.core.config_loader import get_snyk_to_team_map
        return get_snyk_to_team_map()
    except (ImportError, KeyError, AttributeError) as e:
        logger.debug(f"Snyk team mapping not available: {e}")
        return {}


def _get_token() -> str:
    try:
        from backend.services.domain_credentials import get_snyk_settings
        return get_snyk_settings().get("token", "")
    except (ImportError, Exception):
        return os.getenv("SNYK_TOKEN", "")


@dataclass
class SnykMetrics:
    team: str
    snyk_org: str
    critical: int
    high: int
    medium: int
    low: int
    total: int


class SnykService:
    """Fetches and caches Snyk vulnerability data per team."""

    def __init__(self):
        data_dir = PROJECT_ROOT / "data"
        data_dir.mkdir(parents=True, exist_ok=True)
        self.current_report_path = data_dir / "snyk_severity_report.csv"
        self.timeseries_path = data_dir / "snyk_monthly_by_team.csv"

    def _snyk_request(self, method: str, url: str, headers: Dict, **kwargs) -> requests.Response:
        for attempt in range(5):
            try:
                r = requests.request(method, url, headers=headers, timeout=60, **kwargs)
                if r.status_code in (429, 500, 502, 503, 504):
                    time.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                return r
            except requests.exceptions.RequestException:
                if attempt == 4:
                    raise
                time.sleep(2 ** attempt)
        raise RuntimeError("Snyk API request failed after retries")

    def _list_orgs(self, token: str) -> List[Dict[str, str]]:
        rest_base = "https://api.snyk.io/rest"
        api_version = "2024-10-15"
        headers = {"Authorization": f"token {token}", "Accept": "application/json"}

        orgs: List[Dict[str, str]] = []
        url: Optional[str] = f"{rest_base}/orgs?version={api_version}&limit=100"

        while url:
            response = self._snyk_request("GET", url, headers)
            data = response.json()
            orgs.extend(
                {"id": d["id"], "name": d["attributes"]["name"]}
                for d in data.get("data", [])
            )
            url = data.get("links", {}).get("next")

        return orgs

    def _list_projects(self, token: str, org_id: str) -> List[str]:
        rest_base = "https://api.snyk.io/rest"
        api_version = "2024-10-15"
        headers = {"Authorization": f"token {token}", "Accept": "application/json"}

        project_ids: List[str] = []
        url: Optional[str] = f"{rest_base}/orgs/{org_id}/projects?version={api_version}&limit=100"

        while url:
            response = self._snyk_request("GET", url, headers)
            data = response.json()
            project_ids.extend(d["id"] for d in data.get("data", []))
            next_url = data.get("links", {}).get("next")
            url = (
                f"https://api.snyk.io{next_url}"
                if next_url and not next_url.startswith("http")
                else next_url
            )

        return project_ids

    def _get_severity_counts(self, token: str, org_ids: List[str]) -> Dict[str, int]:
        v1_base = "https://api.snyk.io/v1"
        headers = {
            "Authorization": f"token {token}",
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

        totals: Dict[str, int] = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        for org_id in org_ids:
            project_ids = self._list_projects(token, org_id)

            for pid in project_ids:
                url = f"{v1_base}/org/{org_id}/project/{pid}/aggregated-issues"
                payload = {
                    "includeDescription": False,
                    "includeIntroducedThrough": False,
                    "filters": {
                        "severities": ["critical", "high", "medium", "low"],
                        "types": ["vuln", "license"],
                        "ignored": False,
                        "patched": False,
                        "isFixed": False,
                    },
                }
                try:
                    response = self._snyk_request("POST", url, headers, json=payload)
                    for issue in response.json().get("issues", []):
                        sev = issue.get("issueData", {}).get("severity")
                        if sev in totals:
                            totals[sev] += 1
                except requests.exceptions.HTTPError:
                    pass
                time.sleep(0.25)

        return totals

    def _read_current_metrics(self) -> Dict[str, Any]:
        snyk_to_team = _get_snyk_to_team()
        if not self.current_report_path.exists():
            return {"teams": [], "totals": {}}

        teams: List[Dict[str, Any]] = []
        totals = {"critical": 0, "high": 0, "medium": 0, "low": 0}

        with open(self.current_report_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                org = row["org"]
                if org == "TOTAL":
                    continue

                team_name = snyk_to_team.get(org, org)

                critical = int(row["critical"])
                high = int(row["high"])
                medium = int(row["medium"])
                low = int(row["low"])

                teams.append({
                    "team": team_name,
                    "snyk_org": org,
                    "critical": critical,
                    "high": high,
                    "medium": medium,
                    "low": low,
                    "total": critical + high + medium + low,
                })

                totals["critical"] += critical
                totals["high"] += high
                totals["medium"] += medium
                totals["low"] += low

        teams.sort(key=lambda x: (x["critical"], x["high"]), reverse=True)
        return {"teams": teams, "totals": totals, "generated_at": datetime.now().isoformat()}

    def _read_timeseries(self, months_limit: Optional[int] = None) -> Dict[str, Any]:
        snyk_to_team = _get_snyk_to_team()
        if not self.timeseries_path.exists():
            return {"teams": {}, "months": []}

        month_order = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]

        teams_data: Dict[str, List[Dict]] = {}
        months_seen: set = set()

        with open(self.timeseries_path, "r") as f:
            reader = csv.DictReader(f)
            for row in reader:
                month = row["Month"]
                org = row["Team"]
                critical = int(row["Critical"])
                high = int(row["High"])

                team_name = snyk_to_team.get(org, org)

                teams_data.setdefault(team_name, []).append({
                    "month": month,
                    "month_abbrev": month.split()[0][:3],
                    "critical": critical,
                    "high": high,
                })
                months_seen.add(month)

        sorted_months = sorted(
            months_seen,
            key=lambda m: (int(m.split()[1]), month_order.index(m.split()[0]))
            if m.split()[0] in month_order else (0, 0),
        )

        if months_limit and len(sorted_months) > months_limit:
            sorted_months = sorted_months[-months_limit:]

        for team in teams_data:
            teams_data[team].sort(
                key=lambda x: (
                    int(x["month"].split()[1]),
                    month_order.index(x["month"].split()[0])
                    if x["month"].split()[0] in month_order else 0,
                )
            )

        return {
            "teams": teams_data,
            "months": sorted_months,
            "months_abbrev": [m.split()[0][:3] for m in sorted_months],
            "generated_at": datetime.now().isoformat(),
        }

    def _update_timeseries_csv(self, org_data: List[Dict[str, Any]]) -> bool:
        current_month = datetime.now().strftime("%B %Y")
        month_order = [
            "January", "February", "March", "April", "May", "June",
            "July", "August", "September", "October", "November", "December",
        ]

        try:
            existing_rows: List[Dict] = []
            if self.timeseries_path.exists():
                with open(self.timeseries_path, "r") as f:
                    reader = csv.DictReader(f)
                    for row in reader:
                        if row["Month"] != current_month:
                            existing_rows.append(row)

            for org in org_data:
                existing_rows.append({
                    "Month": current_month,
                    "Team": org["org"],
                    "Critical": org["critical"],
                    "High": org["high"],
                })

            existing_rows.sort(key=lambda row: (
                int(row["Month"].split()[1]),
                month_order.index(row["Month"].split()[0])
                if row["Month"].split()[0] in month_order else 0,
                row["Team"],
            ))

            with open(self.timeseries_path, "w", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["Month", "Team", "Critical", "High"])
                writer.writeheader()
                writer.writerows(existing_rows)

            logger.info(f"Updated timeseries with {len(org_data)} orgs for {current_month}")
            return True
        except Exception as e:
            logger.error(f"Failed to update timeseries CSV: {e}")
            return False

    # ---- Public API (matches router contract) ----

    def refresh_data(self) -> Dict[str, Any]:
        token = _get_token()
        if not token:
            return {"success": False, "error": "SNYK_TOKEN not configured", "orgs_found": 0}

        logger.info("Refreshing Snyk data from API...")
        start_time = datetime.now()

        try:
            orgs = self._list_orgs(token)
            if not orgs:
                return {"success": False, "error": "No orgs visible to this token", "orgs_found": 0}

            logger.info(f"Found {len(orgs)} Snyk organizations")

            rows: List[Dict[str, Any]] = []
            totals = {"critical": 0, "high": 0, "medium": 0, "low": 0}

            with ThreadPoolExecutor(max_workers=4) as executor:
                futures = {
                    executor.submit(self._get_severity_counts, token, [org["id"]]): org
                    for org in orgs
                }
                for future in as_completed(futures):
                    org = futures[future]
                    try:
                        severity = future.result()
                    except Exception as e:
                        logger.warning(f"Snyk fetch failed for {org['name']}: {e}")
                        severity = {"critical": 0, "high": 0, "medium": 0, "low": 0}
                    rows.append({
                        "org": org["name"],
                        "critical": severity.get("critical", 0),
                        "high": severity.get("high", 0),
                        "medium": severity.get("medium", 0),
                        "low": severity.get("low", 0),
                    })
                    for key in totals:
                        totals[key] += severity.get(key, 0)

            with open(self.current_report_path, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow(["org", "critical", "high", "medium", "low"])
                for row in rows:
                    writer.writerow([row["org"], row["critical"], row["high"], row["medium"], row["low"]])
                writer.writerow(["TOTAL", totals["critical"], totals["high"], totals["medium"], totals["low"]])

            self._update_timeseries_csv(rows)

            elapsed = (datetime.now() - start_time).total_seconds()
            logger.info(f"Snyk data refreshed: {len(orgs)} orgs in {elapsed:.1f}s")

            return {
                "success": True,
                "orgs_refreshed": len(orgs),
                "totals": totals,
                "elapsed_seconds": round(elapsed, 1),
                "refreshed_at": datetime.now().isoformat(),
            }
        except requests.exceptions.HTTPError as e:
            logger.error(f"Snyk API error: {e}")
            return {"success": False, "error": f"Snyk API error: {e}", "orgs_found": 0}
        except Exception as e:
            logger.error(f"Snyk refresh failed: {e}")
            return {"success": False, "error": str(e), "orgs_found": 0}

    def get_security_summary(self) -> Dict[str, Any]:
        metrics = self._read_current_metrics()
        timeseries = self._read_timeseries()

        teams = metrics.get("teams", [])
        totals = metrics.get("totals", {})

        return {
            "summary": {
                "total_critical": totals.get("critical", 0),
                "total_high": totals.get("high", 0),
                "total_medium": totals.get("medium", 0),
                "total_low": totals.get("low", 0),
                "teams_with_critical": sum(1 for t in teams if t.get("critical", 0) > 0),
                "teams_with_high": sum(1 for t in teams if t.get("high", 0) > 0),
                "total_teams": len(teams),
            },
            "teams": teams,
            "trend": timeseries.get("teams", {}),
            "months": timeseries.get("months", []),
            "generated_at": datetime.now().isoformat(),
        }

    def get_security_by_team(self) -> Dict[str, Any]:
        metrics = self._read_current_metrics()
        teams = sorted(
            metrics.get("teams", []),
            key=lambda t: (t.get("critical", 0), t.get("high", 0)),
            reverse=True,
        )
        return {"teams": teams, "count": len(teams), "generated_at": datetime.now().isoformat()}

    def get_critical_vulns(self) -> Dict[str, Any]:
        metrics = self._read_current_metrics()
        critical_teams = [
            {"team": t["team"], "snyk_org": t["snyk_org"], "critical": t["critical"], "high": t["high"]}
            for t in metrics.get("teams", [])
            if t.get("critical", 0) > 0
        ]
        return {
            "critical_teams": critical_teams,
            "count": len(critical_teams),
            "total_critical": sum(t["critical"] for t in critical_teams),
            "generated_at": datetime.now().isoformat(),
        }

    def get_high_risk_teams(self, threshold: int = 5) -> Dict[str, Any]:
        metrics = self._read_current_metrics()
        high_risk = [
            {
                "team": t["team"],
                "snyk_org": t["snyk_org"],
                "critical": t["critical"],
                "high": t["high"],
                "total_severe": t["critical"] + t["high"],
            }
            for t in metrics.get("teams", [])
            if (t.get("critical", 0) + t.get("high", 0)) >= threshold
        ]
        high_risk.sort(key=lambda t: t["total_severe"], reverse=True)
        return {
            "high_risk_teams": high_risk,
            "count": len(high_risk),
            "threshold": threshold,
            "generated_at": datetime.now().isoformat(),
        }

    def get_security_trend(self, months: int = 6) -> Dict[str, Any]:
        timeseries = self._read_timeseries(months_limit=months)
        teams_data = timeseries.get("teams", {})
        recent_months = timeseries.get("months", [])

        filtered_teams = {}
        for team, data in teams_data.items():
            filtered_teams[team] = [d for d in data if d.get("month") in recent_months]

        trends = {}
        for team, data in filtered_teams.items():
            if len(data) >= 2:
                first, last = data[0], data[-1]
                trends[team] = {
                    "critical_change": last.get("critical", 0) - first.get("critical", 0),
                    "high_change": last.get("high", 0) - first.get("high", 0),
                    "direction": (
                        "improving"
                        if (last.get("critical", 0) + last.get("high", 0))
                        < (first.get("critical", 0) + first.get("high", 0))
                        else "worsening"
                    ),
                }

        return {
            "teams": filtered_teams,
            "months": recent_months,
            "trends": trends,
            "generated_at": datetime.now().isoformat(),
        }


_snyk_service: Optional[SnykService] = None


def get_snyk_service() -> SnykService:
    global _snyk_service
    if _snyk_service is None:
        _snyk_service = SnykService()
    return _snyk_service
