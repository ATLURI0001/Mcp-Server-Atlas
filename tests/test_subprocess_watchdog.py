import pytest
from scripts.subprocess_watchdog import (
    SubprocessWatchdog,
    WatchdogConfig,
    ProcessHealthState,
    WatchdogError,
)


def test_watchdog_registration_and_heartbeat():
    watchdog = SubprocessWatchdog()
    desc = watchdog.register_process("mcp-github", 12345)

    assert desc.server_id == "mcp-github"
    assert desc.pid == 12345
    assert desc.state == ProcessHealthState.STARTING

    # Heartbeat marks it healthy
    assert watchdog.record_heartbeat("mcp-github") is True
    assert watchdog.processes["mcp-github"].state == ProcessHealthState.HEALTHY
    assert watchdog.processes["mcp-github"].consecutive_failures == 0


def test_watchdog_input_validation():
    watchdog = SubprocessWatchdog()

    with pytest.raises(ValueError):
        watchdog.register_process("", 123)

    with pytest.raises(ValueError):
        watchdog.register_process("valid-id", -5)


def test_watchdog_failure_progression_and_quarantine():
    cfg = WatchdogConfig(max_consecutive_failures=3, quarantine_cooldown_sec=10.0)
    watchdog = SubprocessWatchdog(cfg)
    watchdog.register_process("mcp-unstable", 2222)

    # 1st failure -> UNRESPONSIVE
    state = watchdog.record_failure("mcp-unstable")
    assert state == ProcessHealthState.UNRESPONSIVE

    # 2nd failure -> UNRESPONSIVE
    state = watchdog.record_failure("mcp-unstable")
    assert state == ProcessHealthState.UNRESPONSIVE

    # 3rd failure -> QUARANTINED
    state = watchdog.record_failure("mcp-unstable")
    assert state == ProcessHealthState.QUARANTINED

    # Can spawn is blocked
    assert watchdog.can_spawn("mcp-unstable") is False

    # Attempting to register again during quarantine raises WatchdogError
    with pytest.raises(WatchdogError):
        watchdog.register_process("mcp-unstable", 3333)


def test_watchdog_scan_and_reap_timeout():
    cfg = WatchdogConfig(heartbeat_timeout_sec=5.0)
    watchdog = SubprocessWatchdog(cfg)

    t0 = 1000.0
    watchdog.register_process("mcp-slow", 4444, start_time=t0)
    watchdog.record_heartbeat("mcp-slow", timestamp=t0)

    # Scan at t0 + 2s (within 5s timeout) -> nothing reaped
    reaped = watchdog.scan_and_reap(current_time=t0 + 2.0)
    assert len(reaped) == 0

    # Scan at t0 + 6s (past 5s timeout) -> reaped as UNRESPONSIVE
    reaped = watchdog.scan_and_reap(current_time=t0 + 6.0)
    assert len(reaped) == 1
    assert reaped[0]["server_id"] == "mcp-slow"
    assert reaped[0]["new_state"] == ProcessHealthState.UNRESPONSIVE

    telemetry = watchdog.get_telemetry()
    assert telemetry["timeouts_detected"] == 1
    assert telemetry["reaped_count"] == 1


def test_watchdog_quarantine_cooldown_expiry():
    cfg = WatchdogConfig(max_consecutive_failures=1, quarantine_cooldown_sec=15.0)
    watchdog = SubprocessWatchdog(cfg)

    t0 = 2000.0
    watchdog.register_process("mcp-flaky", 5555, start_time=t0)
    watchdog.record_failure("mcp-flaky", timestamp=t0)
    assert watchdog.processes["mcp-flaky"].state == ProcessHealthState.QUARANTINED

    # At t0 + 5s: still quarantined
    assert watchdog.can_spawn("mcp-flaky", current_time=t0 + 5.0) is False

    # At t0 + 20s (> 15s cooldown): permitted to spawn
    assert watchdog.can_spawn("mcp-flaky", current_time=t0 + 20.0) is True


def test_watchdog_termination_and_telemetry():
    watchdog = SubprocessWatchdog()
    watchdog.register_process("srv-1", 101)
    watchdog.register_process("srv-2", 102)
    watchdog.record_heartbeat("srv-1")

    assert watchdog.terminate_process("srv-2") is True
    assert watchdog.processes["srv-2"].state == ProcessHealthState.TERMINATED

    telemetry = watchdog.get_telemetry()
    assert telemetry["total_tracked"] == 2
    assert telemetry["active_healthy"] == 1
