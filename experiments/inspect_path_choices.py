from __future__ import annotations

from common.routing import choose_path
from common.topology import switch_graph
from common.traffic_types import TrafficType


def main() -> None:
    graph = switch_graph()
    for traffic_type in TrafficType:
        decision = choose_path(graph, "s1", "s6", traffic_type)
        print(f"{traffic_type.value:5s}: {' -> '.join(decision.path)} | cost={decision.cost:.2f}")
        print(f"       {decision.reason}")


if __name__ == "__main__":
    main()
