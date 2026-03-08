"""
Active domain state for the multi-domain architecture.

Stores which domain slug is currently active. Defaults to the first available
domain on startup. Changes via POST /api/domains/switch.
"""
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_ACTIVE_FILE = Path(__file__).resolve().parent.parent.parent / "data" / "active_domain.txt"

_active_slug: str | None = None


def get_active_slug() -> str:
    """Return the active domain slug, initialising from file or first available domain."""
    global _active_slug
    if _active_slug:
        return _active_slug

    # Try reading from persistence file
    if _ACTIVE_FILE.exists():
        saved = _ACTIVE_FILE.read_text().strip()
        if saved:
            _active_slug = saved
            return _active_slug

    # Fall back to first available domain
    from backend.core.config_loader import list_domain_slugs
    slugs = list_domain_slugs()
    if slugs:
        _active_slug = slugs[0]
        _persist()
        return _active_slug

    # Legacy fallback
    _active_slug = "ecosystem"
    return _active_slug


def switch_domain(slug: str) -> None:
    """Switch the active domain to a new slug."""
    global _active_slug
    from backend.core.config_loader import list_domain_slugs, reload_domain_config
    slugs = list_domain_slugs()
    if slug not in slugs:
        raise ValueError(f"Domain '{slug}' not found. Available: {slugs}")
    _active_slug = slug
    _persist()
    reload_domain_config(slug)
    try:
        from backend.config.gitlab_teams import _reset_for_testing
        _reset_for_testing()
    except Exception:
        pass
    logger.info(f"Switched active domain to: {slug}")


def get_active_config():
    """Return OrganizationConfig for the active domain."""
    from backend.core.config_loader import get_domain_config
    return get_domain_config(get_active_slug())


def list_domains() -> list:
    """Return metadata for all configured domains."""
    from backend.core.config_loader import list_domain_slugs, get_domain_config
    result = []
    active = get_active_slug()
    for slug in list_domain_slugs():
        try:
            cfg = get_domain_config(slug)
            result.append({
                "slug": slug,
                "name": cfg.name,
                "description": cfg.description,
                "team_count": len(cfg.teams),
                "active": slug == active,
                "is_configured": bool(cfg.teams),
            })
        except Exception as e:
            result.append({"slug": slug, "name": slug, "active": slug == active, "error": str(e)})
    return result


def _persist() -> None:
    _ACTIVE_FILE.parent.mkdir(parents=True, exist_ok=True)
    _ACTIVE_FILE.write_text(_active_slug or "")
