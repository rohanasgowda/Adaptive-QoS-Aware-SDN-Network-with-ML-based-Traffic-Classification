from __future__ import annotations

import time
from dataclasses import dataclass, field


@dataclass
class FlowStats:
    packet_count: int = 0
    total_bytes: int = 0
    first_seen: float = field(default_factory=time.monotonic)
    last_seen: float = field(default_factory=time.monotonic)
    last_arrival: float | None = None
    interarrival_ms_total: float = 0.0

    def update(self, packet_size: int, now: float | None = None) -> None:
        now = time.monotonic() if now is None else now
        if self.last_arrival is not None:
            self.interarrival_ms_total += (now - self.last_arrival) * 1000.0
        self.last_arrival = now
        self.last_seen = now
        self.packet_count += 1
        self.total_bytes += packet_size

    @property
    def avg_packet_size(self) -> float:
        return self.total_bytes / max(self.packet_count, 1)

    @property
    def avg_interarrival_ms(self) -> float:
        if self.packet_count <= 1:
            return 0.0
        return self.interarrival_ms_total / (self.packet_count - 1)


def feature_vector(packet_size: int, interarrival_ms: float, src_port: int, dst_port: int) -> list[float]:
    service_port = min(p for p in (src_port, dst_port) if p > 0) if src_port or dst_port else 0
    return [float(packet_size), float(interarrival_ms), float(src_port), float(dst_port), float(service_port)]
