"""GitHub implementation of GitProvider using REST + Search APIs."""

import logging
import time
import requests
from backend.services.git_providers.base import GitProvider, PullRequestData
from backend.services.datetime_utils import parse_dt
from backend.plugins.registry import register

logger = logging.getLogger(__name__)
MAX_PAGES = 10  # GitHub Search API: 1000 results max (10 pages * 100)
SEARCH_RATE_LIMIT_PAUSE = 2.0  # seconds between Search API calls (30/min limit)


@register("git_provider", "github")
class GitHubProvider(GitProvider):
    """Fetches engineer activity from the GitHub REST + Search APIs."""

    def __init__(self, token: str, org: str):
        self._org = org
        self._http = requests.Session()
        self._http.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })

    def fetch_pull_requests(
        self, username: str, since_iso: str
    ) -> list[PullRequestData]:
        """
        Fetch PRs via GitHub Search API.

        Query: is:pr author:{username} org:{org} created:>={date}
        This is the GitHub equivalent of GitLab's scope=all — cross-repo search.

        Note: Search API returns max 1,000 results and has a 30 req/min limit.
        """
        since_date = since_iso[:10]  # "2026-01-01T00:00:00Z" -> "2026-01-01"
        query = f"is:pr author:{username} org:{self._org} created:>={since_date}"

        prs: list[PullRequestData] = []
        page = 1
        while page <= MAX_PAGES:
            if page > 1:
                time.sleep(SEARCH_RATE_LIMIT_PAUSE)

            resp = self._http.get(
                "https://api.github.com/search/issues",
                params={
                    "q": query,
                    "sort": "created",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                },
                timeout=30,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("items", [])
            if not items:
                break

            for item in items:
                pr_data = item.get("pull_request", {})
                merged_at_str = pr_data.get("merged_at")
                state = item.get("state", "open")
                # GitHub: closed + merged_at means merged; closed without means rejected
                if state == "closed" and merged_at_str:
                    state = "merged"

                # Extract repo from repository_url:
                # "https://api.github.com/repos/acme/repo" -> "acme/repo"
                repo_url = item.get("repository_url", "")
                repo_id = "/".join(repo_url.split("/")[-2:]) if repo_url else ""

                web_url = pr_data.get("html_url") or item.get("html_url")

                prs.append(PullRequestData(
                    pr_iid=item["number"],
                    repo_id=repo_id,
                    title=item.get("title", ""),
                    source_branch=None,  # Not available from Search API
                    author_username=username,
                    state=state,
                    created_at=parse_dt(item.get("created_at")),
                    merged_at=parse_dt(merged_at_str),
                    web_url=web_url,
                    description=item.get("body"),
                ))

            if len(items) < 100:
                break
            page += 1

        return prs

    def fetch_commit_count(self, username: str, since_iso: str) -> int:
        """
        Count commits by username across all org repos.

        Uses GitHub Search API: author:{username} org:{org} committer-date:>={date}
        """
        since_date = since_iso[:10]
        query = f"author:{username} org:{self._org} committer-date:>={since_date}"
        try:
            resp = self._http.get(
                "https://api.github.com/search/commits",
                params={"q": query, "per_page": 1},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json().get("total_count", 0)
        except Exception as e:
            logger.warning(f"GitHub commit count fetch failed for {username}: {e}")
            return 0

    def fetch_review_count(self, username: str, since_iso: str) -> int:
        """
        Count PR reviews by username.

        Uses GitHub Search API: is:pr reviewed-by:{username} org:{org} created:>={date}
        """
        since_date = since_iso[:10]
        query = f"is:pr reviewed-by:{username} org:{self._org} created:>={since_date}"
        try:
            resp = self._http.get(
                "https://api.github.com/search/issues",
                params={"q": query, "per_page": 1},
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json().get("total_count", 0)
        except Exception as e:
            logger.warning(f"GitHub review count fetch failed for {username}: {e}")
            return 0

    def close(self) -> None:
        self._http.close()
