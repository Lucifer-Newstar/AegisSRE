from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest
from incidents_service.models import StrictModel
from incidents_service.providers import (
    ProviderConfig,
    ProviderError,
    StructuredProvider,
    wire_schema,
)
from pydantic import Field, ValidationError


class Reply(StrictModel):
    answer: str = Field(min_length=1, max_length=100)
    citation_ids: list[str] = Field(max_length=5)


@pytest.mark.parametrize("protocol", ["ollama", "openai"])
def test_structured_wire_protocol_without_live_inference(protocol: Any) -> None:
    observed: list[httpx.Request] = []

    def respond(request: httpx.Request) -> httpx.Response:
        observed.append(request)
        body = json.loads(request.content)
        assert "tools" not in body
        assert body["stream"] is False
        if protocol == "ollama":
            assert request.url.path == "/api/chat"
            assert body["format"]["additionalProperties"] is False
            assert body["options"]["num_predict"] == 1024
        else:
            assert request.url.path == "/v1/chat/completions"
            assert body["response_format"]["json_schema"]["strict"] is True
            assert body["max_completion_tokens"] == 1024
            assert body["store"] is False
        message = {
            "role": "assistant",
            "content": json.dumps({"answer": "Observed sample", "citation_ids": ["evidence-1"]}),
        }
        result = (
            {"message": message, "done": True, "done_reason": "stop"}
            if protocol == "ollama"
            else {"choices": [{"message": message, "finish_reason": "stop"}]}
        )
        return httpx.Response(200, json=result)

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            config = ProviderConfig(
                provider=protocol,
                base_url="http://localhost:11434"
                if protocol == "ollama"
                else "http://127.0.0.1:8000/v1",
                model="explicit-test-model",
            )
            provider = StructuredProvider(config, client)
            answer = await provider.generate(
                Reply, {"evidence": [{"id": "evidence-1", "message": "Observed sample"}]}
            )
            assert answer.citation_ids == ["evidence-1"]

    asyncio.run(exercise())
    assert len(observed) == 1


def test_disabled_provider_never_constructs_a_network_client() -> None:
    provider = StructuredProvider(ProviderConfig())
    assert provider.client is None

    async def exercise() -> None:
        with pytest.raises(ProviderError, match="provider_disabled"):
            await provider.generate(Reply, {})
        await provider.close()

    asyncio.run(exercise())


@pytest.mark.parametrize(
    "url,remote",
    [
        ("https://remote.invalid/v1", False),
        ("http://remote.invalid/v1", True),
        ("file:///etc/passwd", True),
        ("https://name:password@remote.invalid/v1", True),
    ],
)
def test_remote_origin_requires_deliberate_configuration(url: str, remote: bool) -> None:
    with pytest.raises(ValidationError):
        ProviderConfig(
            provider="openai", base_url=url, model="explicit-test-model", allow_remote=remote
        )
    config = ProviderConfig(api_key="synthetic-test-value")
    assert "synthetic-test-value" not in repr(config)
    assert "api_key" not in config.model_dump()


@pytest.mark.parametrize(
    "scenario",
    ["tools", "refusal", "truncated", "extra_fields", "oversized", "redirect", "timeout"],
)
def test_invalid_output_is_not_executed_retried_or_returned(scenario: str) -> None:
    calls = 0

    def respond(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        if scenario == "redirect":
            return httpx.Response(302, headers={"Location": "https://unapproved.invalid/"})
        if scenario == "timeout":
            raise httpx.ReadTimeout("synthetic timeout")
        if scenario == "oversized":
            return httpx.Response(200, content=b"x" * 64001)
        content: dict[str, Any] = {"answer": "Sample", "citation_ids": ["evidence-1"]}
        if scenario == "extra_fields":
            content["execute"] = "must-not-be-accepted"
        message: dict[str, Any] = {"role": "assistant", "content": json.dumps(content)}
        if scenario == "tools":
            message["tool_calls"] = [{"function": {"name": "execute", "arguments": "{}"}}]
        if scenario == "refusal":
            message["refusal"] = "synthetic refusal"
        return httpx.Response(
            200,
            json={
                "choices": [
                    {
                        "message": message,
                        "finish_reason": "length" if scenario == "truncated" else "stop",
                    }
                ]
            },
        )

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = StructuredProvider(
                ProviderConfig(
                    provider="openai",
                    base_url="http://localhost:8000/v1",
                    model="explicit-test-model",
                ),
                client,
            )
            with pytest.raises(ProviderError):
                await provider.generate(Reply, {})

    asyncio.run(exercise())
    assert calls == 1


def test_wire_subset_keeps_local_output_validation() -> None:
    schema = wire_schema(Reply.model_json_schema())
    assert schema["additionalProperties"] is False
    assert "maxLength" not in schema["properties"]["answer"]
    assert set(schema["required"]) == {"answer", "citation_ids"}
    with pytest.raises(ValidationError):
        Reply(answer="x" * 101, citation_ids=[])


@pytest.mark.parametrize(
    "payload",
    [{"value": object()}, {"value": float("nan")}, {"question": "x" * 24001}],
    ids=["non_json", "non_finite", "oversized"],
)
def test_invalid_input_never_reaches_transport(payload: dict[str, Any]) -> None:
    def respond(request: httpx.Request) -> httpx.Response:
        raise AssertionError("Invalid input was transmitted")

    async def exercise() -> None:
        async with httpx.AsyncClient(transport=httpx.MockTransport(respond)) as client:
            provider = StructuredProvider(
                ProviderConfig(
                    provider="openai",
                    base_url="http://localhost:8000/v1",
                    model="explicit-test-model",
                ),
                client,
            )
            with pytest.raises(ProviderError):
                await provider.generate(Reply, payload)

    asyncio.run(exercise())
