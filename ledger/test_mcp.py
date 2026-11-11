import json
from datetime import date, timedelta
from io import StringIO

from django.core.management import call_command
from django.test import Client, TestCase
from django.urls import reverse
from django.utils import timezone

from .models import FxRate, Grant, MCPApiKey, Security, User, WorkspaceMembership


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

    def set_access(self, access, client=None, **data):
        key = MCPApiKey.objects.get()
        return (client or self.client).post(
            reverse("mcp_key_write", args=[key.pk]),
            {"workspace_id": self.workspace_id, "access": access, **data},
        )

    def call(self, name, **arguments):
        return self.post("tools/call", {"name": name, "arguments": arguments}).json()

    def test_write_requires_key_owner_consent_and_current_editor_role(self):
        fields = {"date": "2026-04-06", "units": "3.25"}
        self.assertEqual(self.call("create_grant", fields=fields)["error"]["code"], -32000)
        other_user = User.objects.create_user(email="other@example.com", username="other")
        WorkspaceMembership.objects.create(
            user=other_user, workspace_id=self.workspace_id, role=WorkspaceMembership.Role.OWNER
        )
        self.client.force_login(other_user)
        session = self.client.session
        session["active_workspace_id"] = self.workspace_id
        session.save()
        self.assertEqual(self.set_access("read-write").status_code, 404)
        self.client.force_login(self.user)
        self.assertEqual(self.set_access("read-write", workspace_id=0).status_code, 403)
        self.membership.role = WorkspaceMembership.Role.VIEWER
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.set_access("read-write").status_code, 403)
        self.membership.role = WorkspaceMembership.Role.EDITOR
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.set_access("read-write").status_code, 302)
        tools = self.post("tools/list").json()["result"]["tools"]
        self.assertIn("create_grant", {tool["name"] for tool in tools})
        self.membership.role = WorkspaceMembership.Role.VIEWER
        self.membership.save(update_fields=["role"])
        self.assertEqual(self.call("create_grant", fields=fields)["error"]["code"], -32000)
        self.assertEqual(self.set_access("read-only").status_code, 302)
        self.assertFalse(MCPApiKey.objects.get().allow_write)

    def test_write_consent_requires_csrf(self):
        client = Client(enforce_csrf_checks=True)
        client.force_login(self.user)
        self.assertEqual(self.set_access("read-write", client=client).status_code, 403)
        self.assertFalse(MCPApiKey.objects.get().allow_write)
        page = client.get(reverse("mcp_keys"))
        self.assertContains(page, "Allow write access")
        client.defaults["HTTP_X_CSRFTOKEN"] = client.cookies["csrftoken"].value
        self.assertEqual(self.set_access("read-write", client=client).status_code, 302)
        self.assertTrue(MCPApiKey.objects.get().allow_write)

    def test_consented_key_can_create_update_and_delete_in_its_ledger(self):
        self.client.force_login(self.user)
        self.assertEqual(self.set_access("read-write").status_code, 302)
        FxRate.objects.create(
            workspace_id=self.workspace_id,
            label="Test",
            method="manual",
            starts_on=date(2026, 4, 1),
            ends_on=date(2026, 4, 30),
            usd_per_gbp="1.25",
        )
        security = Security.objects.create(workspace_id=self.workspace_id, name="Test", ticker="T")
        fields = {"date": "2026-04-06", "units": "3.25", "security": security.pk}
        other_user = User.objects.create_user(email="other@example.com", username="other")
        other_workspace = other_user.workspace_memberships.get().workspace
        other_security = Security.objects.create(
            workspace=other_workspace, name="Other", ticker="O"
        )
        other_grant = Grant.objects.create(
            workspace=other_workspace, date=date(2026, 4, 6), units="3.25"
        )
        self.assertTrue(
            self.call("create_grant", fields={**fields, "security": other_security.pk})["result"][
                "isError"
            ]
        )
        self.assertTrue(self.call("delete_grant", record_id=other_grant.pk)["result"]["isError"])
        self.assertTrue(Grant.objects.filter(pk=other_grant.pk).exists())

        required_fields = {
            "grant": {},
            "vest": {"withheld_units": "0", "income_tax": "0", "employee_nic": "0"},
            "sale": {"fees_gbp": "0"},
            "purchase": {"fees_gbp": "0"},
        }
        for record, extra in required_fields.items():
            with self.subTest(record=record):
                result = self.call(f"create_{record}", fields={**fields, **extra})["result"]
                self.assertFalse(result["isError"], result)
                record_id = result["structuredContent"]["record_id"]
                result = self.call(f"update_{record}", record_id=record_id, fields={"units": "2"})[
                    "result"
                ]
                self.assertFalse(result["isError"], result)
                rows = self.call(f"list_{record}s")["result"]["structuredContent"]["records"]
                self.assertEqual(rows[0]["units"], "2.0000")
                self.assertEqual(rows[0]["security_id"], security.pk)
                self.assertFalse(
                    self.call(f"delete_{record}", record_id=record_id)["result"]["isError"]
                )

        self.assertEqual(self.set_access("read-only").status_code, 302)
        self.assertEqual(self.call("create_grant", fields=fields)["error"]["code"], -32000)
