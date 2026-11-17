"""Chrome-stream matching and link planning against a hand-written synthetic pw-dump."""
import json
from pathlib import Path

import pytest

from omni_recorder import pwgraph
from omni_recorder.capture_daemon import PORT_LAYOUT, node_name_for, pw_record_cmd

FIX = Path(__file__).parent / "fixtures" / "pw_dump_synthetic.json"
BIN = ["chrome", "chromium"]
NAMES = ["Google Chrome"]
EXCL = ["steamwebhelper"]


@pytest.fixture
def g():
    return pwgraph.parse_dump(json.loads(FIX.read_text()))


def test_parse_counts(g):
    assert len(g.nodes) == 10
    assert len(g.links) == 2          # the null-info link is skipped
    assert g.defaults == {"default.audio.sink": "test_sink_main", "default.audio.source": "test_mic_stereo"}


def test_client_props_fallback(g):
    n = g.nodes[50]
    assert "application.process.binary" not in n.props
    assert n.prop("application.process.binary") == "chrome"
    assert n.describe()["application.process.id"] == 1111


def test_chrome_matching(g):
    ids = [n.id for n in pwgraph.find_chrome_streams(g, BIN, NAMES, EXCL)]
    # 50: Chrome playback (binary via client); 55: Chrome playback (binary on node)
    # 51: Steam "Chromium" excluded; 52: Chrome *input* stream ignored; 53: other app;
    # 54: no binary, name "Chromium" does not contain "Google Chrome"; 60: our recorder
    assert ids == [50, 55]


def test_name_fallback_only_without_binary(g):
    ids = [n.id for n in pwgraph.find_chrome_streams(g, BIN, ["Chromium"], EXCL)]
    assert 54 in ids          # no binary -> name match used
    assert 51 not in ids      # has binary steamwebhelper -> name never consulted


def test_exclusion_wins_over_binary_list(g):
    ids = [n.id for n in pwgraph.find_chrome_streams(g, ["steamwebhelper", "chrome"], NAMES, EXCL)]
    assert 51 not in ids


def test_resolve_device(g):
    n, how = pwgraph.resolve_device(g, "default", "default.audio.source")
    assert (n.name, how) == ("test_mic_stereo", "default")
    n, how = pwgraph.resolve_device(g, "test_mic_mono", "default.audio.source")
    assert (n.name, how) == ("test_mic_mono", "configured")
    n, how = pwgraph.resolve_device(g, "unplugged_mic", "default.audio.source")
    assert (n.name, how) == ("test_mic_stereo", "fallback-default")


def test_lr_pair_orders_by_channel(g):
    l, r = pwgraph.lr_pair(g.ports_of(41, "output"))
    assert (l.channel, r.channel) == ("FL", "FR")       # even though FR has the lower id
    l, r = pwgraph.lr_pair(g.ports_of(42, "output"))
    assert l.id == r.id == 120                          # mono mic feeds both sides
    assert pwgraph.lr_pair([]) is None


def test_monitor_ports_only_for_sink(g):
    assert [p.name for p in g.ports_of(40, "output", monitor=True)] == ["monitor_FL", "monitor_FR"]
    assert g.ports_of(40, "output", monitor=False) == []


def test_desired_links(g):
    rec = g.nodes[60]
    chrome = pwgraph.find_chrome_streams(g, BIN, NAMES, EXCL)
    want = pwgraph.desired_links(g, rec, g.nodes[41], chrome, g.nodes[40], PORT_LAYOUT)
    assert want == {
        (111, 160), (110, 161),          # mic FL->AUX0, FR->AUX1
        (130, 162), (131, 163),          # chrome stream 50 FL/FR -> AUX2/AUX3
        (134, 162), (134, 163),          # chrome stream 55 mono -> both
        (102, 164), (103, 165),          # sink monitor -> AUX4/AUX5
    }
    have = {(l.out_port, l.in_port) for l in g.links_into(60)}
    assert have == {(111, 160)}


def test_desired_links_without_chrome_or_sink(g):
    want = pwgraph.desired_links(g, g.nodes[60], g.nodes[42], [], None, PORT_LAYOUT)
    assert want == {(120, 160), (120, 161)}


def test_recorder_command_is_safe():
    name = node_name_for("2026-11-17_1450_2")
    assert name == "omni_rec_capture_2026_11_17_1450_2"
    cmd = pw_record_cmd(name, 48000, Path("x.f32"))
    joined = " ".join(cmd)
    assert "--target 0" in joined                     # never auto-linked by WirePlumber
    assert "node.autoconnect = false" in joined
    assert "--raw" in cmd and "f32" in cmd
    assert f'node.name = "{name}"' in joined
