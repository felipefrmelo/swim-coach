"""Guide and verify the P07 disposable live Garmin write canary without handling credentials."""

from __future__ import annotations

import argparse
import json
import os
import sys


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify explicit live-write safeguards before the P07 disposable canary."
    )
    parser.add_argument(
        "--acknowledge-external-write",
        action="store_true",
        help=(
            "Confirm that the operator understands the PWA action creates and schedules "
            "one workout."
        ),
    )
    args = parser.parse_args()
    enabled = os.getenv("SWIM_COACH_GARMIN_WRITE_ENABLED", "false").casefold() == "true"
    mode = os.getenv("SWIM_COACH_GARMIN_WRITE_MODE", "disabled")
    canary_only = os.getenv("SWIM_COACH_GARMIN_WRITE_CANARY_ONLY", "true").casefold() == "true"
    prefix = os.getenv("SWIM_COACH_GARMIN_WRITE_CANARY_TITLE_PREFIX", "[CANARY]").strip()
    ready = (
        enabled
        and mode == "live"
        and canary_only
        and bool(prefix)
        and args.acknowledge_external_write
    )
    result = {
        "garmin_write_canary_probe": "ready" if ready else "blocked",
        "external_write_performed": False,
        "write_enabled": enabled,
        "write_mode": mode,
        "canary_only": canary_only,
        "required_title_prefix": prefix,
        "operator_acknowledged_external_write": args.acknowledge_external_write,
        "next": (
            f"Na PWA, crie um treino descartável começando por {prefix}, aprove, agende, "
            "revise o impacto e clique uma vez no verbo explícito de publicação."
            if ready
            else "Configure live+canary e confirme com --acknowledge-external-write."
        ),
    }
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if ready else 2


if __name__ == "__main__":
    sys.exit(main())
