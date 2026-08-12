"""Wrapper around hex_helpers zendesk to extract ticket data for the deletion workflow."""
import logging
from serviceHelpers.zendesk import zendesk

from net import retrying

logger = logging.getLogger(__name__)

# Zendesk custom field ID for "ProjectId".
# Must be set to the actual field ID from Zendesk Admin > Ticket Fields.
PROJECT_ID_CUSTOM_FIELD_ID = 24423845
ORG_ID_CUSTOM_FIELD_ID = 360010264252


class ZendeskClient:
    """Extracts ticket data needed for the environment deletion workflow."""

    def __init__(self, host: str, api_key: str):
        self._zd = zendesk(host, api_key)
        self._host = host

    @retrying("Zendesk")
    def get_ticket_data(self, ticket_id: int) -> dict:
        """Fetch a ticket and return the fields needed for deletion tracking.

        Returns a dict with keys:
            request_date, org_id, project_id, requester_email,
            assignee_name, ticket_url
        """
        # Search for the ticket by ID
        tickets = self._zd.search_for_tickets(str(ticket_id))
        ticket = tickets.get(ticket_id)
        if ticket is None:
            raise ValueError(f"Ticket {ticket_id} not found in Zendesk.")

        # Get requester details
        requester_email = ""
        if ticket.requester_id:
            requester = self._zd.get_user(ticket.requester_id)
            if requester:
                requester_email = requester.email

        # Get assignee details
        assignee_name = ""
        if ticket.assignee_id:
            assignee = self._zd.get_user(ticket.assignee_id)
            if assignee:
                assignee_name = assignee.name

        # Extract org_id and project_id from custom fields
        org_id = str(ticket.custom_fields.get(ORG_ID_CUSTOM_FIELD_ID, ""))
        project_id = str(ticket.custom_fields.get(PROJECT_ID_CUSTOM_FIELD_ID, ""))

        return {
            "request_date": ticket.created_ts.strftime("%d %b %Y"),
            "org_id": org_id,
            "project_id": project_id,
            "requester_email": requester_email,
            "assignee_name": assignee_name,
            "ticket_url": ticket.url,
        }
