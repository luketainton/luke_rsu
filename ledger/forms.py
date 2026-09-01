from django import forms

from .importers import IMPORT_TYPE_CHOICES
from .models import (
    Broker,
    FxRate,
    Grant,
    Sale,
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
        fields = ["broker", "grant_id", "date", "units", "usd_price", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class GrantForm(RecordBaseForm):
    def __init__(self, *args, workspace, **kwargs):
        super().__init__(*args, workspace=workspace, **kwargs)
        self.fields["security"].queryset = Security.objects.filter(workspace=workspace)
        self.fields["security"].empty_label = "No security selected"

    class Meta(RecordBaseForm.Meta):
        model = Grant
        fields = ["broker", "grant_id", "security", "ticker", "date", "units", "usd_price", "notes"]

    def clean_ticker(self):
        security = self.cleaned_data.get("security")
        return security.ticker if security else self.cleaned_data["ticker"].strip().upper()


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
            grant_ids = Grant.objects.filter(workspace=workspace, broker_id=broker_id).exclude(
                grant_id=""
            )
            grant_ids = grant_ids.order_by("grant_id").values_list("grant_id", flat=True).distinct()
        self.fields["grant_id"] = forms.ChoiceField(
            choices=[("", "No Grant ID selected")]
            + [(grant_id, grant_id) for grant_id in grant_ids],
            required=False,
            widget=forms.Select(attrs={"data-grant-id-select": "true"}),
        )


class VestForm(BrokerGrantRecordForm):
    class Meta(RecordBaseForm.Meta):
        model = Vest
        fields = RecordBaseForm.Meta.fields + ["withheld_units", "income_tax", "employee_nic"]


class SaleForm(BrokerGrantRecordForm):
    class Meta(RecordBaseForm.Meta):
        model = Sale
        fields = RecordBaseForm.Meta.fields + ["fees_gbp"]


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

    def clean_ticker(self):
        return self.cleaned_data["ticker"].strip().upper()

    class Meta:
        model = StockPrice
        fields = ["ticker", "price_date", "usd_price", "source_url", "notes"]
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
