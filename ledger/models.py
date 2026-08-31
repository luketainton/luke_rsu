from django.conf import settings
from django.contrib.auth.models import AbstractUser
from django.db import models
from django.db.models.signals import post_save
from django.dispatch import receiver


class User(AbstractUser):
    email = models.EmailField(unique=True)
    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = ["username"]


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
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        abstract = True


class Grant(WorkspaceRecord):
    pass


class Vest(WorkspaceRecord):
    withheld_units = models.DecimalField(max_digits=16, decimal_places=4, default=0)
    income_tax = models.DecimalField(max_digits=16, decimal_places=2, default=0)
    employee_nic = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class Sale(WorkspaceRecord):
    fees_gbp = models.DecimalField(max_digits=16, decimal_places=2, default=0)


class FxRate(models.Model):
    workspace = models.ForeignKey(Workspace, on_delete=models.CASCADE)
    label = models.CharField(max_length=120)
    method = models.CharField(
        max_length=20,
        choices=[("spot", "HMRC spot"), ("monthly", "HMRC monthly"), ("average", "HMRC average")],
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
