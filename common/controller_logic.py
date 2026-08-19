from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path

from ai.classifier import TrafficClassifier
from common.flow_features import FlowStats
from common.routing import PathDecision, apply_flow_load, choose_path, decay_utilization, should_reroute
from common.topology import IP_TO_HOST, host_to_switch, switch_graph
from common.traffic_types import TrafficType, profile_for_port


@dataclass(frozen=True)
class PacketMetadata:
    src_ip: str
    dst_ip: str
    src_port: int
    dst_port: int
    packet_size: int
    ip_proto: int


@dataclass(frozen=True)
class FlowDecision:
    flow_key: tuple[str, str, int, int, int]
    traffic_type: TrafficType
    path_decision: PathDecision
    rerouted: bool


class ControllerBrain:
    def __init__(self, model_path: str | Path = "models/traffic_rf.joblib") -> None:
        self.graph = switch_graph()
        self.flow_stats: dict[tuple[str, str, int, int, int], FlowStats] = {}
        self.flow_paths: dict[tuple[str, str, int, int, int], tuple[str, ...]] = {}
        self.classifier: TrafficClassifier | None = None
        try:
            self.classifier = TrafficClassifier(model_path)
        except (FileNotFoundError, ModuleNotFoundError, ImportError, OSError):
            self.classifier = None

    def decide(self, packet: PacketMetadata) -> FlowDecision | None:
        src_host = IP_TO_HOST.get(packet.src_ip)
        dst_host = IP_TO_HOST.get(packet.dst_ip)
        if src_host is None or dst_host is None:
            return None

        flow_key = (
            packet.src_ip,
            packet.dst_ip,
            packet.src_port,
            packet.dst_port,
            packet.ip_proto,
        )
        now = time.monotonic()
        stats = self.flow_stats.setdefault(flow_key, FlowStats())
        stats.update(packet.packet_size, now)

        traffic_type = self._classify(
            packet.packet_size,
            stats.avg_interarrival_ms,
            packet.src_port,
            packet.dst_port,
        )
        source_switch = host_to_switch(src_host)
        dest_switch = host_to_switch(dst_host)
        previous = self.flow_paths.get(flow_key)
        rerouted = bool(previous and should_reroute(traffic_type, previous, self.graph))

        if previous is None or rerouted:
            decision = choose_path(self.graph, source_switch, dest_switch, traffic_type)
            self.flow_paths[flow_key] = decision.path
            apply_flow_load(self.graph, decision.path, traffic_type)
        else:
            decision = choose_path(self.graph, source_switch, dest_switch, traffic_type)
            decision = PathDecision(traffic_type, previous, decision.cost, decision.reason)

        decay_utilization(self.graph)
        return FlowDecision(flow_key, traffic_type, decision, rerouted)

    def _classify(
        self,
        packet_size: int,
        interarrival_ms: float,
        src_port: int,
        dst_port: int,
    ) -> TrafficType:
        if self.classifier is not None:
            return self.classifier.predict(packet_size, interarrival_ms, src_port, dst_port)
        profile = profile_for_port(dst_port) or profile_for_port(src_port)
        if profile is not None:
            return profile.name
        return TrafficType.WEB
