"""Stateless MCP Streamable HTTP endpoint for the RSU ledger."""

import json
import re
from hashlib import sha256

from django.conf import settings
from django.core.exceptions import RequestDataTooBig
from django.core.serializers.json import DjangoJSONEncoder
from django.db import transaction
from django.http import HttpResponse, JsonResponse
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_exempt

from .mcp_writes import MAX_ID, can_write, write_record, write_tools
from .models import Grant, MCPApiKey, Purchase, Sale, Vest

PROTOCOL_VERSIONS = ("2025-11-25", "2025-06-18", "2025-03-26")
MAX_BODY_BYTES = 16_384
KEY_PATTERN = re.compile(r"Bearer (rsu_mcp_[A-Za-z0-9_-]{43})", re.IGNORECASE | re.ASCII)
COMMON_FIELDS = (
    "id",
    "grant_id",
    "date",
    "contract_date",
    "units",
    "usd_price",
    "security_id",
    "broker_id",
)
RECORDS = {
    "grants": (Grant, ()),
    "vests": (
        Vest,
        (
            "capital_cost_gbp",
            "withheld_units",
            "income_tax",
            "employee_nic",
            "withholding_treatment",
            "sell_to_cover_proceeds_gbp",
            "sell_to_cover_fees_gbp",
        ),
    ),
    "sales": (Sale, ("proceeds_gbp", "fees_gbp")),
    "purchases": (Purchase, ("capital_cost_gbp", "fees_gbp")),
}

READ_TOOLS = [
    {
        "name": f"list_{name}",
        "description": (
            f"List {name} in the ledger linked to this key, ordered by ascending record ID. "
            "Monetary values and share quantities are decimal strings."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "after_id": {"type": "integer", "minimum": 0, "maximum": MAX_ID, "default": 0},
                "limit": {"type": "integer", "minimum": 1, "maximum": 100, "default": 50},
            },
            "additionalProperties": False,
        },
        "annotations": {"readOnlyHint": True, "openWorldHint": False},
    }
    for name in RECORDS
]


def rpc_error(request_id, code, message, status=200):
    return JsonResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status=status,
    )


def list_records(params, workspace_id):
    name = params.get("name")
    if not isinstance(name, str) or not name.startswith("list_"):
        raise ValueError("Unknown tool.")
    record = RECORDS.get(name.removeprefix("list_"))
    if record is None:
        raise ValueError("Unknown tool.")
    arguments = params.get("arguments", {})
    if not isinstance(arguments, dict) or arguments.keys() - {"after_id", "limit"}:
        raise ValueError("Expected only after_id and limit.")
    after_id, limit = arguments.get("after_id", 0), arguments.get("limit", 50)
    if type(after_id) is not int or not 0 <= after_id <= MAX_ID:
        raise ValueError("after_id must be a non-negative record ID.")
    if type(limit) is not int or not 1 <= limit <= 100:
        raise ValueError("limit must be an integer between 1 and 100.")

    model, extra_fields = record
    rows = list(
        model.objects.filter(workspace_id=workspace_id, pk__gt=after_id)
        .order_by("pk")
        .values(*COMMON_FIELDS, *extra_fields)[: limit + 1]
    )
    data = {
        "workspace_id": workspace_id,
        "records": rows[:limit],
        "next_after_id": rows[limit - 1]["id"] if len(rows) > limit else None,
    }
    return data


def tool_result(data):
    return {
        "structuredContent": data,
        "content": [{"type": "text", "text": json.dumps(data, cls=DjangoJSONEncoder)}],
        "isError": "errors" in data,
    }


def authenticate(digest, *, lock=False):
    keys = MCPApiKey.objects.select_related("membership__workspace")
    if lock:
        keys = keys.select_related("membership__user").select_for_update()
    return keys.filter(
        digest=digest,
        expires_at__gt=timezone.now(),
        membership__user__is_active=True,
    ).first()


def call_tool(params, key):
    name = params.get("name")
    if not isinstance(name, str):
        raise TypeError("Tool name must be a string.")
    if name.startswith("list_"):
        return list_records(params, key.membership.workspace_id)
    if not can_write(key):
        raise PermissionError("Write access is disabled for this key.")
    with transaction.atomic():
        # Recheck consent and account access under the same lock as the write.
        locked_key = authenticate(key.digest, lock=True)
        if locked_key is None:
            raise PermissionError("This key no longer has access.")
        return write_record(name, params.get("arguments"), locked_key)


def dispatch(message, key):
    if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
        return rpc_error(None, -32600, "Invalid Request", status=400)

    method = message.get("method")
    request_id = message.get("id")
    if not isinstance(method, str) or ("id" in message and type(request_id) not in (str, int)):
        return rpc_error(None, -32600, "Invalid Request", status=400)
    if "id" not in message:
        return HttpResponse(status=202)

    params = message.get("params", {})
    if not isinstance(params, dict):
        return rpc_error(request_id, -32602, "Invalid params")

    if method == "initialize":
        version = params.get("protocolVersion")
        if not isinstance(version, str):
            return rpc_error(request_id, -32602, "protocolVersion is required")
        result = {
            "protocolVersion": version if version in PROTOCOL_VERSIONS else PROTOCOL_VERSIONS[0],
            "capabilities": {"tools": {"listChanged": False}},
            "serverInfo": {"name": "rsu-ledger", "version": settings.APP_VERSION},
        }
    elif method == "ping":
        result = {}
    elif method == "tools/list":
        result = {"tools": READ_TOOLS + (list(write_tools()) if can_write(key) else [])}
    elif method == "tools/call":
        try:
            result = tool_result(call_tool(params, key))
        except PermissionError as error:
            return rpc_error(request_id, -32000, str(error))
        except (TypeError, ValueError) as error:
            return rpc_error(request_id, -32602, str(error))
    else:
        return rpc_error(request_id, -32601, "Method not found")
    return JsonResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


@csrf_exempt  # Every request requires its own Authorization header and has no session fallback.
@never_cache
def endpoint(request):
    # Native clients omit Origin. Browser access is unsupported.
    if "Origin" in request.headers:
        return HttpResponse(status=403)

    match = KEY_PATTERN.fullmatch(request.headers.get("Authorization", ""))
    key = authenticate(sha256(match[1].encode("ascii")).hexdigest()) if match else None
    if key is None:
        return HttpResponse(status=401, headers={"WWW-Authenticate": 'Bearer realm="RSU MCP"'})

    if request.method != "POST":
        return HttpResponse(status=405, headers={"Allow": "POST"})
    if request.content_type != "application/json":
        return HttpResponse(status=415)
    if not request.accepts("application/json"):
        return HttpResponse(status=406)
    version = request.headers.get("MCP-Protocol-Version", "2025-03-26")
    if version not in PROTOCOL_VERSIONS:
        return HttpResponse(status=400)

    try:
        if len(request.body) > MAX_BODY_BYTES:
            return HttpResponse(status=413)
        message = json.loads(request.body.decode("utf-8"))
    except RequestDataTooBig:
        return HttpResponse(status=413)
    except ValueError, RecursionError:
        return rpc_error(None, -32700, "Parse error", status=400)
    return dispatch(message, key)
