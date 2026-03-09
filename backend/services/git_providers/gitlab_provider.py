"""GitLab implementation of GitProvider."""

import logging
import requests
from backend.services.git_providers.base import GitProvider, PullRequestData
from backend.services.datetime_utils import parse_dt

logger = logging.getLogger(__name__)
MAX_PAGES = 50


class GitLabProvider(GitProvider):
    """Fetches engineer activity from the GitLab REST API."""

    def __init__(self, url: str, token: str):
        self._url = url.rstrip("/")
        self._http = requests.Session()
        self._http.headers["PRIVATE-TOKEN"] = token

    def fetch_pull_requests(
        self, username: str, since_iso: str
    ) -> list[PullRequestData]:
        mrs: list[PullRequestData] = []
        page = 1
        while page <= MAX_PAGES:
            resp = self._http.get(
                f"{self._url}/api/v4/merge_requests",
                params={
                    "author_username": username,
                    "created_after": since_iso,
                    "state": "all",
                    "scope": "all",
                    "per_page": 100,
                    "page": page,
                    "order_by": "created_at",
                    "sort": "desc",
                },
                timeout=30,
            )
            resp.raise_for_status()
            batch = resp.json()
            if not batch:
                break
            for mr in batch:
                mrs.append(PullRequestData(
                    pr_iid=mr["iid"],
                    repo_id=str(mr.get("project_id", "")),
                    title=mr.get("title", ""),
                    source_branch=mr.get("source_branch"),
                    author_username=username,
                    state=mr.get("state", ""),
                    created_at=parse_dt(mr.get("created_at")),
                    merged_at=parse_dt(mr.get("merged_at")),
                    web_url=mr.get("web_url"),
                    description=mr.get("description"),
                ))
            if len(batch) < 100:
                break
            page += 1
        return mrs

    def fetch_commit_count(self, username: str, since_iso: str) -> int:
        try:
            resp = self._http.get(
                f"{self._url}/api/v4/users",
                params={"username": username},
                timeout=10,
            )
            resp.raise_for_status()
            users = resp.json()
            if not users:
                return 0
            user_id = users[0]["id"]

            count = 0
            page = 1
            while page <= MAX_PAGES:
                ev_resp = self._http.get(
                    f"{self._url}/api/v4/users/{user_id}/events",
                    params={
                        "action": "pushed",
                        "created_after": since_iso,
                        "per_page": 100,
                        "page": page,
                    },
                    timeout=20,
                )
                ev_resp.raise_for_status()
                events = ev_resp.json()
                if not events:
                    break
                for ev in events:
                    count += ev.get("push_data", {}).get("commit_count", 0)
                if len(events) < 100:
                    break
                page += 1
            return count
        except Exception as e:
            logger.warning(f"GitLab commit count fetch failed for {username}: {e}")
            return 0

    def fetch_review_count(self, username: str, since_iso: str) -> int:
        try:
            count = 0
            page = 1
            while page <= MAX_PAGES:
                resp = self._http.get(
                    f"{self._url}/api/v4/merge_requests",
                    params={
                        "reviewer_username": username,
                        "created_after": since_iso,
                        "state": "all",
                        "scope": "all",
                        "per_page": 100,
                        "page": page,
                    },
                    timeout=20,
                )
                resp.raise_for_status()
                batch = resp.json()
                if not batch:
                    break
                count += len(batch)
                if len(batch) < 100:
                    break
                page += 1
            return count
        except Exception as e:
            logger.warning(f"GitLab review count fetch failed for {username}: {e}")
            return 0

    def close(self) -> None:
        self._http.close()
