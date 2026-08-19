from __future__ import annotations

from dataclasses import dataclass

from common.traffic_types import TRAFFIC_PROFILES, TrafficType, normalize_traffic_type


@dataclass(frozen=True)
class PathDecision:
    traffic_type: TrafficType
    path: tuple[str, ...]
    cost: float
    reason: str


def _path_cost(
    graph: dict[str, dict[str, dict[str, float]]],
    path: tuple[str, ...],
    traffic_type: TrafficType,
) -> float:
    profile = TRAFFIC_PROFILES[traffic_type]
    edges = [graph[left][right] for left, right in zip(path, path[1:])]
    delay = sum(edge["delay_ms"] for edge in edges)
    bottleneck = min(edge["bandwidth_mbps"] for edge in edges)
    inverse_bandwidth = 100.0 / max(bottleneck, 0.1)
    congestion = 100.0 * (sum(edge.get("utilization", 0.0) for edge in edges) / max(len(edges), 1))
    loss = 20.0 * sum(edge.get("loss_percent", 0.0) for edge in edges)
    return (
        profile.delay_weight * delay
        + profile.bandwidth_weight * inverse_bandwidth
        + profile.congestion_weight * congestion
        + loss
    )


def choose_path(
    graph: dict[str, dict[str, dict[str, float]]],
    source: str,
    destination: str,
    traffic_type: str | TrafficType,
) -> PathDecision:
    kind = normalize_traffic_type(traffic_type)
    candidates = list(_simple_paths(graph, source, destination, max_depth=len(graph)))
    if not candidates:
        raise ValueError(f"No path between {source} and {destination}")
    best_path = min(candidates, key=lambda path: (_path_cost(graph, path, kind), len(path), path))
    return PathDecision(kind, best_path, _path_cost(graph, best_path, kind), _reason(kind))


def _simple_paths(
    graph: dict[str, dict[str, dict[str, float]]],
    source: str,
    destination: str,
    max_depth: int,
) -> list[tuple[str, ...]]:
    paths: list[tuple[str, ...]] = []
    stack: list[tuple[str, tuple[str, ...]]] = [(source, (source,))]
    while stack:
        node, path = stack.pop()
        if len(path) > max_depth:
            continue
        if node == destination:
            paths.append(path)
            continue
        for neighbor in graph[node]:
            if neighbor not in path:
                stack.append((neighbor, path + (neighbor,)))
    return paths


def overloaded_links(
    graph: dict[str, dict[str, dict[str, float]]], threshold: float = 0.80
) -> list[tuple[str, str, float]]:
    seen: set[tuple[str, str]] = set()
    overloaded: list[tuple[str, str, float]] = []
    for left, neighbors in graph.items():
        for right, edge in neighbors.items():
            key = tuple(sorted((left, right)))
            if key in seen:
                continue
            seen.add(key)
            utilization = edge.get("utilization", 0.0)
            if utilization >= threshold:
                overloaded.append((left, right, utilization))
    return overloaded


def should_reroute(
    traffic_type: str | TrafficType,
    current_path: tuple[str, ...],
    graph: dict[str, dict[str, dict[str, float]]],
    threshold: float = 0.80,
) -> bool:
    kind = normalize_traffic_type(traffic_type)
    if TRAFFIC_PROFILES[kind].priority >= 4:
        return False
    for left, right in zip(current_path, current_path[1:]):
        if graph[left][right].get("utilization", 0.0) >= threshold:
            return True
    return False


def apply_flow_load(
    graph: dict[str, dict[str, dict[str, float]]],
    path: tuple[str, ...],
    traffic_type: str | TrafficType,
) -> None:
    profile = TRAFFIC_PROFILES[normalize_traffic_type(traffic_type)]
    for left, right in zip(path, path[1:]):
        edge = graph[left][right]
        added = profile.bandwidth_mbps / edge["bandwidth_mbps"]
        new_util = min(1.0, edge.get("utilization", 0.0) + added)
        edge["utilization"] = new_util
        graph[right][left]["utilization"] = new_util


def decay_utilization(
    graph: dict[str, dict[str, dict[str, float]]], factor: float = 0.94
) -> None:
    seen: set[tuple[str, str]] = set()
    for left, neighbors in graph.items():
        for right, edge in neighbors.items():
            key = tuple(sorted((left, right)))
            if key in seen:
                continue
            seen.add(key)
            new_value = max(0.0, edge.get("utilization", 0.0) * factor)
            edge["utilization"] = new_value
            graph[right][left]["utilization"] = new_value


def _reason(kind: TrafficType) -> str:
    if kind is TrafficType.VOIP:
        return "VoIP is delay-sensitive, so delay dominates the path cost."
    if kind is TrafficType.FILE:
        return "File transfer is throughput-sensitive, so bandwidth dominates the path cost."
    if kind is TrafficType.VIDEO:
        return "Video balances bandwidth with delay and congestion."
    return "Web traffic is bursty, so congestion avoidance receives extra weight."
