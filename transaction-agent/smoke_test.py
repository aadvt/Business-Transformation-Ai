#!/usr/bin/env python3
"""Standalone check that watsonx.ai credentials work, before building the graph.

    python smoke_test.py

Exits non-zero with a clear message if env vars are missing or auth fails.
"""

from __future__ import annotations

import sys

from dotenv import load_dotenv

from transaction_agent.llm import WatsonxConfigError, check_env, get_llm

load_dotenv()


def main() -> int:
    try:
        check_env()
    except WatsonxConfigError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print("Env vars present. Calling watsonx.ai...")
    try:
        llm = get_llm()
        response = llm.invoke("Reply with exactly one word: OK")
    except Exception as exc:  # noqa: BLE001 - deliberately broad: this is a diagnostic script
        print(f"watsonx.ai call failed: {exc}", file=sys.stderr)
        return 1

    print(f"watsonx.ai responded: {response.content!r}")
    print("Auth OK.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
