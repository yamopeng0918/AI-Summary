from pathlib import Path

from ai_digest.extractors.youtube_captions import CaptionTrack, normalize_vtt, select_caption


def track(language: str, *, automatic: bool = False) -> CaptionTrack:
    return CaptionTrack(language=language, url=f"https://captions.example/{language}", automatic=automatic)


def test_prefers_manual_traditional_chinese_then_manual_original_language() -> None:
    manual = [track("en"), track("zh-Hant"), track("ja")]
    automatic = [track("zh-TW", automatic=True)]
    assert select_caption(manual, automatic, "ja") == manual[1]
    assert select_caption([track("en"), track("ja")], automatic, "ja").language == "ja"


def test_uses_automatic_only_when_no_manual_caption_is_available() -> None:
    automatic = [track("en", automatic=True), track("zh-TW", automatic=True)]
    assert select_caption([], automatic, "en") == automatic[1]


def test_other_language_fallback_is_deterministic_and_preserves_identity() -> None:
    selected = select_caption([track("ja"), track("de"), track("en")], [], None)

    assert selected is not None
    assert selected.language == "de"
    assert selected.url == "https://captions.example/de"


def test_normalize_vtt_removes_markup_timestamps_and_consecutive_duplicates() -> None:
    payload = Path("tests/fixtures/youtube/captions-duplicate.vtt").read_text(encoding="utf-8")
    assert normalize_vtt(payload) == "第一句\n第二句 & 補充"
