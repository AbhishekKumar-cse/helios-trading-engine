"""Explicit HELIOS datasets and fields; not an export of BRAIN's private catalogue."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DatasetSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    dataset_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    family: Literal["price_volume", "fundamental", "delivery"]
    provider: str
    market: Literal["NSE"] = "NSE"
    source_url: str
    frequency: Literal["daily", "filing_event"]
    history_status: Literal["available_unverified", "collection_required", "sample_only"]
    historical_units_certified: Literal[False] = False


class DataFieldSpec(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    field_id: str = Field(pattern=r"^[a-z][a-z0-9_]+$")
    dataset_id: str
    description: str
    kind: Literal["MATRIX", "VECTOR", "TIMESTAMP"]
    unit: Literal[
        "INR", "uncertified_vendor_price", "uncertified_vendor_volume", "shares", "ratio", "UTC"
    ]
    availability: str
    reducer: str | None = None
    carryable: bool = False
    max_age_days: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def carry_contract(self) -> "DataFieldSpec":
        if self.carryable and (self.kind != "MATRIX" or self.max_age_days is None):
            raise ValueError("carry requires a scalar as-of field and explicit age limit")
        if self.kind == "VECTOR" and self.carryable:
            raise ValueError("event vectors require explicit reduction before carry")
        return self


class FieldCatalog(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    version: Literal["helios_nse_field_catalog_v1"] = "helios_nse_field_catalog_v1"
    datasets: tuple[DatasetSpec, ...]
    fields: tuple[DataFieldSpec, ...]

    @model_validator(mode="after")
    def identities(self) -> "FieldCatalog":
        dataset_ids = {x.dataset_id for x in self.datasets}
        if len(dataset_ids) != len(self.datasets) or len({x.field_id for x in self.fields}) != len(
            self.fields
        ):
            raise ValueError("dataset and field identities must be unique")
        if any(x.dataset_id not in dataset_ids for x in self.fields):
            raise ValueError("every field must name an existing dataset")
        return self

    def scalar(self, field_id: str) -> DataFieldSpec:
        for field in self.fields:
            if field.field_id == field_id:
                if field.kind != "MATRIX":
                    raise ValueError(
                        "vector/timestamp fields cannot be used as scalar alpha inputs"
                    )
                return field
        raise ValueError(f"unavailable field: {field_id}")


def nse_catalog() -> FieldCatalog:
    prices = "nse_vendor_daily_v1"
    fundamental = "nse_financial_filings_v1"
    delivery = "nse_delivery_positions_v1"
    return FieldCatalog(
        datasets=(
            DatasetSpec(
                dataset_id=prices,
                family="price_volume",
                provider="Yahoo-distributed NSE",
                source_url="https://query1.finance.yahoo.com/v8/finance/chart/",
                frequency="daily",
                history_status="available_unverified",
            ),
            DatasetSpec(
                dataset_id=fundamental,
                family="fundamental",
                provider="NSE filings/XBRL",
                source_url="https://www.nseindia.com/companies-listing/corporate-filings-financial-results",
                frequency="filing_event",
                history_status="collection_required",
            ),
            DatasetSpec(
                dataset_id=delivery,
                family="delivery",
                provider="NSE delivery position",
                source_url="https://nsearchives.nseindia.com/archives/equities/mto/",
                frequency="daily",
                history_status="sample_only",
            ),
        ),
        fields=(
            DataFieldSpec(
                field_id="adjusted_close",
                dataset_id=prices,
                kind="MATRIX",
                unit="uncertified_vendor_price",
                description="Retrospective adjusted close",
                availability="assumed following calendar midnight; unverified vintage",
            ),
            DataFieldSpec(
                field_id="volume",
                dataset_id=prices,
                kind="MATRIX",
                unit="uncertified_vendor_volume",
                description="Vendor reported volume",
                availability="same daily candle; not delivery quantity or trade imbalance",
            ),
            DataFieldSpec(
                field_id="filing_events",
                dataset_id=fundamental,
                kind="VECTOR",
                unit="INR",
                description="Dated scalar profit facts within multiple filing events",
                availability="exchange-reported dissemination plus five minutes",
                reducer="latest published compatible quarterly context, never quarter-end fill",
            ),
            DataFieldSpec(
                field_id="filing_available_at",
                dataset_id=fundamental,
                kind="TIMESTAMP",
                unit="UTC",
                description="Reported publication proxy, not observed old receipt",
                availability="max broadcast/dissemination timestamp plus five minutes",
            ),
            DataFieldSpec(
                field_id="quarterly_profit",
                dataset_id=fundamental,
                kind="MATRIX",
                unit="INR",
                description="Consolidated noncumulative OneD ProfitLossForPeriod",
                availability="as-of published filing; strict symbol/context/unit checks",
                carryable=True,
                max_age_days=180,
            ),
            DataFieldSpec(
                field_id="profit_yoy_growth",
                dataset_id=fundamental,
                kind="MATRIX",
                unit="ratio",
                description="(current profit - as-of same-quarter prior-year profit)/abs(prior)",
                availability="both quarterly facts published; expires180days after current filing",
                carryable=True,
                max_age_days=180,
            ),
            DataFieldSpec(
                field_id="deliverable_quantity",
                dataset_id=delivery,
                kind="MATRIX",
                unit="shares",
                description="Gross delivery quantity across clients; not net institutional buying",
                availability="daily report receipt; only one schema sample presently retained",
            ),
            DataFieldSpec(
                field_id="delivery_ratio",
                dataset_id=delivery,
                kind="MATRIX",
                unit="ratio",
                description="Deliverable quantity / quantity traded",
                availability="daily report receipt; not an observed signed money flow",
            ),
        ),
    )
