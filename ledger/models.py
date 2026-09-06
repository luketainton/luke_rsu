from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
from django.db.models.functions import Lower
from django.db.models.signals import post_save, pre_save
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
    contract_date = models.DateField(null=True, blank=True)
    units = models.DecimalField(max_digits=16, decimal_places=4)
    usd_price = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    notes = models.TextField(blank=True)
    beneficial_owner = models.CharField(max_length=160, blank=True)
    capacity = models.CharField(max_length=40, default="personal", blank=True)
    account_reference = models.CharField(max_length=160, blank=True)
    evidence_url = models.URLField(blank=True)
    source_key = models.CharField(max_length=64, null=True, blank=True, editable=False)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def hmrc_financial_year(self):
        """Return the UK tax year containing this event (5 April to 4 April)."""
        event_date = self.tax_date
        start_year = (
            event_date.year if (event_date.month, event_date.day) >= (4, 5) else event_date.year - 1
        )
        return f"{start_year}/{(start_year + 1) % 100:02d}"

    @property
    def tax_date(self):
        return self.contract_date or self.date

    @property
    def gbp_per_usd(self):
        """Derive GBP per USD from the saved rate that covers this event date."""
        rate = (
            FxRate.objects.filter(
                workspace=self.workspace, starts_on__lte=self.tax_date, ends_on__gte=self.tax_date
            )
            .order_by("-starts_on", "-id")
            .first()
        )
        return None if rate is None else Decimal(1) / rate.usd_per_gbp

    class Meta:
        abstract = True


class Grant(WorkspaceRecord):
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
    # Optional direct link for records that have no usable Grant ID.
    security = models.ForeignKey(Security, on_delete=models.SET_NULL, null=True, blank=True)
    capital_cost_gbp = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Total allowable CGT acquisition cost for the shares acquired, if evidenced.",
    )
    withholding_treatment = models.CharField(
        max_length=20,
        choices=[
            ("net", "Net shares acquired (legacy/default)"),
            ("gross_sell_to_cover", "Gross shares acquired; withheld shares sold to cover"),
        ],
        default="net",
        blank=True,
    )
    sell_to_cover_proceeds_gbp = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Net GBP proceeds for the withheld-share sell-to-cover disposal, if evidenced.",
    )
    sell_to_cover_fees_gbp = models.DecimalField(
        max_digits=16, decimal_places=2, default=0, blank=True
    )
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
    # Optional direct link for open-market or imported sales without a Grant ID.
    security = models.ForeignKey(Security, on_delete=models.SET_NULL, null=True, blank=True)
    proceeds_gbp = models.DecimalField(
        max_digits=16,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Net disposal proceeds in GBP, if evidenced directly.",
    )
    fees_gbp = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_key"],
                condition=Q(source_key__isnull=False),
                name="unique_imported_sale",
            )
        ]


class Purchase(WorkspaceRecord):
    """An open-market acquisition that can enter a Section 104 pool."""

    security = models.ForeignKey(Security, on_delete=models.SET_NULL, null=True, blank=True)
    capital_cost_gbp = models.DecimalField(max_digits=16, decimal_places=2, null=True, blank=True)
    fees_gbp = models.DecimalField(max_digits=16, decimal_places=2, default=0)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "source_key"],
                condition=Q(source_key__isnull=False),
                name="unique_imported_purchase",
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


class Section104OpeningBalance(models.Model):
    """An evidenced pool balance carried into the ledger."""

    workspace = models.ForeignKey(
        Workspace, on_delete=models.CASCADE, related_name="opening_balances"
    )
    security = models.ForeignKey(
        Security, on_delete=models.CASCADE, related_name="opening_balances"
    )
    effective_on = models.DateField()
    units = models.DecimalField(max_digits=16, decimal_places=4)
    pool_cost_gbp = models.DecimalField(max_digits=16, decimal_places=2)
    source_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "security"], name="unique_workspace_security_opening_balance"
            )
        ]


class PoolAdjustment(models.Model):
    """Manual, evidenced pool movement for a corporate action."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    effective_on = models.DateField()
    units_delta = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    cost_delta_gbp = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    reason = models.CharField(max_length=160)
    source_url = models.URLField(blank=True)
    notes = models.TextField(blank=True)


class Section104Snapshot(models.Model):
    """Immutable JSON evidence of a generated Section 104 working paper."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    security = models.ForeignKey(Security, on_delete=models.CASCADE)
    created_at = models.DateTimeField(auto_now_add=True)
    engine_version = models.CharField(max_length=40)
    input_hash = models.CharField(max_length=64)
    payload = models.JSONField()

    def save(self, *args, **kwargs):
        if self.pk:
            raise ValueError("Section 104 snapshots are immutable")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValueError("Section 104 snapshots are immutable")


class StockPrice(models.Model):
    """A dated USD share price kept separately for each private workspace."""

    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE, related_name="stock_prices")
    security = models.ForeignKey(Security, on_delete=models.CASCADE, related_name="stock_prices")
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
                fields=["workspace", "security", "price_date", "source"],
                name="unique_workspace_security_price_date_source",
            )
        ]
        ordering = ["security__ticker", "-price_date"]


@receiver(post_save, sender=User)
def create_private_workspace(sender, instance, created, **kwargs):
    if created:
        workspace = Workspace.objects.create(
            name=f"{instance.get_full_name() or instance.email}'s private ledger"
        )
        WorkspaceMembership.objects.create(
            workspace=workspace, user=instance, role=WorkspaceMembership.Role.OWNER
        )


@receiver(pre_save, sender=Vest)
@receiver(pre_save, sender=Sale)
def infer_event_security_on_save(sender, instance, **kwargs):
    """Enrich every write path, including imports and Django admin."""
    from .enrichment import enrich_event_security

    enrich_event_security(instance)


@receiver(post_save, sender=Grant)
def backfill_event_security_from_grant(sender, instance, **kwargs):
    """Backfill earlier imported events when their Grant is created later."""
    from .enrichment import enrich_event_security

    for event_model in (Vest, Sale):
        events = event_model.objects.filter(
            workspace_id=instance.workspace_id,
            broker_id=instance.broker_id,
            grant_id=instance.grant_id,
            security__isnull=True,
        )
        for event in events.iterator():
            enrich_event_security(event)
            if event.security_id is not None:
                event.save(update_fields=["security"])
