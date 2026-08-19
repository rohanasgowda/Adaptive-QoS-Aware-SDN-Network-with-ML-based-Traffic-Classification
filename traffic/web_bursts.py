from __future__ import annotations

import argparse
import random
import time
import urllib.request


def run(url: str, duration: int, seed: int) -> None:
    rng = random.Random(seed)
    end = time.time() + duration
    request_count = 0
    while time.time() < end:
        try:
            with urllib.request.urlopen(url, timeout=2.0) as response:
                response.read(rng.randint(256, 4096))
            request_count += 1
        except OSError as exc:
            print(f"web request failed: {exc}")
        time.sleep(rng.uniform(0.2, 1.8))
    print(f"completed {request_count} web burst requests")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate irregular HTTP web-browsing bursts.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--duration", type=int, default=30)
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args()
    run(args.url, args.duration, args.seed)


if __name__ == "__main__":
    main()
