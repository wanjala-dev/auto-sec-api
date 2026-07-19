"""Unit tests for InvitationView GET handler."""

from unittest.mock import MagicMock, patch

from components.membership.api.controller import InvitationView


class TestInvitationViewGet:
    def _make_request(self, workspace_id=None):
        request = MagicMock()
        request.user.id = 1
        request.user.is_staff = False
        request.user.is_superuser = False
        request.query_params = {}
        if workspace_id:
            request.query_params["workspace_id"] = workspace_id
        return request

    @patch("components.membership.api.controller.membership_service")
    def test_get_returns_pending_invitations(self, mock_service):
        mock_query = MagicMock()
        mock_query.list_workspace_pending_invitations.return_value = []
        mock_service.query_membership.return_value = mock_query

        view = InvitationView()
        request = self._make_request(workspace_id="ws-1")
        response = view.get(request)

        assert response.status_code == 200
        assert response.data["success"] is True
        assert response.data["count"] == 0
        mock_query.list_workspace_pending_invitations.assert_called_once()

    @patch("components.membership.api.controller.membership_service")
    def test_get_returns_400_on_value_error(self, mock_service):
        mock_query = MagicMock()
        mock_query.list_workspace_pending_invitations.side_effect = ValueError("bad input")
        mock_service.query_membership.return_value = mock_query

        view = InvitationView()
        request = self._make_request()
        response = view.get(request)

        assert response.status_code == 400

    @patch("components.membership.api.controller.membership_service")
    def test_get_returns_403_on_permission_error(self, mock_service):
        mock_query = MagicMock()
        mock_query.list_workspace_pending_invitations.side_effect = PermissionError("denied")
        mock_service.query_membership.return_value = mock_query

        view = InvitationView()
        request = self._make_request(workspace_id="ws-1")
        response = view.get(request)

        assert response.status_code == 403
