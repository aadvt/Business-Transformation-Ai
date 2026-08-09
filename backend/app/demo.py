"""Small deterministic scenario runner for rehearsal; network calls remain optional."""
import argparse
def main():
    parser = argparse.ArgumentParser(); sub = parser.add_subparsers(dest="command", required=True)
    run = sub.add_parser("run"); run.add_argument("scenario", choices=["golden_path", "stockout", "guardrail_breach"]); run.add_argument("--speed", choices=["1x", "instant"], default="1x"); run.add_argument("--pause-at-approval", action="store_true"); run.add_argument("--pause-before-call", action="store_true")
    args = parser.parse_args()
    if args.command == "run":
        print(f"Scenario {args.scenario} selected; manual Bolna pause={args.pause_before_call}")
        print("Use the demo UI or simulate endpoint to create the disruption, then resume after the webhook.")

if __name__ == "__main__": main()
