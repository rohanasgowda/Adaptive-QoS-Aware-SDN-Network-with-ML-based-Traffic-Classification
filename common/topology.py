from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class LinkSpec:
    left: str
    right: str
    bandwidth_mbps: float
    delay_ms: float
    loss_percent: float = 0.0
    jitter_ms: float = 0.0


HOSTS: tuple[str, ...] = ("h1", "h2", "h3", "h4", "h5", "h6")
SWITCHES: tuple[str, ...] = ("s1", "s2", "s3", "s4", "s5", "s6")


HOST_LINKS: tuple[LinkSpec, ...] = (
    LinkSpec("h1", "s1", 100, 1, jitter_ms=0.15),
    LinkSpec("h2", "s2", 100, 1, jitter_ms=0.20),
    LinkSpec("h3", "s3", 100, 1, jitter_ms=0.18),
    LinkSpec("h4", "s4", 100, 1, jitter_ms=0.22),
    LinkSpec("h5", "s5", 100, 1, jitter_ms=0.16),
    LinkSpec("h6", "s6", 100, 1, jitter_ms=0.20),
)


SWITCH_LINKS: tuple[LinkSpec, ...] = (
    LinkSpec("s1", "s2", 25, 3, jitter_ms=0.45),
    LinkSpec("s2", "s3", 25, 3, jitter_ms=0.55),
    LinkSpec("s3", "s6", 20, 4, jitter_ms=0.70),
    LinkSpec("s1", "s4", 12, 9, jitter_ms=1.40),
    LinkSpec("s4", "s5", 12, 8, jitter_ms=1.20),
    LinkSpec("s5", "s6", 12, 8, jitter_ms=1.35),
    LinkSpec("s2", "s5", 18, 5, jitter_ms=0.85),
    LinkSpec("s3", "s4", 15, 6, jitter_ms=1.00),
    LinkSpec("s1", "s6", 8, 18, jitter_ms=2.50),
)


def switch_graph() -> dict[str, dict[str, dict[str, float]]]:
    graph: dict[str, dict[str, dict[str, float]]] = {switch: {} for switch in SWITCHES}
    for link in SWITCH_LINKS:
        graph[link.left][link.right] = {
            "bandwidth_mbps": link.bandwidth_mbps,
            "delay_ms": link.delay_ms,
            "loss_percent": link.loss_percent,
            "utilization": 0.0,
        }
        graph[link.right][link.left] = {
            "bandwidth_mbps": link.bandwidth_mbps,
            "delay_ms": link.delay_ms,
            "loss_percent": link.loss_percent,
            "utilization": 0.0,
        }
    return graph


def host_to_switch(host: str) -> str:
    index = HOSTS.index(host)
    return SWITCHES[index]


def dpid_for_switch(switch: str) -> int:
    return int(switch.removeprefix("s"))


def switch_for_dpid(dpid: int) -> str:
    return f"s{dpid}"


HOST_IPS: dict[str, str] = {
    "h1": "10.0.0.1",
    "h2": "10.0.0.2",
    "h3": "10.0.0.3",
    "h4": "10.0.0.4",
    "h5": "10.0.0.5",
    "h6": "10.0.0.6",
}

HOST_MACS: dict[str, str] = {
    host: f"00:00:00:00:00:{index:02x}" for index, host in enumerate(HOSTS, start=1)
}

IP_TO_HOST: dict[str, str] = {ip: host for host, ip in HOST_IPS.items()}
MAC_TO_HOST: dict[str, str] = {mac: host for host, mac in HOST_MACS.items()}


SWITCH_PORTS: dict[str, dict[str, int]] = {
    "s1": {"h1": 1, "s2": 2, "s4": 3, "s6": 4},
    "s2": {"h2": 1, "s1": 2, "s3": 3, "s5": 4},
    "s3": {"h3": 1, "s2": 2, "s6": 3, "s4": 4},
    "s4": {"h4": 1, "s1": 2, "s5": 3, "s3": 4},
    "s5": {"h5": 1, "s4": 2, "s6": 3, "s2": 4},
    "s6": {"h6": 1, "s3": 2, "s5": 3, "s1": 4},
}


def output_port(current_switch: str, next_hop: str) -> int:
    return SWITCH_PORTS[current_switch][next_hop]
