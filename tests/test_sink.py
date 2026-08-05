import json
from flowsense.sink import JsonlSink

def test_jsonl_sink_emits(tmp_path):
    p = tmp_path / "out.jsonl"
    sink = JsonlSink(p)
    sink.emit({"ts": 100})
    sink.emit({"ts": 200})
    lines = p.read_text().splitlines()
    assert json.loads(lines[0]) == {"ts": 100}
    assert json.loads(lines[1]) == {"ts": 200}
