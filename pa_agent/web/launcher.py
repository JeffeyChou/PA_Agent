"""Command-line launcher for the FastAPI browser surface."""

from __future__ import annotations

import argparse
import webbrowser
from contextlib import suppress


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="pa-agent", description="Launch PA Agent web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--no-open", action="store_true", help="Do not open the browser automatically."
    )
    args = parser.parse_args(argv)

    import uvicorn

    url = f"http://{args.host}:{args.port}"
    if not args.no_open:
        with suppress(Exception):
            webbrowser.open(url)
    uvicorn.run("pa_agent.web.app:create_app", factory=True, host=args.host, port=args.port)
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
