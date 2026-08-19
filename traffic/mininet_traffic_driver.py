from __future__ import annotations

import argparse
import itertools
import time

from common.traffic_types import TrafficType
from traffic.profiles import TRAFFIC_COMMANDS


FLOWS: tuple[tuple[str, str, TrafficType], ...] = (
    ("h1", "h6", TrafficType.VOIP),
    ("h2", "h5", TrafficType.VIDEO),
    ("h3", "h4", TrafficType.FILE),
    ("h4", "h1", TrafficType.WEB),
)


def _host_ip(host_name: str) -> str:
    return f"10.0.0.{host_name.removeprefix('h')}"


def run_on_net(net, profile: str, duration: int) -> None:
    selected = FLOWS if profile == "mixed" else tuple(flow for flow in FLOWS if flow[2].value == profile)
    servers = []
    clients = []

    for _, dst, traffic_type in selected:
        command = TRAFFIC_COMMANDS[traffic_type]
        host = net.get(dst)
        servers.append(host.popen(command.server_cmd, shell=True))
        time.sleep(0.2)

    for src, dst, traffic_type in selected:
        command = TRAFFIC_COMMANDS[traffic_type]
        client_cmd = command.client_cmd.format(dst_ip=_host_ip(dst), duration=duration)
        clients.append(net.get(src).popen(client_cmd, shell=True))

    for proc in clients:
        proc.wait()
    for proc in servers:
        proc.terminate()


def print_plan(profile: str, duration: int) -> None:
    selected = FLOWS if profile == "mixed" else tuple(flow for flow in FLOWS if flow[2].value == profile)
    for index, (src, dst, traffic_type) in enumerate(itertools.cycle(selected), start=1):
        if index > len(selected):
            break
        command = TRAFFIC_COMMANDS[traffic_type]
        print(f"{src}->{dst} {traffic_type.value}: {command.description}")
        print(f"  server on {dst}: {command.server_cmd}")
        print(f"  client on {src}: {command.client_cmd.format(dst_ip=_host_ip(dst), duration=duration)}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Drive realistic traffic in the Mininet topology.")
    parser.add_argument("--profile", choices=["mixed", "voip", "video", "file", "web"], default="mixed")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if args.dry_run:
        print_plan(args.profile, args.duration)
    else:
        raise SystemExit(
            "Run this through topologies/run_mininet_experiment.py so the driver can access the Mininet object."
        )


if __name__ == "__main__":
    main()
