"""Usage:  python main.py [--config config.yaml] [--topic "..."]"""
import argparse
import asyncio
from datetime import datetime
from pathlib import Path

import yaml

from autoresearch.runner import run_pipeline


def main() -> None:
    parser = argparse.ArgumentParser(description="AutoResearch Agent")
    parser.add_argument("--config", default="config.yaml")
    parser.add_argument("--topic", help="override the topic in the config")
    args = parser.parse_args()

    config = yaml.safe_load(Path(args.config).read_text(encoding="utf-8"))
    if args.topic:
        config["topic"] = args.topic
    run_dir = Path("runs") / datetime.now().strftime("%Y%m%d-%H%M%S")
    print(f"Topic: {config['topic']}\nRun folder: {run_dir}\n")

    state = asyncio.run(run_pipeline(config, run_dir))

    print(f"\nStatus: {state.get('status')} | sandbox: {state.get('sandbox')} | "
          f"cost: ${state['cost_usd']:.3f} | time: {state['seconds']}s")
    if state.get("reviews"):
        print(f"Final review score: {state['reviews'][-1].get('score')}/10")
    print(f"Outputs in {run_dir}")


if __name__ == "__main__":
    main()
