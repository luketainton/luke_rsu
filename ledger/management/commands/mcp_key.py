import secrets
from datetime import timedelta
from hashlib import sha256

from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone

from ledger.models import MCPApiKey, WorkspaceMembership


class Command(BaseCommand):
    help = "Issue or revoke a read-only MCP API key."

    def add_arguments(self, parser):
        actions = parser.add_subparsers(dest="action", required=True)
        issue = actions.add_parser("issue")
        issue.add_argument("email")
        issue.add_argument("workspace_id", type=int)
        revoke = actions.add_parser("revoke")
        revoke.add_argument("key_id", type=int)

    def handle(self, *args, **options):
        if options["action"] == "revoke":
            deleted, _ = MCPApiKey.objects.filter(pk=options["key_id"]).delete()
            if not deleted:
                raise CommandError("No such MCP key.")
            return "MCP key revoked."

        membership = WorkspaceMembership.objects.filter(
            user__email=options["email"], user__is_active=True, workspace_id=options["workspace_id"]
        ).first()
        if membership is None:
            raise CommandError("No active membership for that email and workspace.")
        token = "rsu_mcp_" + secrets.token_urlsafe(32)
        key = MCPApiKey.objects.create(
            membership=membership,
            digest=sha256(token.encode("ascii")).hexdigest(),
            expires_at=timezone.now() + timedelta(days=90),
        )
        self.stderr.write(f"Key ID: {key.pk}. Expires: {key.expires_at.isoformat()}.")
        return token
