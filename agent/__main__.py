"""
Run: python -m agent "Create user john@company.com with name John"
     python -m agent "Reset password for john@company.com"

Requires:
- OPENAI_API_KEY: LLM planner (structured steps + entities)
- BROWSER_USE_API_KEY: Browser Use Cloud (https://docs.browser-use.com/cloud/quickstart)
- ADMIN_BASE_URL: must be publicly reachable (not plain localhost) for Cloud browser
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from agent.executor import run_browser_use_task
from agent.planner import plan_task


def main() -> None:
    load_dotenv()
    parser = argparse.ArgumentParser(description="IT support agent (OpenAI plan + Browser Use Cloud)")
    parser.add_argument("request", help="Natural language IT request")
    parser.add_argument(
        "--recording",
        action="store_true",
        help="Request a session recording (Browser Use Cloud; see session response for URLs)",
    )
    parser.add_argument(
        "--skills",
        action="store_true",
        help="Enable Cloud agent skills (Google Sheets, etc.); default is browser-only",
    )
    parser.add_argument(
        "--open-live",
        action="store_true",
        help="Open the Browser Use live view URL in your default browser when it is available",
    )
    args = parser.parse_args()

    if not os.environ.get("ADMIN_BASE_URL"):
        print("[Agent] ERROR: Set ADMIN_BASE_URL in .env (public URL for Cloud, e.g. https://xxx.ngrok-free.app)", file=sys.stderr)
        sys.exit(1)

    print("[Agent] Understanding request", flush=True)
    try:
        entities, steps = plan_task(args.request)
    except Exception as e:
        print(f"[Agent] Planning failed: {e}", file=sys.stderr, flush=True)
        sys.exit(1)

    print("[Agent] Planning steps", flush=True)
    print(f"[Agent] Entities: {entities}", flush=True)
    for i, st in enumerate(steps):
        print(f"[Agent] Planned step {i + 1}: {st}", flush=True)

    try:
        result = run_browser_use_task(
            args.request,
            entities,
            steps,
            enable_recording=args.recording,
            skills=args.skills,
            open_live_browser=args.open_live,
        )
        out = result.output
        print("[Agent] --- Browser Use output ---", flush=True)
        print(out if out is not None else "(no output text)", flush=True)
    except Exception as e:
        print(f"[Agent] Browser Use failed: {e}", file=sys.stderr, flush=True)
        sys.exit(2)


if __name__ == "__main__":
    main()
