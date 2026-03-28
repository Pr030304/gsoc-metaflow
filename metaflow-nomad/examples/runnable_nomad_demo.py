import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from metaflow_nomad_demo import nomad, run_nomad_step


@nomad(cpu=500, memory=256, image="python:3.11-slim")
def train():
    return (
        "python -c \"import time; "
        "print('Epoch 1...'); "
        "time.sleep(1); "
        "print('Epoch 2...'); "
        "time.sleep(1); "
        "print('Training complete')\""
    )


@nomad(cpu=500, memory=256, image="python:3.11-slim")
def train_fail():
    return (
        "python -c \"import sys, time; "
        "print('Epoch 1...'); "
        "time.sleep(1); "
        "print('Worker crashed'); "
        "sys.exit(2)\""
    )


def parse_args():
    parser = argparse.ArgumentParser(
        description="Runnable proof-of-work demo for the Metaflow Nomad backend."
    )
    parser.add_argument(
        "--mode",
        choices=("success", "fail"),
        default="success",
        help="Run a successful or failing remote task.",
    )
    parser.add_argument("--address", default="http://127.0.0.1:4646")
    parser.add_argument("--namespace", default="default")
    parser.add_argument("--datacenters", default="dc1")
    parser.add_argument("--image", default="python:3.11-slim")
    parser.add_argument("--cpu", type=int, default=500)
    parser.add_argument("--memory", type=int, default=256)
    parser.add_argument("--poll-interval", type=float, default=1.0)
    parser.add_argument(
        "--print-jobspec",
        action="store_true",
        help="Print the generated Nomad job JSON before submission.",
    )
    parser.add_argument(
        "--keep-existing",
        action="store_true",
        help="Do not purge a previous demo job with the same name.",
    )
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    target = train if args.mode == "success" else train_fail

    run_nomad_step(
        target,
        cpu=args.cpu,
        memory=args.memory,
        image=args.image,
        datacenters=args.datacenters,
        address=args.address,
        namespace=args.namespace,
        purge_existing=not args.keep_existing,
        print_jobspec=args.print_jobspec,
        poll_interval=args.poll_interval,
        attrs={"demo.mode": args.mode},
    )
