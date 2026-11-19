#!/usr/bin/env python3
"""
Unit tests for Mcp-Server-Atlas server registry & health probe engine.
"""

import sys
import unittest
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent.parent / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from server_registry import (
    HealthStatus,
    McpServerManifest,
    McpToolDefinition,
    ServerRegistryEngine,
    parse_semver,
    satisfies_semver,
)


class TestServerRegistry(unittest.TestCase):
    def setUp(self):
        self.engine = ServerRegistryEngine(failure_threshold=3, degrade_threshold=1)
        self.tool_read = McpToolDefinition(
            name="read_file",
            description="Reads file contents",
            required_params={"path"},
            optional_params={"encoding"},
        )
        self.tool_write = McpToolDefinition(
            name="write_file",
            description="Writes file contents",
            required_params={"path", "content"},
        )
        self.manifest_v1 = McpServerManifest(
            server_id="filesystem-server",
            display_name="Filesystem Server",
            version="1.4.2",
            homepage="https://github.com/example/filesystem",
            tools=(self.tool_read, self.tool_write),
        )
        self.manifest_v2 = McpServerManifest(
            server_id="filesystem-server-v2",
            display_name="Filesystem Server 2",
            version="2.0.1",
            homepage="https://github.com/example/filesystem2",
            tools=(self.tool_read,),
        )

    def test_semver_parsing_and_constraints(self):
        self.assertEqual(parse_semver("1.2.3"), (1, 2, 3))
        self.assertEqual(parse_semver("v2.10.4"), (2, 10, 4))
        with self.assertRaises(ValueError):
            parse_semver("invalid-version")

        self.assertTrue(satisfies_semver("1.4.2", "^1.0.0"))
        self.assertFalse(satisfies_semver("2.0.0", "^1.0.0"))
        self.assertTrue(satisfies_semver("1.4.2", ">=1.4.0"))
        self.assertFalse(satisfies_semver("1.3.9", ">=1.4.0"))
        self.assertTrue(satisfies_semver("2.0.1", "==2.0.1"))
        self.assertTrue(satisfies_semver("1.0.0", "*"))

    def test_registration_and_tool_query(self):
        self.engine.register(self.manifest_v1)
        self.engine.register(self.manifest_v2)

        # Query tool available on both
        results = self.engine.find_servers_for_tool("read_file")
        self.assertEqual(len(results), 2)

        # Query tool with version constraint
        v1_only = self.engine.find_servers_for_tool("read_file", version_constraint="^1.0.0")
        self.assertEqual(len(v1_only), 1)
        self.assertEqual(v1_only[0].server_id, "filesystem-server")

        # Query tool with parameter requirement
        write_servers = self.engine.find_servers_for_tool(
            "write_file", required_params={"path", "content"}
        )
        self.assertEqual(len(write_servers), 1)
        self.assertEqual(write_servers[0].server_id, "filesystem-server")

    def test_health_probe_transitions(self):
        self.engine.register(self.manifest_v1)
        sid = "filesystem-server"

        # Initially healthy on 1st success
        st = self.engine.record_probe(sid, success=True, latency_ms=45.0)
        self.assertEqual(st, HealthStatus.HEALTHY)

        # 1 failure -> Degraded
        st = self.engine.record_probe(sid, success=False, latency_ms=500.0)
        self.assertEqual(st, HealthStatus.DEGRADED)

        # 2nd failure -> Still Degraded (< failure_threshold 3)
        st = self.engine.record_probe(sid, success=False, latency_ms=500.0)
        self.assertEqual(st, HealthStatus.DEGRADED)

        # 3rd failure -> Failing
        st = self.engine.record_probe(sid, success=False, latency_ms=500.0)
        self.assertEqual(st, HealthStatus.FAILING)

        # Recovery on success -> Healthy
        st = self.engine.record_probe(sid, success=True, latency_ms=40.0)
        self.assertEqual(st, HealthStatus.HEALTHY)

    def test_latency_metrics_percentiles(self):
        self.engine.register(self.manifest_v1)
        sid = "filesystem-server"

        # Record latencies: 10, 20, 30, ..., 100
        for lat in range(10, 110, 10):
            self.engine.record_probe(sid, success=True, latency_ms=float(lat))

        metrics = self.engine.get_health_metrics(sid)
        self.assertEqual(metrics["total_probes"], 10)
        self.assertEqual(metrics["status"], "HEALTHY")
        self.assertEqual(metrics["p50_latency_ms"], 50.0)
        self.assertEqual(metrics["p95_latency_ms"], 100.0)


if __name__ == "__main__":
    unittest.main()
