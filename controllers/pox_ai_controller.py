from __future__ import annotations

import json
import socket
import struct
import time
from pathlib import Path

from common.controller_logic import ControllerBrain, PacketMetadata
from common.routing import choose_path
from common.topology import IP_TO_HOST, host_to_switch, output_port, switch_for_dpid
from common.traffic_types import TrafficType

try:
    from pox.core import core
    import pox.openflow.libopenflow_01 as of
except ImportError:  # Allows syntax checks on non-POX machines.
    core = None
    of = None


class POXAIRoutingController:
    def __init__(self) -> None:
        self.brain = ControllerBrain()
        self.connections = {}
        self.metrics_path = Path("results/pox_decisions.jsonl")
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        core.openflow.addListeners(self)

    def _handle_ConnectionUp(self, event) -> None:
        self.connections[event.dpid] = event.connection
        core.getLogger().info("switch connected: s%s", event.dpid)

    def _handle_PacketIn(self, event) -> None:
        started = time.perf_counter()
        frame = bytes(event.ofp.data)
        arp_ips = _parse_arp_ips(frame)
        if arp_ips is not None:
            src_ip, dst_ip = arp_ips
            out_port = self._arp_out_port(event.dpid, src_ip, dst_ip)
            event.connection.send(of.ofp_packet_out(data=event.ofp, action=of.ofp_action_output(port=out_port)))
            return

        metadata = _parse_ipv4_transport(frame)
        if metadata is None:
            event.connection.send(of.ofp_packet_out(data=event.ofp, action=of.ofp_action_output(port=of.OFPP_IN_PORT)))
            return
        decision = self.brain.decide(metadata)
        if decision is None:
            event.connection.send(of.ofp_packet_out(data=event.ofp, action=of.ofp_action_output(port=of.OFPP_FLOOD)))
            return

        self._install_path(decision, metadata)
        switch = switch_for_dpid(event.dpid)
        out_port = self._next_port_for_switch(switch, decision.path_decision.path)
        msg = of.ofp_packet_out(data=event.ofp)
        msg.actions.append(of.ofp_action_output(port=out_port))
        event.connection.send(msg)
        self._record_decision("pox", decision, time.perf_counter() - started)

    def _install_path(self, decision, metadata: PacketMetadata) -> None:
        for switch in decision.path_decision.path:
            dpid = int(switch.removeprefix("s"))
            connection = self.connections.get(dpid)
            if connection is None:
                continue
            flow = of.ofp_flow_mod()
            flow.priority = 100
            flow.idle_timeout = 30
            flow.match.dl_type = 0x0800
            flow.match.nw_src = metadata.src_ip
            flow.match.nw_dst = metadata.dst_ip
            flow.match.nw_proto = metadata.ip_proto
            flow.match.tp_src = metadata.src_port
            flow.match.tp_dst = metadata.dst_port
            flow.actions.append(of.ofp_action_output(port=self._next_port_for_switch(switch, decision.path_decision.path)))
            connection.send(flow)

    def _next_port_for_switch(self, switch: str, path: tuple[str, ...]) -> int:
        if switch not in path:
            return of.OFPP_IN_PORT
        index = path.index(switch)
        if index == len(path) - 1:
            host = f"h{switch.removeprefix('s')}"
            return output_port(switch, host)
        return output_port(switch, path[index + 1])

    def _arp_out_port(self, dpid: int, src_ip: str, dst_ip: str) -> int:
        src_host = IP_TO_HOST.get(src_ip)
        dst_host = IP_TO_HOST.get(dst_ip)
        if src_host is None or dst_host is None:
            return of.OFPP_IN_PORT
        current = switch_for_dpid(dpid)
        source_switch = host_to_switch(src_host)
        dest_switch = host_to_switch(dst_host)
        decision = choose_path(self.brain.graph, source_switch, dest_switch, TrafficType.WEB)
        return self._next_port_for_switch(current, decision.path)

    def _record_decision(self, controller: str, decision, seconds: float) -> None:
        row = {
            "controller": controller,
            "flow": list(decision.flow_key),
            "traffic_type": decision.traffic_type.value,
            "path": list(decision.path_decision.path),
            "install_seconds": seconds,
            "rerouted": decision.rerouted,
        }
        with self.metrics_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(row) + "\n")


def launch() -> None:
    if core is None:
        raise RuntimeError("POX is not installed or not on PYTHONPATH.")
    core.registerNew(POXAIRoutingController)


def _parse_ipv4_transport(frame: bytes) -> PacketMetadata | None:
    if len(frame) < 34:
        return None
    eth_type = struct.unpack("!H", frame[12:14])[0]
    if eth_type != 0x0800:
        return None
    ihl = (frame[14] & 0x0F) * 4
    protocol = frame[23]
    src_ip = socket.inet_ntoa(frame[26:30])
    dst_ip = socket.inet_ntoa(frame[30:34])
    transport_offset = 14 + ihl
    src_port = dst_port = 0
    if protocol in (6, 17) and len(frame) >= transport_offset + 4:
        src_port, dst_port = struct.unpack("!HH", frame[transport_offset : transport_offset + 4])
    return PacketMetadata(src_ip, dst_ip, src_port, dst_port, len(frame), protocol)


def _parse_arp_ips(frame: bytes) -> tuple[str, str] | None:
    if len(frame) < 42:
        return None
    eth_type = struct.unpack("!H", frame[12:14])[0]
    if eth_type != 0x0806:
        return None
    sender_ip = socket.inet_ntoa(frame[28:32])
    target_ip = socket.inet_ntoa(frame[38:42])
    return sender_ip, target_ip
