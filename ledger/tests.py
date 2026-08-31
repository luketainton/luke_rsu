from datetime import date
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.http import HttpResponse
from django.test import RequestFactory, TestCase
from django.urls import reverse

from .models import Vest
from .scim import ScimBearerAuthMiddleware


class WorkspaceIsolationTests(TestCase):
    def setUp(self):
        user_model = get_user_model()
        self.alice = user_model.objects.create_user(
            username="alice", email="alice@example.test", password="safe-password"
        )
        self.bob = user_model.objects.create_user(
            username="bob", email="bob@example.test", password="safe-password"
        )
        self.alice_workspace = self.alice.workspace_memberships.get().workspace
        Vest.objects.create(
            workspace=self.alice_workspace,
            date=date(2026, 1, 1),
            units=10,
            usd_price=100,
            gbp_per_usd=0.8,
        )

    def test_new_user_gets_an_owner_private_workspace(self):
        membership = self.bob.workspace_memberships.get()
        self.assertEqual(membership.role, "owner")
        self.assertNotEqual(membership.workspace_id, self.alice_workspace.id)

    def test_dashboard_does_not_show_another_private_workspace_records(self):
        self.client.force_login(self.bob)
        response = self.client.get(reverse("dashboard"))
        self.assertNotContains(response, "2026-01-01")

    def test_viewer_cannot_add_a_vest(self):
        member = self.bob.workspace_memberships.get()
        member.role = "viewer"
        member.save()
        self.client.force_login(self.bob)
        response = self.client.get(reverse("add_vest"))
        self.assertEqual(response.status_code, 403)

    def test_editor_vest_is_written_to_their_workspace(self):
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("add_vest"),
            {
                "date": "2026-02-01",
                "units": "12",
                "usd_price": "123",
                "gbp_per_usd": "0.8",
                "withheld_units": "0",
                "income_tax": "0",
                "employee_nic": "0",
            },
        )
        self.assertRedirects(response, reverse("dashboard"))
        vest = Vest.objects.get(date=date(2026, 2, 1))
        self.assertEqual(vest.workspace, self.bob.workspace_memberships.get().workspace)

    def test_owner_can_invite_existing_user_as_viewer(self):
        self.client.force_login(self.alice)
        response = self.client.post(
            reverse("access_management"), {"email": self.bob.email, "role": "viewer"}
        )
        self.assertRedirects(response, reverse("access_management"))
        self.assertEqual(
            self.alice_workspace.memberships.get(user=self.bob).role,
            "viewer",
        )


class ScimTokenTests(TestCase):
    def test_scim_middleware_rejects_missing_or_wrong_token(self):
        middleware = ScimBearerAuthMiddleware(lambda request: HttpResponse(status=204))
        with patch.dict("os.environ", {"SCIM_BEARER_TOKEN": "expected"}, clear=False):
            self.assertEqual(middleware(RequestFactory().get("/scim/v2/Users")).status_code, 401)
            self.assertEqual(
                middleware(
                    RequestFactory().get("/scim/v2/Users", HTTP_AUTHORIZATION="Bearer wrong")
                ).status_code,
                401,
            )
            self.assertEqual(
                middleware(
                    RequestFactory().get("/scim/v2/Users", HTTP_AUTHORIZATION="Bearer expected")
                ).status_code,
                204,
            )
