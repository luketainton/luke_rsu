import json
from datetime import date
from io import BytesIO
from unittest.mock import patch

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from django.http import HttpResponse
from django.test import RequestFactory, TestCase, override_settings
from django.urls import reverse
from openpyxl import Workbook

from .hmrc import HmrcRate
from .models import Broker, FxRate, Grant, Sale, Vest
from .scim import ScimBearerAuthMiddleware


class SsoLoginTests(TestCase):
    @override_settings(SOCIALACCOUNT_LOGIN_ON_GET=True)
    def test_sso_link_does_not_render_allauth_confirmation_page(self):
        from allauth.socialaccount.providers.base.utils import respond_to_login_on_get

        response = respond_to_login_on_get(
            RequestFactory().get("/accounts/oidc/company/login/"), None
        )
        self.assertIsNone(response)


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
        )
        FxRate.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            label="2026 test rate",
            method="manual",
            starts_on=date(2026, 1, 1),
            ends_on=date(2026, 12, 31),
            usd_per_gbp=1.25,
            source_url="https://example.test/rate",
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
                "withheld_units": "0",
                "income_tax": "0",
                "employee_nic": "0",
            },
        )
        self.assertRedirects(response, reverse("vest_list"))
        vest = Vest.objects.get(date=date(2026, 2, 1))
        self.assertEqual(vest.workspace, self.bob.workspace_memberships.get().workspace)

    def test_event_creation_retrieves_and_uses_a_missing_rate(self):
        workspace = self.bob.workspace_memberships.get().workspace
        retrieved_rate = HmrcRate(
            label="January 2027 HMRC monthly rate",
            method="monthly",
            starts_on=date(2027, 1, 1),
            ends_on=date(2027, 1, 31),
            usd_per_gbp=1.25,
            source_url="https://example.test/hmrc-rate",
        )
        self.client.force_login(self.bob)
        with patch("ledger.fx.fetch_hmrc_usd_rate", return_value=retrieved_rate) as fetch_rate:
            response = self.client.post(
                reverse("add_grant"),
                {"date": "2027-01-15", "units": "12", "usd_price": "100"},
            )
        self.assertRedirects(response, reverse("grant_list"))
        fetch_rate.assert_called_once_with("monthly", date(2027, 1, 15))
        grant = Grant.objects.get(workspace=workspace, date=date(2027, 1, 15))
        self.assertEqual(str(grant.gbp_per_usd), "0.8")
        self.assertTrue(
            FxRate.objects.filter(workspace=workspace, starts_on=date(2027, 1, 1)).exists()
        )
        self.assertNotContains(self.client.get(reverse("add_grant")), "Gbp per usd")

    def test_brokers_are_workspace_scoped_and_can_be_managed(self):
        own_broker = Broker.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace, name="Schwab"
        )
        other_broker = Broker.objects.create(workspace=self.alice_workspace, name="E*TRADE")
        self.client.force_login(self.bob)

        response = self.client.post(reverse("add_broker"), {"name": "Fidelity"})
        self.assertRedirects(response, reverse("broker_management"))
        fidelity = Broker.objects.get(name="Fidelity")
        self.assertEqual(fidelity.workspace, self.bob.workspace_memberships.get().workspace)
        self.assertNotContains(self.client.get(reverse("broker_management")), other_broker.name)
        response = self.client.post(reverse("add_broker"), {"name": "schwab"})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "A broker with this name already exists.")

        response = self.client.post(
            reverse("add_grant"),
            {
                "grant_id": "RSU-2026",
                "broker": own_broker.id,
                "date": "2026-02-01",
                "units": "12",
            },
        )
        self.assertRedirects(response, reverse("grant_list"))
        grant = Grant.objects.get(grant_id="RSU-2026")
        self.assertEqual(grant.broker, own_broker)
        self.assertContains(self.client.get(reverse("grant_list")), "RSU-2026")
        self.assertContains(self.client.get(reverse("grant_list")), "Schwab")

        self.client.post(
            reverse("edit_broker", args=[fidelity.id]), {"name": "Fidelity NetBenefits"}
        )
        fidelity.refresh_from_db()
        self.assertEqual(fidelity.name, "Fidelity NetBenefits")
        Sale.objects.create(
            workspace=grant.workspace, date=date(2026, 2, 2), units=1, broker=fidelity
        )
        self.client.post(reverse("delete_broker", args=[fidelity.id]))
        self.assertFalse(Broker.objects.filter(id=fidelity.id).exists())
        self.assertIsNone(Sale.objects.get(workspace=grant.workspace).broker)

        response = self.client.post(
            reverse("add_sale"),
            {"date": "2026-02-03", "units": "1", "broker": other_broker.id},
        )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "Select a valid choice")

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

    def test_grant_list_displays_workspace_grants_and_navigation(self):
        grant = Grant.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            date=date(2026, 3, 1),
            units=20,
            usd_price=100,
            notes="Annual award",
        )
        self.client.force_login(self.bob)
        response = self.client.get(reverse("grant_list"))
        self.assertContains(response, "Grants")
        self.assertContains(response, grant.notes)
        self.assertContains(response, reverse("edit_grant", args=[grant.id]))
        self.assertContains(response, reverse("vest_list"))

    def test_dashboard_shows_compact_summary_and_record_pages_are_isolated(self):
        own_grant = Grant.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            date=date(2026, 3, 1),
            units=20,
            notes="Bob grant",
        )
        self.client.force_login(self.bob)
        response = self.client.get(reverse("dashboard"))
        self.assertContains(response, "Current holding")
        self.assertNotContains(response, own_grant.notes)
        response = self.client.get(reverse("grant_list"))
        self.assertContains(response, own_grant.notes)
        self.assertNotContains(response, "2026-01-01")

    def test_hmrc_financial_year_uses_5_april_boundary(self):
        workspace = self.bob.workspace_memberships.get().workspace
        before_boundary = Grant.objects.create(
            workspace=workspace,
            date=date(2026, 4, 4),
            units=1,
        )
        after_boundary = Grant.objects.create(
            workspace=workspace,
            date=date(2026, 4, 5),
            units=1,
        )
        self.assertEqual(before_boundary.hmrc_financial_year, "2025/26")
        self.assertEqual(after_boundary.hmrc_financial_year, "2026/27")
        self.client.force_login(self.bob)
        response = self.client.get(reverse("grant_list"))
        self.assertContains(response, "UK tax year")
        self.assertContains(response, "2025/26")
        self.assertContains(response, "2026/27")

    def test_editor_can_edit_and_delete_their_grant(self):
        grant = Grant.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            date=date(2026, 3, 1),
            units=20,
            usd_price=100,
        )
        self.client.force_login(self.bob)
        destination = f"{reverse('grant_list')}?page=2"
        response = self.client.post(
            reverse("edit_grant", args=[grant.id]),
            {
                "date": "2026-03-02",
                "units": "25",
                "usd_price": "110",
                "notes": "Corrected award",
                "next": destination,
            },
        )
        self.assertRedirects(response, destination)
        grant.refresh_from_db()
        self.assertEqual(grant.units, 25)
        response = self.client.post(reverse("delete_grant", args=[grant.id]))
        self.assertRedirects(response, reverse("grant_list"))
        self.assertFalse(Grant.objects.filter(id=grant.id).exists())

    def test_viewer_cannot_edit_or_delete_a_grant(self):
        grant = Grant.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            date=date(2026, 3, 1),
            units=20,
            usd_price=100,
        )
        member = self.bob.workspace_memberships.get()
        member.role = "viewer"
        member.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("edit_grant", args=[grant.id])).status_code, 403)
        self.assertEqual(
            self.client.post(reverse("delete_grant", args=[grant.id])).status_code, 403
        )

    def test_rate_list_displays_workspace_hmrc_rates(self):
        rate = FxRate.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            label="March 2026 monthly rate",
            method="monthly",
            starts_on=date(2026, 3, 1),
            ends_on=date(2026, 3, 31),
            usd_per_gbp=1.27,
            source_url="https://example.test/hmrc-rate",
        )
        self.client.force_login(self.bob)
        response = self.client.get(reverse("rate_list"))
        self.assertContains(response, "Exchange rates")
        self.assertContains(response, rate.label)
        self.assertContains(response, reverse("edit_rate", args=[rate.id]))

    def test_editor_can_edit_and_delete_an_hmrc_rate(self):
        rate = FxRate.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            label="March 2026 monthly rate",
            method="monthly",
            starts_on=date(2026, 3, 1),
            ends_on=date(2026, 3, 31),
            usd_per_gbp=1.27,
            source_url="https://example.test/hmrc-rate",
        )
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("edit_rate", args=[rate.id]),
            {
                "label": "March 2026 spot rate",
                "method": "spot",
                "starts_on": "2026-03-02",
                "ends_on": "2026-03-02",
                "usd_per_gbp": "1.25",
                "source_url": "https://example.test/hmrc-spot-rate",
            },
        )
        self.assertRedirects(response, reverse("rate_list"))
        rate.refresh_from_db()
        self.assertEqual(rate.method, "spot")
        response = self.client.post(reverse("delete_rate", args=[rate.id]))
        self.assertRedirects(response, reverse("rate_list"))
        self.assertFalse(FxRate.objects.filter(id=rate.id).exists())

    def test_viewer_cannot_edit_or_delete_an_hmrc_rate(self):
        rate = FxRate.objects.create(
            workspace=self.bob.workspace_memberships.get().workspace,
            label="March 2026 monthly rate",
            method="monthly",
            starts_on=date(2026, 3, 1),
            ends_on=date(2026, 3, 31),
            usd_per_gbp=1.27,
            source_url="https://example.test/hmrc-rate",
        )
        member = self.bob.workspace_memberships.get()
        member.role = "viewer"
        member.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("edit_rate", args=[rate.id])).status_code, 403)
        self.assertEqual(self.client.post(reverse("delete_rate", args=[rate.id])).status_code, 403)

    def test_editor_can_edit_and_delete_a_vest_and_sale(self):
        workspace = self.bob.workspace_memberships.get().workspace
        vest = Vest.objects.create(workspace=workspace, date=date(2026, 3, 1), units=20)
        sale = Sale.objects.create(workspace=workspace, date=date(2026, 3, 2), units=10)
        self.client.force_login(self.bob)
        response = self.client.post(
            reverse("edit_vest", args=[vest.id]),
            {
                "date": "2026-03-01",
                "units": "25",
                "withheld_units": "5",
                "income_tax": "0",
                "employee_nic": "0",
            },
        )
        self.assertRedirects(response, reverse("vest_list"))
        vest.refresh_from_db()
        self.assertEqual(vest.units, 25)
        response = self.client.post(
            reverse("edit_sale", args=[sale.id]),
            {"date": "2026-03-03", "units": "12", "fees_gbp": "1.25"},
        )
        self.assertRedirects(response, reverse("sale_list"))
        sale.refresh_from_db()
        self.assertEqual(sale.units, 12)
        self.client.post(reverse("delete_vest", args=[vest.id]))
        self.client.post(reverse("delete_sale", args=[sale.id]))
        self.assertFalse(Vest.objects.filter(id=vest.id).exists())
        self.assertFalse(Sale.objects.filter(id=sale.id).exists())

    def test_viewer_cannot_edit_or_delete_vests_or_sales(self):
        workspace = self.bob.workspace_memberships.get().workspace
        vest = Vest.objects.create(workspace=workspace, date=date(2026, 3, 1), units=20)
        sale = Sale.objects.create(workspace=workspace, date=date(2026, 3, 2), units=10)
        member = self.bob.workspace_memberships.get()
        member.role = "viewer"
        member.save()
        self.client.force_login(self.bob)
        self.assertEqual(self.client.get(reverse("edit_vest", args=[vest.id])).status_code, 403)
        self.assertEqual(self.client.post(reverse("delete_sale", args=[sale.id])).status_code, 403)


def benefit_history_file():
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Restricted Stock"
    headers = [
        "Record Type",
        "Event Type",
        "Grant Number",
        "Date",
        "Qty. or Amount",
        "Grant Date",
        "Granted Qty.",
    ]
    sheet.append(headers)
    sheet.append(["Event", "Shares granted", "101", "01/10/2025", 100, None, None])
    sheet.append(["Event", "Shares vested", "101", "01/10/2026", 25, None, None])
    sheet.append(["Event", "Shares released", "101", "01/10/2026", 15, None, None])
    sheet.append(["Event", "Shares sold", "101", "01/11/2026", 15, None, None])
    stream = BytesIO()
    workbook.save(stream)
    stream.seek(0)
    stream.name = "BenefitHistory.xlsx"
    return stream


class ImportAndRateFetchTests(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="importer", email="importer@example.test", password="safe-password"
        )
        self.workspace = self.user.workspace_memberships.get().workspace
        self.client.force_login(self.user)

    def test_etrade_import_is_idempotent_and_derives_withheld_units(self):
        response = self.client.post(
            reverse("import_etrade_history"), {"file": benefit_history_file()}
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(Grant.objects.filter(workspace=self.workspace).count(), 1)
        grant = Grant.objects.get(workspace=self.workspace)
        self.assertEqual(grant.grant_id, "101")
        self.assertEqual(grant.broker.name, "Morgan Stanley E*TRADE")
        vest = Vest.objects.get(workspace=self.workspace)
        self.assertEqual(vest.withheld_units, 10)
        self.assertEqual(vest.grant_id, "101")
        self.assertEqual(vest.broker.name, "Morgan Stanley E*TRADE")
        sale = Sale.objects.get(workspace=self.workspace)
        self.assertEqual(sale.grant_id, "101")
        self.assertEqual(sale.broker.name, "Morgan Stanley E*TRADE")
        self.assertIsNone(sale.usd_price)
        self.assertIn("add the USD sale price", sale.notes)
        response = self.client.post(
            reverse("import_etrade_history"), {"file": benefit_history_file()}
        )
        self.assertRedirects(response, reverse("dashboard"))
        self.assertEqual(Grant.objects.filter(workspace=self.workspace).count(), 1)
        self.assertEqual(Vest.objects.filter(workspace=self.workspace).count(), 1)
        self.assertEqual(Sale.objects.filter(workspace=self.workspace).count(), 1)

    def test_hmrc_fetch_saves_rate_from_official_csv(self):
        csv_content = (
            "Country/Territories,Currency,Currency Code,Currency Units per £1,Start date,End date\n"
            "USA,Dollar,USD,1.3502,01/05/2026,31/05/2026\n"
        ).encode()

        class Response:
            def read(self):
                return csv_content

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with patch("ledger.hmrc.urlopen", return_value=Response()):
            response = self.client.post(
                reverse("fetch_hmrc_rate"), {"method": "monthly", "rate_date": "2026-05-15"}
            )
        self.assertRedirects(response, reverse("rate_list"))
        rate = FxRate.objects.get(workspace=self.workspace)
        self.assertEqual(str(rate.usd_per_gbp), "1.35020000")
        self.assertEqual(rate.starts_on, date(2026, 5, 1))
        self.assertIn("type=monthly", rate.source_url)

    def test_wise_fetch_saves_historical_rate_without_exposing_token(self):
        payload = b'[{"rate": 1.2789, "source": "GBP", "target": "USD"}]'

        class Response:
            def read(self):
                return payload

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

        with (
            patch.dict("os.environ", {"WISE_PERSONAL_API_TOKEN": "secret-token"}, clear=False),
            patch("ledger.wise.urlopen", return_value=Response()) as urlopen,
        ):
            response = self.client.post(reverse("fetch_wise_rate"), {"rate_date": "2026-05-15"})
        self.assertRedirects(response, reverse("rate_list"))
        rate = FxRate.objects.get(workspace=self.workspace, method="wise")
        self.assertEqual(str(rate.usd_per_gbp), "1.27890000")
        self.assertEqual(rate.starts_on, date(2026, 5, 15))
        self.assertIn("source=GBP", rate.source_url)
        self.assertNotIn("secret-token", rate.source_url)
        self.assertEqual(
            urlopen.call_args.args[0].get_header("Authorization"), "Bearer secret-token"
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

    def test_users_endpoint_lists_users_with_a_valid_bearer_token(self):
        user_model = get_user_model()
        user_model.objects.create_user(
            username="scim-user", email="scim-user@example.test", password="safe-password"
        )
        with patch.dict("os.environ", {"SCIM_BEARER_TOKEN": "expected"}, clear=False):
            response = self.client.get(
                "/scim/v2/Users?count=1000&startIndex=1",
                HTTP_AUTHORIZATION="Bearer expected",
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, "scim-user@example.test")

    def test_users_endpoint_creates_a_scim_user(self):
        payload = {
            "schemas": ["urn:ietf:params:scim:schemas:core:2.0:User"],
            "userName": "provisioned@example.test",
            "name": {"givenName": "Provisioned", "familyName": "User"},
            "emails": [{"value": "provisioned@example.test", "primary": True}],
            "active": True,
        }
        with patch.dict("os.environ", {"SCIM_BEARER_TOKEN": "expected"}, clear=False):
            response = self.client.post(
                "/scim/v2/Users",
                data=json.dumps(payload),
                content_type="application/scim+json",
                HTTP_AUTHORIZATION="Bearer expected",
            )
        self.assertEqual(response.status_code, 201)
        user = get_user_model().objects.get(email="provisioned@example.test")
        self.assertEqual(user.scim_username, "provisioned@example.test")
        self.assertIsNotNone(user.scim_id)

    def test_groups_endpoint_lists_django_groups(self):
        group = Group.objects.create(name="Ledger editors")
        with patch.dict("os.environ", {"SCIM_BEARER_TOKEN": "expected"}, clear=False):
            response = self.client.get(
                "/scim/v2/Groups?count=1000&startIndex=1",
                HTTP_AUTHORIZATION="Bearer expected",
            )
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, group.name)
