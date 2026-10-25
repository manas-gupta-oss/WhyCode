import traceback

import pytest

from whycode.config import ConfigError, Settings, load_settings

# Distinctive fake values so the tests can prove none of them ever leak into an error.
FAKE_ENV = {
    "NEO4J_URI": "neo4j+s://fake-host.example",
    "NEO4J_USERNAME": "fake-user-u1",
    "NEO4J_PASSWORD": "fake-secret-p1",
    "NEO4J_DATABASE": "fake-db-d1",
    "GEMINI_API_KEY": "fake-secret-g1",
    "GROQ_API_KEY": "fake-secret-q1",
    "GEMINI_MODEL": "fake-model-gm",
    "GROQ_MODEL": "fake-model-qm",
    "LLM_MAX_CALLS": "20",
    "GITHUB_TOKEN": "fake-secret-t1",
    "POSTGRES_DSN": "postgresql://u:fake-secret-pg@localhost/db",
}


@pytest.fixture
def env(monkeypatch):
    """Isolate from the developer's real .env and environment."""
    for name in FAKE_ENV:
        monkeypatch.delenv(name, raising=False)

    def apply(**overrides):
        for name, value in {**FAKE_ENV, **overrides}.items():
            if value is None:
                monkeypatch.delenv(name, raising=False)
            else:
                monkeypatch.setenv(name, value)

    return apply


def _assert_no_values_leak(exc: BaseException):
    rendered = str(exc) + repr(exc) + "".join(traceback.format_exception(exc))
    for value in FAKE_ENV.values():
        assert value not in rendered


def test_loads_all_settings(env):
    env()
    s = load_settings(_env_file=None)
    assert s.gemini_model == "fake-model-gm"
    assert s.llm_max_calls == 20
    assert s.groq_api_key.get_secret_value() == "fake-secret-q1"


def test_secrets_hidden_in_repr(env):
    env()
    s = load_settings(_env_file=None)
    for value in FAKE_ENV.values():
        if "secret" in value:
            assert value not in repr(s)
            assert value not in str(s)


def test_missing_variable_is_named_without_values(env):
    env(GROQ_API_KEY=None)
    with pytest.raises(ConfigError) as info:
        load_settings(_env_file=None)
    assert "GROQ_API_KEY" in str(info.value)
    assert "missing" in str(info.value)
    _assert_no_values_leak(info.value)


def test_empty_value_counts_as_missing(env):
    env(GITHUB_TOKEN="")
    with pytest.raises(ConfigError, match="GITHUB_TOKEN"):
        load_settings(_env_file=None)


def test_several_missing_all_named(env):
    env(NEO4J_PASSWORD=None, POSTGRES_DSN=None)
    with pytest.raises(ConfigError) as info:
        load_settings(_env_file=None)
    assert "NEO4J_PASSWORD" in str(info.value)
    assert "POSTGRES_DSN" in str(info.value)
    _assert_no_values_leak(info.value)


def test_invalid_value_named_but_not_shown(env):
    env(LLM_MAX_CALLS="not-a-number-fake-secret-x9")
    with pytest.raises(ConfigError) as info:
        load_settings(_env_file=None)
    assert "LLM_MAX_CALLS" in str(info.value)
    assert "not-a-number-fake-secret-x9" not in "".join(traceback.format_exception(info.value))


def test_negative_budget_rejected(env):
    env(LLM_MAX_CALLS="-1")
    with pytest.raises(ConfigError, match="LLM_MAX_CALLS"):
        load_settings(_env_file=None)


def test_error_does_not_chain_pydantic_error(env):
    env(GEMINI_API_KEY=None)
    with pytest.raises(ConfigError) as info:
        load_settings(_env_file=None)
    assert info.value.__suppress_context__ is True
    assert info.value.__cause__ is None


def test_env_file_points_at_project_root():
    assert str(Settings.model_config["env_file"]).endswith(".env")
