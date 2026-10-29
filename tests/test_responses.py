"""Offline contracts for Azure Responses, local secrets and optional monetary limits."""

import json

import pytest
from pydantic import SecretStr, ValidationError

from algofactory.llm.providers import APIConfig, APIProvider, ProviderError, ProviderRequest
from algofactory.schemas.contracts import Contract


class Reply(Contract):
    value: str


def config(**changes):
    return APIConfig(
        **(
            dict(
                base_url="https://example.invalid/openai/v1/",
                model="deployment",
                api_key=SecretStr("do-not-print"),
                api_style="responses",
                auth_style="api_key",
                max_calls=2,
                max_retries=0,
            )
            | changes
        )
    )


def request():
    return ProviderRequest(role="builder", operation="check", instruction="Return JSON", source={})


def envelope(**changes):
    return json.dumps(
        dict(
            status="completed",
            error=None,
            output=[
                {
                    "type": "message",
                    "role": "assistant",
                    "status": "completed",
                    "content": [{"type": "output_text", "text": '{"value":"ok"}'}],
                }
            ],
            usage={"input_tokens": 12, "output_tokens": 8},
        )
        | changes
    ).encode()


def test_responses_wire_and_usage_without_prices():
    captured = []

    def transport(url, headers, body, timeout):
        captured.append((url, headers, json.loads(body)))
        return envelope()

    provider = APIProvider(config(), transport)
    assert provider.complete(request(), Reply).value == "ok"
    url, headers, body = captured[0]
    assert url == "https://example.invalid/openai/v1/responses"
    assert headers["api-key"] == "do-not-print" and "Authorization" not in headers
    assert body["store"] is False and "tools" not in body
    assert body["text"] == {"format": {"type": "json_object"}}
    assert body["max_output_tokens"] == 8192
    assert "JSON" in body["instructions"] and body["model"] == "deployment"
    assert "JSON" in body["input"]  # Azure JSON mode validates input as well as instructions.
    summary = provider.usage_summary()
    assert summary["known_input_tokens"] == 12 and summary["known_output_tokens"] == 8
    assert summary["reserved_cost_estimate_usd"] is None
    assert summary["known_usage_cost_estimate_usd"] is None
    assert "do-not-print" not in json.dumps(summary) + repr(provider.audit)


@pytest.mark.parametrize(
    "payload,category",
    [
        (b"[]", "invalid_api_envelope"),
        (envelope(status="incomplete"), "incomplete_response"),
        (envelope(output=[]), "invalid_api_envelope"),
        (envelope(output=[1]), "invalid_api_envelope"),
        (
            envelope(
                output=[
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "refusal", "refusal": "secret"}],
                    }
                ]
            ),
            "model_refusal",
        ),
        (envelope(output=[{"type": "function_call"}]), "invalid_api_envelope"),
    ],
)
def test_responses_rejects_invalid_or_refused_output(payload, category):
    provider = APIProvider(config(), lambda *args: payload)
    with pytest.raises(ProviderError, match=category):
        provider.complete(request(), Reply)
    assert provider.calls == 1 and provider.audit[0].status == category
    assert "secret" not in repr(provider.audit)


def test_optional_money_limit_keeps_call_and_size_limits():
    provider = APIProvider(config(max_calls=1), lambda *args: envelope())
    provider.complete(request(), Reply)
    with pytest.raises(ProviderError, match="call_budget_exhausted"):
        provider.complete(request(), Reply)
    provider = APIProvider(config(max_request_bytes=1024), lambda *args: pytest.fail("sent"))
    big = request().model_copy(update={"source": {"text": "a" * 3000}})
    with pytest.raises(ProviderError, match="request_too_large"):
        provider.complete(big, Reply)
    with pytest.raises(ValidationError):
        config(max_cost_usd=1)
    with pytest.raises(ValidationError):
        config(input_usd_per_million=2.5)


def test_known_prices_track_estimates_without_enforcing_money_limit():
    provider = APIProvider(
        config(input_usd_per_million=2.5, output_usd_per_million=10), lambda *args: envelope()
    )
    provider.complete(request(), Reply)
    assert provider.usage_summary()["known_usage_cost_estimate_usd"] == pytest.approx(0.00011)
    assert provider.reserved_cost_usd > 0.00011
    assert provider.config.max_cost_usd is None


def test_missing_usage_is_unknown_not_zero():
    provider = APIProvider(config(), lambda *args: envelope(usage=None))
    provider.complete(request(), Reply)
    assert provider.audit[0].input_tokens is None
    assert provider.usage_summary()["calls_without_usage"] == 1
    assert provider.usage_summary()["known_usage_cost_estimate_usd"] is None


def test_env_file_is_explicit_literal_and_environment_has_priority(tmp_path, monkeypatch):
    for key in list(__import__("os").environ):
        if key.startswith("ALGOFACTORY_API_"):
            monkeypatch.delenv(key)
    path = tmp_path / ".env"
    path.write_text(
        "ALGOFACTORY_API_BASE_URL=https://example.invalid/v1\n"
        "ALGOFACTORY_API_MODEL=file-deployment\n"
        'ALGOFACTORY_API_KEY="$(do-not-execute)"\n'
        "ALGOFACTORY_API_MAX_COST_USD=\n"
        "ALGOFACTORY_API_STYLE=responses\n"
        "ALGOFACTORY_API_MAX_RETRIES=0\n"
    )
    with pytest.raises(ProviderError, match="api_configuration_missing"):
        APIConfig.from_env()
    monkeypatch.setenv("ALGOFACTORY_API_MODEL", "environment-deployment")
    cfg = APIConfig.from_env(path)
    assert cfg.model == "environment-deployment" and cfg.max_retries == 0
    assert cfg.api_key.get_secret_value() == "$(do-not-execute)"
    assert cfg.api_style == "responses" and cfg.max_cost_usd is None
    path.write_text("ALGOFACTORY_API_KEY=secret\nINVALID secret syntax\n")
    with pytest.raises(ProviderError, match="api_env_file_invalid") as error:
        APIConfig.from_env(path)
    assert "secret" not in str(error.value)


@pytest.mark.parametrize(
    "code,expected", [("DeploymentNotFound", "DeploymentNotFound"), ("secret-do-not-print", None)]
)
def test_http_error_only_persists_known_codes(monkeypatch, code, expected):
    import io
    from urllib.error import HTTPError

    from algofactory.llm import providers

    class Opener:
        def open(self, *args, **kwargs):
            raise HTTPError(
                "https://example.invalid",
                404,
                "not logged",
                {},
                io.BytesIO(json.dumps({"error": {"code": code, "message": "secret"}}).encode()),
            )

    monkeypatch.setattr(providers, "build_opener", lambda *args: Opener())
    provider = APIProvider(config())
    with pytest.raises(ProviderError, match="http_error"):
        provider.complete(request(), Reply)
    assert provider.audit[0].http_status == 404
    assert provider.audit[0].service_error_code == expected
    assert "secret" not in repr(provider.audit)


def test_live_verifier_has_one_shared_budget_and_no_retries(tmp_path, monkeypatch, capsys):
    import sys

    from scripts import verify_live_api as live

    cfg = config(max_calls=4, max_retries=2)
    monkeypatch.setattr(live.APIConfig, "from_env", lambda path: cfg)
    monkeypatch.setattr(live, "verify_dataset", lambda path: {"task_profile": "banking77"})
    monkeypatch.setattr(live, "DockerExecutor", lambda *args: None)
    used = []

    def provider_factory(configuration):
        p = APIProvider(
            configuration,
            lambda *args: envelope(
                output=[
                    {
                        "type": "message",
                        "role": "assistant",
                        "status": "completed",
                        "content": [{"type": "output_text", "text": '{"status":"ok"}'}],
                    }
                ]
            ),
        )
        used.append(p)
        return p

    def workflow(**kwargs):
        p = kwargs["provider"]
        assert p.calls == 1 and p.max_calls == 5 and p.max_retries == 0
        for _ in range(4):
            p.complete(request(), live.SmokeReply)
        with pytest.raises(ProviderError, match="call_budget_exhausted"):
            p.complete(request(), live.SmokeReply)
        return dict(status="accepted", error_category=None, test_attempted=True, persisted=True)

    monkeypatch.setattr(live, "APIProvider", provider_factory)
    monkeypatch.setattr(live, "run_workflow", workflow)
    out = tmp_path / "run"
    monkeypatch.setattr(
        sys, "argv", ["verify_live_api", "--env-file", "unused", "--output-dir", str(out)]
    )
    assert live.main() == 0
    assert used[0].calls == 5
    summary = json.loads((out / "verification.json").read_text())
    assert summary["smoke_status"] == "passed" and summary["usage"]["calls_with_usage"] == 5
    assert "do-not-print" not in capsys.readouterr().out
