"""Regenerate public artifacts without network access or cloud credentials."""
import argparse
from build_demo import main as build_demo
from model_experiment import run_experiment


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--demo-only", action="store_true")
    args = parser.parse_args()
    build_demo()
    if not args.demo_only:
        run_experiment()
