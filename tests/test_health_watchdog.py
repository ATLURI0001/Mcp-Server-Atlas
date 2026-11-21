"""Unit tests for Distributed Server Health Watchdog & Ping Heartbeat Rotary."""

import pytest
from scripts.health_watchdog import (
    ServerHealthWatchdog,
    ServerHealthState,
    WatchdogConfig,
)


def test_watchdog_registration():
    wd = ServerHealthWatchdog()
    wd.register_server("atlas-postgres", transport="stdio")

    snap = wd.get_snapshot("atlas-postgres")
    assert snap.server_id == "atlas-postgres"
    assert snap.state == ServerHealthState.HEALTHY
    assert snap.total_pings == 0
    assert snap.availability_pct == 100.0

    # Duplicate registration fails
    with pytest.raises(ValueError):
        wd.register_server("atlas-postgres")

    # Non-existent server lookup fails
    with pytest.raises(KeyError):
        wd.get_snapshot("unknown-server")


def test_heartbeat_success_and_latency_percentiles():
    wd = ServerHealthWatchdog(WatchdogConfig(degraded_latency_ms=500.0))
    wd.register_server("atlas-github")

    latencies = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]
    for lat in latencies:
        state = wd.record_heartbeat("atlas-github", success=True, latency_ms=lat)
        assert state == ServerHealthState.HEALTHY

    snap = wd.get_snapshot("atlas-github")
    assert snap.total_pings == 10
    assert snap.successful_pings == 10
    assert snap.availability_pct == 100.0
    assert snap.last_ping_ms == 100.0
    assert snap.p50_latency_ms == 55.0
    assert snap.p90_latency_ms == 91.0


def test_consecutive_failure_tripping_and_offline_recovery():
    config = WatchdogConfig(
        consecutive_failures_threshold=3,
        recovery_cooldown_sec=15.0,
    )
    wd = ServerHealthWatchdog(config)
    wd.register_server("atlas-k8s")

    t0 = 1000.0
    # 2 failures do not trip to OFFLINE
    wd.record_heartbeat("atlas-k8s", success=False, timestamp_sec=t0)
    wd.record_heartbeat("atlas-k8s", success=False, timestamp_sec=t0 + 1)
    assert wd.get_snapshot("atlas-k8s").state == ServerHealthState.HEALTHY

    # 3rd failure trips to OFFLINE
    state3 = wd.record_heartbeat("atlas-k8s", success=False, timestamp_sec=t0 + 2)
    assert state3 == ServerHealthState.OFFLINE
    snap_offline = wd.get_snapshot("atlas-k8s")
    assert snap_offline.state == ServerHealthState.OFFLINE
    assert snap_offline.consecutive_failures == 3

    # Recovery probe before cooldown -> False
    assert wd.should_probe_offline_server("atlas-k8s", current_time=t0 + 10) is False

    # Recovery probe after cooldown (15s elapsed) -> True
    assert wd.should_probe_offline_server("atlas-k8s", current_time=t0 + 20) is True

    # Successful canary probe ping recovers server to HEALTHY
    recovered_state = wd.record_heartbeat("atlas-k8s", success=True, latency_ms=15.0, timestamp_sec=t0 + 20)
    assert recovered_state == ServerHealthState.HEALTHY
    assert wd.get_snapshot("atlas-k8s").consecutive_failures == 0


def test_degraded_latency_state_transition():
    config = WatchdogConfig(degraded_latency_ms=200.0)
    wd = ServerHealthWatchdog(config)
    wd.register_server("atlas-search")

    # Fast pings
    wd.record_heartbeat("atlas-search", success=True, latency_ms=50.0)
    assert wd.get_snapshot("atlas-search").state == ServerHealthState.HEALTHY

    # High latency pings breach degraded threshold
    for _ in range(5):
        wd.record_heartbeat("atlas-search", success=True, latency_ms=350.0)

    snap = wd.get_snapshot("atlas-search")
    assert snap.state == ServerHealthState.DEGRADED
    assert snap.p90_latency_ms is not None and snap.p90_latency_ms >= 200.0
