from django import forms

from .broker_rules import grants_for_event_broker
from .importers import IMPORT_TYPE_CHOICES
from .models import (
    Broker,
    FxRate,
    Grant,
    PoolAdjustment,
    Purchase,
    Sale,
    Section104OpeningBalance,
    Security,
    StockPrice,
    Vest,
    Workspace,
    WorkspaceMembership,
)


class RecordBaseForm(forms.ModelForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["broker"].queryset = Broker.objects.filter(workspace=workspace)
        self.fields["broker"].empty_label = "No broker selected"

    class Meta:
        fields = [
            "broker",
            "grant_id",
            "date",
            "contract_date",
            "units",
            "usd_price",
            "beneficial_owner",
            "capacity",
            "account_reference",
            "evidence_url",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "contract_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class GrantForm(RecordBaseForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, workspace=workspace, **kwargs)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)
        self.fields["security"].empty_label = "No security selected"

    class Meta(RecordBaseForm.Meta):
        model = Grant
        fields = [
            "broker",
            "grant_id",
            "security",
            "date",
            "contract_date",
            "units",
            "usd_price",
            "beneficial_owner",
            "capacity",
            "account_reference",
            "evidence_url",
            "notes",
        ]


class SecurityForm(forms.ModelForm):
    def clean_ticker(self):
        return self.cleaned_data["ticker"].strip().upper()

    class Meta:
        model = Security
        fields = ["name", "ticker", "isin", "share_class"]


class BrokerGrantRecordForm(RecordBaseForm):
    """Use the selected broker's existing grants as vest/sale Grant ID choices."""

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, workspace=workspace, **kwargs)
        broker_id = self.data.get(self.add_prefix("broker")) if self.is_bound else None
        broker_id = broker_id or self.initial.get("broker") or self.instance.broker_id
        grant_ids = []
        if broker_id:
            broker = Broker.objects.filter(workspace=workspace, id=broker_id).first()
            grant_ids = grants_for_event_broker(
                Grant.objects.filter(workspace=workspace), broker
            ).exclude(grant_id="")
            grant_ids = grant_ids.order_by("grant_id").values_list("grant_id", flat=True).distinct()
        self.fields["grant_id"] = forms.ChoiceField(
            choices=[("", "No Grant ID selected")]
            + [(grant_id, grant_id) for grant_id in grant_ids],
            required=False,
            widget=forms.Select(attrs={"data-grant-id-select": "true"}),
        )
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)
        self.fields["security"].required = False
        self.fields["security"].empty_label = "Infer from Grant ID where possible"


class VestForm(BrokerGrantRecordForm):
    class Meta(RecordBaseForm.Meta):
        model = Vest
        fields = RecordBaseForm.Meta.fields + [
            "security",
            "capital_cost_gbp",
            "withholding_treatment",
            "withheld_units",
            "sell_to_cover_proceeds_gbp",
            "sell_to_cover_fees_gbp",
            "income_tax",
            "employee_nic",
        ]


class SaleForm(BrokerGrantRecordForm):
    class Meta(RecordBaseForm.Meta):
        model = Sale
        fields = RecordBaseForm.Meta.fields + ["security", "proceeds_gbp", "fees_gbp"]


class PurchaseForm(forms.ModelForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["broker"].queryset = Broker.objects.filter(workspace=workspace)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)
        self.fields["security"].empty_label = "Select security"

    class Meta:
        model = Purchase
        fields = [
            "broker",
            "security",
            "date",
            "contract_date",
            "units",
            "usd_price",
            "capital_cost_gbp",
            "fees_gbp",
            "beneficial_owner",
            "capacity",
            "account_reference",
            "evidence_url",
            "notes",
        ]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "contract_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class SimulationForm(forms.Form):
    TRANSACTION_CHOICES = [
        ("sale", "Sale"),
        ("purchase", "Purchase"),
        ("vest", "Vest"),
    ]

    security = forms.ModelChoiceField(queryset=Security.objects.none(), label="Security")
    transaction = forms.ChoiceField(choices=TRANSACTION_CHOICES, label="Transaction")
    date = forms.DateField(widget=forms.DateInput(attrs={"type": "date"}))
    units = forms.DecimalField(max_digits=16, decimal_places=4, min_value=0)
    usd_price = forms.DecimalField(max_digits=16, decimal_places=6, required=False)
    capital_cost_gbp = forms.DecimalField(max_digits=16, decimal_places=2, required=False)
    proceeds_gbp = forms.DecimalField(max_digits=16, decimal_places=2, required=False)
    fees_gbp = forms.DecimalField(max_digits=16, decimal_places=2, required=False, initial=0)

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)

    def clean(self):
        cleaned = super().clean()
        transaction = cleaned.get("transaction")
        if transaction in {"purchase", "vest"} and not (
            cleaned.get("capital_cost_gbp") is not None or cleaned.get("usd_price") is not None
        ):
            raise forms.ValidationError(
                "Enter either a GBP cost or a USD price for this acquisition."
            )
        if transaction == "sale" and not (
            cleaned.get("proceeds_gbp") is not None or cleaned.get("usd_price") is not None
        ):
            raise forms.ValidationError("Enter either GBP proceeds or a USD sale price.")
        return cleaned


class PoolAdjustmentForm(forms.ModelForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)

    class Meta:
        model = PoolAdjustment
        fields = [
            "security",
            "effective_on",
            "units_delta",
            "cost_delta_gbp",
            "reason",
            "source_url",
            "notes",
        ]
        widgets = {
            "effective_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class Section104OpeningBalanceForm(forms.ModelForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)

    class Meta:
        model = Section104OpeningBalance
        fields = ["security", "effective_on", "units", "pool_cost_gbp", "source_url", "notes"]
        widgets = {
            "effective_on": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class BrokerForm(forms.ModelForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.workspace = workspace

    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        matches = Broker.objects.filter(workspace=self.workspace, name__iexact=name)
        if self.instance.pk:
            matches = matches.exclude(pk=self.instance.pk)
        if matches.exists():
            raise forms.ValidationError("A broker with this name already exists.")
        return name

    class Meta:
        model = Broker
        fields = ["name"]


class FxRateForm(forms.ModelForm):
    source_url = forms.URLField(assume_scheme="https")

    class Meta:
        model = FxRate
        fields = ["label", "method", "starts_on", "ends_on", "usd_per_gbp", "source_url"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }


class StockPriceForm(forms.ModelForm):
    source_url = forms.URLField(required=False, assume_scheme="https")

    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)
        self.fields["security"].empty_label = "No security selected"

    class Meta:
        model = StockPrice
        fields = ["security", "price_date", "usd_price", "source_url", "notes"]
        widgets = {
            "price_date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class MembershipForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=WorkspaceMembership.Role.choices)


class WorkspaceForm(forms.ModelForm):
    def clean_name(self):
        name = self.cleaned_data["name"].strip()
        if not name:
            raise forms.ValidationError("Enter a ledger name.")
        return name

    class Meta:
        model = Workspace
        fields = ["name"]


class BenefitHistoryImportForm(forms.Form):
    import_type = forms.ChoiceField(
        choices=IMPORT_TYPE_CHOICES,
        required=False,
        initial="etrade_benefit_history",
        label="Import type",
    )
    file = forms.FileField(help_text="Upload an Excel .xlsx or CSV export.")

    def clean_import_type(self):
        return self.cleaned_data.get("import_type") or "etrade_benefit_history"

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith((".xlsx", ".csv")):
            raise forms.ValidationError("Upload an Excel .xlsx or CSV file.")
        if upload.size > 10 * 1024 * 1024:
            raise forms.ValidationError("The import file must be no larger than 10 MB.")
        return upload


class HmrcRateFetchForm(forms.Form):
    method = forms.ChoiceField(
        choices=[("monthly", "HMRC monthly"), ("spot", "HMRC spot"), ("average", "HMRC average")]
    )
    rate_date = forms.DateField(
        label="Date in the required period",
        widget=forms.DateInput(attrs={"type": "date"}),
    )


class WiseRateFetchForm(forms.Form):
    rate_date = forms.DateField(
        label="Event date",
        widget=forms.DateInput(attrs={"type": "date"}),
    )
