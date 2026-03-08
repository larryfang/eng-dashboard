"""
Repo Scanner Service

Scans GitLab repositories to collect metadata for analysis.
Uses a hybrid approach:
1. GitLab API - Discover repos and get basic metadata
2. Local scan (optional) - Deep analysis if repos are cloned locally

This replaces gitlab-analysis/scripts/scan_repos.py.

Usage:
    from backend.services.gitlab_intelligence import get_repo_scanner

    scanner = get_repo_scanner()
    results = scanner.scan_all_teams()
"""

import json
import logging
import os
import re
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests
from sqlalchemy.orm import Session

from backend.database import GitLabRepo, SessionLocal
from backend.config.gitlab_teams import (
    TEAM_GITLAB_PATHS,
    TEAM_DISPLAY_NAMES,
    normalize_team_name,
)
from backend.services.domain_credentials import get_gitlab_settings

logger = logging.getLogger(__name__)

REQUEST_TIMEOUT = 60

# Local clone base path (optional - for deep scanning)
LOCAL_CLONE_BASE = Path.home() / "Projects" / "gitlab"

# Language detection by extension
LANGUAGE_MAP = {
    ".py": "Python",
    ".js": "JavaScript",
    ".ts": "TypeScript",
    ".tsx": "TypeScript",
    ".jsx": "JavaScript",
    ".java": "Java",
    ".kt": "Kotlin",
    ".go": "Go",
    ".rs": "Rust",
    ".rb": "Ruby",
    ".php": "PHP",
    ".cs": "C#",
    ".scala": "Scala",
    ".swift": "Swift",
    ".c": "C",
    ".cpp": "C++",
    ".sql": "SQL",
    ".sh": "Shell",
    ".yml": "YAML",
    ".yaml": "YAML",
    ".json": "JSON",
    ".tf": "Terraform",
    ".vue": "Vue",
}

# Framework detection patterns
FRAMEWORK_PATTERNS = {
    # Python
    "Django": ["django", "DJANGO_SETTINGS_MODULE"],
    "Flask": ["flask", "Flask(__name__)"],
    "FastAPI": ["fastapi", "FastAPI()"],
    "Pytest": ["pytest", "def test_"],
    # JavaScript/TypeScript
    "React": ["react", "from 'react'", 'from "react"'],
    "Vue": ["vue", "createApp", ".vue"],
    "Angular": ["@angular", "angular.json"],
    "Next.js": ["next", "next.config"],
    "Express": ["express", "app.listen"],
    "NestJS": ["@nestjs", "NestFactory"],
    "Jest": ["jest", "describe(", "it("],
    "Playwright": ["playwright", "@playwright"],
    # Java/Kotlin
    "Spring Boot": ["spring-boot", "SpringApplication"],
    "Gradle": ["build.gradle"],
    "Maven": ["pom.xml"],
    # Infrastructure
    "Terraform": [".tf", "terraform {"],
    "Docker": ["Dockerfile", "docker-compose"],
    "Kubernetes": ["kubernetes", "k8s"],
    "Serverless": ["serverless.yml", "serverless.yaml"],
    "AWS CDK": ["aws-cdk-lib", "@aws-cdk", "from aws_cdk"],
}


class RepoScannerError(Exception):
    """Raised when repo scanning fails."""
    pass


class RepoScanner:
    """
    Scans GitLab repositories for metadata.

    Supports two modes:
    1. API-only: Fetches metadata from GitLab GraphQL API
    2. Hybrid: API + local file system scanning for cloned repos
    """

    def __init__(
        self,
        db: Optional[Session] = None,
        gitlab_token: Optional[str] = None,
        gitlab_url: Optional[str] = None,
        local_clone_base: Optional[Path] = None,
    ):
        self._db = db
        settings = get_gitlab_settings()
        self.gitlab_url = (gitlab_url or settings["url"] or "https://gitlab.com").rstrip("/")
        self.graphql_url = f"{self.gitlab_url}/api/graphql"
        self.gitlab_token = gitlab_token or settings["token"]
        self.local_clone_base = local_clone_base or LOCAL_CLONE_BASE
        self._stats = {
            "repos_scanned": 0,
            "repos_created": 0,
            "repos_updated": 0,
            "errors": [],
        }

    def _get_db(self) -> Session:
        """Get database session."""
        if self._db:
            return self._db
        return SessionLocal()

    def _close_db(self, db: Session):
        """Close database session if we created it."""
        if db != self._db:
            db.close()

    def _graphql_query(self, query: str, variables: Optional[dict] = None) -> dict:
        """Execute a GraphQL query against GitLab."""
        if not self.gitlab_token:
            raise RepoScannerError("GitLab credentials are not configured for the active domain")

        headers = {
            "Authorization": f"Bearer {self.gitlab_token}",
            "Content-Type": "application/json",
        }

        try:
            response = requests.post(
                self.graphql_url,
                json={"query": query, "variables": variables or {}},
                headers=headers,
                timeout=REQUEST_TIMEOUT,
            )
            response.raise_for_status()
            result = response.json()

            if "errors" in result:
                logger.warning(f"GraphQL errors: {result['errors']}")

            return result.get("data", {})

        except requests.exceptions.Timeout:
            raise RepoScannerError(f"GitLab API timeout after {REQUEST_TIMEOUT}s")
        except requests.exceptions.RequestException as e:
            raise RepoScannerError(f"GitLab API error: {e}")

    def discover_repos(self, group_path: str) -> list[dict]:
        """
        Discover all repositories in a GitLab group.

        Args:
            group_path: GitLab group path

        Returns:
            List of project dicts with basic metadata
        """
        query = """
        query($fullPath: ID!, $after: String) {
          group(fullPath: $fullPath) {
            projects(first: 100, after: $after, includeSubgroups: true) {
              pageInfo { hasNextPage endCursor }
              nodes {
                id
                name
                fullPath
                description
                webUrl
                visibility
                archived
                createdAt
                lastActivityAt
                statistics {
                  repositorySize
                  commitCount
                }
                repository {
                  rootRef
                  exists
                }
                languages {
                  name
                  share
                }
              }
            }
          }
        }
        """

        all_projects = []
        after = None

        while True:
            data = self._graphql_query(query, {"fullPath": group_path, "after": after})
            group = data.get("group")

            if not group:
                logger.warning(f"Group not found: {group_path}")
                break

            projects = group.get("projects", {})

            for project in projects.get("nodes", []):
                all_projects.append({
                    "id": project.get("id"),
                    "name": project.get("name"),
                    "full_path": project.get("fullPath"),
                    "description": project.get("description"),
                    "web_url": project.get("webUrl"),
                    "visibility": project.get("visibility"),
                    "archived": project.get("archived", False),
                    "created_at": project.get("createdAt"),
                    "last_activity_at": project.get("lastActivityAt"),
                    "repository_size": project.get("statistics", {}).get("repositorySize"),
                    "commit_count": project.get("statistics", {}).get("commitCount"),
                    "default_branch": project.get("repository", {}).get("rootRef"),
                    "repo_exists": project.get("repository", {}).get("exists", True),
                    "languages": project.get("languages", []),
                })

            page_info = projects.get("pageInfo", {})
            if not page_info.get("hasNextPage"):
                break
            after = page_info.get("endCursor")

        return all_projects

    def _get_primary_language(self, languages: list[dict]) -> Optional[str]:
        """Get primary language from GitLab languages response."""
        if not languages:
            return None
        # Sort by share and return highest
        sorted_langs = sorted(languages, key=lambda x: x.get("share", 0), reverse=True)
        return sorted_langs[0].get("name") if sorted_langs else None

    def _get_local_clone_path(self, team: str, repo_name: str) -> Optional[Path]:
        """Get path to local clone if it exists."""
        # Try common patterns
        patterns = [
            self.local_clone_base / team / repo_name,
            self.local_clone_base / f"{team}-{repo_name}",
            Path.home() / "Projects" / team / repo_name,
        ]

        for path in patterns:
            if path.is_dir() and (path / ".git").exists():
                return path

        return None

    def _scan_local_files(self, repo_path: Path) -> dict:
        """
        Scan a locally cloned repository for detailed metadata.

        Args:
            repo_path: Path to the cloned repository

        Returns:
            Dict with file counts, languages, frameworks, tests, CI info
        """
        result = {
            "total_files": 0,
            "total_lines": 0,
            "code_lines": 0,
            "has_tests": False,
            "has_ci": False,
            "has_docker": False,
            "has_readme": False,
            "has_api_docs": False,
            "doc_score": 0,
            "languages_detail": {},
            "frameworks": [],
            "test_frameworks": [],
            "ci_platform": None,
        }

        skip_dirs = {
            "node_modules", "vendor", "venv", ".venv", "__pycache__",
            "dist", "build", "target", ".git", ".idea", ".vscode"
        }

        code_extensions = {
            ".py", ".js", ".ts", ".tsx", ".jsx", ".java", ".kt",
            ".go", ".rs", ".rb", ".php", ".cs", ".scala"
        }

        # Walk directory
        languages = defaultdict(int)

        try:
            for root, dirs, files in os.walk(repo_path):
                dirs[:] = [d for d in dirs if d not in skip_dirs]

                for f in files:
                    fpath = Path(root) / f
                    ext = fpath.suffix.lower()

                    if ext in LANGUAGE_MAP:
                        languages[LANGUAGE_MAP[ext]] += 1

                    if ext in code_extensions:
                        result["total_files"] += 1
                        try:
                            with open(fpath, errors="ignore") as fp:
                                lines = sum(1 for _ in fp)
                                result["total_lines"] += lines
                                result["code_lines"] += lines
                        except Exception:
                            pass

            result["languages_detail"] = dict(languages)

        except Exception as e:
            logger.warning(f"Error scanning {repo_path}: {e}")

        # Check for tests
        test_patterns = ["test", "spec", "__tests__", "tests"]
        for pattern in test_patterns:
            if (repo_path / pattern).is_dir():
                result["has_tests"] = True
                break

        # Check for CI
        ci_files = {
            ".gitlab-ci.yml": "GitLab CI",
            ".buildkite": "Buildkite",
            ".github/workflows": "GitHub Actions",
        }
        for ci_file, platform in ci_files.items():
            ci_path = repo_path / ci_file
            if ci_path.exists():
                result["has_ci"] = True
                result["ci_platform"] = platform
                break

        # Check for Docker
        if (repo_path / "Dockerfile").exists() or (repo_path / "docker-compose.yml").exists():
            result["has_docker"] = True

        # Check documentation
        for readme in ["README.md", "README.rst", "README.txt", "README"]:
            if (repo_path / readme).exists():
                result["has_readme"] = True
                break

        # API docs
        api_doc_files = ["openapi.yaml", "openapi.json", "swagger.yaml", "swagger.json"]
        result["has_api_docs"] = any((repo_path / f).exists() for f in api_doc_files)

        # Calculate doc score
        score = 0
        if result["has_readme"]:
            score += 40
        if result["has_api_docs"]:
            score += 20
        if (repo_path / "docs").is_dir():
            score += 20
        if (repo_path / "CHANGELOG.md").exists():
            score += 10
        if (repo_path / "LICENSE").exists():
            score += 10
        result["doc_score"] = score

        # Detect frameworks
        result["frameworks"] = self._detect_frameworks(repo_path)

        return result

    def _detect_frameworks(self, repo_path: Path) -> list[str]:
        """Detect frameworks used in a repository."""
        detected = set()

        # Check common config files
        files_to_check = [
            "package.json", "requirements.txt", "pyproject.toml",
            "build.gradle", "pom.xml", "go.mod", "Cargo.toml",
            "serverless.yml", "cdk.json", "angular.json"
        ]

        content_cache = {}
        for fname in files_to_check:
            fpath = repo_path / fname
            if fpath.exists():
                try:
                    content_cache[fname] = fpath.read_text()[:10000]  # First 10KB
                except Exception:
                    pass

        all_content = "\n".join(content_cache.values()).lower()

        for framework, patterns in FRAMEWORK_PATTERNS.items():
            for pattern in patterns:
                if pattern.lower() in all_content:
                    detected.add(framework)
                    break

        return list(detected)

    def _detect_packages(self, repo_path: Path) -> list[dict]:
        """
        Detect packages/dependencies from manifest files.

        Returns list of package dicts with: package, language, version, is_dev, source_file
        """
        packages = []

        # Python: requirements.txt
        req_file = repo_path / "requirements.txt"
        if req_file.exists():
            try:
                content = req_file.read_text()
                for line in content.splitlines():
                    line = line.strip()
                    if not line or line.startswith("#") or line.startswith("-"):
                        continue
                    # Parse package==version or package>=version
                    import re
                    match = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*([<>=!~]+\s*[\d\.]+)?", line)
                    if match:
                        packages.append({
                            "package": match.group(1).lower(),
                            "language": "Python",
                            "version": match.group(2).strip() if match.group(2) else None,
                            "is_dev": False,
                            "source_file": "requirements.txt",
                        })
            except Exception:
                pass

        # Python: dev requirements
        for dev_file in ["requirements-dev.txt", "requirements_dev.txt", "dev-requirements.txt"]:
            dev_req = repo_path / dev_file
            if dev_req.exists():
                try:
                    content = dev_req.read_text()
                    for line in content.splitlines():
                        line = line.strip()
                        if not line or line.startswith("#") or line.startswith("-"):
                            continue
                        import re
                        match = re.match(r"^([a-zA-Z0-9_\-\.]+)\s*([<>=!~]+\s*[\d\.]+)?", line)
                        if match:
                            packages.append({
                                "package": match.group(1).lower(),
                                "language": "Python",
                                "version": match.group(2).strip() if match.group(2) else None,
                                "is_dev": True,
                                "source_file": dev_file,
                            })
                except Exception:
                    pass

        # JavaScript: package.json
        pkg_json = repo_path / "package.json"
        if pkg_json.exists():
            try:
                import json
                data = json.loads(pkg_json.read_text())

                # Regular dependencies
                for pkg, version in data.get("dependencies", {}).items():
                    packages.append({
                        "package": pkg,
                        "language": "JavaScript",
                        "version": version,
                        "is_dev": False,
                        "source_file": "package.json",
                    })

                # Dev dependencies
                for pkg, version in data.get("devDependencies", {}).items():
                    packages.append({
                        "package": pkg,
                        "language": "JavaScript",
                        "version": version,
                        "is_dev": True,
                        "source_file": "package.json",
                    })
            except Exception:
                pass

        # Java: pom.xml (basic parsing)
        pom_file = repo_path / "pom.xml"
        if pom_file.exists():
            try:
                import re
                content = pom_file.read_text()
                # Find <dependency> blocks
                deps = re.findall(
                    r"<dependency>\s*<groupId>([^<]+)</groupId>\s*<artifactId>([^<]+)</artifactId>(?:\s*<version>([^<]+)</version>)?",
                    content,
                    re.DOTALL
                )
                for group_id, artifact_id, version in deps:
                    packages.append({
                        "package": f"{group_id}:{artifact_id}",
                        "language": "Java",
                        "version": version if version else None,
                        "is_dev": False,
                        "source_file": "pom.xml",
                    })
            except Exception:
                pass

        return packages

    def _detect_versions(self, repo_path: Path) -> list[dict]:
        """
        Detect language and framework versions.

        Returns list of version dicts with: type, name, current_version, source_file
        """
        versions = []

        # Python version from .python-version
        py_version_file = repo_path / ".python-version"
        if py_version_file.exists():
            try:
                version = py_version_file.read_text().strip()
                if version:
                    versions.append({
                        "type": "language",
                        "name": "Python",
                        "current_version": version,
                        "source_file": ".python-version",
                    })
            except Exception:
                pass

        # Node version from .nvmrc or .node-version
        for nvm_file in [".nvmrc", ".node-version"]:
            node_file = repo_path / nvm_file
            if node_file.exists():
                try:
                    version = node_file.read_text().strip().lstrip("v")
                    if version:
                        versions.append({
                            "type": "language",
                            "name": "Node.js",
                            "current_version": version,
                            "source_file": nvm_file,
                        })
                        break
                except Exception:
                    pass

        # Node version from package.json engines
        pkg_json = repo_path / "package.json"
        if pkg_json.exists():
            try:
                import json
                data = json.loads(pkg_json.read_text())
                engines = data.get("engines", {})
                if "node" in engines:
                    version = engines["node"].lstrip(">=^~v").split()[0]
                    # Only add if we don't already have it from .nvmrc
                    if not any(v["name"] == "Node.js" for v in versions):
                        versions.append({
                            "type": "language",
                            "name": "Node.js",
                            "current_version": version,
                            "source_file": "package.json",
                        })
            except Exception:
                pass

        # Java version from pom.xml
        pom_file = repo_path / "pom.xml"
        if pom_file.exists():
            try:
                import re
                content = pom_file.read_text()
                # Look for <java.version> or <maven.compiler.source>
                java_match = re.search(r"<java\.version>(\d+)</java\.version>", content)
                if java_match:
                    versions.append({
                        "type": "language",
                        "name": "Java",
                        "current_version": java_match.group(1),
                        "source_file": "pom.xml",
                    })
                else:
                    compiler_match = re.search(r"<maven\.compiler\.source>(\d+)</maven\.compiler\.source>", content)
                    if compiler_match:
                        versions.append({
                            "type": "language",
                            "name": "Java",
                            "current_version": compiler_match.group(1),
                            "source_file": "pom.xml",
                        })

                # Spring Boot version
                spring_match = re.search(r"<spring-boot\.version>([^<]+)</spring-boot\.version>", content)
                if not spring_match:
                    spring_match = re.search(r"<version>([^<]+)</version>\s*<!--.*spring.*boot", content, re.I)
                if spring_match:
                    versions.append({
                        "type": "framework",
                        "name": "Spring Boot",
                        "current_version": spring_match.group(1),
                        "source_file": "pom.xml",
                    })
            except Exception:
                pass

        return versions

    def _save_packages(self, db: Session, repo_id: str, packages: list[dict]):
        """Save detected packages to database."""
        from backend.database import GitLabPackage

        now = datetime.now(timezone.utc)

        for pkg_data in packages:
            try:
                # Upsert
                existing = db.query(GitLabPackage).filter(
                    GitLabPackage.repo_id == repo_id,
                    GitLabPackage.package == pkg_data["package"],
                ).first()

                if existing:
                    existing.language = pkg_data["language"]
                    existing.version = pkg_data.get("version")
                    existing.is_dev = pkg_data.get("is_dev", False)
                    existing.source_file = pkg_data.get("source_file")
                    existing.synced_at = now
                else:
                    new_pkg = GitLabPackage(
                        repo_id=repo_id,
                        package=pkg_data["package"],
                        language=pkg_data["language"],
                        version=pkg_data.get("version"),
                        is_dev=pkg_data.get("is_dev", False),
                        source_file=pkg_data.get("source_file"),
                        synced_at=now,
                    )
                    db.add(new_pkg)
            except Exception as e:
                logger.warning(f"Error saving package {pkg_data.get('package')} for {repo_id}: {e}")

    def _save_versions(self, db: Session, repo_id: str, team: str, versions: list[dict]):
        """Save detected versions to database."""
        from backend.database import GitLabVersion
        from .version_service import is_eol, get_eol_date

        now = datetime.now(timezone.utc)

        for v_data in versions:
            try:
                name = v_data["name"]
                version = v_data["current_version"]
                eol_flag, eol_date = is_eol(name, version)

                # Determine risk level
                if eol_flag:
                    risk_level = "critical"
                elif eol_date:
                    from datetime import date, timedelta
                    days_to_eol = (eol_date - date.today()).days
                    if days_to_eol < 90:
                        risk_level = "high"
                    elif days_to_eol < 365:
                        risk_level = "medium"
                    else:
                        risk_level = "low"
                else:
                    risk_level = "low"

                # Upsert
                existing = db.query(GitLabVersion).filter(
                    GitLabVersion.repo_id == repo_id,
                    GitLabVersion.type == v_data["type"],
                    GitLabVersion.name == name,
                ).first()

                if existing:
                    existing.current_version = version
                    existing.is_eol = eol_flag
                    existing.eol_date = eol_date
                    existing.risk_level = risk_level
                    existing.source_file = v_data.get("source_file")
                    existing.synced_at = now
                else:
                    new_version = GitLabVersion(
                        repo_id=repo_id,
                        team=team,
                        type=v_data["type"],
                        name=name,
                        current_version=version,
                        is_eol=eol_flag,
                        eol_date=eol_date,
                        risk_level=risk_level,
                        source_file=v_data.get("source_file"),
                        synced_at=now,
                    )
                    db.add(new_version)
            except Exception as e:
                logger.warning(f"Error saving version {v_data.get('name')} for {repo_id}: {e}")

    def _is_orphaned(self, project: dict, days_threshold: int = 365) -> tuple[bool, Optional[str]]:
        """
        Determine if a repo is orphaned.

        A repo is considered orphaned if:
        - Archived
        - No commits
        - No activity for over a year

        Returns:
            (is_orphaned, reason)
        """
        if project.get("archived"):
            return True, "archived"

        if not project.get("repo_exists"):
            return True, "empty_repository"

        commit_count = project.get("commit_count") or 0
        if commit_count == 0:
            return True, "no_commits"

        last_activity = project.get("last_activity_at")
        if last_activity:
            try:
                last_dt = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                days_inactive = (datetime.now(timezone.utc) - last_dt).days
                if days_inactive > days_threshold:
                    return True, f"inactive_{days_inactive}_days"
            except Exception:
                pass

        return False, None

    def scan_team(
        self,
        team: str,
        gitlab_paths: list[str],
        scan_local: bool = True,
        db: Optional[Session] = None,
    ) -> dict:
        """
        Scan all repositories for a team.

        Args:
            team: Team slug
            gitlab_paths: List of GitLab group paths
            scan_local: Whether to scan local clones for detailed metadata
            db: Optional database session

        Returns:
            Summary dict with scan statistics
        """
        logger.info(f"Scanning repos for {team}...")

        own_session = db is None
        if own_session:
            db = SessionLocal()

        try:
            now = datetime.now(timezone.utc)
            team_display = TEAM_DISPLAY_NAMES.get(team, team)

            repos_found = 0
            repos_created = 0
            repos_updated = 0

            for path in gitlab_paths:
                logger.info(f"  Discovering from {path}...")

                try:
                    projects = self.discover_repos(path)
                except RepoScannerError as e:
                    logger.error(f"  Error discovering repos from {path}: {e}")
                    self._stats["errors"].append(f"{team}/{path}: {e}")
                    continue

                logger.info(f"  Found {len(projects)} projects")

                for project in projects:
                    repos_found += 1
                    repo_id = f"{team}/{project['name']}"

                    # Get primary language from GitLab
                    primary_language = self._get_primary_language(project.get("languages", []))

                    # Check if orphaned
                    is_orphaned, orphan_reason = self._is_orphaned(project)

                    # Prepare base data
                    repo_data = {
                        "repo_id": repo_id,
                        "name": project["name"],
                        "team": team,
                        "team_display": team_display,
                        "primary_language": primary_language,
                        "is_orphaned": is_orphaned,
                        "orphan_reason": orphan_reason,
                        "synced_at": now,
                    }

                    # Parse languages from GitLab
                    if project.get("languages"):
                        repo_data["languages"] = json.dumps([
                            {"language": l["name"], "share": l["share"]}
                            for l in project["languages"]
                        ])

                    # Calculate days since last activity
                    if project.get("last_activity_at"):
                        try:
                            last_dt = datetime.fromisoformat(
                                project["last_activity_at"].replace("Z", "+00:00")
                            )
                            repo_data["last_commit_date"] = last_dt
                            repo_data["days_since_commit"] = (now - last_dt).days
                        except Exception:
                            pass

                    # Scan local clone if available and requested
                    packages_detected = []
                    versions_detected = []

                    if scan_local:
                        local_path = self._get_local_clone_path(team, project["name"])
                        if local_path:
                            logger.debug(f"    Scanning local clone: {local_path}")
                            local_data = self._scan_local_files(local_path)

                            repo_data.update({
                                "total_files": local_data["total_files"],
                                "total_lines": local_data["total_lines"],
                                "code_lines": local_data["code_lines"],
                                "has_tests": local_data["has_tests"],
                                "has_ci": local_data["has_ci"],
                                "doc_score": local_data["doc_score"],
                                "has_api_docs": local_data["has_api_docs"],
                                "frameworks": json.dumps(local_data["frameworks"]),
                            })

                            # Detect packages and versions
                            packages_detected = self._detect_packages(local_path)
                            versions_detected = self._detect_versions(local_path)

                    # Upsert to database
                    existing = db.query(GitLabRepo).filter(
                        GitLabRepo.repo_id == repo_id
                    ).first()

                    if existing:
                        for key, value in repo_data.items():
                            setattr(existing, key, value)
                        repos_updated += 1
                    else:
                        new_repo = GitLabRepo(**repo_data)
                        db.add(new_repo)
                        repos_created += 1

                    # Save packages and versions if detected
                    if packages_detected:
                        self._save_packages(db, repo_id, packages_detected)

                    if versions_detected:
                        self._save_versions(db, repo_id, team, versions_detected)

            if own_session:
                db.commit()
            else:
                db.flush()

            self._stats["repos_scanned"] += repos_found
            self._stats["repos_created"] += repos_created
            self._stats["repos_updated"] += repos_updated

            return {
                "team": team,
                "status": "success",
                "repos_found": repos_found,
                "repos_created": repos_created,
                "repos_updated": repos_updated,
            }

        except Exception as e:
            logger.error(f"Error scanning {team}: {e}")
            self._stats["errors"].append(f"{team}: {e}")
            if own_session:
                db.rollback()
            raise
        finally:
            if own_session:
                db.close()

    def scan_all_teams(
        self,
        teams: Optional[list[str]] = None,
        scan_local: bool = True,
    ) -> dict:
        """
        Scan repositories for all teams.

        Args:
            teams: Optional list of team slugs (default: all)
            scan_local: Whether to scan local clones

        Returns:
            Summary dict with per-team results
        """
        if not self.gitlab_token:
            raise RepoScannerError("GitLab credentials are not configured for the active domain")

        logger.info(f"Repo Scanner - scanning {'all teams' if not teams else teams}")

        # Reset stats
        self._stats = {
            "repos_scanned": 0,
            "repos_created": 0,
            "repos_updated": 0,
            "errors": [],
        }

        teams_to_scan = TEAM_GITLAB_PATHS
        if teams:
            teams_to_scan = {t: TEAM_GITLAB_PATHS[t] for t in teams if t in TEAM_GITLAB_PATHS}

        results = {}

        for team, paths in teams_to_scan.items():
            try:
                results[team] = self.scan_team(team, paths, scan_local=scan_local)
            except Exception as e:
                results[team] = {"team": team, "status": "error", "error": str(e)}

        return {
            "results": results,
            "stats": self._stats,
            "scanned_at": datetime.now(timezone.utc).isoformat(),
        }

    def get_team_repos(self, team: str, db: Optional[Session] = None) -> list[dict]:
        """
        Get all repos for a team from the database.

        Args:
            team: Team slug

        Returns:
            List of repo dicts
        """
        own_session = db is None
        if own_session:
            db = SessionLocal()

        try:
            normalized = normalize_team_name(team) or team
            repos = db.query(GitLabRepo).filter(GitLabRepo.team == normalized).all()

            return [
                {
                    "repo_id": r.repo_id,
                    "name": r.name,
                    "team": r.team,
                    "primary_language": r.primary_language,
                    "has_tests": r.has_tests,
                    "has_ci": r.has_ci,
                    "doc_score": r.doc_score,
                    "is_orphaned": r.is_orphaned,
                    "orphan_reason": r.orphan_reason,
                    "days_since_commit": r.days_since_commit,
                    "synced_at": r.synced_at.isoformat() if r.synced_at else None,
                }
                for r in repos
            ]
        finally:
            if own_session:
                db.close()

    def get_orphaned_repos(self, team: Optional[str] = None, db: Optional[Session] = None) -> list[dict]:
        """
        Get orphaned repos, optionally filtered by team.

        Args:
            team: Optional team slug filter

        Returns:
            List of orphaned repo dicts
        """
        own_session = db is None
        if own_session:
            db = SessionLocal()

        try:
            query = db.query(GitLabRepo).filter(GitLabRepo.is_orphaned == True)

            if team:
                normalized = normalize_team_name(team) or team
                query = query.filter(GitLabRepo.team == normalized)

            repos = query.order_by(GitLabRepo.days_since_commit.desc()).all()

            return [
                {
                    "repo_id": r.repo_id,
                    "name": r.name,
                    "team": r.team,
                    "orphan_reason": r.orphan_reason,
                    "days_since_commit": r.days_since_commit,
                    "last_commit_date": r.last_commit_date.isoformat() if r.last_commit_date else None,
                }
                for r in repos
            ]
        finally:
            if own_session:
                db.close()

    def health_check(self) -> dict:
        """Check if scanner is properly configured."""
        result = {
            "gitlab_token": bool(self.gitlab_token),
            "local_clone_base": str(self.local_clone_base),
            "local_clone_exists": self.local_clone_base.is_dir(),
        }

        if self.gitlab_token:
            try:
                query = "query { currentUser { username } }"
                data = self._graphql_query(query)
                result["authenticated_as"] = data.get("currentUser", {}).get("username")
                result["status"] = "healthy"
            except Exception as e:
                result["status"] = "error"
                result["error"] = str(e)
        else:
            result["status"] = "not_configured"

        return result


def get_repo_scanner() -> RepoScanner:
    """Return a repo scanner configured for the current active domain."""
    return RepoScanner()
