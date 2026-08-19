from __future__ import annotations

import argparse
import json
import socket
import struct
import threading
import time
from dataclasses import dataclass
from pathlib import Path

from common.controller_logic import ControllerBrain, PacketMetadata
from common.routing import choose_path
from common.topology import IP_TO_HOST, host_to_switch, output_port, switch_for_dpid
from common.traffic_types import TrafficType


OF_VERSION = 0x01
OFPT_HELLO = 0
OFPT_FEATURES_REQUEST = 5
OFPT_FEATURES_REPLY = 6
OFPT_PACKET_IN = 10
OFPT_PACKET_OUT = 13
OFPT_FLOW_MOD = 14
OFPFC_ADD = 0
OFP_NO_BUFFER = 0xFFFFFFFF
OFPP_FLOOD = 0xFFFB
OFPP_IN_PORT = 0xFFF8


@dataclass
class SwitchConnection:
    sock: socket.socket
    address: tuple[str, int]
    dpid: int | None = None


class RawOpenFlowController:
    def __init__(self, host: str, port: int, metrics_path: Path) -> None:
        self.host = host
        self.port = port
        self.metrics_path = metrics_path
        self.metrics_path.parent.mkdir(parents=True, exist_ok=True)
        self.brain = ControllerBrain()
        self.connections: dict[int, SwitchConnection] = {}
        self._xid = 1

    def serve_forever(self) -> None:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            server.bind((self.host, self.port))
            server.listen()
            print(f"raw OpenFlow controller listening on {self.host}:{self.port}")
            while True:
                client, address = server.accept()
                connection = SwitchConnection(client, address)
                threading.Thread(target=self._handle_switch, args=(connection,), daemon=True).start()

    def _handle_switch(self, connection: SwitchConnection) -> None:
        with connection.sock:
            try:
                self._send(connection.sock, OFPT_HELLO, b"")
                self._send(connection.sock, OFPT_FEATURES_REQUEST, b"")
                while True:
                    header = self._recv_exact(connection.sock, 8)
                    if not header:
                        return
                    version, msg_type, length, xid = struct.unpack("!BBHI", header)
                    payload = self._recv_exact(connection.sock, length - 8)
                    if version != OF_VERSION:
                        continue
                    if msg_type == OFPT_FEATURES_REPLY:
                        dpid = struct.unpack("!Q", payload[:8])[0]
                        connection.dpid = dpid
                        self.connections[dpid] = connection
                        print(f"switch connected: s{dpid}")
                    elif msg_type == OFPT_PACKET_IN and connection.dpid is not None:
                        self._handle_packet_in(connection, payload, xid)
            except (BrokenPipeError, ConnectionResetError, OSError):
                if connection.dpid in self.connections:
                    del self.connections[connection.dpid]

    def _handle_packet_in(self, connection: SwitchConnection, payload: bytes, xid: int) -> None:
        started = time.perf_counter()
        if len(payload) < 10:
            return
        buffer_id, total_len, in_port, reason = struct.unpack("!IHHB", payload[:9])
        frame = payload[10:]
        metadata = _parse_ipv4_transport(frame)
        if metadata is None:
            arp_ips = _parse_arp_ips(frame)
            if arp_ips is not None:
                src_ip, dst_ip = arp_ips
                out_port = self._arp_out_port(connection.dpid or 0, src_ip, dst_ip)
                self._packet_out(connection.sock, buffer_id, in_port, out_port, frame)
                return
        if metadata is None:
            self._packet_out(connection.sock, buffer_id, in_port, OFPP_IN_PORT, frame)
            return
        decision = self.brain.decide(metadata)
        if decision is None:
            self._packet_out(connection.sock, buffer_id, in_port, OFPP_FLOOD, frame)
            return

        self._install_path(decision, metadata)
        switch = switch_for_dpid(connection.dpid or 0)
        out_port = self._next_port_for_switch(switch, decision.path_decision.path)
        self._packet_out(connection.sock, buffer_id, in_port, out_port, frame)
        self._record_decision("raw", decision, time.perf_counter() - started)

    def _install_path(self, decision, metadata: PacketMetadata) -> None:
        for switch in decision.path_decision.path:
            dpid = int(switch.removeprefix("s"))
            connection = self.connections.get(dpid)
            if connection is None:
                continue
            out_port = self._next_port_for_switch(switch, decision.path_decision.path)
            connection.sock.sendall(_flow_mod(metadata, out_port, self._next_xid()))

    def _next_port_for_switch(self, switch: str, path: tuple[str, ...]) -> int:
        if switch not in path:
            return OFPP_IN_PORT
        index = path.index(switch)
        if index == len(path) - 1:
            host = f"h{switch.removeprefix('s')}"
            return output_port(switch, host)
        return output_port(switch, path[index + 1])

    def _arp_out_port(self, dpid: int, src_ip: str, dst_ip: str) -> int:
        src_host = IP_TO_HOST.get(src_ip)
        dst_host = IP_TO_HOST.get(dst_ip)
        if src_host is None or dst_host is None:
            return OFPP_IN_PORT
        current = switch_for_dpid(dpid)
        source_switch = host_to_switch(src_host)
        dest_switch = host_to_switch(dst_host)
        decision = choose_path(self.brain.graph, source_switch, dest_switch, TrafficType.WEB)
        return self._next_port_for_switch(current, decision.path)

    def _packet_out(self, sock: socket.socket, buffer_id: int, in_port: int, out_port: int, frame: bytes) -> None:
        actions = struct.pack("!HHHH", 0, 8, out_port, 0)
        data = b"" if buffer_id != OFP_NO_BUFFER else frame
        body = struct.pack("!IHH", buffer_id, in_port, len(actions)) + actions + data
        self._send(sock, OFPT_PACKET_OUT, body)

    def _send(self, sock: socket.socket, msg_type: int, payload: bytes) -> None:
        xid = self._next_xid()
        sock.sendall(struct.pack("!BBHI", OF_VERSION, msg_type, len(payload) + 8, xid) + payload)

    def _next_xid(self) -> int:
        self._xid += 1
        return self._xid

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

    @staticmethod
    def _recv_exact(sock: socket.socket, length: int) -> bytes:
        chunks = bytearray()
        while len(chunks) < length:
            chunk = sock.recv(length - len(chunks))
            if not chunk:
                return b""
            chunks.extend(chunk)
        return bytes(chunks)


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


def _flow_mod(metadata: PacketMetadata, out_port: int, xid: int) -> bytes:
    wildcards = (1 << 0) | (1 << 1) | (1 << 2) | (1 << 3) | (1 << 20) | (1 << 21)
    match = struct.pack(
        "!IH6s6sHBBHBBHIIHH",
        wildcards,
        0,
        b"\x00" * 6,
        b"\x00" * 6,
        0,
        0,
        0,
        0x0800,
        0,
        metadata.ip_proto,
        0,
        struct.unpack("!I", socket.inet_aton(metadata.src_ip))[0],
        struct.unpack("!I", socket.inet_aton(metadata.dst_ip))[0],
        metadata.src_port,
        metadata.dst_port,
    )
    actions = struct.pack("!HHHH", 0, 8, out_port, 0)
    body = (
        match
        + struct.pack("!QHHHHIHH", 0, OFPFC_ADD, 30, 0, 100, OFP_NO_BUFFER, 0, 0)
        + actions
    )
    return struct.pack("!BBHI", OF_VERSION, OFPT_FLOW_MOD, len(body) + 8, xid) + body


def main() -> None:
    parser = argparse.ArgumentParser(description="Raw low-level OpenFlow 1.0 AI routing controller.")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=6633)
    parser.add_argument("--metrics", type=Path, default=Path("results/raw_decisions.jsonl"))
    args = parser.parse_args()
    RawOpenFlowController(args.host, args.port, args.metrics).serve_forever()


if __name__ == "__main__":
    main()
