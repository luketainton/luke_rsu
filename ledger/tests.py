from datetime import date

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models import Vest


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
