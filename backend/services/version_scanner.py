"""
Language version scanner using GitLab API.

Fetches config files (pom.xml, package.json, pyproject.toml, etc.) from
GitLab repos via the REST API and extracts the language version.

Only tracks language version (not framework versions).
Ported from gitlab-analysis/scripts/version_scanner.py — adapted to use
the GitLab API instead of local repo clones.
"""

import json
import logging
import re
import xml.etree.ElementTree as ET
from typing import Optional

import requests

from backend.services.domain_credentials import get_gitlab_settings

logger = logging.getLogger(__name__)

def _gitlab_settings() -> tuple[str, dict]:
    settings = get_gitlab_settings()
    base_url = (settings["url"] or "https://gitlab.com").rstrip("/")
    token = settings["token"]
    headers = {"PRIVATE-TOKEN": token} if token else {}
    return base_url, headers


def _fetch_file(project_path: str, file_path: str) -> Optional[str]:
    """Fetch raw file content from GitLab API. Returns None if not found."""
    gitlab_url, headers = _gitlab_settings()
    gitlab_api = f"{gitlab_url}/api/v4"
    encoded_path = requests.utils.quote(project_path, safe="")
    encoded_file = requests.utils.quote(file_path, safe="")
    for ref in ["HEAD", "main", "master"]:
        try:
            resp = requests.get(
                f"{gitlab_api}/projects/{encoded_path}/repository/files/{encoded_file}/raw",
                params={"ref": ref},
                headers=headers,
                timeout=10,
            )
            if resp.status_code == 200:
                return resp.text
            if resp.status_code == 404:
                continue  # try next ref
        except Exception as exc:
            logger.debug("Error fetching %s from %s: %s", file_path, project_path, exc)
            break
    return None


def _extract_project_path(url: str) -> Optional[str]:
    """Extract GitLab project path from a web URL.

    e.g. https://gitlab.com/acme/teams/platform/billing-api
         → acme/teams/platform/billing-api
    """
    if not url:
        return None
    gitlab_url, _ = _gitlab_settings()
    base = gitlab_url.replace("https://", "").replace("http://", "")
    pattern = rf"https?://{re.escape(base)}/(.+?)(?:\.git|/-/|/?$)"
    match = re.search(pattern, url, re.I)
    if match:
        return match.group(1).rstrip("/")
    # Generic fallback — strip schema+host
    match = re.search(r"https?://[^/]+/(.+?)(?:\.git|/-/|/?$)", url, re.I)
    if match:
        return match.group(1).rstrip("/")
    return None


def _parse_version(s: Optional[str]) -> Optional[str]:
    """Extract the first semver-ish number from a version string."""
    if not s:
        return None
    s = str(s).strip().lstrip("v^~>=<")
    m = re.search(r"(\d+(?:\.\d+)?(?:\.\d+)?)", s)
    return m.group(1) if m else None


# ---------------------------------------------------------------------------
# Language-specific parsers
# ---------------------------------------------------------------------------

def _infer_java_from_spring_boot(spring_boot_version: str) -> Optional[str]:
    """Infer minimum Java version from Spring Boot version (SB 3.x → 17, SB 2.x → 11)."""
    try:
        major = int(spring_boot_version.split(".")[0])
        if major >= 3:
            return "17"
        if major >= 2:
            return "11"
    except (ValueError, IndexError):
        pass
    return None


def _infer_java_from_mm_framework(version_str: str) -> str:
    """
    Infer Java version from MessageMedia internal framework version.

    MM framework 2.x → Spring Boot 3 → Java 17
    MM framework 1.4.x with spring6 marker → Java 17
    MM framework 1.x (no spring6) → Spring Boot 2 → Java 11
    """
    lower = version_str.lower()
    if "spring6" in lower or "spring-6" in lower:
        return "17"
    m = re.search(r"(\d+)\.", version_str)
    if m and int(m.group(1)) >= 2:
        return "17"
    return "11"


def _scan_java_version(pom_content: str) -> Optional[str]:
    """
    Extract Java version from pom.xml content.

    First looks for explicit version properties (java.version, maven.compiler.source, etc.).
    Falls back to inferring from the Spring Boot or MessageMedia parent POM version.
    Returns a version string like "17" or "11", or None if truly undetermined.
    """
    # Quick regex for explicit version properties (handles malformed XML too)
    for pattern in [
        r"<java\.version>(\d+(?:\.\d+)?)</java\.version>",
        r"<maven\.compiler\.source>(\d+(?:\.\d+)?)</maven\.compiler\.source>",
        r"<maven\.compiler\.release>(\d+(?:\.\d+)?)</maven\.compiler\.release>",
        r"<jdk\.version>(\d+(?:\.\d+)?)</jdk\.version>",
    ]:
        m = re.search(pattern, pom_content)
        if m:
            return _parse_version(m.group(1))

    # Structured XML parse — explicit properties + parent inference
    ns = "{http://maven.apache.org/POM/4.0.0}"
    try:
        root = ET.fromstring(pom_content)

        # Check <properties> for explicit Java version
        props = root.find(f"{ns}properties")
        if props is not None:
            for prop in props:
                tag = prop.tag.replace(ns, "")
                if "java" in tag.lower() and "version" in tag.lower():
                    v = _parse_version(prop.text)
                    if v:
                        return v
                if tag in ("maven.compiler.source", "maven.compiler.release"):
                    v = _parse_version(prop.text)
                    if v:
                        return v

        # Infer from <parent> (Spring Boot BOM or MessageMedia framework)
        parent = root.find(f"{ns}parent")
        if parent is not None:
            artifact_el = parent.find(f"{ns}artifactId")
            group_el = parent.find(f"{ns}groupId")
            version_el = parent.find(f"{ns}version")
            artifact = (artifact_el.text or "") if artifact_el is not None else ""
            group = (group_el.text or "") if group_el is not None else ""
            version = (version_el.text or "") if version_el is not None else ""

            if "spring-boot" in artifact.lower():
                sb_ver = _parse_version(version)
                if sb_ver:
                    return _infer_java_from_spring_boot(sb_ver)

            if "messagemedia.framework" in group.lower() or "mm-framework" in artifact.lower():
                return _infer_java_from_mm_framework(version)

    except ET.ParseError:
        pass

    return None


def _scan_gradle_java_version(gradle_content: str) -> Optional[str]:
    """Extract Java version from build.gradle(.kts) content."""
    for pattern in [
        r"sourceCompatibility\s*=\s*['\"]?(\d+)['\"]?",
        r"JavaVersion\.VERSION_(\d+)",
        r"jvmTarget\s*=\s*['\"](\d+)['\"]",
        r"java\.sourceCompatibility\s*=\s*JavaVersion\.VERSION_(\d+)",
    ]:
        m = re.search(pattern, gradle_content)
        if m:
            return m.group(1)
    return None


def _scan_kotlin_version(gradle_content: str) -> Optional[str]:
    """Extract Kotlin version from build.gradle(.kts) content."""
    m = re.search(r"kotlin['\"]?\s*version\s*['\"]?([0-9.]+)", gradle_content)
    return _parse_version(m.group(1)) if m else None


def _scan_node_ts(pkg_content: str) -> tuple[Optional[str], Optional[str]]:
    """Return (node_version, typescript_version) from package.json content."""
    try:
        pkg = json.loads(pkg_content)
        engines = pkg.get("engines", {})
        node_ver = _parse_version(engines.get("node"))
        all_deps: dict = {}
        all_deps.update(pkg.get("dependencies", {}))
        all_deps.update(pkg.get("devDependencies", {}))
        ts_ver = _parse_version(all_deps.get("typescript"))
        return node_ver, ts_ver
    except Exception:
        return None, None


def _scan_python_version(content: str, filename: str) -> Optional[str]:
    """Extract Python version from pyproject.toml, .python-version, setup.cfg, or serverless.yml."""
    if filename == ".python-version":
        return _parse_version(content.strip().splitlines()[0])
    if filename == "pyproject.toml":
        # python = "^3.11"
        m = re.search(r'python\s*=\s*["\'][\^~>=]*([0-9.]+)', content)
        if m:
            return _parse_version(m.group(1))
        # requires-python = ">=3.11"
        m = re.search(r'requires-python\s*=\s*["\'][>=<~^]*([0-9.]+)', content)
        if m:
            return _parse_version(m.group(1))
    if filename == "setup.cfg":
        m = re.search(r"python_requires\s*=\s*[>=<~^]*([0-9.]+)", content)
        if m:
            return _parse_version(m.group(1))
    if filename == "serverless.yml":
        m = re.search(r"runtime:\s*python(\d+\.\d+)", content)
        if m:
            return m.group(1)
    return None


def _scan_go_version(gomod_content: str) -> Optional[str]:
    """Extract Go version from go.mod content."""
    m = re.search(r"^go\s+(\d+\.\d+(?:\.\d+)?)", gomod_content, re.M)
    return _parse_version(m.group(1)) if m else None


def _scan_serverless_runtime(content: str) -> Optional[tuple[str, str]]:
    """
    Extract runtime language from serverless.yml.
    Returns (language, version) or None.
    """
    m = re.search(r"runtime:\s*python(\d+\.\d+)", content)
    if m:
        return "python", m.group(1)
    m = re.search(r"runtime:\s*nodejs(\d+)", content)
    if m:
        return "node", m.group(1)
    m = re.search(r"runtime:\s*go(\d+(?:\.\d+)?)", content)
    if m:
        return "go", m.group(1)
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def scan_service_version(service_url: str, hint_language: Optional[str] = None) -> Optional[dict]:
    """
    Scan a GitLab repo for its language version via the GitLab REST API.

    When hint_language is provided (from Port.io's language field), the relevant
    config files are tried first to minimise API calls. Falls back to full scan
    if the hinted files don't yield a version.

    Returns:
        {"language": "java", "version": "17", "language_version": "Java 17"}
        or None if version cannot be determined.
    """
    project_path = _extract_project_path(service_url)
    if not project_path:
        logger.debug("Could not extract project path from URL: %s", service_url)
        return None

    lang = (hint_language or "").lower()

    # ------------------------------------------------------------------ Java
    if not lang or lang in ("java", "kotlin", "scala", "groovy"):
        pom = _fetch_file(project_path, "pom.xml")
        if pom:
            ver = _scan_java_version(pom)
            if ver:
                return {"language": "java", "version": ver, "language_version": f"Java {ver}"}

        gradle = _fetch_file(project_path, "build.gradle") or _fetch_file(project_path, "build.gradle.kts")
        if gradle:
            kt_ver = _scan_kotlin_version(gradle)
            if kt_ver:
                return {"language": "kotlin", "version": kt_ver, "language_version": f"Kotlin {kt_ver}"}
            java_ver = _scan_gradle_java_version(gradle)
            if java_ver:
                return {"language": "java", "version": java_ver, "language_version": f"Java {java_ver}"}

    # ------------------------------------------------- TypeScript / JavaScript
    if not lang or lang in ("typescript", "javascript", "node", "nodejs", "js", "ts"):
        pkg_json = _fetch_file(project_path, "package.json")
        if pkg_json:
            node_ver, ts_ver = _scan_node_ts(pkg_json)
            if ts_ver:
                return {"language": "typescript", "version": ts_ver, "language_version": f"TypeScript {ts_ver}"}
            if node_ver:
                return {"language": "node", "version": node_ver, "language_version": f"Node {node_ver}"}

    # ----------------------------------------------------------------- Python
    if not lang or lang in ("python",):
        pv = _fetch_file(project_path, ".python-version")
        if pv:
            ver = _scan_python_version(pv, ".python-version")
            if ver:
                return {"language": "python", "version": ver, "language_version": f"Python {ver}"}

        pyproject = _fetch_file(project_path, "pyproject.toml")
        if pyproject:
            ver = _scan_python_version(pyproject, "pyproject.toml")
            if ver:
                return {"language": "python", "version": ver, "language_version": f"Python {ver}"}

        setup_cfg = _fetch_file(project_path, "setup.cfg")
        if setup_cfg:
            ver = _scan_python_version(setup_cfg, "setup.cfg")
            if ver:
                return {"language": "python", "version": ver, "language_version": f"Python {ver}"}

    # -------------------------------------------------------------------- Go
    if not lang or lang in ("go",):
        gomod = _fetch_file(project_path, "go.mod")
        if gomod:
            ver = _scan_go_version(gomod)
            if ver:
                return {"language": "go", "version": ver, "language_version": f"Go {ver}"}

    # -------------------------------------------------- Serverless (any lang)
    for sls_name in ("serverless.yml", "serverless.yaml"):
        sls = _fetch_file(project_path, sls_name)
        if sls:
            result = _scan_serverless_runtime(sls)
            if result:
                detected_lang, ver = result
                label = "Node" if detected_lang == "node" else detected_lang.capitalize()
                return {"language": detected_lang, "version": ver, "language_version": f"{label} {ver}"}

    # ------------------------------ Fallback: try other langs if hint missed
    if lang and lang not in ("java", "kotlin", "scala", "groovy"):
        pom = _fetch_file(project_path, "pom.xml")
        if pom:
            ver = _scan_java_version(pom)
            if ver:
                return {"language": "java", "version": ver, "language_version": f"Java {ver}"}

    if lang and lang not in ("typescript", "javascript", "node", "nodejs", "js", "ts"):
        pkg_json = _fetch_file(project_path, "package.json")
        if pkg_json:
            node_ver, ts_ver = _scan_node_ts(pkg_json)
            if ts_ver:
                return {"language": "typescript", "version": ts_ver, "language_version": f"TypeScript {ts_ver}"}
            if node_ver:
                return {"language": "node", "version": node_ver, "language_version": f"Node {node_ver}"}

    return None
