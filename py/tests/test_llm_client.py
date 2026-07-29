"""Tests for kb_ai.llm._client module."""

from __future__ import annotations

import os
from unittest.mock import patch

from kb_ai.llm._infra import get_client, reset_client, _DEFAULT_BASE_URL


class TestGetClient:
    """Test the get_client singleton."""

    def setup_method(self):
        reset_client()

    def teardown_method(self):
        reset_client()

    @patch.dict(os.environ, {"LLM_BASE_URL": "http://test:8080/v1", "LLM_API_KEY": "sk-test"})
    def test_creates_client_with_env_vars(self):
        client = get_client()
        assert str(client.base_url).rstrip("/") == "http://test:8080/v1"
        assert client.api_key == "sk-test"

    @patch.dict(os.environ, {"OPENAI_BASE_URL": "http://openai:8080/v1", "OPENAI_API_KEY": "sk-oai"}, clear=False)
    def test_falls_back_to_openai_env_vars(self):
        # Remove LLM-specific vars if present
        env = os.environ.copy()
        env.pop("LLM_BASE_URL", None)
        env.pop("LLM_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            os.environ["OPENAI_BASE_URL"] = "http://openai:8080/v1"
            os.environ["OPENAI_API_KEY"] = "sk-oai"
            client = get_client()
            assert str(client.base_url).rstrip("/") == "http://openai:8080/v1"
            assert client.api_key == "sk-oai"

    @patch.dict(os.environ, {"OPENAI_API_KEY": "sk-placeholder"}, clear=False)
    def test_default_base_url(self):
        env = os.environ.copy()
        env.pop("LLM_BASE_URL", None)
        env.pop("OPENAI_BASE_URL", None)
        env["OPENAI_API_KEY"] = "sk-placeholder"
        with patch.dict(os.environ, env, clear=True):
            client = get_client()
            assert str(client.base_url).rstrip("/") == _DEFAULT_BASE_URL

    def test_singleton_returns_same_instance(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}):
            c1 = get_client()
            c2 = get_client()
            assert c1 is c2

    def test_reset_client_clears_singleton(self):
        with patch.dict(os.environ, {"LLM_API_KEY": "sk-test"}):
            c1 = get_client()
            reset_client()
            c2 = get_client()
            assert c1 is not c2
