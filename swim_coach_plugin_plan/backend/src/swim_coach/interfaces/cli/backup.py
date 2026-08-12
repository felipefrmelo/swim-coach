"""Create or restore a verified encrypted personal backup."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from swim_coach.infrastructure.backup import (
    create_backup,
    load_key,
    prune_backups,
    restore_backup,
)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    create = subparsers.add_parser("create")
    create.add_argument("--database-url", required=True)
    create.add_argument("--artifacts", required=True, type=Path)
    create.add_argument("--output", required=True, type=Path)
    create.add_argument("--key-file", required=True, type=Path)
    create.add_argument("--retain", default=7, type=int)
    restore = subparsers.add_parser("restore")
    restore.add_argument("--database-url", required=True)
    restore.add_argument("--artifacts", required=True, type=Path)
    restore.add_argument("--input", required=True, type=Path)
    restore.add_argument("--key-file", required=True, type=Path)
    restore.add_argument("--allow-nonempty-artifacts", action="store_true")
    args = parser.parse_args()
    key = load_key(args.key_file)
    if args.command == "create":
        manifest = create_backup(args.database_url, args.artifacts, args.output, key)
        removed = prune_backups(args.output.parent, retain=args.retain, protected=args.output)
        manifest["retention"] = {"retained": args.retain, "removed": len(removed)}
    else:
        manifest = restore_backup(
            args.input,
            args.database_url,
            args.artifacts,
            key,
            allow_nonempty_artifacts=args.allow_nonempty_artifacts,
        )
    print(json.dumps(manifest, sort_keys=True))


if __name__ == "__main__":
    main()
