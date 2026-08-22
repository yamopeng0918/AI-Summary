"""Validated domain objects for AI Digest summary data."""

import json
from datetime import datetime
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


_CATEGORIES_PATH = Path(__file__).parents[2] / "data" / "categories.json"
VALID_CATEGORIES = frozenset(json.loads(_CATEGORIES_PATH.read_text(encoding="utf-8")))


def _camel_case(field_name: str) -> str:
    first, *rest = field_name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def _validate_non_blank_items(values: list[str]) -> list[str]:
    if any(not value.strip() for value in values):
        raise ValueError("items must not be blank")
    return values


def _normalize_tags(values: Any) -> Any:
    if not isinstance(values, list):
        return values

    normalized: list[str] = []
    seen: set[str] = set()
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("tags must not be blank")
        tag = value.strip()
        normalized_key = tag.upper().lower()
        if normalized_key not in seen:
            seen.add(normalized_key)
            normalized.append(tag)
    return normalized


def _require_aware_datetime(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("timestamp must include a timezone")
    return value


class DomainModel(BaseModel):
    """Base model with camelCase JSON aliases and shared value checks."""

    model_config = ConfigDict(
        alias_generator=_camel_case,
        populate_by_name=True,
        serialize_by_alias=True,
    )

    @field_validator("*", mode="before")
    @classmethod
    def reject_blank_scalar_strings(cls, value: Any) -> Any:
        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be blank")
        return value


class ExtractedArticle(DomainModel):
    canonical_url: HttpUrl
    source_type: Literal["web", "youtube"] = "web"
    title: str
    author: str | None = None
    published_at: datetime | None = None
    text: str

    @field_validator("published_at")
    @classmethod
    def require_aware_published_at(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)


class SummaryDraft(DomainModel):
    summary: str
    key_points: list[str] = Field(alias="keyPoints", min_length=3, max_length=5)
    tags: list[str] = Field(min_length=1, max_length=5)
    editorial: str

    _validate_key_points = field_validator("key_points")(_validate_non_blank_items)
    _normalize_tags = field_validator("tags", mode="before")(_normalize_tags)


class SummaryRecord(DomainModel):
    schema_version: Literal[1] = Field(alias="schemaVersion")
    id: str
    canonical_url: HttpUrl = Field(alias="canonicalUrl")
    source_type: Literal["web", "youtube"] = Field(alias="sourceType")
    title: str
    author: str | None
    source_published_at: datetime | None = Field(alias="sourcePublishedAt")
    created_at: datetime = Field(alias="createdAt")
    updated_at: datetime = Field(alias="updatedAt")
    summary: str
    key_points: list[str] = Field(alias="keyPoints", min_length=3, max_length=5)
    category: str
    tags: list[str] = Field(min_length=1, max_length=5)
    editorial: str
    status: Literal["published", "archived"]

    _validate_key_points = field_validator("key_points")(_validate_non_blank_items)
    _normalize_tags = field_validator("tags", mode="before")(_normalize_tags)

    @field_validator("category")
    @classmethod
    def validate_category(cls, value: str) -> str:
        if value not in VALID_CATEGORIES:
            raise ValueError("must be one of the configured categories")
        return value

    @field_validator("source_published_at", "created_at", "updated_at")
    @classmethod
    def require_aware_timestamps(cls, value: datetime | None) -> datetime | None:
        return _require_aware_datetime(value)


class DigestError(Exception):
    """A safe, structured error returned by pipeline boundaries."""

    def __init__(self, stage: str, code: str, message: str, retryable: bool) -> None:
        super().__init__(message)
        self.stage = stage
        self.code = code
        self.message = message
        self.retryable = retryable

    def as_dict(self) -> dict[str, str | bool]:
        return {
            "stage": self.stage,
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
        }
