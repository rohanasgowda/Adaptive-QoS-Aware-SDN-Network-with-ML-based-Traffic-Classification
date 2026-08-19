from __future__ import annotations

import argparse

from common.topology import HOST_LINKS, HOSTS, SWITCH_LINKS, SWITCHES


class SixSwitchTopo:
    """Factory wrapper so importing this file does not require Mininet."""

    @staticmethod
    def build():
        from mininet.topo import Topo

        class _Topo(Topo):
            def build(self) -> None:
                for host in HOSTS:
                    self.addHost(host, ip=f"10.0.0.{host.removeprefix('h')}/24")
                for switch in SWITCHES:
                    self.addSwitch(switch, protocols="OpenFlow10")
                for link in HOST_LINKS:
                    self.addLink(
                        link.left,
                        link.right,
                        bw=link.bandwidth_mbps,
                        delay=f"{link.delay_ms}ms",
                        jitter=f"{link.jitter_ms}ms",
                        loss=link.loss_percent,
                    )
                for link in SWITCH_LINKS:
                    self.addLink(
                        link.left,
                        link.right,
                        bw=link.bandwidth_mbps,
                        delay=f"{link.delay_ms}ms",
                        jitter=f"{link.jitter_ms}ms",
                        loss=link.loss_percent,
                    )

        return _Topo()


def run_cli(controller_ip: str, controller_port: int) -> None:
    from mininet.cli import CLI
    from mininet.link import TCLink
    from mininet.log import setLogLevel
    from mininet.net import Mininet
    from mininet.node import OVSKernelSwitch, RemoteController

    setLogLevel("info")
    topo = SixSwitchTopo.build()
    net = Mininet(
        topo=topo,
        controller=lambda name: RemoteController(
            name, ip=controller_ip, port=controller_port
        ),
        switch=OVSKernelSwitch,
        link=TCLink,
        autoSetMacs=True,
        autoStaticArp=True,
    )
    net.start()
    try:
        print("Network is running. Try: pingall")
        print("Traffic driver: sudo python -m traffic.mininet_traffic_driver --profile mixed")
        CLI(net)
    finally:
        net.stop()


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the 6-switch/6-host Mininet topology.")
    parser.add_argument("--controller-ip", default="127.0.0.1")
    parser.add_argument("--controller-port", type=int, default=6633)
    args = parser.parse_args()
    run_cli(args.controller_ip, args.controller_port)


if __name__ == "__main__":
    main()
