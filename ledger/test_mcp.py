import json
from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from .models import Grant, MCPApiKey, User


class MCPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(email="reader@example.com", username="reader")
        self.membership = self.user.workspace_memberships.get()
        self.workspace_id = self.membership.workspace_id
        output = StringIO()
        call_command(
            "mcp_key",
            "issue",
            self.user.email,
            str(self.workspace_id),
            stdout=output,
            stderr=StringIO(),
        )
        self.token = output.getvalue().strip()
        self.url = reverse("mcp")

    def post(self, method, params=None, *, notification=False, **headers):
        message = {"jsonrpc": "2.0", "method": method}
        if not notification:
            message["id"] = 1
        if params is not None:
            message["params"] = params
        return self.client.post(
            self.url,
            json.dumps(message),
            content_type="application/json",
            headers={
                "Authorization": f"Bearer {self.token}",
                "Accept": "application/json, text/event-stream",
                **headers,
            },
        )

    def test_initialize_and_discover_tools(self):
        result = self.post("initialize", {"protocolVersion": "2025-11-25"}).json()["result"]
        self.assertEqual(result["protocolVersion"], "2025-11-25")
        self.assertEqual(self.post("notifications/initialized", notification=True).status_code, 202)
        response = self.post("tools/list", **{"MCP-Protocol-Version": "2025-11-25"})
        self.assertEqual(
            {tool["name"] for tool in response.json()["result"]["tools"]},
            {"list_grants", "list_vests", "list_sales", "list_purchases"},
        )
        self.assertIn("no-store", response.headers["Cache-Control"])
        self.assertEqual(
            self.post("tools/list", **{"MCP-Protocol-Version": "other"}).status_code, 400
        )

    def test_workspace_isolation_and_pagination(self):
        other_user = User.objects.create_user(email="other@example.com", username="other")
        other_id = other_user.workspace_memberships.get().workspace_id
        fields = {"date": date(2026, 4, 6), "units": "3.2500"}
        first = Grant.objects.create(workspace_id=self.workspace_id, **fields)
        Grant.objects.create(workspace_id=other_id, **fields)
        second = Grant.objects.create(workspace_id=self.workspace_id, **fields)

        def page(**arguments):
            response = self.post("tools/call", {"name": "list_grants", "arguments": arguments})
            return response.json()["result"]["structuredContent"]

        data = page(limit=1)
        self.assertEqual(data["records"][0]["id"], first.pk)
        self.assertEqual(data["records"][0]["units"], "3.2500")
        self.assertEqual(data["next_after_id"], first.pk)
        data = page(after_id=data["next_after_id"])
        self.assertEqual([row["id"] for row in data["records"]], [second.pk])
        self.assertIsNone(data["next_after_id"])
        response = self.post(
            "tools/call",
            {
                "name": "list_grants",
                "arguments": {"workspace_id": other_id},
            },
        )
        self.assertEqual(response.json()["error"]["code"], -32602)

    def test_browser_origin_and_session_are_rejected(self):
        self.client.force_login(self.user)
        self.assertEqual(self.post("tools/list", Origin="https://other.example").status_code, 403)
        self.assertEqual(self.post("tools/list", Authorization="").status_code, 401)

    def test_key_expiry_deactivation_and_membership_removal(self):
        key = MCPApiKey.objects.get()
        self.assertNotEqual(key.digest, self.token)
        expiry = key.expires_at
        key.expires_at = timezone.now() - timedelta(seconds=1)
        key.save(update_fields=["expires_at"])
        self.assertEqual(self.post("tools/list").status_code, 401)
        key.expires_at = expiry
        key.save(update_fields=["expires_at"])
        self.user.is_active = False
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.post("tools/list").status_code, 401)
        self.user.is_active = True
        self.user.save(update_fields=["is_active"])
        self.assertEqual(self.post("tools/list").status_code, 200)
        self.membership.delete()
        self.assertEqual(self.post("tools/list").status_code, 401)

    def test_revoke_key(self):
        call_command("mcp_key", "revoke", str(MCPApiKey.objects.get().pk), stdout=StringIO())
        self.assertEqual(self.post("tools/list").status_code, 401)
