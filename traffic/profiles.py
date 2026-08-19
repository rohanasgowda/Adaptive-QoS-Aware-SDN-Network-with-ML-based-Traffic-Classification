from __future__ import annotations

from dataclasses import dataclass

from common.traffic_types import TrafficType


@dataclass(frozen=True)
class TrafficCommand:
    name: TrafficType
    server_cmd: str
    client_cmd: str
    duration_s: int
    description: str


TRAFFIC_COMMANDS: dict[TrafficType, TrafficCommand] = {
    TrafficType.VOIP: TrafficCommand(
        name=TrafficType.VOIP,
        server_cmd="iperf -s -u -p 5060",
        client_cmd="iperf -c {dst_ip} -u -p 5060 -b 120k -l 160 -t {duration}",
        duration_s=30,
        description="Small UDP packets at frequent intervals for call-like traffic.",
    ),
    TrafficType.VIDEO: TrafficCommand(
        name=TrafficType.VIDEO,
        server_cmd="iperf -s -u -p 5004",
        client_cmd="iperf -c {dst_ip} -u -p 5004 -b 6M -l 1200 -t {duration}",
        duration_s=30,
        description="Steady high-rate UDP stream with large packets.",
    ),
    TrafficType.FILE: TrafficCommand(
        name=TrafficType.FILE,
        server_cmd="iperf -s -p 8081",
        client_cmd="iperf -c {dst_ip} -p 8081 -t {duration}",
        duration_s=30,
        description="Bulk TCP transfer that tries to maximize throughput.",
    ),
    TrafficType.WEB: TrafficCommand(
        name=TrafficType.WEB,
        server_cmd="python3 -m http.server 8080",
        client_cmd="python3 -m traffic.web_bursts --url http://{dst_ip}:8080 --duration {duration}",
        duration_s=30,
        description="Small irregular HTTP bursts.",
    ),
}
