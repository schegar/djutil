"""python -m djutil_server {hash-password,serve}."""

from __future__ import annotations

import argparse
import getpass
import sys


def main() -> None:
    parser = argparse.ArgumentParser(prog="djutil_server")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("hash-password", help="Print an argon2 hash of a password")
    openapi_p = sub.add_parser(
        "openapi", help="Print the OpenAPI schema as JSON"
    )
    openapi_p.add_argument(
        "-o", "--out", help="Write to a file instead of stdout"
    )
    seed = sub.add_parser(
        "seed-demo", help="Fill an empty DB with deterministic demo data"
    )
    seed.add_argument("--tracks", type=int, default=500)
    seed.add_argument("--force", action="store_true",
                      help="Allow seeding into a non-empty tracks table")
    serve = sub.add_parser("serve", help="Run the server (single worker)")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    backup = sub.add_parser("backup", help="Online SQLite backup with rotation")
    backup.add_argument("--dir", required=True, help="Destination directory")
    backup.add_argument("--keep", type=int, default=14,
                        help="Number of newest copies to retain")
    backup.add_argument("--loop-hours", type=float, default=None,
                        help="Repeat every H hours")
    args = parser.parse_args()

    if args.command == "hash-password":
        from argon2 import PasswordHasher

        pw = getpass.getpass("Password: ")
        pw2 = getpass.getpass("Repeat: ")
        if pw != pw2:
            sys.exit("Passwords do not match")
        print(PasswordHasher().hash(pw))
        return

    if args.command == "openapi":
        import json

        from .app import create_app

        schema = json.dumps(create_app().openapi())
        if args.out:
            with open(args.out, "w") as f:
                f.write(schema)
        else:
            print(schema)
        return

    if args.command == "seed-demo":
        from .seed import seed_demo

        seed_demo(args.tracks, force=args.force)
        return

    if args.command == "backup":
        from pathlib import Path

        from .backup import backup_loop, run_backup
        from .config import get_settings

        dest_dir = Path(args.dir)
        db_path = get_settings().db_path
        if args.loop_hours:
            backup_loop(db_path, dest_dir, args.keep, args.loop_hours)
        else:
            dest = run_backup(db_path, dest_dir, args.keep)
            print(f"backup written: {dest}")
        return

    import uvicorn

    from .app import create_app

    app = create_app()
    # The app only ever sits behind Caddy on the compose network, so trusting
    # forwarded headers from any peer is safe here.
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        workers=1,
        proxy_headers=True,
        forwarded_allow_ips="*",
    )


if __name__ == "__main__":
    main()
