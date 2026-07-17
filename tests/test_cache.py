"""Cache key stability and sensitivity."""

from evalkit.cache import cache_key


def _key(**over):
    base = dict(
        model="m",
        system="sys",
        prompt="hello",
        params={"temperature": 0, "max_tokens": 10},
        sample=0,
    )
    base.update(over)
    return cache_key(**base)


def test_key_is_stable():
    assert _key() == _key()


def test_model_changes_key():
    assert _key() != _key(model="other")


def test_system_changes_key():
    assert _key() != _key(system="different")


def test_prompt_changes_key():
    assert _key() != _key(prompt="hi")


def test_params_change_key():
    assert _key() != _key(params={"temperature": 1, "max_tokens": 10})


def test_param_order_does_not_change_key():
    assert cache_key("m", "s", "p", {"a": 1, "b": 2}, 0) == cache_key(
        "m", "s", "p", {"b": 2, "a": 1}, 0
    )


def test_sample_changes_key():
    assert _key(sample=0) != _key(sample=1)
