#!/usr/bin/env python3
"""Register (or update) a Bolna agent config with Bolna's API. Two configs
live in this directory: bolna_agent_config.json (the owner-approval agent,
the default) and bolna_negotiation_agent_config.json (the outbound vendor
negotiation agent — pass --config negotiation to target it).

Defaults to a dry run — it resolves the config's placeholder URLs/token and
prints what WOULD be sent, but does not call Bolna's API. Pass --submit to
actually create the agent.

    python -m voice.register_agent                              # dry run, approval agent
    python -m voice.register_agent --submit                     # really create it
    python -m voice.register_agent --submit --update <agent_id> # update instead
    python -m voice.register_agent --config negotiation --submit  # the negotiation agent instead

Requires (in .env or the environment):
    BOLNA_API_KEY               your Bolna API key
    VOICE_ADAPTER_BASE_URL      public URL the voice adapter is reachable at
                                 (an ngrok tunnel in dev, a real host in prod —
                                 Bolna's tool-call webhooks need to reach this)
    VOICE_ADAPTER_SHARED_SECRET the same secret voice/adapter.py checks

A real webhook URL is required for the agent to actually work on a call —
registering with the placeholder left in bolna_agent_config.json will create
an agent Bolna can't reach.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()

BOLNA_API_BASE = "https://api.bolna.ai"
CONFIG_PATHS = {
    "approval": Path(__file__).parent / "bolna_agent_config.json",
    "negotiation": Path(__file__).parent / "bolna_negotiation_agent_config.json",
}

PLACEHOLDER_HOST = "https://YOUR_PUBLIC_HOST"
PLACEHOLDER_SECRET = "YOUR_VOICE_ADAPTER_SHARED_SECRET"


def resolve_config(config_path: Path, base_url: str, shared_secret: str) -> dict:
    config = json.loads(config_path.read_text())
    tools_params = config["agent_config"]["tasks"][0]["tools_config"]["api_tools"]["tools_params"]
    for tool_name, params in tools_params.items():
        params["url"] = params["url"].replace(PLACEHOLDER_HOST, base_url.rstrip("/"))
        params["api_token"] = shared_secret
    return config


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--config",
        choices=sorted(CONFIG_PATHS),
        default="approval",
        help="Which agent config to register (default: approval)",
    )
    parser.add_argument("--submit", action="store_true", help="Actually call Bolna's API (default: dry run / print only)")
    parser.add_argument("--update", metavar="AGENT_ID", default=None, help="Update this agent instead of creating a new one")
    args = parser.parse_args(argv)

    api_key = os.environ.get("BOLNA_API_KEY")
    base_url = os.environ.get("VOICE_ADAPTER_BASE_URL", PLACEHOLDER_HOST)
    shared_secret = os.environ.get("VOICE_ADAPTER_SHARED_SECRET", PLACEHOLDER_SECRET)

    if not api_key:
        print("BOLNA_API_KEY is not set (check .env). Aborting.", file=sys.stderr)
        return 1
    if base_url == PLACEHOLDER_HOST:
        print(
            "VOICE_ADAPTER_BASE_URL is not set — the agent would be created pointing at a "
            "placeholder URL Bolna can't reach. Set it to a public URL (e.g. an ngrok tunnel) first.",
            file=sys.stderr,
        )
        if args.submit:
            return 1

    config = resolve_config(CONFIG_PATHS[args.config], base_url, shared_secret)

    print("Resolved tool webhook URLs:")
    tools_params = config["agent_config"]["tasks"][0]["tools_config"]["api_tools"]["tools_params"]
    for tool_name, params in tools_params.items():
        print(f"  {tool_name}: {params['method']} {params['url']}")
    print()

    if not args.submit:
        print("Dry run only — not calling Bolna. Re-run with --submit to actually register this agent.")
        print()
        print(json.dumps(config, indent=2))
        return 0

    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    with httpx.Client(base_url=BOLNA_API_BASE, headers=headers, timeout=30.0) as client:
        if args.update:
            resp = client.put(f"/v2/agent/{args.update}", json=config)
        else:
            resp = client.post("/v2/agent", json=config)

    if resp.status_code not in (200, 201):
        print(f"Bolna API error {resp.status_code}: {resp.text}", file=sys.stderr)
        return 1

    data = resp.json()
    print(json.dumps(data, indent=2))
    agent_id = data.get("agent_id")
    if agent_id:
        print()
        print(f"Agent id: {agent_id}")
        print(f"Add this to .env: BOLNA_AGENT_ID={agent_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
