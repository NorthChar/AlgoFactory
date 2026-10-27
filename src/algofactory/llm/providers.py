"""Bounded, structured provider calls with redacted audit records."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Callable
from http.client import HTTPException
from pathlib import Path
from typing import Literal, TypeVar
from urllib.error import HTTPError, URLError
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener

from pydantic import (
    BaseModel,
    Field,
    JsonValue,
    SecretStr,
    TypeAdapter,
    ValidationError,
    model_validator,
)

from algofactory.schemas.contracts import Contract, Digest, Text

T = TypeVar("T", bound=BaseModel)


class ProviderError(RuntimeError):
    """Only a safe category is exposed; raw server responses may contain secrets."""

    def __init__(self, category: str, retryable: bool = False):
        self.category = category
        self.retryable = retryable
        super().__init__(f"Provider failed: {category}")


class ProviderRequest(Contract):
    role: Literal["knowledge", "builder", "review"]
    operation: Text
    instruction: Text
    source: dict[str, JsonValue]


class CallRecord(Contract):
    mode: Literal["mock", "api"]
    operation: Text
    attempt: int
    status: Text
    reserved_cost_usd: float


class Provider:
    """Shared response validation and retry loop for both provider modes."""

    mode: Literal["mock", "api"]

    def __init__(self, max_calls: int = 4, max_retries: int = 1):
        if max_calls < 1 or max_retries < 0 or max_retries > 3:
            raise ValueError("Invalid provider call/retry budget")
        self.max_calls, self.max_retries = max_calls, max_retries
        self.calls = 0
        self.audit: list[CallRecord] = []

    def _reserve(self, request: ProviderRequest, schema: dict) -> float:
        return 0.0

    def _raw(self, request: ProviderRequest, schema: dict) -> str:
        raise NotImplementedError

    def complete(self, request: ProviderRequest, response_model: type[T]) -> T:
        schema = response_model.model_json_schema()
        for attempt in range(1, self.max_retries + 2):
            if self.calls >= self.max_calls:
                raise ProviderError("call_budget_exhausted")
            cost = self._reserve(request, schema)
            self.calls += 1
            try:
                raw = self._raw(request, schema)
                try:
                    result = response_model.model_validate_json(raw)
                except (ValidationError, ValueError, TypeError):
                    raise ProviderError("invalid_structured_response", retryable=True) from None
            except ProviderError as exc:
                self.audit.append(
                    CallRecord(
                        mode=self.mode,
                        operation=request.operation,
                        attempt=attempt,
                        status=exc.category,
                        reserved_cost_usd=cost,
                    )
                )
                if not exc.retryable or attempt > self.max_retries:
                    raise
                # Bounded backoff; tests and Mock require no sleeping.
                if self.mode == "api":
                    time.sleep(min(0.25 * attempt, 1.0))
            else:
                self.audit.append(
                    CallRecord(
                        mode=self.mode,
                        operation=request.operation,
                        attempt=attempt,
                        status="ok",
                        reserved_cost_usd=cost,
                    )
                )
                return result
        raise AssertionError("Unreachable")


class MockFixture(Contract):
    description: Text = "Explicit test fixture"
    faults: list[Literal["invalid_json", "timeout", "rate_limited", "authentication_failed"]] = (
        Field(default_factory=list)
    )
    response: dict[str, JsonValue]


class MockProvider(Provider):
    """Replay explicit fixtures keyed by source hash; unknown documents fail visibly."""

    mode = "mock"

    def __init__(self, fixtures: dict[str, dict], **kwargs):
        super().__init__(**kwargs)
        try:
            self.fixtures = TypeAdapter(dict[Digest, MockFixture]).validate_python(fixtures)
        except ValidationError:
            raise ProviderError("invalid_mock_fixture") from None
        self.positions: dict[str, int] = {}

    @classmethod
    def from_file(cls, path: Path, **kwargs):
        return cls(json.loads(path.read_text(encoding="utf-8")), **kwargs)

    def _raw(self, request: ProviderRequest, schema: dict) -> str:
        key = request.source.get("sha256", "")
        fixture = self.fixtures.get(key)
        if fixture is None:
            raise ProviderError("mock_fixture_missing")
        faults = fixture.faults
        position = self.positions.get(key, 0)
        self.positions[key] = position + 1
        if position < len(faults):
            fault = faults[position]
            if fault == "invalid_json":
                return "{invalid json"
            raise ProviderError(fault, retryable=fault in {"timeout", "rate_limited"})
        return json.dumps(fixture.response, ensure_ascii=False)


class APIConfig(Contract):
    base_url: Text
    model: Text
    api_key: SecretStr
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_calls: int = Field(default=4, ge=1, le=100)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_output_tokens: int = Field(default=8192, ge=1, le=32768)
    max_request_bytes: int = Field(default=131072, ge=1024, le=1048576)
    max_cost_usd: float = Field(gt=0)
    input_usd_per_million: float = Field(ge=0)
    output_usd_per_million: float = Field(ge=0)
    allow_local_http: bool = False

    @model_validator(mode="after")
    def check_endpoint(self):
        url = urlsplit(self.base_url)
        local = self.allow_local_http and url.hostname in {"localhost", "127.0.0.1", "::1"}
        if (url.scheme != "https" and not (local and url.scheme == "http")) or not url.hostname:
            raise ValueError("API base URL requires HTTPS (local HTTP is test-only)")
        if url.username or url.password or url.query or url.fragment:
            raise ValueError("API base URL must not contain credentials, a query or fragment")
        if not self.api_key.get_secret_value().strip():
            raise ValueError("API key is required")
        return self

    @classmethod
    def from_env(cls):
        required = {
            "base_url": "ALGOFACTORY_API_BASE_URL",
            "model": "ALGOFACTORY_API_MODEL",
            "api_key": "ALGOFACTORY_API_KEY",
            "max_cost_usd": "ALGOFACTORY_API_MAX_COST_USD",
            "input_usd_per_million": "ALGOFACTORY_API_INPUT_USD_PER_MILLION",
            "output_usd_per_million": "ALGOFACTORY_API_OUTPUT_USD_PER_MILLION",
        }
        if any(not os.environ.get(key) for key in required.values()):
            raise ProviderError("api_configuration_missing")
        values = {field: os.environ[key] for field, key in required.items()}
        try:
            for name in ("max_cost_usd", "input_usd_per_million", "output_usd_per_million"):
                values[name] = float(values[name])
            values["api_key"] = SecretStr(values["api_key"])
            return cls(**values)
        except (ValueError, ValidationError):
            raise ProviderError("api_configuration_invalid") from None


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # Never forward authorization to a redirected host.
        return None


def http_transport(url: str, headers: dict, body: bytes, timeout: float) -> bytes:
    opener = build_opener(NoRedirect())
    try:
        with opener.open(
            Request(url, data=body, headers=headers, method="POST"), timeout=timeout
        ) as response:
            payload = response.read(2_000_001)
            if len(payload) > 2_000_000:
                raise ProviderError("response_too_large")
            return payload
    except HTTPError as exc:
        status = exc.code
        exc.close()
        if status in {401, 403}:
            raise ProviderError("authentication_failed") from None
        if status == 429:
            raise ProviderError("rate_limited", retryable=True) from None
        raise ProviderError("http_error", retryable=status >= 500) from None
    except TimeoutError:
        raise ProviderError("timeout", retryable=True) from None
    except (URLError, OSError, HTTPException):
        raise ProviderError("connection_failed", retryable=True) from None


class APIProvider(Provider):
    """Chat-completions-compatible JSON API; billing estimates never claim actual spend."""

    mode = "api"

    def __init__(self, config: APIConfig, transport: Callable = http_transport):
        super().__init__(max_calls=config.max_calls, max_retries=config.max_retries)
        self.config, self.transport = config, transport
        self.reserved_cost_usd = 0.0

    def _body(self, request: ProviderRequest, schema: dict) -> bytes:
        return json.dumps(
            {
                "model": self.config.model,
                "messages": [
                    {
                        "role": "system",
                        "content": request.instruction
                        + "\nJSON Schema:\n"
                        + json.dumps(schema, ensure_ascii=False),
                    },
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                                "operation": request.operation,
                                "role": request.role,
                                "source": request.source,
                            },
                            ensure_ascii=False,
                        ),
                    },
                ],
                "response_format": {"type": "json_object"},
                "max_tokens": self.config.max_output_tokens,
                "temperature": 0,
            },
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")

    def _reserve(self, request: ProviderRequest, schema: dict) -> float:
        size = len(self._body(request, schema))
        if size > self.config.max_request_bytes:
            raise ProviderError("request_too_large")
        # Conservative byte-based input estimate plus framing allowance. Keep reservations
        # even on failed requests because an interrupted request may still incur charges.
        cost = (
            (size + 1024) * self.config.input_usd_per_million
            + self.config.max_output_tokens * self.config.output_usd_per_million
        ) / 1_000_000
        if self.reserved_cost_usd + cost > self.config.max_cost_usd:
            raise ProviderError("cost_budget_exhausted")
        self.reserved_cost_usd += cost
        return cost

    def _raw(self, request: ProviderRequest, schema: dict) -> str:
        payload = self.transport(
            self.config.base_url.rstrip("/") + "/chat/completions",
            {
                "Content-Type": "application/json",
                "Authorization": "Bearer " + self.config.api_key.get_secret_value(),
            },
            self._body(request, schema),
            self.config.timeout_seconds,
        )
        try:
            data = json.loads(payload)
            choice = data["choices"][0]
            if not isinstance(choice, dict):
                raise ValueError("Choice must be an object")
            if choice.get("finish_reason") != "stop":
                raise ProviderError("incomplete_response", retryable=True)
            content = choice["message"]["content"]
            if not isinstance(content, str):
                raise ValueError("Content must be JSON text")
            return content
        except (ValueError, KeyError, IndexError, TypeError):
            raise ProviderError("invalid_api_envelope", retryable=True) from None
