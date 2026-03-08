"""
/jirareport slash command — generates and sends the Ecosystem Jira Progress Report.

Usage:
    /jirareport                    — generate and send to default recipient
    /jirareport user@example.com   — send to specific email
    /jirareport preview            — return summary in chat (no email)
"""

import logging
import os

logger = logging.getLogger(__name__)


def register(registry):
    """Register the jirareport command."""
    registry.register(
        name="jirareport",
        description="Generate and send the Ecosystem Jira Progress Report via email",
        handler=handle_jira_report,
        args_description="[email|preview]",
    )


async def handle_jira_report(args: str) -> str:
    """Handle /jirareport command."""
    from backend.services.jira_report_service import JiraReportService
    
    service = JiraReportService()
    
    if not service.jira.is_configured:
        return "❌ Jira is not configured. Set JIRA_EMAIL, JIRA_API_TOKEN, JIRA_URL in .env"
    
    args = args.strip().lower()
    
    if args == "preview":
        # Generate report data and return text summary (no email)
        teams_data = service.fetch_active_issues()
        total = sum(sum(len(v) for v in types.values()) for types in teams_data.values())
        
        lines = [f"📊 **Ecosystem Jira Report** — {total} active WIP items\n"]
        for team in sorted(teams_data.keys()):
            types = teams_data[team]
            count = sum(len(v) for v in types.values())
            breakdown = ", ".join(f"{len(v)} {k}" for k, v in sorted(types.items(), key=lambda x: -len(x[1])))
            lines.append(f"**{team}**: {count} items ({breakdown})")
        
        return "\n".join(lines)
    
    # Determine recipient
    default_to = os.getenv("JIRA_REPORT_RECIPIENT", "")
    to = args if "@" in args else default_to
    
    # Generate and send
    result = service.generate_and_send(to=to, include_pulse=True)
    
    if result.get("success"):
        return f"✅ Jira Report sent to **{to}**\n📊 {result.get('teams', 0)} teams, {result.get('total_items', 0)} active items"
    else:
        return f"❌ Failed to send report: {result.get('error', 'Unknown error')}"
