#!/usr/bin/env bash
set -euo pipefail

python3 -m ai.train_model
python3 -m experiments.run_comparison --events 240 --output-dir results
