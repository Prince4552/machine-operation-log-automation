from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import Request, urlopen


class IntegrationError(RuntimeError):
    pass


@dataclass(frozen=True)
class RestConfig:
    base_url: str
    token_env: str | None = None
    timeout_s: float = 10.0
    max_retries: int = 3


class RestClient:
    """Small dependency-free REST client for production adapter implementations."""

    def __init__(self, config: RestConfig):
        if not config.base_url.startswith(("https://", "http://")):
            raise ValueError("base_url must be an HTTP(S) URL")
        self.config = config

    def request(self, method: str, path: str, payload: dict[str, Any] | None = None) -> dict[str, Any]:
        token = os.getenv(self.config.token_env) if self.config.token_env else None
        url = urljoin(self.config.base_url.rstrip("/") + "/", path.lstrip("/"))
        headers = {"Accept": "application/json"}
        body = None
        if payload is not None:
            headers["Content-Type"] = "application/json"
            body = json.dumps(payload).encode("utf-8")
        if token:
            headers["Authorization"] = f"Bearer {token}"

        last_error: Exception | None = None
        for attempt in range(self.config.max_retries + 1):
            try:
                req = Request(url, data=body, headers=headers, method=method.upper())
                with urlopen(req, timeout=self.config.timeout_s) as response:
                    raw = response.read().decode("utf-8")
                    return json.loads(raw) if raw else {}
            except HTTPError as exc:
                last_error = exc
                if exc.code not in {429, 500, 502, 503, 504} or attempt >= self.config.max_retries:
                    raise IntegrationError(f"HTTP {exc.code} from integration endpoint") from exc
            except URLError as exc:
                last_error = exc
                if attempt >= self.config.max_retries:
                    raise IntegrationError("Integration endpoint unavailable") from exc
            time.sleep(min(2 ** attempt, 8))
        raise IntegrationError("Integration request failed") from last_error
