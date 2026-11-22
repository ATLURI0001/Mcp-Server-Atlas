import unittest
from endpoint_telemetry import (
    EndpointTelemetryCollector,
    EndpointHealthStatus,
)


class TestEndpointTelemetry(unittest.TestCase):

    def setUp(self):
        self.collector = EndpointTelemetryCollector(max_history_per_server=20)

    def test_register_and_initial_state(self):
        self.collector.register_endpoint("weather-mcp", "https://api.example.com/weather")
        stats = self.collector.get_server_stats("weather-mcp")

        self.assertIsNotNone(stats)
        self.assertEqual(stats["status"], EndpointHealthStatus.UNKNOWN.value)
        self.assertEqual(stats["total_probes"], 0)
        self.assertEqual(stats["availability_pct"], 0.0)

    def test_record_successful_probes_and_percentiles(self):
        sid = "sqlite-mcp"
        # Record 10 probes: 10ms, 20ms, ... 100ms
        for i in range(1, 11):
            self.collector.record_probe(sid, latency_ms=i * 10, success=True)

        stats = self.collector.get_server_stats(sid)
        self.assertEqual(stats["total_probes"], 10)
        self.assertEqual(stats["successful_probes"], 10)
        self.assertEqual(stats["availability_pct"], 100.0)
        self.assertEqual(stats["status"], EndpointHealthStatus.HEALTHY.value)

        # p50 of 10..100 is 55.0
        self.assertEqual(stats["latency_p50_ms"], 55.0)
        # p90 of 10..100 is 90.0
        self.assertEqual(stats["latency_p90_ms"], 90.0)
        self.assertGreater(stats["jitter_ms"], 0.0)

    def test_health_degradation_and_down_transition(self):
        sid = "flaky-mcp"
        # 10 successful fast probes
        for _ in range(10):
            self.collector.record_probe(sid, latency_ms=50, success=True)
        self.assertEqual(self.collector.get_server_stats(sid)["status"], EndpointHealthStatus.HEALTHY.value)

        # 3 consecutive failures trigger DOWN
        self.collector.record_probe(sid, latency_ms=0, success=False)
        self.collector.record_probe(sid, latency_ms=0, success=False)
        self.collector.record_probe(sid, latency_ms=0, success=False)

        stats = self.collector.get_server_stats(sid)
        self.assertEqual(stats["status"], EndpointHealthStatus.DOWN.value)
        self.assertEqual(stats["failed_probes"], 3)

    def test_degraded_due_to_high_latency(self):
        sid = "slow-mcp"
        for _ in range(5):
            self.collector.record_probe(sid, latency_ms=1500, success=True)  # > 1000ms threshold

        stats = self.collector.get_server_stats(sid)
        self.assertEqual(stats["status"], EndpointHealthStatus.DEGRADED.value)

    def test_diagnostic_summary_and_prometheus(self):
        self.collector.record_probe("server-a", latency_ms=25, success=True)
        self.collector.record_probe("server-b", latency_ms=45, success=True)

        summary = self.collector.generate_diagnostic_summary()
        self.assertIn("# MCP Server Atlas - Catalog Endpoint Availability Diagnostic", summary)
        self.assertIn("server-a", summary)
        self.assertIn("server-b", summary)

        prom = self.collector.export_prometheus_metrics()
        self.assertIn('mcp_endpoint_availability_ratio{server="server-a"}', prom)
        self.assertIn('mcp_endpoint_latency_p90_ms{server="server-b"}', prom)

    def test_reset(self):
        self.collector.record_probe("server-x", latency_ms=10, success=True)
        self.collector.reset()
        self.assertIsNone(self.collector.get_server_stats("server-x"))


if __name__ == "__main__":
    unittest.main()
