"""Google Sheets integration via an Apps Script web app."""
import logging
import requests

from net import TransientError, retrying

logger = logging.getLogger(__name__)

# Apps Script serves its response via a redirect to script.googleusercontent.com.
# That layer intermittently answers 404 (and occasionally an HTML shell instead
# of the JSON body) even when the deployment is healthy, so these are retried
# rather than treated as a hard failure.
_RETRYABLE_STATUS = frozenset({404, 408, 429, 500, 502, 503, 504})


class SheetsClient:
    """Read/write access to the deletion tracking Google Sheet via Apps Script."""

    def __init__(self, script_url: str):
        self._script_url = script_url
        self._sheet_url: str | None = None
        self._gid: int | None = None

    def _post(self, payload: dict) -> dict:
        """POST to the Apps Script web app and return the decoded JSON body.

        Raises:
            TransientError: for a flaky status or a non-JSON body, so the
                caller's retry wrapper tries again.
            requests.HTTPError: for a genuine client/server rejection.
        """
        response = requests.post(self._script_url, json=payload, timeout=30)

        if response.status_code in _RETRYABLE_STATUS:
            raise TransientError(
                f"HTTP {response.status_code} from the Apps Script endpoint "
                "(deployment is usually fine; this layer is flaky)."
            )
        response.raise_for_status()

        try:
            return response.json()
        except ValueError as err:
            raise TransientError(
                "response was not JSON (got a "
                f"{response.headers.get('content-type', 'unknown')} body)."
            ) from err

    @retrying("the Google Sheets logging script")
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

        result = self._post(payload)
        row_index = result.get("row", -1)
        resumed = result.get("resumed", False)
        self._sheet_url = result.get("url")
        self._gid = result.get("gid")
        if resumed:
            logger.info("Resuming existing in-progress row at index %d", row_index)
        else:
            logger.info("Appended pre-deletion row at index %d", row_index)
        return row_index

    def row_link(self, row_index: int) -> str | None:
        """Return a direct link to a specific row, if the sheet URL is known.

        Requires log_pre_deletion to have run first (it populates the sheet
        URL and gid from the Apps Script response).
        """
        if not self._sheet_url:
            return None
        base = self._sheet_url.split("#", 1)[0]
        rng = f"range=A{row_index}:K{row_index}"
        if self._gid is not None:
            return f"{base}#gid={self._gid}&{rng}"
        return f"{base}#{rng}"

    @retrying("the Google Sheets logging script")
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

        self._post(payload)
        logger.info("Updated row %d: status=%s", row_index, status)
