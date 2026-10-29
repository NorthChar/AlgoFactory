import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from pydantic import SecretStr, ValidationError

from algofactory.knowledge.extraction import extract_document
from algofactory.llm.providers import (
    APIConfig,
    APIProvider,
    MockProvider,
    ProviderError,
    ProviderRequest,
)
from algofactory.schemas.knowledge import Extraction


def config(**kwargs):
    return APIConfig(
        **(
            dict(
                base_url="https://example.invalid/v1",
                model="contract-test",
                api_key=SecretStr("test-key-never-log"),
                max_cost_usd=2.0,
                input_usd_per_million=1.0,
                output_usd_per_million=2.0,
            )
            | kwargs
        )
    )


def envelope(response, finish_reason="stop"):
    return json.dumps(
        {
            "choices": [
                {"finish_reason": finish_reason, "message": {"content": json.dumps(response)}}
            ]
        }
    ).encode()


def test_mock_and_api_share_extraction_contract(source, fixtures):
    observed = []

    def transport(url, headers, body, timeout):
        observed.append((url, headers, json.loads(body), timeout))
        return envelope(fixtures[source.sha256]["response"])

    mock_batch = extract_document(source, MockProvider(fixtures))
    api = APIProvider(config(), transport)
    api_batch = extract_document(source, api)
    assert mock_batch == api_batch
    url, headers, body, timeout = observed[0]
    assert url.endswith("/v1/chat/completions")
    assert headers["Authorization"] == "Bearer test-key-never-log"
    assert body["response_format"] == {"type": "json_object"}
    assert body["max_tokens"] == 8192
    assert body["model"] == "contract-test"
    assert json.loads(body["messages"][1]["content"])["source"]["sha256"] == source.sha256
    assert timeout == 30.0
    assert api.audit[0].mode == "api"
    assert "test-key-never-log" not in repr(api.audit)
    assert "test-key-never-log" not in repr(api.config)


@pytest.mark.parametrize("fault", ["invalid_json", "timeout", "rate_limited"])
def test_mock_fault_recovery_and_attempt_log(source, fixtures, fault):
    fixtures[source.sha256]["faults"] = [fault]
    provider = MockProvider(fixtures)
    result = extract_document(source, provider)
    assert len(result.entities) == 6
    assert provider.calls == 2
    assert provider.audit[-1].status == "ok"
    assert provider.audit[0].status != "ok"


def test_retry_exhaustion_has_no_silent_fallback(source, fixtures):
    calls = []

    def transport(*args):
        calls.append(True)
        raise ProviderError("timeout", retryable=True)

    provider = APIProvider(config(), transport)
    with pytest.raises(ProviderError, match="timeout"):
        extract_document(source, provider)
    assert len(calls) == 2
    assert all(a.mode == "api" and a.status == "timeout" for a in provider.audit)
    assert provider.reserved_cost_usd > 0


def test_api_malformed_json_retries_bounded(source, fixtures):
    responses = iter(
        [envelope("not a matching object"), envelope(fixtures[source.sha256]["response"])]
    )
    provider = APIProvider(config(), lambda *args: next(responses))
    extract_document(source, provider)
    assert [a.status for a in provider.audit] == ["invalid_structured_response", "ok"]


@pytest.mark.parametrize(
    "body",
    [
        b"not JSON",
        b"{}",
        b'{"choices":[]}',
        b'{"choices":[1]}',
        b'{"choices":[{"finish_reason":"length"}]}',
    ],
)
def test_bad_envelope_or_truncated_answer_is_not_accepted(source, body):
    provider = APIProvider(config(max_retries=0), lambda *args: body)
    with pytest.raises(ProviderError):
        extract_document(source, provider)
    assert provider.calls == 1


def test_authentication_failure_is_not_retried(source):
    def transport(*args):
        raise ProviderError("authentication_failed")

    provider = APIProvider(config(), transport)
    with pytest.raises(ProviderError, match="authentication_failed"):
        extract_document(source, provider)
    assert provider.calls == 1


def test_call_and_cost_budgets_prevent_request(source, fixtures):
    provider = MockProvider(fixtures, max_calls=1)
    extract_document(source, provider)
    with pytest.raises(ProviderError, match="call_budget_exhausted"):
        extract_document(source, provider)
    calls = []
    api = APIProvider(config(max_cost_usd=0.000001), lambda *args: calls.append(True))
    with pytest.raises(ProviderError, match="cost_budget_exhausted"):
        extract_document(source, api)
    assert calls == [] and api.calls == 0


def test_request_size_budget_and_schema_checks(source):
    api = APIProvider(config(max_request_bytes=1024), lambda *args: pytest.fail("should not send"))
    with pytest.raises(ProviderError, match="request_too_large"):
        extract_document(source, api)
    with pytest.raises(ValidationError):
        config(max_cost_usd=float("nan"))


@pytest.mark.parametrize(
    "url",
    [
        "http://external.example/v1",
        "https://name:password@example.com/v1",
        "https://example.com/v1?key=secret",
        "https://example.com/v1#fragment",
    ],
)
def test_unsafe_endpoint_configuration_rejected(url):
    with pytest.raises(ValidationError):
        config(base_url=url)


def test_missing_api_configuration_does_not_fall_back(monkeypatch):
    monkeypatch.delenv("ALGOFACTORY_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="api_configuration_missing"):
        APIConfig.from_env()


def test_source_mismatch_and_historical_claim_rejected(source, fixtures):
    response = fixtures[source.sha256]["response"]
    response["source_id"] = "source:wrong"
    with pytest.raises(ProviderError, match="extraction_source_mismatch"):
        extract_document(source, MockProvider(fixtures))
    response["source_id"] = source.id
    original = response["entities"][0]
    response["entities"][0] = {k: original[k] for k in ("id", "source_id", "source_span", "name")}
    response["entities"][0].update(
        type="Experience",
        record={
            "experience_id": original["id"],
            "condition": "a",
            "action": "b",
            "outcome": "unverified",
            "verification_status": "proposed",
        },
    )
    # The document-only schema now rejects historical claims before graph assembly.
    with pytest.raises(ProviderError, match="invalid_structured_response"):
        extract_document(source, MockProvider(fixtures))


def test_shared_provider_rejects_extra_fields(source, fixtures):
    fixtures[source.sha256]["response"]["arbitrary"] = "must not leak into the store"
    request = ProviderRequest(
        role="knowledge",
        operation="extract",
        instruction="Extract JSON",
        source=source.model_dump(mode="json"),
    )
    provider = MockProvider(fixtures, max_retries=0)
    with pytest.raises(ProviderError, match="invalid_structured_response"):
        provider.complete(request, Extraction)


def test_invalid_mock_fixture_is_explicit_failure():
    with pytest.raises(ProviderError, match="invalid_mock_fixture"):
        MockProvider({"not-a-source-hash": {"response": {}}})


@pytest.fixture
def local_api():
    state = {"requests": [], "status": 200, "payload": b"{}", "redirect": None}

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            state["requests"].append(
                {
                    "path": self.path,
                    "body": json.loads(self.rfile.read(int(self.headers["Content-Length"]))),
                }
            )
            self.send_response(state["status"])
            if state["redirect"]:
                self.send_header("Location", state["redirect"])
            self.end_headers()
            self.wfile.write(state["payload"])

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}/v1", state
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def test_real_http_transport_against_local_fake_service(local_api, source, fixtures):
    url, state = local_api
    state["payload"] = envelope(fixtures[source.sha256]["response"])
    provider = APIProvider(config(base_url=url, allow_local_http=True))
    assert len(extract_document(source, provider).entities) == 6
    assert state["requests"][0]["path"] == "/v1/chat/completions"
    assert len(state["requests"]) == 1


@pytest.mark.parametrize(
    "status, category", [(401, "authentication_failed"), (429, "rate_limited"), (503, "http_error")]
)
def test_http_errors_redact_server_body(local_api, source, status, category):
    url, state = local_api
    state.update(status=status, payload=b"secret response do not log test-key-never-log")
    provider = APIProvider(config(base_url=url, allow_local_http=True, max_retries=0))
    with pytest.raises(ProviderError, match=category) as error:
        extract_document(source, provider)
    assert "secret response" not in str(error.value)
    assert "test-key-never-log" not in repr(provider.audit)


def test_redirect_does_not_forward_credentials(local_api, source):
    url, state = local_api
    state.update(status=307, redirect=url + "/redirect-target")
    provider = APIProvider(config(base_url=url, allow_local_http=True, max_retries=0))
    with pytest.raises(ProviderError, match="http_error"):
        extract_document(source, provider)
    assert len(state["requests"]) == 1
