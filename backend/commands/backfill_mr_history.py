"""
Backfill MR history from GitLab API.

Fetches MR activity for all active engineers going back N days (default 365)
and upserts into ecosystem.db. Uses the same sync logic as the scheduler.

Usage:
    uv run python -m backend.commands.backfill_mr_history          # 365 days
    uv run python -m backend.commands.backfill_mr_history --days 730  # 2 years
    uv run python -m backend.commands.backfill_mr_history --days 365 --force  # clean re-fetch
"""

import argparse
import logging
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

# Load .env the same way backend/main.py does
_repo_env = Path(__file__).resolve().parent.parent.parent / ".env"
if _repo_env.exists():
    load_dotenv(_repo_env, override=False)
load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
logger = logging.getLogger(__name__)


def main():
    parser = argparse.ArgumentParser(description="Backfill MR history from GitLab")
    parser.add_argument("--days", type=int, default=365, help="Days to look back (default: 365)")
    parser.add_argument("--force", action="store_true", help="Delete existing rows first (clean re-fetch)")
    args = parser.parse_args()

    from backend.database_domain import init_domain_db
    from backend.services.sync_tasks import sync_engineers

    # Ensure tables exist
    init_domain_db()

    logger.info(f"Starting MR backfill: {args.days} days, force_full={args.force}")
    start = time.time()

    try:
        sync_engineers(days=args.days, force_full=args.force, trigger_source="backfill")
    except Exception as e:
        logger.error(f"Backfill failed: {e}")
        sys.exit(1)

    elapsed = time.time() - start
    logger.info(f"Backfill complete in {elapsed:.0f}s")


if __name__ == "__main__":
    main()
