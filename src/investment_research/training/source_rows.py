from __future__ import annotations

from datetime import date, datetime
from typing import Mapping, TypeAlias

from pydantic import AliasChoices, BaseModel, ConfigDict, Field

JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | list[JsonScalar] | dict[str, JsonScalar | list[JsonScalar]] | list[dict[str, JsonScalar]]
JsonObject: TypeAlias = dict[str, JsonValue]


class ProviderRowModel(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)
    exchange_time: datetime | date | str | None = None
    source_time: datetime | date | str | None = None
    received_at: datetime | date | str | None = None
    persisted_at: datetime | date | str | None = None
    available_at: datetime | date | str | None = None
    revised_at: datetime | date | str | None = None

    def to_json_object(self) -> JsonObject:
        return self.model_dump(mode="json", by_alias=True, exclude_none=True)


ProviderRowInput: TypeAlias = ProviderRowModel | Mapping[str, JsonValue]


DateLike: TypeAlias = date | datetime | str
DateTimeLike: TypeAlias = datetime | date | str


class YFinancePriceRow(ProviderRowModel):
    trade_date: DateLike = Field(validation_alias=AliasChoices("date", "trade_date"))
    open: float
    high: float
    low: float
    close: float
    adj_close: float | None = None
    volume: float | None = None
    published_at: DateTimeLike | None = Field(default=None, validation_alias=AliasChoices("published_at", "fetched_at"))


class AksharePriceRow(ProviderRowModel):
    trade_date: DateLike = Field(validation_alias=AliasChoices("date", "trade_date", "日期"))
    open: float = Field(validation_alias=AliasChoices("open", "开盘"))
    high: float = Field(validation_alias=AliasChoices("high", "最高"))
    low: float = Field(validation_alias=AliasChoices("low", "最低"))
    close: float = Field(validation_alias=AliasChoices("close", "收盘"))
    adjusted_close: float | None = Field(default=None, validation_alias=AliasChoices("adjusted_close", "复权收盘"))
    volume: float | None = Field(default=None, validation_alias=AliasChoices("volume", "成交量"))
    fx_rate_to_usd: float | None = None
    published_at: DateTimeLike | None = Field(
        default=None,
        validation_alias=AliasChoices("published_at", "更新时间", "date", "日期"),
    )


class SecFilingRow(ProviderRowModel):
    form: str | None = None
    acceptance_datetime: DateTimeLike | None = None
    published_at: DateTimeLike | None = None
    filed_at: DateTimeLike | None = None
    event_time: DateTimeLike | None = None
    accession_number: str | None = None
    url: str | None = None


class CnAnnouncementRow(ProviderRowModel):
    title: str | None = None
    published_at: DateTimeLike | None = Field(default=None, validation_alias=AliasChoices("published_at", "公告时间", "date"))
    event_time: DateTimeLike | None = None
    id: str | None = None
    url: str | None = None


class NewsRow(ProviderRowModel):
    headline: str | None = None
    published_at: DateTimeLike | None = Field(default=None, validation_alias=AliasChoices("published_at", "datetime", "time"))
    event_time: DateTimeLike | None = None
    id: str | None = None
    url: str | None = None


ProviderPriceRow: TypeAlias = YFinancePriceRow | AksharePriceRow
ProviderEventRow: TypeAlias = SecFilingRow | CnAnnouncementRow | NewsRow
