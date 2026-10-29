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

    def __init__(
        self,
        category: str,
        retryable: bool = False,
        *,
        http_status: int | None = None,
        service_error_code: str | None = None,
    ):
        self.category = category
        self.retryable = retryable
        self.http_status = http_status
        self.service_error_code = service_error_code
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
    reserved_cost_usd: float | None
    input_tokens: int | None = Field(default=None, ge=0)
    output_tokens: int | None = Field(default=None, ge=0)
    http_status: int | None = None
    service_error_code: str | None = None


class Provider:
    """Shared response validation and retry loop for both provider modes."""

    mode: Literal["mock", "api"]

    def __init__(self, max_calls: int = 4, max_retries: int = 1):
        if max_calls < 1 or max_retries < 0 or max_retries > 3:
            raise ValueError("Invalid provider call/retry budget")
        self.max_calls, self.max_retries = max_calls, max_retries
        self.calls = 0
        self.audit: list[CallRecord] = []
        self.last_usage: dict[str, int] = {}

    def _reserve(self, request: ProviderRequest, schema: dict) -> float | None:
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
            self.last_usage = {}
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
                        http_status=exc.http_status,
                        service_error_code=exc.service_error_code,
                        **self.last_usage,
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
                        **self.last_usage,
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
    api_style: Literal["chat_completions", "responses"] = "chat_completions"
    auth_style: Literal["bearer", "api_key"] = "bearer"
    timeout_seconds: float = Field(default=30.0, gt=0, le=120)
    max_calls: int = Field(default=4, ge=1, le=100)
    max_retries: int = Field(default=1, ge=0, le=3)
    max_output_tokens: int = Field(default=8192, ge=1, le=32768)
    max_request_bytes: int = Field(default=131072, ge=1024, le=1048576)
    max_cost_usd: float | None = Field(default=None, gt=0)
    input_usd_per_million: float | None = Field(default=None, ge=0)
    output_usd_per_million: float | None = Field(default=None, ge=0)
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
        if (self.input_usd_per_million is None) != (self.output_usd_per_million is None):
            raise ValueError("Both token prices must be supplied together")
        if self.max_cost_usd is not None and self.input_usd_per_million is None:
            raise ValueError("A monetary budget requires known token prices")
        return self

    @classmethod
    def from_env(cls, env_file: Path | None = None):
        # Explicit opt-in avoids loading a real credential in tests or Mock runs.
        environment = dict(os.environ)
        if env_file is not None:
            environment = read_env_file(env_file) | environment
        required = {
            "base_url": "ALGOFACTORY_API_BASE_URL",
            "model": "ALGOFACTORY_API_MODEL",
            "api_key": "ALGOFACTORY_API_KEY",
        }
        if any(not environment.get(key) for key in required.values()):
            raise ProviderError("api_configuration_missing")
        values = {field: environment[key] for field, key in required.items()}
        optional = (
            "api_style",
            "auth_style",
            "max_cost_usd",
            "input_usd_per_million",
            "output_usd_per_million",
            "max_calls",
            "max_retries",
            "max_output_tokens",
            "max_request_bytes",
            "timeout_seconds",
        )
        for name in optional:
            env_name = (
                "ALGOFACTORY_API_STYLE"
                if name == "api_style"
                else "ALGOFACTORY_API_" + name.upper()
            )
            value = environment.get(env_name, "").strip()
            if value:
                values[name] = value
        try:
            for name in (
                "max_cost_usd",
                "input_usd_per_million",
                "output_usd_per_million",
                "timeout_seconds",
            ):
                if name in values:
                    values[name] = float(values[name])
            for name in ("max_calls", "max_retries", "max_output_tokens", "max_request_bytes"):
                if name in values:
                    values[name] = int(values[name])
            values["api_key"] = SecretStr(values["api_key"])
            return cls(**values)
        except (ValueError, ValidationError):
            raise ProviderError("api_configuration_invalid") from None


def read_env_file(path: Path) -> dict[str, str]:
    """Read literal assignments without executing shell or expanding variables."""
    import re

    try:
        if path.stat().st_size > 65536:
            raise ValueError("Too large")
        result = {}
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            key, separator, value = line.removeprefix("export ").partition("=")
            key, value = key.strip(), value.strip()
            if not separator or not re.fullmatch(r"ALGOFACTORY_[A-Z0-9_]+", key) or key in result:
                raise ValueError("Invalid assignment")
            if value.startswith(("'", '"')):
                if len(value) < 2 or value[-1] != value[0]:
                    raise ValueError("Invalid quote")
                value = value[1:-1]
            result[key] = value
        return result
    except (OSError, UnicodeError, ValueError):
        raise ProviderError("api_env_file_invalid") from None


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
        # Preserve only known machine codes; never persist arbitrary server text.
        service_code = None
        try:
            error = json.loads(exc.read(16384)).get("error", {})
            code = error.get("code") if isinstance(error, dict) else None
            if code in {
                "DeploymentNotFound",
                "ResourceNotFound",
                "OperationNotSupported",
                "InvalidApiKey",
                "PermissionDenied",
                "InvalidRequest",
                "BadRequest",
                "invalid_request_error",
                "unsupported_parameter",
                "unsupported_value",
                "model_not_found",
                "content_filter",
                "RateLimitReached",
                "429",
                "404",
            }:
                service_code = code
        except (ValueError, AttributeError, TypeError, OSError):
            pass
        finally:
            exc.close()
        details = {"http_status": status, "service_error_code": service_code}
        if status in {401, 403}:
            raise ProviderError("authentication_failed", **details) from None
        if status == 429:
            raise ProviderError("rate_limited", retryable=True, **details) from None
        raise ProviderError("http_error", retryable=status >= 500, **details) from None
    except TimeoutError:
        raise ProviderError("timeout", retryable=True) from None
    except (URLError, OSError, HTTPException):
        raise ProviderError("connection_failed", retryable=True) from None


class APIProvider(Provider):
    """Responses or Chat Completions; estimates never claim actual billed spend."""

    mode = "api"

    def __init__(self, config: APIConfig, transport: Callable = http_transport):
        super().__init__(max_calls=config.max_calls, max_retries=config.max_retries)
        self.config, self.transport = config, transport
        self.reserved_cost_usd = 0.0 if config.input_usd_per_million is not None else None

    def usage_summary(self) -> dict:
        known = [
            a for a in self.audit if a.input_tokens is not None and a.output_tokens is not None
        ]
        input_tokens = sum(a.input_tokens for a in known)
        output_tokens = sum(a.output_tokens for a in known)
        estimate = None
        if known and self.config.input_usd_per_million is not None:
            estimate = (
                input_tokens * self.config.input_usd_per_million
                + output_tokens * self.config.output_usd_per_million
            ) / 1_000_000
        return {
            "calls": self.calls,
            "call_limit": self.max_calls,
            "calls_with_usage": len(known),
            "calls_without_usage": self.calls - len(known),
            "known_input_tokens": input_tokens,
            "known_output_tokens": output_tokens,
            "known_usage_cost_estimate_usd": estimate,
            "reserved_cost_estimate_usd": self.reserved_cost_usd,
            "max_cost_usd": self.config.max_cost_usd,
            "input_usd_per_million": self.config.input_usd_per_million,
            "output_usd_per_million": self.config.output_usd_per_million,
            "billing_note": "Estimates only; missing usage and subscription pricing require Azure billing reconciliation.",
        }

    def _body(self, request: ProviderRequest, schema: dict) -> bytes:
        if self.config.api_style == "responses":
            return json.dumps(
                {
                    "model": self.config.model,
                    "instructions": request.instruction
                    + "\nReturn JSON matching this schema:\n"
                    + json.dumps(schema, ensure_ascii=False),
                    "input": "Respond with JSON.\n"
                    + json.dumps(request.model_dump(exclude={"instruction"}), ensure_ascii=False),
                    "text": {"format": {"type": "json_object"}},
                    "max_output_tokens": self.config.max_output_tokens,
                    "temperature": 0,
                    "store": False,
                },
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
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

    def _reserve(self, request: ProviderRequest, schema: dict) -> float | None:
        size = len(self._body(request, schema))
        if size > self.config.max_request_bytes:
            raise ProviderError("request_too_large")
        if self.config.input_usd_per_million is None:
            return None
        # Conservative byte-based input estimate plus framing allowance. Keep reservations
        # even on failed requests because an interrupted request may still incur charges.
        cost = (
            (size + 1024) * self.config.input_usd_per_million
            + self.config.max_output_tokens * self.config.output_usd_per_million
        ) / 1_000_000
        if (
            self.config.max_cost_usd is not None
            and self.reserved_cost_usd + cost > self.config.max_cost_usd
        ):
            raise ProviderError("cost_budget_exhausted")
        self.reserved_cost_usd += cost
        return cost

    def _raw(self, request: ProviderRequest, schema: dict) -> str:
        responses = self.config.api_style == "responses"
        auth = (
            {"api-key": self.config.api_key.get_secret_value()}
            if self.config.auth_style == "api_key"
            else {"Authorization": "Bearer " + self.config.api_key.get_secret_value()}
        )
        payload = self.transport(
            self.config.base_url.rstrip("/") + ("/responses" if responses else "/chat/completions"),
            {"Content-Type": "application/json", **auth},
            self._body(request, schema),
            self.config.timeout_seconds,
        )
        try:
            data = json.loads(payload)
            if not isinstance(data, dict):
                raise ValueError("Envelope must be an object")
            usage = data.get("usage")
            if isinstance(usage, dict):
                for target, origin in (
                    ("input_tokens", "input_tokens" if responses else "prompt_tokens"),
                    ("output_tokens", "output_tokens" if responses else "completion_tokens"),
                ):
                    value = usage.get(origin)
                    if type(value) is int and value >= 0:
                        self.last_usage[target] = value
            if responses:
                if data.get("status") != "completed" or data.get("error"):
                    raise ProviderError("incomplete_response", retryable=True)
                output = data["output"]
                if not isinstance(output, list):
                    raise ValueError("Output must be an array")
                parts = []
                for item in output:
                    if not isinstance(item, dict):
                        raise ValueError("Output item must be an object")
                    if item.get("type") == "reasoning":
                        continue
                    if item.get("type") != "message" or item.get("role") != "assistant":
                        raise ValueError("Unexpected output item")
                    if item.get("status") != "completed":
                        raise ProviderError("incomplete_response", retryable=True)
                    content = item["content"]
                    if not isinstance(content, list):
                        raise ValueError("Content must be an array")
                    for part in content:
                        if not isinstance(part, dict):
                            raise ValueError("Invalid content part")
                        if part.get("type") == "refusal":
                            raise ProviderError("model_refusal")
                        if part.get("type") != "output_text" or not isinstance(
                            part.get("text"), str
                        ):
                            raise ValueError("Invalid content part")
                        parts.append(part["text"])
                if not parts:
                    raise ValueError("Missing output text")
                return "".join(parts)
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
