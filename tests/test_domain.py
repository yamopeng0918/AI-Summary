import json
from datetime import datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle, SummaryDraft, SummaryRecord


CATEGORIES_PATH = Path(__file__).parents[1] / "data" / "categories.json"
SCHEMA_PATH = Path(__file__).parents[1] / "schemas" / "summary-v1.json"
CATEGORIES = json.loads(CATEGORIES_PATH.read_text(encoding="utf-8"))


def valid_record(**changes: object) -> SummaryRecord:
    payload = {
        "schemaVersion": 1,
        "id": "20260809-example-article",
        "canonicalUrl": "https://example.com/article",
        "sourceType": "web",
        "title": "文章標題",
        "author": None,
        "sourcePublishedAt": None,
        "createdAt": "2026-08-09T14:00:00+08:00",
        "updatedAt": "2026-08-09T14:00:00+08:00",
        "summary": "繁體中文短摘要",
        "keyPoints": ["重點一", "重點二", "重點三"],
        "category": "人工智慧",
        "tags": ["生成式 AI", "OpenAI"],
        "editorial": "AI 編輯觀點",
        "status": "published",
    }
    payload.update(changes)
    return SummaryRecord.model_validate(payload)


def test_categories_are_the_approved_initial_values() -> None:
    assert CATEGORIES == ["人工智慧", "程式開發", "科技產業", "商業與職場", "設計與創意", "生活與學習"]


def test_summary_record_accepts_the_approved_example() -> None:
    record = valid_record()

    assert record.model_dump(mode="json", by_alias=True)["canonicalUrl"] == "https://example.com/article"


def test_summary_and_extracted_article_accept_youtube_source_type() -> None:
    article = ExtractedArticle(
        canonicalUrl="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        sourceType="youtube",
        title="YouTube video",
        text="Enough transcript content",
    )

    assert article.source_type == "youtube"
    assert valid_record(sourceType="youtube").source_type == "youtube"


def test_summary_record_rejects_two_key_points() -> None:
    with pytest.raises(ValidationError):
        valid_record(keyPoints=["重點一", "重點二"])


def test_summary_record_rejects_six_tags() -> None:
    with pytest.raises(ValidationError):
        valid_record(tags=["一", "二", "三", "四", "五", "六"])


def test_summary_record_rejects_blank_tags() -> None:
    with pytest.raises(ValidationError):
        valid_record(tags=["   "])


def test_summary_record_rejects_an_unknown_category() -> None:
    with pytest.raises(ValidationError):
        valid_record(category="未知分類")


def test_summary_record_rejects_naive_timestamps() -> None:
    with pytest.raises(ValidationError):
        valid_record(createdAt="2026-08-09T14:00:00")


def test_summary_record_normalizes_tags_preserving_first_spelling() -> None:
    record = valid_record(tags=[" OpenAI ", "openai", "AI"])

    assert record.tags == ["OpenAI", "AI"]


def test_summary_record_normalizes_unicode_tags_with_shared_upper_lower_fold() -> None:
    record = valid_record(tags=["Straße", "STRASSE", "ı", "I"])

    assert record.tags == ["Straße", "ı"]


def test_domain_models_reject_blank_strings_and_naive_article_dates() -> None:
    with pytest.raises(ValidationError):
        SummaryDraft(summary="", keyPoints=["一", "二", "三"], tags=["標籤"], editorial="觀點")
    with pytest.raises(ValidationError):
        ExtractedArticle(
            canonical_url="https://example.com/article",
            title="標題",
            published_at=datetime(2026, 8, 9, 14, 0),
            text="正文",
        )


def test_digest_error_serializes_its_public_fields() -> None:
    error = DigestError("extract", "CONTENT_UNAVAILABLE", "無法取得可摘要的公開正文", False)

    assert error.as_dict() == {
        "stage": "extract",
        "code": "CONTENT_UNAVAILABLE",
        "message": "無法取得可摘要的公開正文",
        "retryable": False,
    }


def test_portable_schema_matches_the_summary_record_contract() -> None:
    schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert schema == SummaryRecord.model_json_schema(by_alias=True)
