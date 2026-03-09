"""
GitHub Teams API discovery.

Fetches team structure, members, and repos from a GitHub organization
using the Teams API. Used during onboarding to auto-populate the
organization.yaml roster from GitHub.
"""

import logging
import requests

logger = logging.getLogger(__name__)


def discover_github_teams(token: str, org: str) -> list[dict]:
    """
    Discover all teams in a GitHub org with their members and repos.

    Returns:
        List of dicts: [{
            "name": "Platform",
            "slug": "platform",
            "parent_slug": None,
            "members": [{"username": "alice", "name": "Alice A"}, ...],
            "repos": [{"name": "backend", "full_name": "acme/backend"}, ...],
        }, ...]
    """
    http = requests.Session()
    http.headers.update({
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    })

    try:
        teams_raw = _paginate(http, f"https://api.github.com/orgs/{org}/teams")

        results = []
        for team in teams_raw:
            slug = team["slug"]
            parent = team.get("parent")

            members_raw = _paginate(
                http, f"https://api.github.com/orgs/{org}/teams/{slug}/members"
            )
            members = [
                {"username": m["login"], "name": m.get("name") or m["login"]}
                for m in members_raw
            ]

            repos_raw = _paginate(
                http, f"https://api.github.com/orgs/{org}/teams/{slug}/repos"
            )
            repos = [
                {"name": r["name"], "full_name": r["full_name"]}
                for r in repos_raw
            ]

            results.append({
                "name": team["name"],
                "slug": slug,
                "parent_slug": parent["slug"] if parent else None,
                "members": members,
                "repos": repos,
            })

        return results
    finally:
        http.close()


def _paginate(http: requests.Session, url: str, per_page: int = 100) -> list:
    """Paginate a GitHub REST API endpoint."""
    all_items: list = []
    params: dict = {"per_page": per_page, "page": 1}
    max_pages = 20

    for _ in range(max_pages):
        resp = http.get(url, params=params, timeout=20)
        resp.raise_for_status()
        items = resp.json()
        if not items:
            break
        all_items.extend(items)
        if len(items) < per_page:
            break
        params["page"] += 1

    return all_items
