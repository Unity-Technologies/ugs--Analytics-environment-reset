"""Tests for main.py - CLI argument parsing and utilities."""
import pytest
from unittest.mock import patch
from main import extract_ticket_id


class TestExtractTicketId:

    def test_numeric_string(self):
        assert extract_ticket_id("1236377") == 1236377

    def test_full_url(self):
        url = "https://unity3d.zendesk.com/agent/tickets/1236377"
        assert extract_ticket_id(url) == 1236377

    def test_url_with_trailing_slash(self):
        url = "https://unity3d.zendesk.com/agent/tickets/1236377/"
        assert extract_ticket_id(url) == 1236377

    def test_invalid_raises_system_exit(self):
        with pytest.raises(SystemExit):
            extract_ticket_id("not-a-number")
