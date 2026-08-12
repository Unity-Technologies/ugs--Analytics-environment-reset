"""Client for the auto-provisioning data-deletion API."""
import logging
import requests

from net import retrying

logger = logging.getLogger(__name__)


class DeletionClient:
    """Sends the data-deletion POST to the auto-provisioning service."""

    def __init__(self, base_url: str, api_key: str):
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key

    @retrying("the auto-provisioning service", retry_on_read_timeout=False)
    def delete_environment_data(self, env_id: str) -> str:
        """Send POST to /v1/environments/{env_id}/data-deletion.

        Returns the new DDNA environment ID (a plain number from the response).

        Connect-phase failures (DNS, VPN down) are retried automatically. A read
        timeout is not retried: the deletion may already be running server-side,
        so it is reported for a human to check rather than replayed.

        Raises:
            requests.HTTPError on non-2xx status.
            net.NetworkError if the service is unreachable.
        """
        url = f"{self._base_url}/v1/environments/{env_id}/data-deletion"
        headers = {"x-api-key": self._api_key}

        logger.info("POST %s", url)
        response = requests.post(url, headers=headers, timeout=120)

        if response.status_code not in (200, 201):
            logger.error(
                "Deletion request failed: %d %s",
                response.status_code,
                response.text,
            )
            response.raise_for_status()

        new_ddna_env_id = response.text.strip()
        logger.info("New DDNA environment ID: %s", new_ddna_env_id)

        return new_ddna_env_id
