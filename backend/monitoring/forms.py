import calendar
from django import forms

from monitoring.models import (
    AlertNotification,
    County,
    FloodPrediction,
)

class CountyRiskFilterForm(forms.Form):
    county = forms.ModelChoiceField(
        queryset=County.objects.none(),
        required=True,
        empty_label="Select a county",
        to_field_name="slug",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["county"].queryset = (
            County.objects.order_by("name")
        )
class DashboardPeriodForm(forms.Form):
    year = forms.ChoiceField(
        required=False,
        choices=[
            ("", "Latest available"),
        ],
    )
    month = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All months"),
            *[
                (str(month), calendar.month_name[month])
                for month in range(1, 13)
            ],
        ],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        available_years = (
            FloodPrediction.objects.filter(
                observation__is_synthetic=False
            )
            .order_by()
            .values_list(
                "observation__observation_date__year",
                flat=True,
            )
            .distinct()
        )

        self.fields["year"].choices = [
            ("", "Latest available"),
            *[
                (str(year), str(year))
                for year in sorted(
                    available_years,
                    reverse=True,
                )
                if year is not None
            ],
        ]

    def clean(self):
        cleaned_data = super().clean()
        year = cleaned_data.get("year")
        month = cleaned_data.get("month")

        cleaned_data["year"] = (
            int(year)
            if year
            else None
        )
        cleaned_data["month"] = (
            int(month)
            if month
            else None
        )

        if month and not year:
            self.add_error(
                "month",
                "Select a year before selecting a month.",
            )

        return cleaned_data


class HistoricalDataFilterForm(forms.Form):
    county = forms.ModelChoiceField(
        queryset=County.objects.none(),
        required=False,
        empty_label="All counties",
        to_field_name="slug",
    )
    year = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All years"),
        ],
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

        available_years = (
            FloodPrediction.objects.filter(
                observation__is_synthetic=False
            )
            .order_by()
            .values_list(
                "observation__observation_date__year",
                flat=True,
            )
            .distinct()
        )

        self.fields["year"].choices = [
            ("", "All years"),
            *[
                (str(year), str(year))
                for year in sorted(
                    available_years,
                    reverse=True,
                )
                if year is not None
            ],
        ]

    def clean(self):
        cleaned_data = super().clean()
        year = cleaned_data.get("year")

        if year:
            cleaned_data["year"] = int(year)
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

class AlertFilterForm(forms.Form):
    county = forms.ModelChoiceField(
        queryset=County.objects.none(),
        required=False,
        empty_label="All counties",
        to_field_name="slug",
    )
    channel = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All channels"),
            *AlertNotification.Channel.choices,
        ],
    )
    status = forms.ChoiceField(
        required=False,
        choices=[
            ("", "All statuses"),
            *AlertNotification.Status.choices,
        ],
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["county"].queryset = (
            County.objects.order_by("name")
        )