from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

import requests

from app.core.config import Settings

logger = logging.getLogger(__name__)
_SAFE_ID = re.compile(r"[A-Za-z0-9_-]{1,255}")
_SAFE_REQUEST_ID = re.compile(r"[A-Za-z0-9_.:-]{1,120}")
MAX_RESPONSE_BYTES = 64 * 1024


@dataclass(frozen=True)
class MetaHTTPError(Exception):
    status_code: int
    error_code: str | None
    error_subcode: str | None
    error_type: str | None
    retryable: bool
    authentication: bool
    permission: bool
    is_transient: bool | None = None
    provider_request_id: str | None = None
    operation: str | None = None


class InstagramMetaClient:
    def __init__(self, settings: Settings, *, session: requests.Session | None = None) -> None:
        self.base_url = settings.instagram_graph_api_base_url
        self.version = settings.instagram_graph_api_version
        self.timeout = (
            settings.instagram_http_connect_timeout_seconds,
            settings.instagram_http_read_timeout_seconds,
        )
        self.session = session or requests.Session()

    @staticmethod
    def _identifier(value: str) -> str:
        if not _SAFE_ID.fullmatch(value):
            raise ValueError("Invalid Instagram provider identifier")
        return value

    @staticmethod
    def _error(
        response: requests.Response,
        payload: dict[str, Any] | None,
        *,
        provider_request_id: str | None = None,
        operation: str | None = None,
    ) -> MetaHTTPError:
        error = payload.get("error") if isinstance(payload, dict) else None
        error = error if isinstance(error, dict) else {}
        raw_code = error.get("code")
        raw_subcode = error.get("error_subcode")
        raw_type = error.get("type")
        raw_is_transient = error.get("is_transient")
        code = str(raw_code)[:30] if isinstance(raw_code, (str, int)) else None
        subcode = str(raw_subcode)[:30] if isinstance(raw_subcode, (str, int)) else None
        error_type = str(raw_type)[:80] if isinstance(raw_type, str) else None
        is_transient = raw_is_transient if isinstance(raw_is_transient, bool) else None
        authentication = response.status_code == 401 or code == "190"
        permission = response.status_code == 403 or code in {"10", "200"}
        retryable = response.status_code == 429 or response.status_code >= 500
        if not retryable:
            retryable = (
                is_transient
                if is_transient is not None
                else code in {"1", "2", "4", "17", "32", "341", "368", "613", "9007"}
            )
        return MetaHTTPError(
            response.status_code,
            code,
            subcode,
            error_type,
            retryable,
            authentication,
            permission,
            is_transient,
            provider_request_id,
            operation,
        )

    def _request(
        self,
        method: str,
        path: str,
        *,
        access_token: str,
        data: dict[str, str] | None = None,
        params: dict[str, str] | None = None,
        operation: str,
    ) -> dict[str, Any]:
        request_id = uuid4().hex
        response = self.session.request(
            method,
            f"{self.base_url}/{self.version}/{path.lstrip('/')}",
            headers={"Authorization": f"Bearer {access_token}", "X-Request-ID": request_id},
            data=data,
            params=params,
            timeout=self.timeout,
        )
        content = getattr(response, "content", None)
        if isinstance(content, bytes) and len(content) > MAX_RESPONSE_BYTES:
            payload = None
        else:
            try:
                payload = response.json()
            except ValueError:
                payload = None
        response_headers = getattr(response, "headers", {})
        raw_provider_request_id = (
            response_headers.get("x-fb-trace-id") if hasattr(response_headers, "get") else None
        )
        provider_request_id = (
            raw_provider_request_id
            if isinstance(raw_provider_request_id, str)
            and _SAFE_REQUEST_ID.fullmatch(raw_provider_request_id)
            else None
        )
        logger.info(
            "instagram_meta_request operation=%s status=%s request_id=%s provider_request_id=%s",
            operation,
            response.status_code,
            request_id,
            provider_request_id or "unavailable",
        )
        if not response.ok:
            raise self._error(
                response,
                payload if isinstance(payload, dict) else None,
                provider_request_id=provider_request_id,
                operation=operation,
            )
        if not isinstance(payload, dict):
            raise MetaHTTPError(
                response.status_code, "invalid_json", None, None, False, False, False
            )
        return payload

    @staticmethod
    def _required_id(payload: dict[str, Any]) -> str:
        value = payload.get("id")
        if not isinstance(value, str) or not _SAFE_ID.fullmatch(value):
            raise MetaHTTPError(200, "missing_provider_id", None, None, False, False, False)
        return value

    @staticmethod
    def _status_code(payload: dict[str, Any]) -> str:
        value = payload.get("status_code")
        if not isinstance(value, str) or not re.fullmatch(r"[A-Z_]{1,40}", value):
            raise MetaHTTPError(
                200,
                "invalid_container_status",
                None,
                None,
                False,
                False,
                False,
            )
        return value

    def create_image_container(
        self, *, account_id: str, image_url: str, caption: str, access_token: str
    ) -> str:
        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media",
            access_token=access_token,
            data={"image_url": image_url, "caption": caption},
            operation="create_container",
        )
        return self._required_id(payload)

    def create_carousel_image_container(
        self,
        *,
        account_id: str,
        image_url: str,
        access_token: str,
    ) -> str:
        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media",
            access_token=access_token,
            data={
                "image_url": image_url,
                "is_carousel_item": "true",
            },
            operation="carousel_child_create",
        )
        return self._required_id(payload)

    def create_carousel_container(
        self,
        *,
        account_id: str,
        children: tuple[str, ...],
        caption: str,
        access_token: str,
    ) -> str:
        if len(children) < 2 or len(children) > 10:
            raise ValueError(
                "Instagram carousel requires between 2 and 10 children"
            )

        validated_children = tuple(
            self._identifier(child_id)
            for child_id in children
        )

        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media",
            access_token=access_token,
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(validated_children),
                "caption": caption,
            },
            operation="carousel_parent_create",
        )
        return self._required_id(payload)

    def create_reel_container(
        self,
        *,
        account_id: str,
        video_url: str,
        caption: str,
        access_token: str,
    ) -> str:
        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media",
            access_token=access_token,
            data={
                "media_type": "REELS",
                "video_url": video_url,
                "caption": caption,
            },
            operation="create_reel_container",
        )
        return self._required_id(payload)

    def create_story_image_container(
        self,
        *,
        account_id: str,
        image_url: str,
        access_token: str,
    ) -> str:
        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media",
            access_token=access_token,
            data={
                "media_type": "STORIES",
                "image_url": image_url,
            },
            operation="create_story_image_container",
        )
        return self._required_id(payload)

    def create_story_video_container(
        self,
        *,
        account_id: str,
        video_url: str,
        access_token: str,
    ) -> str:
        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media",
            access_token=access_token,
            data={
                "media_type": "STORIES",
                "video_url": video_url,
            },
            operation="create_story_video_container",
        )
        return self._required_id(payload)

    def get_container_status(
        self,
        container_id: str,
        access_token: str,
    ) -> str:
        payload = self._request(
            "GET",
            self._identifier(container_id),
            access_token=access_token,
            params={"fields": "status_code"},
            operation="container_status",
        )
        return self._status_code(payload)

    def publish_container(self, *, account_id: str, container_id: str, access_token: str) -> str:
        payload = self._request(
            "POST",
            f"{self._identifier(account_id)}/media_publish",
            access_token=access_token,
            data={"creation_id": self._identifier(container_id)},
            operation="media_publish",
        )
        return self._required_id(payload)

    def get_permalink(self, media_id: str, access_token: str) -> str | None:
        payload = self._request(
            "GET",
            self._identifier(media_id),
            access_token=access_token,
            params={"fields": "permalink"},
            operation="get_permalink",
        )
        value = payload.get("permalink")
        return value if isinstance(value, str) and value.startswith("https://") else None

    def inspect_container_best_effort(
        self, container_id: str, access_token: str
    ) -> str | None:
        try:
            payload = self._request(
                "GET",
                self._identifier(container_id),
                access_token=access_token,
                params={"fields": "status_code"},
                operation="inspect_unknown_publish",
            )
        except (MetaHTTPError, requests.RequestException, ValueError):
            return None
        value = payload.get("status_code")
        if isinstance(value, str) and re.fullmatch(r"[A-Z_]{1,40}", value):
            return value
        return None
