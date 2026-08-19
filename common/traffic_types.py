from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class TrafficType(str, Enum):
    VOIP = "voip"
    VIDEO = "video"
    FILE = "file"
    WEB = "web"


@dataclass(frozen=True)
class TrafficProfile:
    name: TrafficType
    ports: tuple[int, ...]
    packet_size_range: tuple[int, int]
    interarrival_ms_range: tuple[float, float]
    bandwidth_mbps: float
    priority: int
    delay_weight: float
    bandwidth_weight: float
    congestion_weight: float


TRAFFIC_PROFILES: dict[TrafficType, TrafficProfile] = {
    TrafficType.VOIP: TrafficProfile(
        name=TrafficType.VOIP,
        ports=(5060, 5061, 10000, 10001, 10002),
        packet_size_range=(120, 240),
        interarrival_ms_range=(10.0, 25.0),
        bandwidth_mbps=0.12,
        priority=4,
        delay_weight=0.70,
        bandwidth_weight=0.10,
        congestion_weight=0.20,
    ),
    TrafficType.VIDEO: TrafficProfile(
        name=TrafficType.VIDEO,
        ports=(5004, 5005, 1935, 8554),
        packet_size_range=(950, 1400),
        interarrival_ms_range=(18.0, 45.0),
        bandwidth_mbps=6.0,
        priority=3,
        delay_weight=0.25,
        bandwidth_weight=0.50,
        congestion_weight=0.25,
    ),
    TrafficType.FILE: TrafficProfile(
        name=TrafficType.FILE,
        ports=(20, 21, 989, 990, 8081),
        packet_size_range=(1200, 1500),
        interarrival_ms_range=(1.0, 8.0),
        bandwidth_mbps=10.0,
        priority=1,
        delay_weight=0.05,
        bandwidth_weight=0.80,
        congestion_weight=0.15,
    ),
    TrafficType.WEB: TrafficProfile(
        name=TrafficType.WEB,
        ports=(80, 443, 8080, 8443),
        packet_size_range=(180, 1100),
        interarrival_ms_range=(40.0, 450.0),
        bandwidth_mbps=1.0,
        priority=2,
        delay_weight=0.35,
        bandwidth_weight=0.25,
        congestion_weight=0.40,
    ),
}


def profile_for_port(port: int) -> TrafficProfile | None:
    for profile in TRAFFIC_PROFILES.values():
        if port in profile.ports:
            return profile
    return None


def normalize_traffic_type(value: str | TrafficType) -> TrafficType:
    if isinstance(value, TrafficType):
        return value
    return TrafficType(value.lower())
