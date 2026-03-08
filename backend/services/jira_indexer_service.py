"""
Jira Indexer Service

Indexes Jira issues to SQLite for semantic search, following the same
patterns as confluence_indexer_service.py:
- Incremental sync via issue updated timestamps
- Embeddings stored in the unified 'embeddings' table (source_type='jira')
- Content classification (bug, feature, tech_debt, incident, etc.)
- Rich metadata extraction

Usage:
    from backend.services.jira_indexer_service import get_jira_indexer

    indexer = get_jira_indexer(db)
    stats = indexer.sync(force_full=False)
"""

import re
import json
import hashlib
import logging
from datetime import datetime, timezone, timedelta
from typing import List, Dict, Any, Optional
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.orm import Session

from backend.services.unified_search_service import get_unified_search_service

logger = logging.getLogger(__name__)

# State file for tracking last sync time
_STATE_FILE = Path(__file__).parent.parent / "data" / "jira_sync_state.json"


# ===================== Issue Classification =====================

class IssueClassifier:
    """Classify Jira issues by type/category."""

    KEYWORD_PATTERNS = {
        "incident": [r'\bincident\b', r'\boutage\b', r'\bsev[\s-]?[012]\b', r'\bhotfix\b', r'\bseverity\b'],
        "tech_debt": [r'\btech[\s-]?debt\b', r'\brefactor\b', r'\bclean[\s-]?up\b', r'\bdeprecate\b', r'\blegacy\b'],
        "improvement": [r'\bimprove\b', r'\benhance\b', r'\boptimi[sz]e\b', r'\bperformance\b'],
    }

    ISSUETYPE_MAP = {
        "bug": "bug",
        "defect": "bug",
        "epic": "epic",
        "story": "feature",
        "new feature": "feature",
        "feature": "feature",
        "task": "task",
        "sub-task": "task",
        "subtask": "task",
        "incident": "incident",
        "improvement": "improvement",
        "spike": "tech_debt",
        "technical task": "tech_debt",
    }

    LABEL_MAP = {
        "tech-debt": "tech_debt",
        "techdebt": "tech_debt",
        "refactor": "tech_debt",
        "incident": "incident",
        "bug": "bug",
        "feature": "feature",
        "enhancement": "improvement",
    }

    @classmethod
    def classify(cls, issuetype: str, summary: str, labels: List[str]) -> str:
        # Check labels first
        for label in labels:
            label_lower = label.lower()
            for key, category in cls.LABEL_MAP.items():
                if key in label_lower:
                    return category

        # Check issuetype
        issuetype_lower = issuetype.lower()
        for key, category in cls.ISSUETYPE_MAP.items():
            if key == issuetype_lower:
                return category

        # Check summary keywords
        summary_lower = summary.lower()
        for category, patterns in cls.KEYWORD_PATTERNS.items():
            for pattern in patterns:
                if re.search(pattern, summary_lower):
                    return category

        return "task"


# ===================== Indexer =====================

class JiraIndexerService:
    """
    Indexes Jira issues into SQLite embeddings table for semantic search.

    - source_type = 'jira'
    - source_id = issue key (e.g., 'NS-123')
    - Incremental sync based on issue updated timestamp
    """

    TARGET_CHUNK_SIZE = 1500
    MAX_CHUNK_SIZE = 2000
    MIN_CHUNK_SIZE = 100

    FIELDS_TO_FETCH = [
        "summary", "description", "status", "assignee", "reporter",
        "priority", "issuetype", "project", "labels", "created",
        "updated", "resolution", "parent", "customfield_10014",  # Epic Link
        "customfield_10020",  # Sprint
        "comment",
    ]

    def __init__(self, db: Session):
        self.db = db
        self.search_service = get_unified_search_service(db)
        self._jira = None
        self._project_to_team = None
        self._sync_status: Dict[str, Any] = {
            "last_sync": None,
            "last_sync_type": None,
            "issues_indexed": 0,
            "issues_skipped": 0,
            "issues_failed": 0,
            "is_syncing": False,
        }

    @property
    def jira(self):
        """Lazy-init the Jira API service."""
        if self._jira is None:
            from backend.services.jira_api_service import JiraAPIService
            self._jira = JiraAPIService()
        return self._jira

    @property
    def project_to_team(self) -> Dict[str, str]:
        if self._project_to_team is None:
            from backend.services.jira_api_service import get_project_to_team
            self._project_to_team = get_project_to_team()
        return self._project_to_team

    @property
    def is_configured(self) -> bool:
        return self.jira.is_configured and bool(self.project_to_team)

    def get_status(self) -> Dict[str, Any]:
        """Get current sync status and stats."""
        try:
            issue_count = self.db.execute(
                text("SELECT COUNT(DISTINCT source_id) FROM embeddings WHERE source_type = 'jira'")
            ).scalar() or 0
            chunk_count = self.db.execute(
                text("SELECT COUNT(*) FROM embeddings WHERE source_type = 'jira'")
            ).scalar() or 0
        except Exception:
            issue_count = 0
            chunk_count = 0

        return {
            **self._sync_status,
            "issues_in_index": issue_count,
            "chunks_in_index": chunk_count,
            "configured_projects": list(self.project_to_team.keys()),
            "is_configured": self.is_configured,
        }

    def sync(self, force_full: bool = False) -> Dict[str, Any]:
        """
        Sync Jira issues to the embeddings index.

        Args:
            force_full: If True, re-index all issues regardless of update time.

        Returns:
            Stats dict with indexed/skipped/failed counts.
        """
        if self._sync_status["is_syncing"]:
            return {"error": "Sync already in progress"}

        if not self.is_configured:
            return {"error": "Jira not configured (missing credentials or project_to_team_map)"}

        self._sync_status["is_syncing"] = True
        start_time = datetime.now(timezone.utc)
        stats = {"indexed": 0, "skipped": 0, "failed": 0, "total_issues": 0}

        try:
            last_sync = None if force_full else self._get_last_sync_time()
            logger.info(f"Jira sync starting (full={force_full}, since={last_sync})")

            projects = list(self.project_to_team.keys())
            all_issues = self._fetch_issues(projects, last_sync)
            stats["total_issues"] = len(all_issues)
            logger.info(f"Fetched {len(all_issues)} issues from Jira")

            # Prepare and batch embed
            BATCH_SIZE = 100
            batch = []

            for i, issue in enumerate(all_issues):
                try:
                    if i > 0 and i % 200 == 0:
                        logger.info(f"  Progress: {i}/{len(all_issues)} (indexed={stats['indexed']}, skipped={stats['skipped']})")

                    issue_key = issue.get("key", "")
                    if not issue_key:
                        stats["failed"] += 1
                        continue

                    if not force_full and not self._needs_reindex(issue):
                        stats["skipped"] += 1
                        continue

                    prepared = self._prepare_issue(issue)
                    if prepared:
                        batch.append(prepared)
                    else:
                        stats["skipped"] += 1

                    if len(batch) >= BATCH_SIZE:
                        indexed = self._batch_embed_and_store(batch)
                        stats["indexed"] += indexed
                        stats["failed"] += len(batch) - indexed
                        batch = []

                except Exception as e:
                    logger.error(f"Error preparing issue {issue.get('key', '?')}: {e}")
                    stats["failed"] += 1

            # Process remaining batch
            if batch:
                indexed = self._batch_embed_and_store(batch)
                stats["indexed"] += indexed
                stats["failed"] += len(batch) - indexed

            self.db.commit()

            # Save sync time
            self._save_sync_time(start_time)

            duration = (datetime.now(timezone.utc) - start_time).total_seconds()
            stats["duration_seconds"] = round(duration, 2)
            stats["sync_type"] = "full" if force_full else "incremental"

            self._sync_status.update({
                "last_sync": start_time.isoformat(),
                "last_sync_type": stats["sync_type"],
                "issues_indexed": stats["indexed"],
                "issues_skipped": stats["skipped"],
                "issues_failed": stats["failed"],
                "is_syncing": False,
            })

            logger.info(f"Jira sync complete: {stats}")
            return stats

        except Exception as e:
            logger.error(f"Jira sync failed: {e}")
            self._sync_status["is_syncing"] = False
            return {"error": str(e), **stats}

    # ── Cached embedding matrix for fast search ──
    _embedding_cache: Optional[dict] = None
    _embedding_cache_count: int = 0

    def _load_embedding_matrix(self, force: bool = False):
        """Load all jira embeddings into a numpy matrix (cached)."""
        import numpy as np

        row_count = self.db.execute(
            text("SELECT COUNT(*) FROM embeddings WHERE source_type = 'jira'")
        ).scalar() or 0

        if not force and self._embedding_cache and self._embedding_cache_count == row_count:
            return self._embedding_cache

        logger.info(f"Loading {row_count} jira embeddings into matrix...")
        rows = self.db.execute(
            text("""
                SELECT source_id, chunk_index, chunk_text, embedding, chunk_metadata
                FROM embeddings WHERE source_type = 'jira'
            """)
        ).fetchall()

        if not rows:
            self._embedding_cache = None
            self._embedding_cache_count = 0
            return None

        valid_rows = []
        vectors = []
        for row in rows:
            try:
                vec = json.loads(row.embedding)
                vectors.append(vec)
                valid_rows.append(row)
            except Exception:
                continue

        if not vectors:
            return None

        matrix = np.array(vectors, dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1
        matrix_normed = matrix / norms

        metadata = []
        for row in valid_rows:
            meta = json.loads(row.chunk_metadata) if row.chunk_metadata else {}
            metadata.append({
                "source_id": row.source_id,
                "chunk_text": row.chunk_text,
                "issue_key": meta.get("issue_key", row.source_id),
                "project_key": meta.get("project_key", ""),
                "team": meta.get("team", ""),
                "issuetype": meta.get("issuetype", ""),
                "status": meta.get("status", ""),
                "priority": meta.get("priority", ""),
                "assignee": meta.get("assignee", ""),
                "summary": meta.get("summary", ""),
                "category": meta.get("category", ""),
                "url": meta.get("url", ""),
                "labels": meta.get("labels", []),
            })

        cache = {"matrix": matrix_normed, "metadata": metadata}
        type(self)._embedding_cache = cache
        type(self)._embedding_cache_count = row_count
        logger.info(f"Jira embedding matrix loaded: {matrix_normed.shape}")
        return cache

    def search(
        self,
        query: str,
        project: Optional[str] = None,
        issuetype: Optional[str] = None,
        limit: int = 10,
    ) -> List[Dict[str, Any]]:
        """Semantic search across indexed Jira issues."""
        import numpy as np

        embedding = self.search_service._get_embedding(query)
        if embedding is None:
            return []

        cache = self._load_embedding_matrix()
        if not cache:
            return []

        matrix = cache["matrix"]
        metadata = cache["metadata"]

        query_vec = np.array(embedding, dtype=np.float32)
        query_norm = np.linalg.norm(query_vec)
        if query_norm == 0:
            return []
        query_normed = query_vec / query_norm

        scores = matrix @ query_normed

        # Apply filters
        if project:
            mask = np.array([m["project_key"].upper() == project.upper() for m in metadata])
            scores = np.where(mask, scores, -1)
        if issuetype:
            mask = np.array([m["issuetype"].lower() == issuetype.lower() for m in metadata])
            scores = np.where(mask, scores, -1)

        top_k = min(limit * 5, len(scores))
        top_indices = np.argpartition(scores, -top_k)[-top_k:]
        top_indices = top_indices[np.argsort(scores[top_indices])[::-1]]

        seen_ids = set()
        results = []
        for idx in top_indices:
            meta = metadata[idx]
            if meta["source_id"] in seen_ids:
                continue
            seen_ids.add(meta["source_id"])

            results.append({
                "issue_key": meta["issue_key"],
                "summary": meta["summary"],
                "project_key": meta["project_key"],
                "team": meta["team"],
                "issuetype": meta["issuetype"],
                "status": meta["status"],
                "priority": meta["priority"],
                "assignee": meta["assignee"],
                "category": meta["category"],
                "excerpt": meta["chunk_text"][:300] if meta["chunk_text"] else "",
                "url": meta["url"],
                "score": round(float(scores[idx]), 4),
                "labels": meta["labels"],
            })

            if len(results) >= limit:
                break

        return results

    def clear_index(self) -> bool:
        """Clear all Jira embeddings."""
        try:
            self.db.execute(text("DELETE FROM embeddings WHERE source_type = 'jira'"))
            self.db.commit()
            type(self)._embedding_cache = None
            type(self)._embedding_cache_count = 0
            logger.info("Cleared Jira index")
            return True
        except Exception as e:
            logger.error(f"Error clearing Jira index: {e}")
            return False

    # ===================== Internal =====================

    def _fetch_issues(self, projects: List[str], since: Optional[datetime] = None) -> List[Dict[str, Any]]:
        """Fetch issues from Jira using JQL."""
        quoted_projects = ', '.join(f'"{p}"' for p in projects)
        project_clause = f"project in ({quoted_projects})"

        if since:
            # Incremental: recently updated issues
            since_str = since.strftime("%Y-%m-%d %H:%M")
            jql = f'{project_clause} AND updated >= "{since_str}" ORDER BY updated DESC'
        else:
            # Full sync: all open + recently resolved (last 90 days)
            ninety_days_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            jql = (
                f'{project_clause} AND '
                f'(status not in (Done, Closed, Cancelled) OR '
                f'(status in (Done, Closed, Cancelled) AND resolved >= "{ninety_days_ago}"))'
                f' ORDER BY updated DESC'
            )

        logger.info(f"Jira JQL: {jql}")
        return self.jira.search_all_issues(jql, fields=self.FIELDS_TO_FETCH, max_total=5000)

    def _get_last_sync_time(self) -> Optional[datetime]:
        """Get last sync time from state file."""
        try:
            if _STATE_FILE.exists():
                state = json.loads(_STATE_FILE.read_text())
                ts = state.get("last_sync")
                if ts:
                    return datetime.fromisoformat(ts)
        except Exception:
            pass
        return None

    def _save_sync_time(self, dt: datetime):
        """Save sync time to state file."""
        try:
            _STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _STATE_FILE.write_text(json.dumps({"last_sync": dt.isoformat()}))
        except Exception as e:
            logger.warning(f"Could not save sync state: {e}")

    def _needs_reindex(self, issue: Dict[str, Any]) -> bool:
        """Check if an issue needs re-indexing by comparing content hash."""
        issue_key = issue.get("key", "")
        content_hash = self._compute_issue_hash(issue)

        try:
            row = self.db.execute(
                text("""
                    SELECT chunk_metadata FROM embeddings
                    WHERE source_type = 'jira' AND source_id = :key
                    LIMIT 1
                """),
                {"key": issue_key},
            ).fetchone()

            if not row:
                return True

            meta = json.loads(row.chunk_metadata) if row.chunk_metadata else {}
            return meta.get("content_hash") != content_hash
        except Exception:
            return True

    def _compute_issue_hash(self, issue: Dict[str, Any]) -> str:
        """Compute hash of issue content for change detection."""
        fields = issue.get("fields", {})
        parts = [
            issue.get("key", ""),
            fields.get("summary", ""),
            str(fields.get("updated", "")),
            self._extract_description(fields),
            str(fields.get("status", {}).get("name", "")),
            str(fields.get("assignee", {}).get("displayName", "") if fields.get("assignee") else ""),
        ]
        return hashlib.md5("|".join(parts).encode()).hexdigest()

    def _extract_description(self, fields: Dict[str, Any]) -> str:
        """Extract description text from ADF or plain text."""
        desc = fields.get("description")
        if not desc:
            return ""
        if isinstance(desc, str):
            return desc
        # ADF (Atlassian Document Format) — extract text nodes
        if isinstance(desc, dict):
            return self._adf_to_text(desc)
        return str(desc)

    def _adf_to_text(self, node: Any) -> str:
        """Recursively extract text from ADF JSON."""
        if isinstance(node, str):
            return node
        if not isinstance(node, dict):
            return ""
        text_parts = []
        if node.get("type") == "text":
            text_parts.append(node.get("text", ""))
        for child in node.get("content", []):
            text_parts.append(self._adf_to_text(child))
        return " ".join(text_parts).strip()

    def _extract_comments(self, fields: Dict[str, Any], max_comments: int = 5) -> List[Dict[str, str]]:
        """Extract latest comments from issue fields."""
        comment_field = fields.get("comment", {})
        if not comment_field:
            return []

        comments_list = comment_field.get("comments", [])
        # Take latest N
        recent = comments_list[-max_comments:] if len(comments_list) > max_comments else comments_list

        result = []
        for c in recent:
            author = c.get("author", {}).get("displayName", "Unknown")
            created = c.get("created", "")[:10]
            body = c.get("body", "")
            if isinstance(body, dict):
                body = self._adf_to_text(body)
            if isinstance(body, str) and len(body) > 500:
                body = body[:500] + "..."
            result.append({"author": author, "date": created, "body": body})
        return result

    def _extract_sprint(self, fields: Dict[str, Any]) -> str:
        """Extract active sprint name."""
        sprint_field = fields.get("customfield_10020")
        if not sprint_field:
            return ""
        if isinstance(sprint_field, list):
            # Find active sprint or use latest
            for s in reversed(sprint_field):
                if isinstance(s, dict):
                    if s.get("state") == "active":
                        return s.get("name", "")
            # Fallback to last sprint
            if sprint_field and isinstance(sprint_field[-1], dict):
                return sprint_field[-1].get("name", "")
        return ""

    def _prepare_issue(self, issue: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        """Prepare an issue for batch indexing."""
        try:
            issue_key = issue.get("key", "")
            fields = issue.get("fields", {})

            summary = fields.get("summary", "")
            description = self._extract_description(fields)
            comments = self._extract_comments(fields)

            project_obj = fields.get("project", {})
            project_key = project_obj.get("key", issue_key.split("-")[0] if "-" in issue_key else "")
            team = self.project_to_team.get(project_key, project_key)

            status = fields.get("status", {}).get("name", "Unknown") if fields.get("status") else "Unknown"
            priority = fields.get("priority", {}).get("name", "Medium") if fields.get("priority") else "Medium"
            issuetype = fields.get("issuetype", {}).get("name", "Unknown") if fields.get("issuetype") else "Unknown"
            assignee = fields.get("assignee", {}).get("displayName", "Unassigned") if fields.get("assignee") else "Unassigned"
            reporter = fields.get("reporter", {}).get("displayName", "Unknown") if fields.get("reporter") else "Unknown"

            labels = fields.get("labels", []) or []
            resolution = fields.get("resolution", {}).get("name", "") if fields.get("resolution") else ""
            created = fields.get("created", "")[:10]
            updated = fields.get("updated", "")[:10]

            # Parent / epic link
            parent_key = ""
            parent_obj = fields.get("parent")
            if parent_obj:
                parent_key = parent_obj.get("key", "")
            if not parent_key:
                epic_link = fields.get("customfield_10014")
                if isinstance(epic_link, str):
                    parent_key = epic_link

            sprint = self._extract_sprint(fields)
            category = IssueClassifier.classify(issuetype, summary, labels)
            content_hash = self._compute_issue_hash(issue)
            url = f"{self.jira.jira_url}/browse/{issue_key}"

            # Build embedding text
            embed_lines = [
                f"Jira Issue: {issue_key} — {summary}",
                f"Project: {project_key} ({team})",
                f"Type: {issuetype} | Status: {status} | Priority: {priority}",
                f"Assignee: {assignee} | Reporter: {reporter}",
            ]
            if labels:
                embed_lines.append(f"Labels: {', '.join(labels)}")
            if sprint:
                embed_lines.append(f"Sprint: {sprint}")
            if parent_key:
                embed_lines.append(f"Parent: {parent_key}")

            embed_lines.append("")
            if description:
                embed_lines.append(description)

            if comments:
                embed_lines.append("")
                embed_lines.append("Recent Comments:")
                for c in comments:
                    embed_lines.append(f"{c['author']} ({c['date']}): {c['body']}")

            full_text = "\n".join(embed_lines)

            # Chunk if necessary
            chunks = self._chunk_text(full_text)

            base_meta = {
                "issue_key": issue_key,
                "summary": summary,
                "project_key": project_key,
                "team": team,
                "issuetype": issuetype,
                "status": status,
                "priority": priority,
                "assignee": assignee,
                "reporter": reporter,
                "labels": labels,
                "resolution": resolution,
                "created": created,
                "updated": updated,
                "parent_key": parent_key,
                "sprint": sprint,
                "category": category,
                "url": url,
                "content_hash": content_hash,
            }

            embed_texts = []
            chunk_records = []
            for chunk_idx, chunk_text in enumerate(chunks):
                embed_texts.append(chunk_text[:8000])
                chunk_records.append({
                    "issue_key": issue_key,
                    "chunk_idx": chunk_idx,
                    "chunk_text": chunk_text[:2000],
                    "chunk_meta": base_meta,
                })

            return {
                "issue_key": issue_key,
                "summary": summary,
                "category": category,
                "embed_texts": embed_texts,
                "chunk_records": chunk_records,
                "num_chunks": len(chunks),
            }
        except Exception as e:
            logger.error(f"Error preparing issue {issue.get('key', '?')}: {e}")
            return None

    def _chunk_text(self, text: str) -> List[str]:
        """Split text into chunks if it exceeds target size."""
        if len(text) <= self.TARGET_CHUNK_SIZE:
            return [text]

        chunks = []
        paragraphs = re.split(r'\n\n+', text)
        current = ""

        for para in paragraphs:
            para = para.strip()
            if not para:
                continue

            if current and len(current) + len(para) + 2 > self.TARGET_CHUNK_SIZE:
                chunks.append(current)
                current = para
            elif not current:
                current = para
            else:
                current = f"{current}\n\n{para}"

            while len(current) > self.TARGET_CHUNK_SIZE:
                split_pos = current[:self.TARGET_CHUNK_SIZE].rfind('. ')
                if split_pos < self.MIN_CHUNK_SIZE:
                    split_pos = current[:self.TARGET_CHUNK_SIZE].rfind(' ')
                if split_pos < self.MIN_CHUNK_SIZE:
                    split_pos = self.TARGET_CHUNK_SIZE
                chunks.append(current[:split_pos + 1].strip())
                current = current[split_pos + 1:].strip()

        if current and len(current) >= self.MIN_CHUNK_SIZE:
            chunks.append(current)
        elif current and chunks:
            chunks[-1] = f"{chunks[-1]}\n\n{current}"
        elif current:
            chunks.append(current)

        return chunks if chunks else [text]

    def _batch_embed_and_store(self, prepared_issues: List[Dict[str, Any]]) -> int:
        """Batch-embed and store chunks for multiple issues. Returns count of issues indexed."""
        import numpy as np

        all_texts = []
        text_map = []
        for issue_idx, pp in enumerate(prepared_issues):
            for cr_idx, embed_text in enumerate(pp["embed_texts"]):
                all_texts.append(embed_text)
                text_map.append((issue_idx, cr_idx))

        if not all_texts:
            return 0

        BATCH_SIZE = 2000
        all_embeddings = [None] * len(all_texts)

        for batch_start in range(0, len(all_texts), BATCH_SIZE):
            batch_end = min(batch_start + BATCH_SIZE, len(all_texts))
            batch_texts = all_texts[batch_start:batch_end]
            try:
                response = self.search_service.embedding_plugin.embed(batch_texts)
                for i, emb in enumerate(response.embeddings):
                    all_embeddings[batch_start + i] = np.array(emb)
            except Exception as e:
                logger.error(f"Batch embedding failed (batch {batch_start}-{batch_end}): {e}")
                for i, txt in enumerate(batch_texts):
                    try:
                        emb = self.search_service._get_embedding(txt)
                        all_embeddings[batch_start + i] = emb
                    except Exception:
                        pass

        indexed = 0
        now = datetime.now(timezone.utc)
        for issue_idx, pp in enumerate(prepared_issues):
            try:
                self.db.execute(
                    text("DELETE FROM embeddings WHERE source_type = 'jira' AND source_id = :key"),
                    {"key": pp["issue_key"]},
                )

                stored = 0
                for cr_idx, cr in enumerate(pp["chunk_records"]):
                    global_idx = None
                    for gi, (pi, ci) in enumerate(text_map):
                        if pi == issue_idx and ci == cr_idx:
                            global_idx = gi
                            break

                    if global_idx is not None and all_embeddings[global_idx] is not None:
                        self.db.execute(
                            text("""
                                INSERT INTO embeddings
                                (source_type, source_id, chunk_index, chunk_text, embedding, embedding_model, chunk_metadata, created_at)
                                VALUES (:source_type, :source_id, :chunk_index, :chunk_text, :embedding, :model, :chunk_metadata, :created_at)
                            """),
                            {
                                "source_type": "jira",
                                "source_id": cr["issue_key"],
                                "chunk_index": cr["chunk_idx"],
                                "chunk_text": cr["chunk_text"],
                                "embedding": json.dumps(all_embeddings[global_idx].tolist()),
                                "model": self.search_service.embedding_model,
                                "chunk_metadata": json.dumps(cr["chunk_meta"]),
                                "created_at": now,
                            },
                        )
                        stored += 1

                if stored > 0:
                    indexed += 1
                    logger.debug(f"Indexed issue {pp['issue_key']}: {pp['summary'][:60]} ({stored} chunks, cat={pp['category']})")

                if indexed % 50 == 0:
                    self.db.commit()

            except Exception as e:
                logger.error(f"Error storing issue {pp['issue_key']}: {e}")

        self.db.commit()
        return indexed


# ===================== Singleton =====================

_indexer: Optional[JiraIndexerService] = None


def get_jira_indexer(db: Session) -> JiraIndexerService:
    """Get or create the Jira indexer instance."""
    global _indexer
    if _indexer is None:
        _indexer = JiraIndexerService(db)
    else:
        _indexer.db = db
    return _indexer
