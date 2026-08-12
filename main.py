"""CLI tool for automating Unity Analytics environment data deletion."""
import argparse
import base64
import logging
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from urllib.parse import urlparse

import keyring
import requests
from dotenv import load_dotenv

KEYRING_SERVICE = "env-reset-tool"

from zendesk_client import ZendeskClient
from sheets_client import SheetsClient
from deletion_client import DeletionClient
from net import NetworkError, retrying

class ColorFormatter(logging.Formatter):
    COLORS = {
        logging.DEBUG: "\033[37m",     # white
        logging.INFO: "\033[32m",      # green
        logging.WARNING: "\033[33m",   # yellow
        logging.ERROR: "\033[31m",     # red
        logging.CRITICAL: "\033[1;31m",# bold red
    }
    RESET = "\033[0m"

    def format(self, record):
        color = self.COLORS.get(record.levelno, self.RESET)
        record.levelname = f"{color}{record.levelname}{self.RESET}"
        record.msg = f"{color}{record.msg}{self.RESET}"
        return super().format(record)

handler = logging.StreamHandler()
handler.setFormatter(ColorFormatter("%(levelname)s: %(message)s"))
logging.basicConfig(level=logging.INFO, handlers=[handler])
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
        "--unity-token",
        default=None,
        help="Unity Services API bearer token for fetching environments.",
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
        "--sheets-script-url",
        default=None,
        help="Google Apps Script URL for Sheets logging. Falls back to SHEETS_SCRIPT_URL env var.",
    )
    parser.add_argument(
        "--skip-sheets",
        action="store_true",
        help="Skip Google Sheets logging.",
    )
    parser.add_argument(
        "--non-interactive",
        action="store_true",
        help="Disable interactive prompts (for CI/CD). Requires all inputs via args/env.",
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


def get_api_key_from_kubectl(interactive: bool = False) -> str:
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
    except FileNotFoundError:
        logger.error("kubectl is not installed or not on PATH.")
        sys.exit(1)
    except subprocess.CalledProcessError as err:
        stderr = err.stderr or ""
        if "Forbidden" in stderr:
            logger.warning("Access denied fetching kubectl secret.")
            logger.warning(
                "Request access via Slack: use the /request-access command "
                "with project `unity-ads-liveopshub-prd` and role `kubernetes-developer`."
            )
            if interactive:
                input("Press Enter to retry once access is granted (Ctrl+C to abort)...")
                try:
                    result = subprocess.run(cmd, capture_output=True, text=True, check=True)
                    encoded_key = result.stdout.strip()
                    return base64.b64decode(encoded_key).decode("utf-8")
                except subprocess.CalledProcessError:
                    logger.error("Still denied after retry. Check that access was granted and try again.")
        else:
            logger.error("Failed to get API key via kubectl: %s", stderr.strip())
            logger.error(
                "Ensure you are on VPN and gcloud is pointed at "
                "unity-ads-liveopshub-prd."
            )
        sys.exit(1)


def get_kube_api_server() -> str | None:
    """Return the current kube API server URL from the active kubeconfig."""
    cmd = [
        "kubectl", "config", "view", "--minify",
        "-o", "jsonpath={.clusters[0].cluster.server}",
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
    except (FileNotFoundError, subprocess.CalledProcessError):
        return None
    server = result.stdout.strip()
    return server or None


def check_vpn_connectivity(internal_url: str, timeout: float = 5.0) -> None:
    """Check that the VPN is connected by opening a TCP connection.

    DNS resolution alone is insufficient: the internal hostname can resolve
    (via cached/public DNS) even when the VPN tunnel is down. We must actually
    establish a connection to confirm reachability.

    We probe the kube API server (the endpoint kubectl actually talks to)
    rather than ``internal_url``, since the two can ride different routes over
    the VPN — the auto-provisioning host may be reachable while the GKE API
    server is not. Falls back to ``internal_url`` if the kube server can't be
    determined.
    """
    target_url = get_kube_api_server() or internal_url
    parsed = urlparse(target_url)
    hostname = parsed.hostname
    port = parsed.port or (443 if parsed.scheme == "https" else 80)

    try:
        addrinfo = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        logger.warning(
            "Cannot resolve %s — the VPN might not be connected. "
            "Continuing anyway.",
            hostname,
        )
        return

    last_error: OSError | None = None
    for family, socktype, proto, _canonname, sockaddr in addrinfo:
        sock = socket.socket(family, socktype, proto)
        sock.settimeout(timeout)
        try:
            sock.connect(sockaddr)
            logger.info("VPN connected.")
            return
        except OSError as exc:
            last_error = exc
        finally:
            sock.close()

    logger.warning(
        "Cannot connect to %s:%s (%s) — the VPN might not be connected. "
        "Continuing anyway.",
        hostname,
        port,
        last_error,
    )


@retrying("the Unity Services API")
def fetch_environments(project_id: str, token: str) -> list[dict]:
    """Fetch environments for a project from the Unity Services API."""
    url = f"{UNITY_LEGACY_SERVICES_BASE_URL}/projects/{project_id}/environments"
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.get(url, headers=headers, timeout=30)
    response.raise_for_status()
    return response.json().get("results", [])


def resolve_environment(
    environments: list[dict],
    env_name: str,
    env_id: str,
    interactive: bool,
) -> tuple[str, str]:
    """Resolve environment name and ID from the environments list.

    - Both set: return as-is (no validation against the list).
    - Only env_name set: look up env_id from environments.
    - Only env_id set: look up env_name from environments.
    - Neither set + interactive: prompt the user to pick one.
    - Neither set + non-interactive: exit with error.

    Returns (env_name, env_id).
    """
    if env_name and env_id:
        for env in environments:
            if env["name"] == env_name and env["id"] == env_id:
                return env_name, env_id
            if env["name"] == env_name and env["id"] != env_id:
                logger.error(
                    "Environment name '%s' exists but has ID '%s', not '%s'.",
                    env_name, env["id"], env_id,
                )
                sys.exit(1)
            if env["id"] == env_id and env["name"] != env_name:
                logger.error(
                    "Environment ID '%s' exists but has name '%s', not '%s'.",
                    env_id, env["name"], env_name,
                )
                sys.exit(1)
        logger.error("No environment matching name '%s' or ID '%s' found.", env_name, env_id)
        sys.exit(1)

    if env_name:
        for env in environments:
            if env["name"] == env_name:
                return env_name, env["id"]
        logger.error("Environment name '%s' not found in project.", env_name)
        sys.exit(1)

    if env_id:
        for env in environments:
            if env["id"] == env_id:
                return env["name"], env_id
        logger.error("Environment ID '%s' not found in project.", env_id)
        sys.exit(1)

    # Neither set
    if not interactive:
        logger.error("No --env-name/--env-id provided and --non-interactive is set.")
        sys.exit(1)

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
    load_dotenv()
    args = parse_args()
    interactive = not args.non_interactive and sys.stdin.isatty()
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
    if not env_name or not env_id:
        project_id = ticket_data.get("project_id", "")
        if not project_id:
            logger.error(
                "No --env-name/--env-id provided and ticket has no project ID."
            )
            sys.exit(1)

        token_sources = [
            ("--unity-token", args.unity_token),
            ("UNITY_GATEWAY_TOKEN env var", os.environ.get("UNITY_GATEWAY_TOKEN")),
            ("credential store", keyring.get_password(KEYRING_SERVICE, "unity-gateway-token")),
        ]

        environments = None
        for source_name, token in token_sources:
            if not token:
                continue
            logger.info("Trying token from %s...", source_name)
            try:
                environments = fetch_environments(project_id, token)
                unity_token = token
                break
            except requests.HTTPError as err:
                if err.response is not None and err.response.status_code in (401, 403):
                    logger.warning("Token from %s rejected (HTTP %d).", source_name, err.response.status_code)
                else:
                    raise

        if environments is None:
            if interactive:
                logger.warning("No valid token found. Enter a new token or press Ctrl+C to abort.")
                unity_token = input("Unity Gateway token: ").strip()
                if not unity_token:
                    sys.exit(1)
                environments = fetch_environments(project_id, unity_token)
                keyring.set_password(KEYRING_SERVICE, "unity-gateway-token", unity_token)
                logger.info("Token saved to credential store.")
            else:
                logger.error(
                    "No valid Unity Gateway token found. "
                    "Pass --unity-token or set UNITY_GATEWAY_TOKEN env var."
                )
                sys.exit(1)

        if not environments:
            logger.error("No environments found for project %s.", project_id)
            sys.exit(1)

        env_name, env_id = resolve_environment(environments, env_name, env_id, interactive)

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
        script_url = args.sheets_script_url or os.environ.get("SHEETS_SCRIPT_URL", "")
        if not script_url:
            logger.error(
                "Pass --sheets-script-url or set SHEETS_SCRIPT_URL env var "
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

    # --- Step 3: VPN check ---
    logger.info("Checking VPN connectivity...")
    check_vpn_connectivity(AUTO_PROV_BASE_URL)

    # --- Step 4: Get API key ---
    api_key = args.api_key or os.environ.get("AUTO_PROV_API_KEY")
    if not api_key:
        logger.info("No API key provided; fetching via kubectl...")
        api_key = get_api_key_from_kubectl(interactive=interactive)

    # --- Step 5: Confirm ---
    if not env_id:
        logger.error("--env-id is required to perform the deletion.")
        sys.exit(1)

    if args.dry_run:
        print("\n[DRY RUN] Would send deletion request for env: %s" % env_id)
        print("Exiting without executing.")
        sys.exit(0)

    if interactive:
        confirm = input(f"\nType '{env_name.upper()}' to confirm data deletion: ")
        if confirm.strip() != env_name.upper():
            print("Aborted.")
            sys.exit(0)

    # --- Step 6: Execute deletion ---
    deletion = DeletionClient(AUTO_PROV_BASE_URL, api_key)
    logger.info("Sending deletion request for environment %s...", env_id)
    new_ddna_env_id = deletion.delete_environment_data(env_id)

    print(f"\nDeletion complete. New DDNA Env ID: {new_ddna_env_id}")

    # --- Step 7: Update Google Sheets ---
    if not args.skip_sheets and row_index is not None:
        completed_date = datetime.now(timezone.utc).strftime("%d %b %Y")
        sheets.update_post_deletion(
            row_index=row_index,
            status="Done",
            completed_date=completed_date,
            new_ddna_env_id=new_ddna_env_id,
        )
        logger.info("Spreadsheet updated.")

        link = sheets.row_link(row_index)
        if link:
            print(f"\nConfirm the logged entry here:\n{link}")

    print("\nDone.")


if __name__ == "__main__":
    try:
        main()
    except NetworkError as err:
        logger.error("%s", err)
        sys.exit(2)
    except KeyboardInterrupt:
        print("\nAborted.")
        sys.exit(130)
