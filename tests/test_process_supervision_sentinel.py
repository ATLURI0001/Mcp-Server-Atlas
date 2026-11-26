"""
Tests for MCP Process Supervision Sentinel.
"""

import pytest
from scripts.process_supervision_sentinel import (
    ProcessRecord,
    ProcessState,
    ProcessSupervisionError,
    ProcessSupervisionSentinel,
)


def test_register_and_complete_process() -> None:
    sentinel = ProcessSupervisionSentinel(default_timeout_sec=5.0)
    rec = sentinel.register_process(
        pid=1001, command=["npx", "@modelcontextprotocol/server-postgres"], start_time=100.0
    )
    assert rec.pid == 1001
    assert rec.state == ProcessState.RUNNING
    assert sentinel.get_active_count() == 1

    completed = sentinel.mark_completed(pid=1001, exit_code=0, bytes_read=4096, end_time=102.5)
    assert completed.state == ProcessState.TERMINATED
    assert completed.exit_code == 0
    assert completed.bytes_read == 4096
    assert sentinel.get_active_count() == 0


def test_sweep_zombies_on_timeout() -> None:
    sentinel = ProcessSupervisionSentinel(default_timeout_sec=3.0)
    sentinel.register_process(
        pid=2001, command=["mcp-server-git"], timeout_sec=2.0, start_time=100.0
    )
    sentinel.register_process(
        pid=2002, command=["mcp-server-sqlite"], timeout_sec=10.0, start_time=100.0
    )

    # Sweep at t = 101.0 -> nothing reaped
    reaped = sentinel.sweep_zombies(current_time=101.0)
    assert len(reaped) == 0

    # Sweep at t = 103.0 -> PID 2001 reaped (elapsed 3.0 > timeout 2.0)
    reaped = sentinel.sweep_zombies(current_time=103.0)
    assert len(reaped) == 1
    assert reaped[0].pid == 2001
    assert reaped[0].state == ProcessState.KILLED_TIMEOUT
    assert "Execution exceeded deadline" in (reaped[0].violation_reason or "")

    # PID 2002 remains active
    assert sentinel.get_process(2002).state == ProcessState.RUNNING


def test_buffer_exhaustion_deadlock_handling() -> None:
    sentinel = ProcessSupervisionSentinel()
    sentinel.register_process(pid=3001, command=["mcp-server-large-output"])
    rec = sentinel.record_buffer_exhaustion(pid=3001, bytes_read=15 * 1024 * 1024)

    assert rec.state == ProcessState.KILLED_DEADLOCK
    assert "Stdout buffer exceeded" in rec.violation_reason


def test_capacity_and_validation_errors() -> None:
    sentinel = ProcessSupervisionSentinel(max_active_processes=2)
    sentinel.register_process(1, ["cmd1"])
    sentinel.register_process(2, ["cmd2"])

    # Exceed capacity
    with pytest.raises(ProcessSupervisionError) as exc_info:
        sentinel.register_process(3, ["cmd3"])
    assert exc_info.value.code == "CONCURRENCY_CAPACITY_EXCEEDED"

    # Invalid PID
    with pytest.raises(ProcessSupervisionError) as exc_info2:
        sentinel.register_process(-5, ["cmd"])
    assert exc_info2.value.code == "INVALID_PID"


def test_postmortem_generation() -> None:
    sentinel = ProcessSupervisionSentinel()
    sentinel.register_process(pid=4001, command=["hung-tool"], timeout_sec=1.0, start_time=10.0)
    sentinel.sweep_zombies(current_time=15.0)

    report = sentinel.generate_postmortem_report("INC-2026-MCP-9104")
    assert report["incident_id"] == "INC-2026-MCP-9104"
    assert report["status"] == "RESOLVED"
    assert report["reaped_process_count"] == 1
    assert len(report["reaped_samples"]) == 1
    assert report["reaped_samples"][0]["pid"] == 4001
