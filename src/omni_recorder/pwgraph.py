"""Read the PipeWire graph (pw-dump JSON) and decide which ports to link.

Pure functions here are unit-tested with a hand-written synthetic pw-dump fixture
(tests/fixtures/pw_dump_synthetic.json). The only functions that touch the live
audio server are dump(), link() and unlink().

Vocabulary:
- node: one audio object (a microphone, a speaker output, an app's playback stream).
- port: one channel input or output of a node (e.g. "output_FL").
- link: a connection from an output port to an input port.
- monitor port: a read-only copy of what an output device (sink) is playing.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from typing import Any, Iterable

# All runtime PipeWire objects this app creates have node.name starting with this.
APP_PREFIX = "omni_rec_"
RECORDER_PREFIX = "omni_rec_capture_"

# Preferred channel order when picking the left/right pair of a node's ports.
_LEFT = ("FL", "MONO", "FC", "AUX0", "SL", "RL")
_RIGHT = ("FR", "MONO", "FC", "AUX1", "SR", "RR")


@dataclass
class Port:
    id: int
    node_id: int
    direction: str          # "input" or "output"
    name: str
    channel: str
    monitor: bool


@dataclass
class Node:
    id: int
    props: dict[str, Any]
    client_props: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return str(self.props.get("node.name", ""))

    @property
    def media_class(self) -> str:
        return str(self.props.get("media.class", ""))

    @property
    def serial(self) -> int | None:
        s = self.props.get("object.serial")
        return int(s) if s is not None else None

    def prop(self, key: str) -> Any:
        """Node property, falling back to the owning client's property."""
        v = self.props.get(key)
        return v if v not in (None, "") else self.client_props.get(key)

    def describe(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "serial": self.serial,
            "node.name": self.name,
            "media.class": self.media_class,
            "application.name": self.prop("application.name"),
            "application.process.binary": self.prop("application.process.binary"),
            "application.process.id": self.prop("application.process.id"),
            "media.name": self.props.get("media.name"),
            "node.description": self.props.get("node.description"),
        }


@dataclass
class Link:
    id: int
    out_node: int
    out_port: int
    in_node: int
    in_port: int
    state: str


@dataclass
class Graph:
    nodes: dict[int, Node]
    ports: dict[int, Port]
    links: dict[int, Link]
    defaults: dict[str, str]   # e.g. {"default.audio.sink": "alsa_output..."}

    # ---- lookup -----------------------------------------------------------------
    def node_by_name(self, name: str) -> Node | None:
        for n in self.nodes.values():
            if n.name == name:
                return n
        return None

    def ports_of(self, node_id: int, direction: str, monitor: bool | None = None) -> list[Port]:
        out = [p for p in self.ports.values() if p.node_id == node_id and p.direction == direction]
        if monitor is not None:
            out = [p for p in out if p.monitor == monitor]
        return sorted(out, key=lambda p: p.id)

    def links_into(self, node_id: int) -> list[Link]:
        return [l for l in self.links.values() if l.in_node == node_id]


def parse_dump(objs: list[dict[str, Any]]) -> Graph:
    """Turn pw-dump's JSON list into a Graph. Unknown/partial objects are skipped."""
    clients: dict[int, dict[str, Any]] = {}
    nodes: dict[int, Node] = {}
    ports: dict[int, Port] = {}
    links: dict[int, Link] = {}
    defaults: dict[str, str] = {}
    for o in objs:
        t = o.get("type", "")
        info = o.get("info") or {}
        oid = o.get("id")
        if oid is None:
            continue
        if t == "PipeWire:Interface:Client":
            clients[oid] = info.get("props") or {}
        elif t == "PipeWire:Interface:Node":
            nodes[oid] = Node(id=oid, props=info.get("props") or {})
        elif t == "PipeWire:Interface:Port":
            props = info.get("props") or {}
            direction = info.get("direction") or {"in": "input", "out": "output"}.get(props.get("port.direction", ""), "")
            node_id = props.get("node.id")
            if node_id is None:
                continue
            ports[oid] = Port(id=oid, node_id=int(node_id), direction=direction,
                              name=str(props.get("port.name", "")),
                              channel=str(props.get("audio.channel", "")),
                              monitor=bool(props.get("port.monitor", False)))
        elif t == "PipeWire:Interface:Link":
            if not info:
                continue
            try:
                links[oid] = Link(id=oid, out_node=int(info["output-node-id"]), out_port=int(info["output-port-id"]),
                                  in_node=int(info["input-node-id"]), in_port=int(info["input-port-id"]),
                                  state=str(info.get("state", "")))
            except (KeyError, TypeError, ValueError):
                continue
        elif t == "PipeWire:Interface:Metadata":
            if (o.get("props") or {}).get("metadata.name") != "default":
                continue
            for entry in o.get("metadata") or []:
                if entry.get("subject") != 0:
                    continue
                val = entry.get("value")
                if isinstance(val, dict) and "name" in val:
                    defaults[str(entry.get("key"))] = str(val["name"])
    for n in nodes.values():
        cid = n.props.get("client.id")
        if cid is not None and int(cid) in clients:
            n.client_props = clients[int(cid)]
    return Graph(nodes=nodes, ports=ports, links=links, defaults=defaults)


# ---- matching ----------------------------------------------------------------------

def is_chrome_stream(node: Node, binaries: Iterable[str], name_match: Iterable[str],
                     exclude_binaries: Iterable[str]) -> bool:
    """True if `node` is a playback stream from Chrome/Chromium.

    Rule (chosen after finding that Steam's built-in browser registers as
    "Chromium input" with binary "steamwebhelper" on this machine):
    1. only playback streams (media.class == "Stream/Output/Audio");
    2. never our own nodes, never an excluded binary;
    3. match if application.process.binary equals one of `binaries` (case-insensitive);
    4. only if the stream reports NO binary at all, fall back to a case-insensitive
       substring match of application.name against `name_match`.
    """
    if node.media_class != "Stream/Output/Audio":
        return False
    if node.name.startswith(RECORDER_PREFIX):
        return False
    binary = str(node.prop("application.process.binary") or "").strip().lower()
    if binary and binary in {b.lower() for b in exclude_binaries}:
        return False
    if binary:
        return binary in {b.lower() for b in binaries}
    app = str(node.prop("application.name") or "").lower()
    return any(m.lower() in app for m in name_match if m)


def find_chrome_streams(g: Graph, binaries: Iterable[str], name_match: Iterable[str],
                        exclude_binaries: Iterable[str]) -> list[Node]:
    binaries, name_match, exclude_binaries = list(binaries), list(name_match), list(exclude_binaries)
    return sorted((n for n in g.nodes.values() if is_chrome_stream(n, binaries, name_match, exclude_binaries)),
                  key=lambda n: n.id)


def resolve_device(g: Graph, wanted: str, default_key: str) -> tuple[Node | None, str]:
    """Find a node by name, or the current default when wanted == "default".

    Returns (node, how) where how is "default", "configured", or
    "fallback-default" (configured name absent, default used instead)."""
    if wanted and wanted != "default":
        n = g.node_by_name(wanted)
        if n is not None:
            return n, "configured"
        how = "fallback-default"
    else:
        how = "default"
    name = g.defaults.get(default_key)
    return (g.node_by_name(name) if name else None), how


def lr_pair(ports: list[Port]) -> tuple[Port, Port] | None:
    """Pick (left, right) from a node's ports. One port -> used for both sides."""
    if not ports:
        return None
    if len(ports) == 1:
        return ports[0], ports[0]
    by_ch = {p.channel: p for p in ports}
    left = next((by_ch[c] for c in _LEFT if c in by_ch), ports[0])
    right = next((by_ch[c] for c in _RIGHT if c in by_ch and by_ch[c] is not left), None)
    if right is None:
        right = next(p for p in ports if p is not left)
    return left, right


def desired_links(g: Graph, recorder: Node, mic: Node | None, chrome: list[Node],
                  monitor_sink: Node | None, layout: dict[str, tuple[str, str]]) -> set[tuple[int, int]]:
    """The set of (output_port_id, recorder_input_port_id) links that should exist.

    layout maps a role ("me", "chrome", "system") to the recorder's two input
    port names for that role, e.g. {"me": ("input_AUX0", "input_AUX1"), ...}.
    """
    in_ports = {p.name: p.id for p in g.ports_of(recorder.id, "input")}
    want: set[tuple[int, int]] = set()

    def add(role: str, pair: tuple[Port, Port] | None) -> None:
        if pair is None or role not in layout:
            return
        lname, rname = layout[role]
        if lname in in_ports:
            want.add((pair[0].id, in_ports[lname]))
        if rname in in_ports:
            want.add((pair[1].id, in_ports[rname]))

    if mic is not None:
        add("me", lr_pair(g.ports_of(mic.id, "output", monitor=False)))
    for c in chrome:
        add("chrome", lr_pair(g.ports_of(c.id, "output", monitor=False)))
    if monitor_sink is not None:
        add("system", lr_pair(g.ports_of(monitor_sink.id, "output", monitor=True)))
    return want


# ---- live server -------------------------------------------------------------------

def dump(timeout: float = 5.0) -> Graph:
    """Run pw-dump and parse it. Raises RuntimeError on failure."""
    try:
        proc = subprocess.run(["pw-dump", "--no-colors"], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"pw-dump failed: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(f"pw-dump exit {proc.returncode}: {proc.stderr.strip()[:200]}")
    try:
        return parse_dump(json.loads(proc.stdout))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"pw-dump output not JSON: {exc}") from exc


def link(out_port: int, in_port: int, timeout: float = 5.0) -> tuple[bool, str]:
    """Create a link between two port ids. The link dies with either port."""
    try:
        p = subprocess.run(["pw-link", str(out_port), str(in_port)], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    if p.returncode == 0:
        return True, ""
    msg = (p.stderr or p.stdout).strip()
    # "File exists" means the link is already there: that is the state we want.
    return ("exist" in msg.lower()), msg


def unlink(link_id: int, timeout: float = 5.0) -> tuple[bool, str]:
    try:
        p = subprocess.run(["pw-link", "-d", str(link_id)], capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return False, str(exc)
    return p.returncode == 0, (p.stderr or p.stdout).strip()
