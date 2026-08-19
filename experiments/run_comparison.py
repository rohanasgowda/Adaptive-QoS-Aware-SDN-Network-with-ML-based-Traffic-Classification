from __future__ import annotations

import argparse
import csv
import json
import random
import statistics
import time
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

from ai.generate_training_data import generate_rows, write_csv
from ai.train_model import train
from common.controller_logic import ControllerBrain, PacketMetadata
from common.routing import overloaded_links
from common.topology import HOST_IPS, HOSTS
from common.traffic_types import TRAFFIC_PROFILES, TrafficType


@dataclass(frozen=True)
class ControllerProfile:
    name: str
    install_overhead_ms: tuple[float, float]
    cpu_base_percent: float
    cpu_jitter_percent: float


CONTROLLERS: tuple[ControllerProfile, ...] = (
    ControllerProfile("ryu", (2.5, 7.0), 18.0, 6.0),
    ControllerProfile("pox", (4.0, 11.0), 14.0, 5.0),
    ControllerProfile("raw", (1.8, 6.0), 10.0, 4.0),
)


def ensure_model(seed: int) -> None:
    data_path = Path("data/training_flows.csv")
    model_path = Path("models/traffic_rf.joblib")
    report_path = Path("results/model_report.json")
    if not data_path.exists():
        write_csv(data_path, generate_rows(samples_per_class=1200, seed=seed))
    if not model_path.exists():
        train(data_path, model_path, report_path, seed)


def simulate(controller: ControllerProfile, events: int, seed: int) -> list[dict[str, object]]:
    rng = random.Random(seed)
    brain = ControllerBrain()
    rows: list[dict[str, object]] = []
    active_flows: list[tuple[str, str, TrafficType, int, int, int]] = []

    for event_id in range(events):
        if active_flows and rng.random() < 0.55:
            src, dst, traffic_type, src_port, dst_port, ip_proto = rng.choice(active_flows)
            profile = TRAFFIC_PROFILES[traffic_type]
        else:
            traffic_type = rng.choices(
                list(TRAFFIC_PROFILES.keys()),
                weights=[0.25, 0.25, 0.30, 0.20],
                k=1,
            )[0]
            src, dst = rng.sample(HOSTS, 2)
            profile = TRAFFIC_PROFILES[traffic_type]
            dst_port = rng.choice(profile.ports)
            src_port = rng.randint(1024, 65000)
            ip_proto = 17 if traffic_type in (TrafficType.VOIP, TrafficType.VIDEO) else 6
            active_flows.append((src, dst, traffic_type, src_port, dst_port, ip_proto))

        packet_size = rng.randint(*profile.packet_size_range)
        metadata = PacketMetadata(
            src_ip=HOST_IPS[src],
            dst_ip=HOST_IPS[dst],
            src_port=src_port,
            dst_port=dst_port,
            packet_size=packet_size,
            ip_proto=ip_proto,
        )

        started = time.perf_counter()
        decision = brain.decide(metadata)
        classify_route_ms = (time.perf_counter() - started) * 1000.0
        if decision is None:
            continue

        path = decision.path_decision.path
        delay_ms = _path_delay_ms(brain.graph, path, rng)
        throughput_mbps = _path_throughput_mbps(brain.graph, path, traffic_type, rng)
        install_ms = classify_route_ms + rng.uniform(*controller.install_overhead_ms)
        overloaded_count = len(overloaded_links(brain.graph, threshold=0.80))
        congestion_handled = decision.rerouted
        cpu = min(100.0, controller.cpu_base_percent + rng.random() * controller.cpu_jitter_percent + overloaded_count * 2.0)

        rows.append(
            {
                "controller": controller.name,
                "event_id": event_id,
                "traffic_type": traffic_type.value,
                "src": src,
                "dst": dst,
                "path": "->".join(path),
                "throughput_mbps": round(throughput_mbps, 3),
                "delay_ms": round(delay_ms, 3),
                "install_ms": round(install_ms, 3),
                "cpu_percent": round(cpu, 3),
                "rerouted": decision.rerouted,
                "congestion_handled": congestion_handled,
                "overloaded_links": overloaded_count,
            }
        )
    return rows


def _path_delay_ms(graph: dict[str, dict[str, dict[str, float]]], path: tuple[str, ...], rng: random.Random) -> float:
    delay = 0.0
    for left, right in zip(path, path[1:]):
        edge = graph[left][right]
        delay += edge["delay_ms"] * (1.0 + edge.get("utilization", 0.0) * 0.75)
    return delay + rng.uniform(0.2, 2.5)


def _path_throughput_mbps(
    graph: dict[str, dict[str, dict[str, float]]],
    path: tuple[str, ...],
    traffic_type: TrafficType,
    rng: random.Random,
) -> float:
    profile = TRAFFIC_PROFILES[traffic_type]
    available = []
    for left, right in zip(path, path[1:]):
        edge = graph[left][right]
        available.append(edge["bandwidth_mbps"] * max(0.05, 1.0 - edge.get("utilization", 0.0)))
    bottleneck = min(available) if available else 100.0
    target = profile.bandwidth_mbps if traffic_type is not TrafficType.FILE else bottleneck
    return min(target, bottleneck) * rng.uniform(0.88, 1.03)


def write_outputs(rows: list[dict[str, object]], output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    raw_csv = output_dir / "comparison_raw.csv"
    with raw_csv.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    data = pd.DataFrame(rows)
    summary = (
        data.groupby("controller")
        .agg(
            throughput_mbps=("throughput_mbps", "mean"),
            delay_ms=("delay_ms", "mean"),
            install_ms=("install_ms", "mean"),
            cpu_percent=("cpu_percent", "mean"),
            reroutes=("rerouted", "sum"),
            congestion_events=("overloaded_links", lambda values: sum(1 for value in values if value > 0)),
            handled_events=("congestion_handled", "sum"),
        )
        .reset_index()
    )
    summary["congestion_handling_score"] = summary.apply(
        lambda row: 0.0
        if row["congestion_events"] == 0
        else round(row["handled_events"] / row["congestion_events"], 3),
        axis=1,
    )
    summary.to_csv(output_dir / "comparison_summary.csv", index=False)
    (output_dir / "comparison_summary.json").write_text(
        json.dumps(summary.to_dict(orient="records"), indent=2),
        encoding="utf-8",
    )
    _plot_summary(summary, output_dir)
    _plot_by_traffic_type(data, output_dir)
    print(f"Wrote raw metrics to {raw_csv}")
    print(f"Wrote summary to {output_dir / 'comparison_summary.csv'}")


def _plot_summary(summary: pd.DataFrame, output_dir: Path) -> None:
    metrics = ["throughput_mbps", "delay_ms", "install_ms", "cpu_percent", "congestion_handling_score"]
    for metric in metrics:
        fig, ax = plt.subplots(figsize=(7, 4))
        ax.bar(summary["controller"], summary[metric], color=["#2b8a8a", "#6b7280", "#c27c2c"])
        ax.set_title(metric.replace("_", " ").title())
        ax.set_xlabel("Controller")
        ax.set_ylabel(metric.replace("_", " "))
        ax.grid(axis="y", alpha=0.25)
        fig.tight_layout()
        fig.savefig(output_dir / f"{metric}.png", dpi=160)
        plt.close(fig)


def _plot_by_traffic_type(data: pd.DataFrame, output_dir: Path) -> None:
    grouped = data.groupby(["controller", "traffic_type"])["delay_ms"].mean().unstack(0)
    fig, ax = plt.subplots(figsize=(8, 4.5))
    grouped.plot(kind="bar", ax=ax, color=["#2b8a8a", "#6b7280", "#c27c2c"])
    ax.set_title("Average Delay By Traffic Type")
    ax.set_xlabel("Traffic type")
    ax.set_ylabel("delay ms")
    ax.grid(axis="y", alpha=0.25)
    fig.tight_layout()
    fig.savefig(output_dir / "delay_by_traffic_type.png", dpi=160)
    plt.close(fig)


def print_summary(output_dir: Path) -> None:
    summary = pd.read_csv(output_dir / "comparison_summary.csv")
    print(summary.to_string(index=False))


def main() -> None:
    parser = argparse.ArgumentParser(description="Compare Ryu, POX, and raw controller behavior.")
    parser.add_argument("--events", type=int, default=240)
    parser.add_argument("--seed", type=int, default=7)
    parser.add_argument("--output-dir", type=Path, default=Path("results"))
    args = parser.parse_args()
    ensure_model(args.seed)
    rows: list[dict[str, object]] = []
    for offset, controller in enumerate(CONTROLLERS):
        rows.extend(simulate(controller, args.events, args.seed + offset))
    write_outputs(rows, args.output_dir)
    print_summary(args.output_dir)


if __name__ == "__main__":
    main()
