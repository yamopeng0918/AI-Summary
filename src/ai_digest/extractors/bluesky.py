"""Safe extraction of directly readable public Bluesky posts."""

from collections.abc import Callable
from datetime import datetime
import json
from typing import Any, Protocol

import httpx
from pydantic import ValidationError

from ai_digest.domain import DigestError, ExtractedArticle
from ai_digest.source_urls import parse_bluesky_post_url


_IMAGE_VIEW = "app.bsky.embed.images#view"
_EXTERNAL_VIEW = "app.bsky.embed.external#view"
_RECORD_WITH_MEDIA_VIEW = "app.bsky.embed.recordWithMedia#view"
_APPVIEW_ROOT = "https://public.api.bsky.app"
_RESOLVE_HANDLE_PATH = "/xrpc/com.atproto.identity.resolveHandle"
_GET_POSTS_PATH = "/xrpc/app.bsky.feed.getPosts"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024
_TIMEOUT_SECONDS = 15.0
_USER_AGENT = "AI-Digest/0.1 (+https://github.com/ai-digest)"


def _error(code: str, message: str, retryable: bool) -> DigestError:
    return DigestError("extract", code, message, retryable)


def _invalid_response() -> DigestError:
    return _error(
        "INVALID_SOURCE_RESPONSE",
        "Bluesky returned an invalid response",
        False,
    )


def _validated_did(value: object) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("did:")
        or not value.removeprefix("did:").strip()
        or value != value.strip()
    ):
        raise _invalid_response()
    return value


def _required_text(container: dict[str, Any], field: str) -> str:
    value = container.get(field)
    if not isinstance(value, str) or not value.strip():
        raise _invalid_response()
    return value.strip()


def _optional_text(container: dict[str, Any], field: str) -> str | None:
    value = container.get(field)
    if value is None:
        return None
    if not isinstance(value, str):
        raise _invalid_response()
    return value.strip() or None


def _published_at(value: object) -> datetime:
    if not isinstance(value, str):
        raise _invalid_response()
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _invalid_response() from None
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise _invalid_response()
    return parsed


def _reply_reference_is_valid(value: object) -> bool:
    if not isinstance(value, dict):
        raise _invalid_response()
    for key in ("root", "parent"):
        reference = value.get(key)
        if not isinstance(reference, dict):
            raise _invalid_response()
        _required_text(reference, "uri")
        _required_text(reference, "cid")
    return True


def _deduplicate(values: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = value.strip()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            unique.append(cleaned)
    return unique


def _image_alts(embed: dict[str, Any]) -> list[str]:
    images = embed.get("images")
    if not isinstance(images, list):
        raise _invalid_response()
    alts: list[str] = []
    for image in images:
        if not isinstance(image, dict) or not isinstance(image.get("alt"), str):
            raise _invalid_response()
        alts.append(image["alt"])
    return alts


def _external_titles(embed: dict[str, Any], *, required: bool) -> list[str]:
    external = embed.get("external")
    if external is None and not required:
        return []
    if not isinstance(external, dict) or not isinstance(external.get("title"), str):
        raise _invalid_response()
    return [external["title"]]


def _embed_text(embed: object) -> tuple[list[str], list[str]]:
    if not isinstance(embed, dict) or not isinstance(embed.get("$type"), str):
        raise _invalid_response()
    embed_type = embed["$type"]
    if embed_type == _RECORD_WITH_MEDIA_VIEW:
        return _embed_text(embed.get("media"))
    if embed_type == _IMAGE_VIEW:
        return _image_alts(embed), _external_titles(embed, required=False)
    if embed_type == _EXTERNAL_VIEW:
        return [], _external_titles(embed, required=True)
    return [], []


class BlueskyAppView(Protocol):
    """Minimal public AppView operations required by the extractor."""

    def resolve_handle(self, handle: str) -> str: ...

    def get_post(self, uri: str) -> dict[str, Any]: ...


class BlueskyAppViewClient:
    """Read bounded JSON from the fixed public Bluesky AppView host."""

    def __init__(self, client_factory: Callable[[], httpx.Client]) -> None:
        self._client_factory = client_factory

    def resolve_handle(self, handle: str) -> str:
        payload = self._get_json(
            _RESOLVE_HANDLE_PATH,
            {"handle": handle},
            author_lookup=True,
        )
        if not isinstance(payload, dict):
            raise _invalid_response()
        return _validated_did(payload.get("did"))

    def get_post(self, uri: str) -> dict[str, Any]:
        payload = self._get_json(
            _GET_POSTS_PATH,
            [("uris", uri)],
            author_lookup=False,
        )
        if not isinstance(payload, dict) or not isinstance(payload.get("posts"), list):
            raise _invalid_response()
        posts = payload["posts"]
        if not posts:
            raise _error(
                "POST_NOT_FOUND",
                "Bluesky post was not found",
                False,
            )
        if len(posts) != 1 or not isinstance(posts[0], dict):
            raise _invalid_response()
        post = posts[0]
        if post.get("uri") != uri:
            raise _invalid_response()
        return post

    def _get_json(
        self,
        path: str,
        params: dict[str, str] | list[tuple[str, str]],
        *,
        author_lookup: bool,
    ) -> object:
        client: httpx.Client | None = None
        response: httpx.Response | None = None
        try:
            client = self._client_factory()
            request = httpx.Request(
                "GET",
                f"{_APPVIEW_ROOT}{path}",
                params=params,
                headers={
                    "Accept": "application/json",
                    "User-Agent": _USER_AGENT,
                    "Accept-Encoding": "identity",
                },
                extensions={
                    "timeout": {
                        "connect": _TIMEOUT_SECONDS,
                        "read": _TIMEOUT_SECONDS,
                        "write": _TIMEOUT_SECONDS,
                        "pool": _TIMEOUT_SECONDS,
                    }
                },
            )
            response = client.send(
                request,
                stream=True,
                follow_redirects=False,
                auth=None,
            )
            self._raise_for_status(response.status_code, author_lookup=author_lookup)
            self._validate_content_type(response)
            self._validate_content_length(response)
            self._validate_content_encoding(response)

            body = bytearray()
            for chunk in response.iter_raw():
                if len(body) + len(chunk) > _MAX_RESPONSE_BYTES:
                    raise _invalid_response()
                body.extend(chunk)
            try:
                return json.loads(bytes(body))
            except (json.JSONDecodeError, UnicodeDecodeError, RecursionError):
                raise _invalid_response() from None
        except DigestError:
            raise
        except (httpx.TimeoutException, httpx.HTTPError):
            raise _error(
                "UPSTREAM_UNAVAILABLE",
                "Bluesky service is unavailable",
                True,
            ) from None
        except Exception:
            raise _error(
                "UPSTREAM_UNAVAILABLE",
                "Bluesky service is unavailable",
                True,
            ) from None
        finally:
            if response is not None:
                try:
                    response.close()
                except Exception:
                    pass
            if client is not None:
                try:
                    client.close()
                except Exception:
                    pass

    @staticmethod
    def _raise_for_status(status_code: int, *, author_lookup: bool) -> None:
        if 200 <= status_code < 300:
            return
        if status_code in {401, 403}:
            raise _error(
                "SOURCE_ACCESS_DENIED",
                "Bluesky post is not publicly accessible",
                False,
            )
        if status_code in {400, 404}:
            if author_lookup:
                raise _error(
                    "AUTHOR_NOT_FOUND",
                    "Bluesky author was not found",
                    False,
                )
            raise _error(
                "POST_NOT_FOUND",
                "Bluesky post was not found",
                False,
            )
        if status_code == 429 or status_code >= 500:
            raise _error(
                "UPSTREAM_UNAVAILABLE",
                "Bluesky service is unavailable",
                True,
            )
        raise _invalid_response()

    @staticmethod
    def _validate_content_type(response: httpx.Response) -> None:
        media_type = (
            response.headers.get("content-type", "")
            .split(";", 1)[0]
            .strip()
            .lower()
        )
        if media_type != "application/json" and not (
            media_type.startswith("application/") and media_type.endswith("+json")
        ):
            raise _invalid_response()

    @staticmethod
    def _validate_content_length(response: httpx.Response) -> None:
        declared_length = response.headers.get("content-length")
        if declared_length is None:
            return
        try:
            declared_size = int(declared_length)
        except ValueError:
            raise _invalid_response() from None
        if declared_size < 0 or declared_size > _MAX_RESPONSE_BYTES:
            raise _invalid_response()

    @staticmethod
    def _validate_content_encoding(response: httpx.Response) -> None:
        content_encoding = response.headers.get("content-encoding")
        if content_encoding is not None and content_encoding.strip().lower() != "identity":
            raise _invalid_response()


class BlueskyExtractor:
    """Map one public, non-reply Bluesky post to shared article data."""

    def __init__(self, appview: BlueskyAppView) -> None:
        self._appview = appview

    def extract(self, url: str) -> ExtractedArticle:
        reference = parse_bluesky_post_url(url)
        try:
            did = (
                reference.actor
                if reference.actor.startswith("did:")
                else self._appview.resolve_handle(reference.actor)
            )
            did = _validated_did(did)
            post = self._appview.get_post(
                f"at://{did}/app.bsky.feed.post/{reference.post_id}"
            )
        except DigestError:
            raise
        except Exception:
            raise _error(
                "UPSTREAM_UNAVAILABLE",
                "Bluesky service is unavailable",
                True,
            ) from None
        return self._article(post, did, reference.post_id)

    @staticmethod
    def _article(post: object, did: str, post_id: str) -> ExtractedArticle:
        if not isinstance(post, dict):
            raise _invalid_response()
        author = post.get("author")
        record = post.get("record")
        if not isinstance(author, dict) or not isinstance(record, dict):
            raise _invalid_response()

        author_did = _required_text(author, "did")
        handle = _required_text(author, "handle")
        if author_did != did:
            raise _invalid_response()
        if record.get("$type") != "app.bsky.feed.post":
            raise _invalid_response()
        display_name = _optional_text(author, "displayName") or handle

        text_value = record.get("text")
        if not isinstance(text_value, str):
            raise _invalid_response()
        text_value = text_value.strip()
        published_at = _published_at(record.get("createdAt"))

        if "reply" in record:
            _reply_reference_is_valid(record["reply"])
            raise _error(
                "REPLY_POST_NOT_SUPPORTED",
                "Bluesky replies are not supported",
                False,
            )

        alts: list[str] = []
        titles: list[str] = []
        if "embed" in post:
            alts, titles = _embed_text(post["embed"])
        alts = _deduplicate(alts)
        supplemental_seen = set(alts)
        titles = [
            title
            for title in _deduplicate(titles)
            if title not in supplemental_seen
        ]

        sections: list[str] = []
        if text_value:
            sections.append(f"貼文：\n{text_value}")
        if alts:
            sections.append("圖片替代文字：\n" + "\n".join(alts))
        if titles:
            sections.append("外部連結標題：\n" + "\n".join(titles))
        if not sections:
            raise _error(
                "NO_EXTRACTABLE_CONTENT",
                "Bluesky post does not contain extractable text",
                False,
            )

        try:
            return ExtractedArticle(
                canonical_url=(
                    f"https://bsky.app/profile/{did}/post/{post_id}"
                ),
                source_type="social",
                title=f"{display_name}（@{handle}）的 Bluesky 貼文",
                author=display_name,
                published_at=published_at,
                text="\n\n".join(sections),
            )
        except (TypeError, ValidationError):
            raise _invalid_response() from None
