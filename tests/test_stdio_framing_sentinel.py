from scripts.stdio_framing_sentinel import StdioFramingSentinel


def test_stdio_framing_sentinel():
    s = StdioFramingSentinel(max_frame_bytes=64)
    assert s.validate_frame('{"jsonrpc":"2.0","id":1}') == (True, "OK")
    assert s.validate_frame("bad\x00frame") == (False, "ERR_NULL_BYTE_IN_FRAME")
    assert s.validate_frame('{"a":"' + ("x" * 100) + '"}') == (False, "ERR_FRAME_BUFFER_OVERFLOW")
    assert s.validate_frame("partial json") == (False, "ERR_MALFORMED_JSONRPC_BOUNDARY")
