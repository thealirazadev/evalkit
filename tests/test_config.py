"""Config resolution: defaults < file < env < flags, plus malformed-file errors."""

import pytest

from evalkit.config import (
    DEFAULT_CONCURRENCY,
    DEFAULT_SUITES_GLOB,
    DEFAULT_TIMEOUT_SECONDS,
    load_config,
)
from evalkit.errors import ConfigError

CONFIG_YAML = """
provider:
  base_url: https://api.example.com/v1
  model: file-model
judge:
  model: file-judge
run:
  concurrency: 8
  timeout_seconds: 30
  cache: true
suites: custom/**/*.yaml
pricing:
  file-model: {input: 3.0, output: 15.0}
  file-judge: {input: 0.5, output: 1.5}
"""


def _write(tmp_path, text):
    path = tmp_path / "evalkit.yaml"
    path.write_text(text, encoding="utf-8")
    return path


def test_defaults_when_no_file_and_no_env(tmp_path):
    cfg = load_config(env={}, cwd=tmp_path)
    assert cfg.concurrency == DEFAULT_CONCURRENCY
    assert cfg.timeout_seconds == DEFAULT_TIMEOUT_SECONDS
    assert cfg.suites_glob == DEFAULT_SUITES_GLOB
    assert cfg.cache is True
    assert cfg.api_key is None
    assert cfg.base_url is None
    assert cfg.pricing == {}
    assert cfg.config_path is None


def test_file_values_applied(tmp_path):
    _write(tmp_path, CONFIG_YAML)
    cfg = load_config(env={}, cwd=tmp_path)
    assert cfg.base_url == "https://api.example.com/v1"
    assert cfg.default_model == "file-model"
    assert cfg.judge_model == "file-judge"
    assert cfg.concurrency == 8
    assert cfg.timeout_seconds == 30
    assert cfg.suites_glob == "custom/**/*.yaml"
    assert cfg.pricing["file-model"] == {"input": 3.0, "output": 15.0}
    assert cfg.config_path == tmp_path / "evalkit.yaml"


def test_env_overrides_file(tmp_path):
    _write(tmp_path, CONFIG_YAML)
    env = {
        "EVALKIT_API_KEY": "secret-key",
        "EVALKIT_BASE_URL": "https://env.example.com/v1",
        "EVALKIT_MODEL": "env-model",
        "EVALKIT_JUDGE_MODEL": "env-judge",
    }
    cfg = load_config(env=env, cwd=tmp_path)
    assert cfg.base_url == "https://env.example.com/v1"
    assert cfg.default_model == "env-model"
    assert cfg.judge_model == "env-judge"
    assert cfg.api_key == "secret-key"


def test_flags_beat_env_and_file(tmp_path):
    _write(tmp_path, CONFIG_YAML)
    env = {"EVALKIT_MODEL": "env-model", "EVALKIT_JUDGE_MODEL": "env-judge"}
    cfg = load_config(
        env=env,
        cwd=tmp_path,
        cli_model="flag-model",
        cli_judge_model="flag-judge",
        cli_concurrency=2,
        cli_no_cache=True,
    )
    assert cfg.model_for(None) == "flag-model"
    assert cfg.judge_model == "flag-judge"
    assert cfg.concurrency == 2
    assert cfg.cache is False


def test_model_precedence_includes_suite(tmp_path):
    _write(tmp_path, CONFIG_YAML)
    cfg = load_config(env={"EVALKIT_MODEL": "env-model"}, cwd=tmp_path)
    # suite model beats env/config default, but a --model flag beats the suite.
    assert cfg.model_for("suite-model") == "suite-model"
    flagged = load_config(env={}, cwd=tmp_path, cli_model="flag-model")
    assert flagged.model_for("suite-model") == "flag-model"


def test_no_color_from_env(tmp_path):
    cfg = load_config(env={"NO_COLOR": "1"}, cwd=tmp_path)
    assert cfg.no_color is True


def test_missing_explicit_config_file_errors(tmp_path):
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path, config_path=str(tmp_path / "nope.yaml"))
    assert "file not found" in exc.value.message


def test_malformed_yaml_errors(tmp_path):
    _write(tmp_path, "provider: [unclosed\n")
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path)
    assert exc.value.message.startswith("Invalid config")
    assert exc.value.exit_code == 2


def test_bad_pricing_errors(tmp_path):
    _write(tmp_path, "pricing:\n  m: {input: notnum, output: 1.0}\n")
    with pytest.raises(ConfigError):
        load_config(env={}, cwd=tmp_path)


def test_pricing_missing_output_errors(tmp_path):
    # A different branch than non-numeric: an entry lacking one of the required keys.
    _write(tmp_path, "pricing:\n  m: {input: 1.0}\n")
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path)
    assert "needs 'input' and 'output'" in exc.value.message
    assert exc.value.exit_code == 2


def test_bad_concurrency_in_config_errors(tmp_path):
    _write(tmp_path, "run:\n  concurrency: 0\n")
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path)
    assert "'run.concurrency' must be >= 1" in exc.value.message


def test_non_integer_timeout_in_config_errors(tmp_path):
    _write(tmp_path, "run:\n  timeout_seconds: soon\n")
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path)
    assert "'run.timeout_seconds' must be an integer" in exc.value.message


def test_non_string_suites_glob_errors(tmp_path):
    _write(tmp_path, "suites: [a, b]\n")
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path)
    assert "'suites' must be a string glob" in exc.value.message


def test_non_mapping_section_errors(tmp_path):
    _write(tmp_path, "provider: not-a-mapping\n")
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path)
    assert "'provider' must be a mapping" in exc.value.message


def test_unreadable_config_is_config_error(tmp_path):
    # A directory at the explicit config path exercises the read-failure branch (exit 2).
    cfgdir = tmp_path / "cfgdir"
    cfgdir.mkdir()
    with pytest.raises(ConfigError) as exc:
        load_config(env={}, cwd=tmp_path, config_path=str(cfgdir))
    assert exc.value.message.startswith("Invalid config")
    assert exc.value.exit_code == 2
