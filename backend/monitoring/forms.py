from django import forms

from monitoring.models import County, FloodPrediction


class HistoricalDataFilterForm(forms.Form):
    county = forms.ModelChoiceField(
        queryset=County.objects.none(),
        required=False,
        empty_label="All counties",
        to_field_name="slug",
    )
    risk_level = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All risk levels"),
            *FloodPrediction.RiskLevel.choices,
        ],
    )
    start_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"}
        ),
    )
    end_date = forms.DateField(
        required=False,
        widget=forms.DateInput(
            attrs={"type": "date"}
        ),
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["county"].queryset = (
            County.objects.order_by("name")
        )

    def clean(self):
        cleaned_data = super().clean()
        start_date = cleaned_data.get("start_date")
        end_date = cleaned_data.get("end_date")

        if (
            start_date
            and end_date
            and start_date > end_date
        ):
            raise forms.ValidationError(
                "Start date must be on or before end date."
            )

        return cleaned_data