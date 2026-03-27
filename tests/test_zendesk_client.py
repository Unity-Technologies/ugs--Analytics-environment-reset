"""Tests for zendesk_client.py."""
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime


class TestGetTicketData:

    def _make_mock_ticket(self, ticket_id=12345):
        ticket = MagicMock()
        ticket.id = ticket_id
        ticket.created_ts = datetime(2022, 5, 16, 10, 30, 0)
        ticket.url = f"https://unity3d.zendesk.com/agent/tickets/{ticket_id}"
        ticket.requester_id = 100
        ticket.assignee_id = 200
        ticket.custom_fields = {9999: "9071127848899", 8888: "555"}
        return ticket

    def _make_mock_user(self, name, email):
        user = MagicMock()
        user.name = name
        user.email = email
        return user

    @patch("zendesk_client.zendesk")
    @patch("zendesk_client.ORG_ID_CUSTOM_FIELD_ID", 8888)
    @patch("zendesk_client.PROJECT_ID_CUSTOM_FIELD_ID", 9999)
    def test_returns_expected_fields(self, MockZendesk):
        mock_zd = MockZendesk.return_value
        ticket = self._make_mock_ticket()
        mock_zd.search_for_tickets.return_value = {12345: ticket}

        requester = self._make_mock_user("Jane Doe", "jane@example.com")
        assignee = self._make_mock_user("C'tri", "ctri@unity.com")
        mock_zd.get_user.side_effect = lambda uid: {
            100: requester, 200: assignee
        }[uid]

        from zendesk_client import ZendeskClient
        client = ZendeskClient("unity3d.zendesk.com", "fake-key")
        result = client.get_ticket_data(12345)

        assert result["request_date"] == "16 May 2022"
        assert result["org_id"] == "555"
        assert result["project_id"] == "9071127848899"
        assert result["requester_email"] == "jane@example.com"
        assert result["assignee_name"] == "C'tri"
        assert result["ticket_url"] == "https://unity3d.zendesk.com/agent/tickets/12345"

    @patch("zendesk_client.zendesk")
    def test_ticket_not_found_raises_value_error(self, MockZendesk):
        mock_zd = MockZendesk.return_value
        mock_zd.search_for_tickets.return_value = {}

        from zendesk_client import ZendeskClient
        client = ZendeskClient("unity3d.zendesk.com", "fake-key")

        with pytest.raises(ValueError, match="not found"):
            client.get_ticket_data(99999)

    @patch("zendesk_client.zendesk")
    def test_missing_assignee_returns_empty_string(self, MockZendesk):
        mock_zd = MockZendesk.return_value
        ticket = self._make_mock_ticket()
        ticket.assignee_id = None
        mock_zd.search_for_tickets.return_value = {12345: ticket}

        requester = self._make_mock_user("Jane", "jane@example.com")
        mock_zd.get_user.return_value = requester

        from zendesk_client import ZendeskClient
        client = ZendeskClient("unity3d.zendesk.com", "fake-key")
        result = client.get_ticket_data(12345)

        assert result["assignee_name"] == ""

    @patch("zendesk_client.zendesk")
    @patch("zendesk_client.PROJECT_ID_CUSTOM_FIELD_ID", 0)
    def test_unconfigured_project_field_returns_empty(self, MockZendesk):
        mock_zd = MockZendesk.return_value
        ticket = self._make_mock_ticket()
        mock_zd.search_for_tickets.return_value = {12345: ticket}
        mock_zd.get_user.return_value = self._make_mock_user("User", "u@e.com")

        from zendesk_client import ZendeskClient
        client = ZendeskClient("unity3d.zendesk.com", "fake-key")
        result = client.get_ticket_data(12345)

        assert result["project_id"] == ""
