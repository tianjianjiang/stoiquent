from __future__ import annotations

from stoiquent.sandbox.policy import default_policy, merge_policy


def test_default_policy_has_standard_values() -> None:
    policy = default_policy()
    assert policy.cpu_seconds == 120.0
    assert policy.memory_mb == 512
    assert policy.disk_mb == 100
    assert policy.max_pids == 64
    assert policy.network == "none"


def test_should_merge_overrides() -> None:
    base = default_policy()
    merged = merge_policy(base, {"memory_mb": 1024, "network": "host"})
    assert merged.memory_mb == 1024
    assert merged.network == "host"
    assert merged.cpu_seconds == 120.0


def test_should_not_mutate_base() -> None:
    base = default_policy()
    merge_policy(base, {"memory_mb": 2048})
    assert base.memory_mb == 512


def test_should_create_independent_policies() -> None:
    p1 = default_policy()
    p2 = default_policy()
    assert p1 is not p2
    assert p1 == p2
