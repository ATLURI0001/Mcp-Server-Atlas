"""
Unit and micro-benchmarking tests for FastRpcDispatcher and RpcBenchmarkProfiler.
"""

import json
from scripts.rpc_dispatcher_profiler import (
    BenchmarkProfile,
    FastRpcDispatcher,
    RpcBenchmarkProfiler,
    RpcRequest,
    RpcResponse,
)


def test_rpc_request_response_dataclass():
    req = RpcRequest(method="tools/list", id="req-1")
    assert req.method == "tools/list"
    assert req.jsonrpc == "2.0"

    resp = RpcResponse(id="req-1", result={"status": "ok"})
    data = resp.to_dict()
    assert data["jsonrpc"] == "2.0"
    assert data["id"] == "req-1"
    assert data["result"] == {"status": "ok"}
    assert "error" not in data


def test_dispatcher_single_execution():
    dispatcher = FastRpcDispatcher()
    dispatcher.register("echo", lambda msg: f"echo:{msg}")
    dispatcher.register("add", lambda a, b: a + b)

    # Success keyword params
    res1 = dispatcher.dispatch_single({"jsonrpc": "2.0", "id": 1, "method": "echo", "params": {"msg": "hello"}})
    assert res1["result"] == "echo:hello"
    assert res1["id"] == 1

    # Success positional params
    res2 = dispatcher.dispatch_single({"jsonrpc": "2.0", "id": 2, "method": "add", "params": [10, 25]})
    assert res2["result"] == 35

    # Method not found (-32601)
    res_err = dispatcher.dispatch_single({"jsonrpc": "2.0", "id": 3, "method": "unknown"})
    assert "error" in res_err
    assert res_err["error"]["code"] == -32601

    # Invalid params (-32602)
    res_err2 = dispatcher.dispatch_single({"jsonrpc": "2.0", "id": 4, "method": "add", "params": {"x": 1}})
    assert res_err2["error"]["code"] == -32602


def test_dispatcher_batch_and_raw():
    dispatcher = FastRpcDispatcher()
    dispatcher.register("ping", lambda: "pong")

    # Batch dispatch
    batch = [
        {"jsonrpc": "2.0", "id": 1, "method": "ping"},
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
    ]
    batch_res = dispatcher.dispatch_batch(batch)
    assert len(batch_res) == 2
    assert batch_res[0]["result"] == "pong"
    assert batch_res[1]["result"] == "pong"

    # Empty batch error
    empty_res = dispatcher.dispatch_batch([])
    assert empty_res[0]["error"]["code"] == -32600

    # Raw JSON dispatch
    raw_str = json.dumps(batch)
    raw_res = json.loads(dispatcher.dispatch_raw(raw_str))
    assert len(raw_res) == 2
    assert raw_res[0]["result"] == "pong"

    # Parse error (-32700)
    bad_raw = dispatcher.dispatch_raw("not a json{")
    assert json.loads(bad_raw)["error"]["code"] == -32700


def test_percentile_calculation():
    # 100 values from 1.0 to 100.0
    latencies = [float(i) for i in range(1, 101)]
    pct = RpcBenchmarkProfiler.calculate_percentiles(latencies)
    assert pct["min"] == 1.0
    assert pct["max"] == 100.0
    assert pct["p50"] == 50.0
    assert pct["p90"] == 90.0
    assert pct["p95"] == 95.0
    assert pct["p99"] == 99.0
    assert pct["mean"] == 50.5


def test_sequential_and_concurrent_benchmarking():
    dispatcher = FastRpcDispatcher()
    dispatcher.register("compute", lambda val: val * 2)

    profiler = RpcBenchmarkProfiler()
    requests = [{"jsonrpc": "2.0", "id": i, "method": "compute", "params": {"val": i}} for i in range(10)]

    # Sequential benchmark
    seq_profile = profiler.run_sequential(dispatcher, requests, iterations=20, name="SeqTest")
    assert seq_profile.total_requests == 200
    assert seq_profile.throughput_rps > 0
    assert seq_profile.p50_ms >= 0.0
    assert seq_profile.errors_count == 0

    # SLA assertion
    assert profiler.assert_sla(seq_profile, max_p99_ms=10.0, min_rps=100.0)

    # Concurrent benchmark
    concur_profile = profiler.run_concurrent(
        dispatcher, requests, concurrency=2, iterations_per_worker=10, name="ConcurTest"
    )
    assert concur_profile.total_requests == 200
    assert concur_profile.throughput_rps > 0

    # Markdown format check
    md = profiler.format_markdown(seq_profile)
    assert "| **Throughput** |" in md
    assert "| **P99 Latency** |" in md
