"""Write MCP records using the ledger's existing form validation."""

from django import forms
from django.forms.models import model_to_dict

from .forms import GrantForm, PurchaseForm, SaleForm, VestForm
from .fx import EventRateUnavailable, ensure_event_rate
from .workspaces import can_edit

RECORD_FORMS = {"grant": GrantForm, "vest": VestForm, "sale": SaleForm, "purchase": PurchaseForm}
MAX_ID = 2**63 - 1
ID_SCHEMA = {"type": "integer", "minimum": 1, "maximum": MAX_ID}


def field_schema(field):
    if isinstance(field, forms.ModelChoiceField):
        schema = ID_SCHEMA.copy()
    else:
        schema = {"type": "string", "maxLength": getattr(field, "max_length", None) or 4096}
        if isinstance(field, forms.DateField):
            schema["format"] = "date"
        if isinstance(field, forms.DecimalField):
            schema["description"] = "Decimal string"
        if isinstance(field, forms.ChoiceField):
            schema["enum"] = [value for value, _ in field.choices]
    if not field.required:
        schema["type"] = [schema["type"], "null"]
        if "enum" in schema:
            schema["enum"].append(None)
    return schema


def write_tools():
    for record, form_class in RECORD_FORMS.items():
        fields = form_class.base_fields
        for action in ("create", "update", "delete"):
            properties = {}
            required = []
            if action != "create":
                properties["record_id"] = ID_SCHEMA
                required.append("record_id")
            if action != "delete":
                data = {
                    "type": "object",
                    "properties": {name: field_schema(field) for name, field in fields.items()},
                    "additionalProperties": False,
                }
                if action == "create":
                    data["required"] = [name for name, field in fields.items() if field.required]
                else:
                    data["minProperties"] = 1
                properties["fields"] = data
                required.append("fields")
            yield {
                "name": f"{action}_{record}",
                "description": f"{action.capitalize()} a {record} in the ledger linked to this key.",
                "inputSchema": {
                    "type": "object",
                    "properties": properties,
                    "required": required,
                    "additionalProperties": False,
                },
                "annotations": {
                    "readOnlyHint": False,
                    "destructiveHint": action != "create",
                    "openWorldHint": False,
                },
            }


def can_write(key):
    return key.allow_write and can_edit(key.membership)


def valid_id(value):
    return type(value) is int and 1 <= value <= MAX_ID


def save_record(form_class, workspace, record, fields):
    if not isinstance(fields, dict) or not fields or fields.keys() - form_class.base_fields.keys():
        raise ValueError("Provide at least one supported record field.")
    for name, value in fields.items():
        if value is None:
            continue
        field = form_class.base_fields[name]
        if isinstance(field, forms.ModelChoiceField):
            if not valid_id(value):
                raise ValueError(f"{name} must be a positive integer ID.")
        elif not isinstance(value, str):
            raise TypeError(f"{name} must be a string.")
    data = model_to_dict(record, fields=form_class.base_fields) if record is not None else {}
    data.update(fields)
    form = form_class(data, workspace=workspace, instance=record)
    if not form.is_valid():
        return {"errors": form.errors.get_json_data()}
    item = form.save(commit=False)
    item.workspace = workspace
    try:
        ensure_event_rate(workspace, item.date)
    except EventRateUnavailable as error:
        return {"errors": {"date": [{"message": str(error), "code": "rate_unavailable"}]}}
    item.save()
    return {"record_id": item.pk}


def write_record(name, arguments, key):
    action, _, record_type = name.partition("_")
    form_class = RECORD_FORMS.get(record_type)
    if action not in {"create", "update", "delete"} or form_class is None:
        raise ValueError("Unknown tool.")
    if not can_write(key):
        raise PermissionError("Write access is disabled for this key.")

    expected = {"fields"} if action == "create" else {"record_id"}
    if action == "update":
        expected.add("fields")
    if not isinstance(arguments, dict) or arguments.keys() != expected:
        raise ValueError(f"Expected arguments: {', '.join(sorted(expected))}.")

    workspace = key.membership.workspace
    record = None
    if action != "create":
        record_id = arguments["record_id"]
        if not valid_id(record_id):
            raise ValueError("record_id must be a positive integer ID.")
        record = (
            form_class._meta.model.objects.select_for_update()
            .filter(pk=record_id, workspace=workspace)
            .first()
        )
        if record is None:
            return {
                "errors": {"record_id": [{"message": "Record not found.", "code": "not_found"}]}
            }
        if action == "delete":
            record.delete()
            return {"record_id": record_id}
    return save_record(form_class, workspace, record, arguments["fields"])
