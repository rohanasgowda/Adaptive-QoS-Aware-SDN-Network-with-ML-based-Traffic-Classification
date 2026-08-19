from __future__ import annotations

import argparse
import json
import subprocess
import time
from pathlib import Path

from traffic.mininet_traffic_driver import run_on_net
from topologies.six_switch_topology import SixSwitchTopo


def run(controller_ip: str, controller_port: int, profile: str, duration: int, output: Path) -> None:
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSKernelSwitch, RemoteController

    setLogLevel("info")
    net = Mininet(
        topo=SixSwitchTopo.build(),
        controller=lambda name: RemoteController(name, ip=controller_ip, port=controller_port),
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True,
    )
    metrics: dict[str, object] = {
        "controller": f"{controller_ip}:{controller_port}",
        "profile": profile,
        "duration_s": duration,
    }
    net.start()
    try:
        ping_start = time.perf_counter()
        loss = net.pingAll()
        metrics["pingall_loss_percent"] = loss
        metrics["pingall_seconds"] = time.perf_counter() - ping_start

        traffic_start = time.perf_counter()
        run_on_net(net, profile, duration)
        metrics["traffic_seconds"] = time.perf_counter() - traffic_start

        iperf_start = time.perf_counter()
        try:
            bandwidth = net.iperf((net.get("h1"), net.get("h6")))
        except (RuntimeError, subprocess.SubprocessError) as exc:
            bandwidth = [f"iperf failed: {exc}"]
        metrics["iperf_h1_h6"] = bandwidth
        metrics["iperf_seconds"] = time.perf_counter() - iperf_start
    finally:
        net.stop()

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(metrics, indent=2), encoding="utf-8")
    print(f"Wrote Mininet metrics to {output}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run topology, traffic, and basic measurements in Mininet.")
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6633)
    parser.add_argument("--profile", choices=["mixed", "voip", "video", "file", "web"], default="mixed")
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--output", type=Path, default=Path("results/mininet_run.json"))
    args = parser.parse_args()
    run(args.controller_ip, args.controller_port, args.profile, args.duration, args.output)


if __name__ == "__main__":
    main()
