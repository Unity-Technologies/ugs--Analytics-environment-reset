"""Tests for deletion_client.py."""
import pytest
from unittest.mock import patch, MagicMock
from deletion_client import DeletionClient


class TestDeleteEnvironmentData:

    @patch("deletion_client.requests")
    def test_success_returns_new_env_id(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "96249885"
        mock_requests.post.return_value = mock_response

        client = DeletionClient("https://auto-prov.example.com", "test-key")
        result = client.delete_environment_data("env-456")

        mock_requests.post.assert_called_once_with(
            "https://auto-prov.example.com/v1/environments/env-456/data-deletion",
            headers={"x-api-key": "test-key"},
            timeout=120,
        )
        assert result == "96249885"

    @patch("deletion_client.requests")
    def test_response_whitespace_stripped(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "  96249885\n"
        mock_requests.post.return_value = mock_response

        client = DeletionClient("https://auto-prov.example.com", "test-key")
        result = client.delete_environment_data("env-456")

        assert result == "96249885"

    @patch("deletion_client.requests")
    def test_status_201_accepted(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 201
        mock_response.text = "12345678"
        mock_requests.post.return_value = mock_response

        client = DeletionClient("https://auto-prov.example.com", "test-key")
        result = client.delete_environment_data("env-456")

        assert result == "12345678"

    @patch("deletion_client.requests")
    def test_failure_raises_http_error(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 500
        mock_response.text = "Internal Server Error"
        mock_response.raise_for_status.side_effect = Exception("500 Server Error")
        mock_requests.post.return_value = mock_response

        client = DeletionClient("https://auto-prov.example.com", "test-key")

        with pytest.raises(Exception, match="500"):
            client.delete_environment_data("env-456")

    @patch("deletion_client.requests")
    def test_trailing_slash_stripped_from_base_url(self, mock_requests):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = "99999"
        mock_requests.post.return_value = mock_response

        client = DeletionClient("https://example.com/", "key")
        client.delete_environment_data("env-1")

        url_called = mock_requests.post.call_args[0][0]
        assert url_called == "https://example.com/v1/environments/env-1/data-deletion"
