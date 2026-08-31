from django import forms

from .models import FxRate, Grant, Sale, Vest, WorkspaceMembership


class RecordBaseForm(forms.ModelForm):
    class Meta:
        fields = ["date", "units", "usd_price", "gbp_per_usd", "notes"]
        widgets = {
            "date": forms.DateInput(attrs={"type": "date"}),
            "notes": forms.Textarea(attrs={"rows": 2}),
        }


class GrantForm(RecordBaseForm):
    class Meta(RecordBaseForm.Meta):
        model = Grant


class VestForm(RecordBaseForm):
    class Meta(RecordBaseForm.Meta):
        model = Vest
        fields = RecordBaseForm.Meta.fields + ["withheld_units", "income_tax", "employee_nic"]


class SaleForm(RecordBaseForm):
    class Meta(RecordBaseForm.Meta):
        model = Sale
        fields = RecordBaseForm.Meta.fields + ["fees_gbp"]


class FxRateForm(forms.ModelForm):
    source_url = forms.URLField(assume_scheme="https")

    class Meta:
        model = FxRate
        fields = ["label", "method", "starts_on", "ends_on", "usd_per_gbp", "source_url"]
        widgets = {
            "starts_on": forms.DateInput(attrs={"type": "date"}),
            "ends_on": forms.DateInput(attrs={"type": "date"}),
        }


class MembershipForm(forms.Form):
    email = forms.EmailField()
    role = forms.ChoiceField(choices=WorkspaceMembership.Role.choices)


class BenefitHistoryImportForm(forms.Form):
    file = forms.FileField(help_text="Upload an E*TRADE Benefit History .xlsx export.")

    def clean_file(self):
        upload = self.cleaned_data["file"]
        if not upload.name.lower().endswith(".xlsx"):
            raise forms.ValidationError("Upload an Excel .xlsx file.")
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
