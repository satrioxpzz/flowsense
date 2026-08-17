"""Tests for the token-free Jateng public CCTV client.

Uses a static HTML fixture (the public cctvData shape) so the parser is checked
offline. We assert:
  - the parser extracts name/region/GPS/url fields,
  - URLs embedding a static auth token (ZoneMinder nph-zms) are SKIPPED,
  - find_jateng_camera resolves by name/idx/host.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from flowsense import jateng_client as J


# Minimal replica of the portal's public cctvData (no real secrets).
_FIXTURE = """
var cctvData = [
    { id:1,  lokasi:'Dieng',    hls_url:'https://cctv.perhubunganjateng.online/Dieng/index.m3u8',     latitude:-7.203919, longitude:109.911200, status:'aktif', wilayah:'Posko',    type:'hls' },
    { id:2,  lokasi:'Bayeman',  hls_url:'https://cctv.perhubunganjateng.online/Bayeman/index.m3u8',   latitude:-7.245043, longitude:109.335388, status:'aktif', wilayah:'Posko',    type:'hls' },
    { id:3,  lokasi:'Karanganyar Leak', hls_url:'https://scctv.karanganyarkab.go.id/zm/cgi-bin/nph-zms?scale=100&monitor=48&auth=deadbeefcafe&rand=1', latitude:-7.6, longitude:110.9, status:'aktif', wilayah:'III', type:'zm' }
];
"""


def test_parse_extracts_fields():
    rows = J._parse_cctv_data(_FIXTURE)
    assert len(rows) == 3
    assert rows[0]["name"] == "Dieng"
    assert rows[0]["latitude"] == -7.203919
    assert rows[0]["longitude"] == 109.911200
    assert rows[0]["region"] == "Posko"
    assert rows[0]["portal_url"].endswith("Dieng/index.m3u8")


def test_fetch_skips_token_urls():
    # Monkeypatch the network GET so no real request is made.
    class _FakeResp:
        text = _FIXTURE
        def raise_for_status(self): pass
    class _FakeClient:
        def get(self, *a, **k): return _FakeResp()
    cams = J.fetch_jateng_cameras(session=_FakeClient())
    # The Karanganyar nph-zms (auth=) entry must be filtered out.
    hosts = {c.host for c in cams}
    assert "scctv.karanganyarkab.go.id" not in hosts
    assert all("auth=" not in c.portal_url for c in cams)
    # The two token-free entries remain.
    assert len(cams) == 2
    assert cams[0].name == "Dieng"


def test_find_by_name_idx_host():
    class _FakeResp:
        text = _FIXTURE
        def raise_for_status(self): pass
    class _FakeClient:
        def get(self, *a, **k): return _FakeResp()
    cams = J.fetch_jateng_cameras(session=_FakeClient())
    assert J.find_jateng_camera(cams, name="Bayeman").idx == 2
    assert J.find_jateng_camera(cams, idx=1).name == "Dieng"
    assert J.find_jateng_camera(cams, host="perhubunganjateng").name == "Dieng"
