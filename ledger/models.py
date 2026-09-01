from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.db.models.signals import post_save
from django.dispatch import receiver
from django_scim.models import AbstractSCIMUserMixin


class User(AbstractSCIMUserMixin, AbstractUser):
    email = models.EmailField(unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]

    @property
    def scim_groups(self):
        """Expose Django groups through the SCIM 2.0 user resource."""
        return self.groups.all()


class Workspace(models.Model):
    name = models.CharField(max_length=160)
    created_at = models.DateTimeField(auto_now_add=True)


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", "Owner"
        EDITOR = "editor", "Editor"
        VIEWER = "viewer", "Viewer"

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="workspace_memberships"
    )
    role = models.CharField(max_length=10, choices=Role.choices)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["workspace", "user"], name="unique_workspace_member")
        ]


class Broker(models.Model):
    """A broker available to one workspace's records."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="brokers")
    name = models.CharField(max_length=120)

    class Meta:
        constraints = [
            models.UniqueConstraint(Lower("name"), "workspace", name="unique_workspace_broker")
        ]
        ordering = ["name"]

    def __str__(self):
        return self.name


class Security(models.Model):
    """One class of shares, with its own UK Section 104 holding."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="securities")
    name = models.CharField(max_length=160)
    ticker = models.CharField(max_length=20)
    isin = models.CharField(max_length=12, blank=True)
    share_class = models.CharField(max_length=80, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "ticker", "share_class"],
                name="unique_workspace_security_share_class",
            )
        ]
        ordering = ["ticker", "share_class", "name"]

    def __str__(self):
        if self.share_class:
            return f"{self.ticker} ({self.share_class})"
        return f"{self.ticker} — {self.name}"


class WorkspaceRecord(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    grant_id = models.CharField(max_length=120, blank=True)
    broker = models.ForeignKey(Broker, on_delete=models.SET_NULL, null=True, blank=True)
    date = models.DateField()
    units = models.DecimalField(max_digits=16, decimal_places=4)
    usd_price = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    notes = models.TextField(blank=True)
    source_key = models.CharField(max_length=64, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def hmrc_financial_year(self):
        """Return the UK tax year containing this event (5 April to 4 April)."""
        start_year = (
            self.date.year if (self.date.month, self.date.day) >= (4, 5) else self.date.year - 1
        )
        return f"{start_year}/{(start_year + 1) % 100:02d}"

    @property
    def gbp_per_usd(self):
        """Derive GBP per USD from the saved rate that covers this event date."""
        rate = (
            FxRate.objects.filter(
                workspace=self.workspace, starts_on__lte=self.date, ends_on__gte=self.date
            )
            .order_by("-starts_on", "-id")
            .first()
        )
        return None if rate is None else Decimal(1) / rate.usd_per_gbp

    class Meta:
        abstract = True


class Grant(WorkspaceRecord):
    ticker = models.CharField(max_length=20, blank=True)
    security = models.ForeignKey(Security, on_delete=models.SET_NULL, null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_key"],
                condition=Q(source_key__isnull=False),
                name="unique_imported_grant",
            )
        ]


class Vest(WorkspaceRecord):
    withheld_units = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    income_tax = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    employee_nic = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_key"],
                condition=Q(source_key__isnull=False),
                name="unique_imported_vest",
            )
        ]


class Sale(WorkspaceRecord):
    fees_gbp = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_key"],
                condition=Q(source_key__isnull=False),
                name="unique_imported_sale",
            )
        ]


class FxRate(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    label = models.CharField(max_length=120)
    method = models.CharField(
        max_length=20,
        choices=[
            ("spot", "HMRC spot"),
            ("monthly", "HMRC monthly"),
            ("average", "HMRC average"),
            ("wise", "Wise historical spot"),
            ("manual", "Manual or migrated rate"),
        ],
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    usd_per_gbp = models.DecimalField(max_digits=16, decimal_places=8)
    source_url = models.URLField()


class StockPrice(models.Model):
    """A dated USD share price kept separately for each private workspace."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="stock_prices")
    ticker = models.CharField(max_length=20)
    price_date = models.DateField()
    usd_price = models.DecimalField(max_digits=16, decimal_places=6)
    source = models.CharField(
        max_length=20,
        choices=[("manual", "Manual"), ("finnhub", "Finnhub live quote")],
        default="manual",
    )
    fetched_at = models.DateTimeField(null=True, blank=True)
    source_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "ticker", "price_date", "source"],
                name="unique_workspace_ticker_price_date_source",
            )
        ]
        ordering = ["ticker", "-price_date"]


@receiver(post_save, sender=User)
def create_private_workspace(sender, instance, created, **kwargs):
    if created:
        workspace = Workspace.objects.create(
            name=f"{instance.get_full_name() or instance.email}'s private ledger"
        )
        WorkspaceMembership.objects.create(
            workspace=workspace, user=instance, role=WorkspaceMembership.Role.OWNER
        )
