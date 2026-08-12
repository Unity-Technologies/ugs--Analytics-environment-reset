"""Tests for sheets_client.py."""
import pytest
from unittest.mock import patch, MagicMock
from net import NetworkError
from sheets_client import SheetsClient


def _response(status_code=200, json_body=None, content_type="application/json"):
    """Build a mock requests response."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.headers = {"content-type": content_type}
    resp.raise_for_status = MagicMock()
    if json_body is None:
        resp.json.side_effect = ValueError("not json")
    else:
        resp.json.return_value = json_body
    return resp


class TestLogPreDeletion:

    @patch("sheets_client.requests")
    def test_sends_correct_payload(self, mock_requests):
        mock_response = MagicMock()
        mock_response.json.return_value = {"row": 5}
        mock_response.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_response

        client = SheetsClient("https://script.google.com/exec/abc")
        row = client.log_pre_deletion(
            request_date="16 May 2022",
            ticket_url="https://unity3d.zendesk.com/agent/tickets/1236377",
            org_id="9071127848899",
            project_id="proj-123",
            env_name="My Game Prod",
            env_id="315a48b9-9448-4043-aa1d-56a94aabd4f0",
            requester="user@example.com",
            engineer="C'tri",
        )

        assert row == 5
        call_args = mock_requests.post.call_args
        payload = call_args[1]["json"]
        assert payload["action"] == "append"
        assert len(payload["row"]) == 11
        assert payload["row"][0] == "16 May 2022"
        assert payload["row"][8] == "In Progress"
        assert payload["row"][9] == ""
        assert payload["row"][10] == ""

    @patch("sheets_client.requests")
    def test_raises_on_http_error(self, mock_requests):
        mock_response = MagicMock()
        mock_response.raise_for_status.side_effect = Exception("403 Forbidden")
        mock_requests.post.return_value = mock_response

        client = SheetsClient("https://script.google.com/exec/abc")

        with pytest.raises(Exception, match="403"):
            client.log_pre_deletion(
                request_date="", ticket_url="", org_id="",
                project_id="", env_name="", env_id="",
                requester="", engineer="",
            )


class TestFlakyAppsScriptEndpoint:
    """Apps Script's content-echo layer intermittently 404s on a healthy deployment."""

    @patch("net.time.sleep")
    @patch("sheets_client.requests")
    def test_retries_through_404_and_succeeds(self, mock_requests, _sleep):
        mock_requests.post.side_effect = [
            _response(404, content_type="text/html"),
            _response(200, {"row": 7}),
        ]

        client = SheetsClient("https://script.google.com/exec/abc")
        row = client.log_pre_deletion(
            request_date="", ticket_url="", org_id="", project_id="",
            env_name="", env_id="", requester="", engineer="",
        )

        assert row == 7
        assert mock_requests.post.call_count == 2

    @patch("net.time.sleep")
    @patch("sheets_client.requests")
    def test_retries_when_body_is_html_instead_of_json(self, mock_requests, _sleep):
        mock_requests.post.side_effect = [
            _response(200, json_body=None, content_type="text/html"),
            _response(200, {"row": 3}),
        ]

        client = SheetsClient("https://script.google.com/exec/abc")
        row = client.log_pre_deletion(
            request_date="", ticket_url="", org_id="", project_id="",
            env_name="", env_id="", requester="", engineer="",
        )

        assert row == 3

    @patch("net.time.sleep")
    @patch("sheets_client.requests")
    def test_gives_up_with_network_error_after_persistent_404(self, mock_requests, _sleep):
        mock_requests.post.return_value = _response(404, content_type="text/html")

        client = SheetsClient("https://script.google.com/exec/abc")

        with pytest.raises(NetworkError, match="Gave up after 3 attempts"):
            client.update_post_deletion(
                row_index=5, status="Done",
                completed_date="", new_ddna_env_id="",
            )
        assert mock_requests.post.call_count == 3


class TestUpdatePostDeletion:

    @patch("sheets_client.requests")
    def test_sends_correct_update_payload(self, mock_requests):
        mock_response = MagicMock()
        mock_response.raise_for_status = MagicMock()
        mock_requests.post.return_value = mock_response

        client = SheetsClient("https://script.google.com/exec/abc")
        client.update_post_deletion(
            row_index=5,
            status="Done",
            completed_date="16 May 2022",
            new_ddna_env_id="96249885",
        )

        call_args = mock_requests.post.call_args
        payload = call_args[1]["json"]
        assert payload["action"] == "update"
        assert payload["row_index"] == 5
        assert payload["updates"]["status"] == "Done"
        assert payload["updates"]["completed_date"] == "16 May 2022"
        assert payload["updates"]["new_ddna_env_id"] == "96249885"
