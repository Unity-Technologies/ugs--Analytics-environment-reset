"""Google Sheets integration via an Apps Script web app."""
import logging
import requests

logger = logging.getLogger(__name__)


class SheetsClient:
    """Read/write access to the deletion tracking Google Sheet via Apps Script."""

    def __init__(self, script_url: str):
        self._script_url = script_url

    def log_pre_deletion(
        self,
        request_date: str,
        ticket_url: str,
        org_id: str,
        project_id: str,
        env_name: str,
        env_id: str,
        requester: str,
        engineer: str,
    ) -> int:
        """Append a new row with pre-deletion data. Returns the row index."""
        payload = {
            "action": "append",
            "row": [
                request_date,
                ticket_url,
                org_id,
                project_id,
                env_name,
                env_id,
                requester,
                engineer,
                "In Progress",
                "",
                "",
            ],
        }

        response = requests.post(self._script_url, json=payload, timeout=30)
        response.raise_for_status()

        result = response.json()
        row_index = result.get("row", -1)
        logger.info("Appended pre-deletion row at index %d", row_index)
        return row_index

    def update_post_deletion(
        self,
        row_index: int,
        status: str,
        completed_date: str,
        new_ddna_env_id: str,
    ) -> None:
        """Update status, completed date, and new DDNA env ID for a row."""
        payload = {
            "action": "update",
            "row_index": row_index,
            "updates": {
                "status": status,
                "completed_date": completed_date,
                "new_ddna_env_id": new_ddna_env_id,
            },
        }

        response = requests.post(self._script_url, json=payload, timeout=30)
        response.raise_for_status()
        logger.info("Updated row %d: status=%s", row_index, status)
