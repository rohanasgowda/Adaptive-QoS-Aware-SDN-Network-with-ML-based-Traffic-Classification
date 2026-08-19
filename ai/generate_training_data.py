from __future__ import annotations

import argparse
import csv
import random
from dataclasses import dataclass
from pathlib import Path

from common.traffic_types import TRAFFIC_PROFILES, TrafficType


@dataclass(frozen=True)
class NoiseConfig:
    """Realistic observation noise without deliberately corrupting labels."""

    shared_port_probability: float = 0.35
    packet_size_jitter: float = 0.12
    interarrival_jitter: float = 0.35
    burst_probability: float = 0.15


SHARED_SERVICE_PORTS: tuple[int, ...] = (443, 8080, 8443)


def _noisy_sample(rng: random.Random, traffic_type: TrafficType, noise: NoiseConfig) -> tuple[int, float, int]:
    profile = TRAFFIC_PROFILES[traffic_type]
    packet_size = rng.randint(*profile.packet_size_range)
    interarrival = rng.uniform(*profile.interarrival_ms_range)
    dst_port = rng.choice(profile.ports)

    # Encryption, reverse proxies, and tunnels make several applications share
    # the same visible service port even when their traffic behavior differs.
    if rng.random() < noise.shared_port_probability:
        dst_port = rng.choice(SHARED_SERVICE_PORTS)

    packet_size += round(rng.gauss(0.0, max(18.0, packet_size * noise.packet_size_jitter)))
    interarrival *= max(0.05, rng.lognormvariate(0.0, noise.interarrival_jitter))

    # Scheduler stalls and application bursts occasionally produce observations
    # outside the nominal profile without changing the true traffic class.
    if rng.random() < noise.burst_probability:
        interarrival *= rng.uniform(0.15, 3.5)
        packet_size += rng.randint(-280, 280)

    return max(60, min(packet_size, 1500)), max(0.2, min(interarrival, 1000.0)), dst_port


def generate_rows(
    samples_per_class: int,
    seed: int,
    noise: NoiseConfig | None = None,
) -> list[dict[str, float | str]]:
    rng = random.Random(seed)
    noise = noise or NoiseConfig()
    rows: list[dict[str, float | str]] = []
    for traffic_type in TRAFFIC_PROFILES:
        for _ in range(samples_per_class):
            packet_size, interarrival, dst_port = _noisy_sample(rng, traffic_type, noise)
            src_port = rng.randint(1024, 65000)
            rows.append(
                {
                    "packet_size": packet_size,
                    "interarrival_ms": round(interarrival, 3),
                    "src_port": src_port,
                    "dst_port": dst_port,
                    "service_port": min(src_port, dst_port),
                    "label": traffic_type.value,
                }
            )
    rng.shuffle(rows)
    return rows


def write_csv(path: Path, rows: list[dict[str, float | str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate labelled synthetic flow features.")
    parser.add_argument("--output", type=Path, default=Path("data/training_flows.csv"))
    parser.add_argument("--samples-per-class", type=int, default=1200)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--shared-port-probability", type=float, default=0.35)
    parser.add_argument("--packet-size-jitter", type=float, default=0.12)
    parser.add_argument("--interarrival-jitter", type=float, default=0.35)
    parser.add_argument("--burst-probability", type=float, default=0.15)
    args = parser.parse_args()
    noise = NoiseConfig(
        shared_port_probability=args.shared_port_probability,
        packet_size_jitter=args.packet_size_jitter,
        interarrival_jitter=args.interarrival_jitter,
        burst_probability=args.burst_probability,
    )
    rows = generate_rows(args.samples_per_class, args.seed, noise)
    write_csv(args.output, rows)
    print(f"Wrote {len(rows)} rows to {args.output}")


if __name__ == "__main__":
    main()
