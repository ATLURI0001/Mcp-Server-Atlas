from scripts.tool_call_rate_rotary import ToolCallRateRotary


def test_tool_call_rate_rotary():
    r = ToolCallRateRotary(capacity=3)
    for i in range(5):
        r.record(float(i))
    assert len(r) == 3
