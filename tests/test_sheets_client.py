"""Tests for sheets_client.py."""
import pytest
from unittest.mock import patch, MagicMock
from sheets_client import SheetsClient


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
