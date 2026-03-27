"""CLI tool for automating Unity Analytics environment data deletion."""
import argparse
import base64
import logging
import os
import subprocess
import sys
from datetime import datetime, timezone

import requests

from zendesk_client import ZendeskClient
from sheets_client import SheetsClient
from deletion_client import DeletionClient

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

AUTO_PROV_BASE_URL = (
    "https://loh-analytics-auto-provisioning.prd.mz.internal.unity3d.com"
)
UNITY_LEGACY_SERVICES_BASE_URL = "https://services.unity.com/api/unity/legacy/v1"


def parse_args():
    parser = argparse.ArgumentParser(
        description="Automate Unity Analytics environment data deletion.",
    )
    parser.add_argument(
        "ticket",
        help=(
            "Zendesk ticket ID or full URL "
            "(e.g. 1236377 or https://unity3d.zendesk.com/agent/tickets/1236377)"
        ),
    )
    parser.add_argument(
        "--env-name",
        default=None,
        help="Environment name",
    )
    parser.add_argument(
        "--env-id",
        default=None,
        help="Environment ID (UUID)",
    )
    parser.add_argument(
        "--api-key",
        default=None,
        help="Auto-provisioning API key. If omitted, fetched via kubectl.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would happen without executing the deletion.",
    )
    parser.add_argument(
        "--skip-sheets",
        action="store_true",
        help="Skip Google Sheets logging.",
    )
    return parser.parse_args()


def extract_ticket_id(ticket_arg: str) -> int:
    """Extract numeric ticket ID from an ID string or a full Zendesk URL."""
    if "/" in ticket_arg:
        parts = ticket_arg.rstrip("/").split("/")
        ticket_arg = parts[-1]
    try:
        return int(ticket_arg)
    except ValueError:
        logger.error("Could not parse ticket ID from: %s", ticket_arg)
        sys.exit(1)


def get_api_key_from_kubectl() -> str:
    """Retrieve the auto-provisioning API key via kubectl."""
    cmd = [
        "kubectl", "get", "secret",
        "--namespace", "loh-analytics-auto-provisioning",
        "api-key", "-o", "jsonpath={.data.key}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        encoded_key = result.stdout.strip()
        return base64.b64decode(encoded_key).decode("utf-8")
    except (subprocess.CalledProcessError, FileNotFoundError) as err:
        logger.error("Failed to get API key via kubectl: %s", err)
        logger.error(
            "Ensure kubectl is installed, you are on VPN, "
            "and gcloud is pointed at unity-ads-liveopshub-prd."
        )
        sys.exit(1)


def fetch_environments(project_id: str) -> list[dict]:
    """Fetch environments for a project from the Unity Services API."""
    url = f"{UNITY_LEGACY_SERVICES_BASE_URL}/projects/{project_id}/environments"
    response = requests.get(url, timeout=30)
    response.raise_for_status()
    return response.json().get("results", [])


def prompt_environment_selection(environments: list[dict]) -> tuple[str, str]:
    """Display environments and let the user pick one. Returns (env_name, env_id)."""
    print("\nAvailable environments:")
    print("-" * 60)
    for i, env in enumerate(environments, 1):
        default_tag = " (default)" if env.get("isDefault") else ""
        print(f"  [{i}] {env['name']}{default_tag}")
        print(f"      ID: {env['id']}")
    print("-" * 60)

    while True:
        choice = input(f"\nSelect environment [1-{len(environments)}]: ").strip()
        try:
            idx = int(choice) - 1
            if 0 <= idx < len(environments):
                selected = environments[idx]
                return selected["name"], selected["id"]
        except ValueError:
            pass
        print(f"Invalid selection. Enter a number between 1 and {len(environments)}.")


def main():
    args = parse_args()
    ticket_id = extract_ticket_id(args.ticket)

    # --- Step 1: Fetch Zendesk ticket data ---
    zendesk_host = os.environ.get("ZENDESK_HOST", "")
    zendesk_key = os.environ.get("ZENDESK_KEY", "")
    if not zendesk_host or not zendesk_key:
        logger.error(
            "ZENDESK_HOST and ZENDESK_KEY environment variables must be set."
        )
        sys.exit(1)

    zd = ZendeskClient(zendesk_host, zendesk_key)
    logger.info("Fetching ticket #%d from Zendesk...", ticket_id)
    ticket_data = zd.get_ticket_data(ticket_id)

    env_name = args.env_name or ""
    env_id = args.env_id or ""

    # --- Step 1b: If no env specified, fetch and prompt ---
    if not env_name and not env_id:
        project_id = ticket_data.get("project_id", "")
        if not project_id:
            logger.error(
                "No --env-name/--env-id provided and ticket has no project ID."
            )
            sys.exit(1)

        logger.info("Fetching environments for project %s...", project_id)
        environments = fetch_environments(project_id)
        if not environments:
            logger.error("No environments found for project %s.", project_id)
            sys.exit(1)

        env_name, env_id = prompt_environment_selection(environments)

    print()
    print("=" * 60)
    print("TICKET DATA")
    print("=" * 60)
    print(f"  Ticket:      {ticket_data['ticket_url']}")
    print(f"  Date:        {ticket_data['request_date']}")
    print(f"  Requester:   {ticket_data['requester_email']}")
    print(f"  Eng/DSE:     {ticket_data['assignee_name']}")
    print(f"  Org ID:      {ticket_data['org_id']}")
    print(f"  Project ID:  {ticket_data['project_id']}")
    print(f"  Env Name:    {env_name}")
    print(f"  Env ID:      {env_id}")
    print("=" * 60)

    # --- Step 2: Log to Google Sheets (pre-deletion) ---
    row_index = None
    if not args.skip_sheets:
        script_url = os.environ.get("SHEETS_SCRIPT_URL", "")
        if not script_url:
            logger.error(
                "SHEETS_SCRIPT_URL environment variable must be set "
                "(or use --skip-sheets)."
            )
            sys.exit(1)

        sheets = SheetsClient(script_url)
        row_index = sheets.log_pre_deletion(
            request_date=ticket_data["request_date"],
            ticket_url=ticket_data["ticket_url"],
            org_id=ticket_data["org_id"],
            project_id=ticket_data["project_id"],
            env_name=env_name,
            env_id=env_id,
            requester=ticket_data["requester_email"],
            engineer=ticket_data["assignee_name"],
        )
        logger.info("Logged pre-deletion row at row %d", row_index)

    # --- Step 3: Get API key ---
    api_key = args.api_key or os.environ.get("AUTO_PROV_API_KEY")
    if not api_key:
        logger.info("No API key provided; fetching via kubectl...")
        api_key = get_api_key_from_kubectl()

    # --- Step 4: Confirm ---
    if not env_id:
        logger.error("--env-id is required to perform the deletion.")
        sys.exit(1)

    if args.dry_run:
        print("\n[DRY RUN] Would send deletion request for env: %s" % env_id)
        print("Exiting without executing.")
        sys.exit(0)

    confirm = input("\nType 'DELETE' to confirm data deletion: ")
    if confirm.strip() != "DELETE":
        print("Aborted.")
        sys.exit(0)

    # --- Step 5: Execute deletion ---
    deletion = DeletionClient(AUTO_PROV_BASE_URL, api_key)
    logger.info("Sending deletion request for environment %s...", env_id)
    new_ddna_env_id = deletion.delete_environment_data(env_id)

    print(f"\nDeletion complete. New DDNA Env ID: {new_ddna_env_id}")

    # --- Step 6: Update Google Sheets ---
    if not args.skip_sheets and row_index is not None:
        completed_date = datetime.now(timezone.utc).strftime("%d %b %Y")
        sheets.update_post_deletion(
            row_index=row_index,
            status="Done",
            completed_date=completed_date,
            new_ddna_env_id=new_ddna_env_id,
        )
        logger.info("Spreadsheet updated.")

    print("\nDone.")


if __name__ == "__main__":
    main()
