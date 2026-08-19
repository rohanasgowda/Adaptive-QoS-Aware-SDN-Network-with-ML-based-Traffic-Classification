from __future__ import annotations

import json
import time
from pathlib import Path

from common.controller_logic import ControllerBrain, PacketMetadata
from common.routing import choose_path
from common.topology import IP_TO_HOST, host_to_switch, output_port, switch_for_dpid
from common.traffic_types import TrafficType

try:
    from ryu.base import app_manager
    from ryu.controller import ofp_event
    from ryu.controller.handler import MAIN_DISPATCHER, set_ev_cls
    from ryu.lib.packet import arp, ethernet, ipv4, packet, tcp, udp
    from ryu.ofproto import ofproto_v1_0
except ImportError:  # Allows syntax checks on non-Ryu machines.
    class _FallbackRyuApp:
        def __init__(self, *args, **kwargs):
            pass

    class _FallbackAppManager:
        RyuApp = _FallbackRyuApp

    class _FallbackOfpEvent:
        class EventOFPPacketIn:
            pass

    app_manager = _FallbackAppManager
    ofp_event = _FallbackOfpEvent
    MAIN_DISPATCHER = None

    def set_ev_cls(*_args, **_kwargs):
        def decorator(func):
            return func

        return decorator

    class ofproto_v1_0:
        OFP_VERSION = 0x01


class RyuAIRoutingController(app_manager.RyuApp):
    OFP_VERSIONS = [ofproto_v1_0.OFP_VERSION]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.brain = ControllerBrain()
        self.datapaths = {}
        self.metrics_path = Path("results/ryu_decisions.jsonl")
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)

    @set_ev_cls(ofp_event.EventOFPPacketIn, MAIN_DISPATCHER)
    def packet_in_handler(self, ev):
        started = time.perf_counter()
        msg = ev.msg
        datapath = msg.datapath
        self.datapaths[datapath.id] = datapath
        parser = datapath.ofproto_parser
        ofproto = datapath.ofproto

        parsed = packet.Packet(msg.data)
        arp_pkt = parsed.get_protocol(arp.arp)
        if arp_pkt is not None:
            out_port = self._arp_out_port(datapath.id, arp_pkt.src_ip, arp_pkt.dst_ip)
            actions = [parser.OFPActionOutput(out_port)]
            self._packet_out(datapath, msg, actions)
            return

        ip_pkt = parsed.get_protocol(ipv4.ipv4)
        if ip_pkt is None:
            actions = [parser.OFPActionOutput(ofproto.OFPP_IN_PORT)]
            self._packet_out(datapath, msg, actions)
            return

        tcp_pkt = parsed.get_protocol(tcp.tcp)
        udp_pkt = parsed.get_protocol(udp.udp)
        src_port = getattr(tcp_pkt or udp_pkt, "src_port", 0)
        dst_port = getattr(tcp_pkt or udp_pkt, "dst_port", 0)
        metadata = PacketMetadata(
            src_ip=ip_pkt.src,
            dst_ip=ip_pkt.dst,
            src_port=src_port,
            dst_port=dst_port,
            packet_size=len(msg.data),
            ip_proto=ip_pkt.proto,
        )
        decision = self.brain.decide(metadata)
        if decision is None:
            self._packet_out(datapath, msg, [parser.OFPActionOutput(ofproto.OFPP_FLOOD)])
            return

        self._install_path(decision, metadata)
        current = switch_for_dpid(datapath.id)
        out_port = self._next_port_for_switch(current, decision.path_decision.path)
        self._packet_out(datapath, msg, [parser.OFPActionOutput(out_port)])
        self._record_decision("ryu", decision, time.perf_counter() - started)

    def _install_path(self, decision, metadata: PacketMetadata) -> None:
        for index, switch in enumerate(decision.path_decision.path):
            datapath = self.datapaths.get(int(switch.removeprefix("s")))
            if datapath is None:
                continue
            out_port = self._next_port_for_switch(switch, decision.path_decision.path)
            parser = datapath.ofproto_parser
            ofproto = datapath.ofproto
            match = parser.OFPMatch(
                dl_type=0x0800,
                nw_src=metadata.src_ip,
                nw_dst=metadata.dst_ip,
                nw_proto=metadata.ip_proto,
                tp_src=metadata.src_port,
                tp_dst=metadata.dst_port,
            )
            actions = [parser.OFPActionOutput(out_port)]
            mod = parser.OFPFlowMod(
                datapath=datapath,
                match=match,
                cookie=0,
                command=ofproto.OFPFC_ADD,
                idle_timeout=30,
                hard_timeout=0,
                priority=100,
                flags=0,
                actions=actions,
            )
            datapath.send_msg(mod)

    def _next_port_for_switch(self, switch: str, path: tuple[str, ...]) -> int:
        if switch not in path:
            return ofproto_v1_0.OFPP_IN_PORT
        index = path.index(switch)
        if index == len(path) - 1:
            host = f"h{switch.removeprefix('s')}"
            return output_port(switch, host)
        return output_port(switch, path[index + 1])

    def _arp_out_port(self, dpid: int, src_ip: str, dst_ip: str) -> int:
        src_host = IP_TO_HOST.get(src_ip)
        dst_host = IP_TO_HOST.get(dst_ip)
        if src_host is None or dst_host is None:
            return ofproto_v1_0.OFPP_IN_PORT
        current = switch_for_dpid(dpid)
        source_switch = host_to_switch(src_host)
        dest_switch = host_to_switch(dst_host)
        decision = choose_path(self.brain.graph, source_switch, dest_switch, TrafficType.WEB)
        return self._next_port_for_switch(current, decision.path)

    def _packet_out(self, datapath, msg, actions) -> None:
        parser = datapath.ofproto_parser
        data = None if msg.buffer_id != datapath.ofproto.OFP_NO_BUFFER else msg.data
        out = parser.OFPPacketOut(
            datapath=datapath,
            buffer_id=msg.buffer_id,
            in_port=msg.in_port,
            actions=actions,
            data=data,
        )
        datapath.send_msg(out)

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
