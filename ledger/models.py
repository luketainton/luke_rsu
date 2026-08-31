from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models import Q
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


class WorkspaceRecord(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    date = models.DateField()
    units = models.DecimalField(max_digits=16, decimal_places=4)
    usd_price = models.DecimalField(max_digits=16, decimal_places=6, null=True, blank=True)
    gbp_per_usd = models.DecimalField(max_digits=16, decimal_places=8, null=True, blank=True)
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

    class Meta:
        abstract = True


class Grant(WorkspaceRecord):
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
        ],
    )
    starts_on = models.DateField()
    ends_on = models.DateField()
    usd_per_gbp = models.DecimalField(max_digits=16, decimal_places=8)
    source_url = models.URLField()


@receiver(post_save, sender=User)
def create_private_workspace(sender, instance, created, **kwargs):
    if created:
        workspace = Workspace.objects.create(
            name=f"{instance.get_full_name() or instance.email}'s private ledger"
        )
        WorkspaceMembership.objects.create(
            workspace=workspace, user=instance, role=WorkspaceMembership.Role.OWNER
        )
