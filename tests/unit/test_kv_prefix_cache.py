"""Unit tests for DeepSeek KV prefix-chain provider detection."""
from __future__ import annotations

from pa_agent.ai.deepseek_client import supports_kv_prefix_chain
from pa_agent.config.settings import AIProviderSettings


def test_prefix_chain_enabled_for_deepseek_native():
    settings = AIProviderSettings(
        base_url="https://api.deepseek.com",
        model="deepseek-reasoner",
        api_key="sk-test",
    )
    assert supports_kv_prefix_chain(settings) is True


def test_prefix_chain_disabled_for_unknown_gateway_model():
    settings = AIProviderSettings(
        base_url="https://gateway.example.com",
        model="custom-model",
        api_key="sk-test",
    )
    assert supports_kv_prefix_chain(settings) is False
