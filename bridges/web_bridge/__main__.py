"""Entry point for ``python -m bridges.web_bridge``.

Runs the FastAPI app from ``server.py`` under uvicorn. Honours the
``--port`` / ``--host`` flags (or ``WEB_BRIDGE_PORT`` / ``WEB_BRIDGE_HOST``
env vars) so deployment containers can override defaults without code
changes.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

# Make the sibling modules importable when run via ``python -m``.
_HERE = Path(__file__).resolve().parent
_BRIDGES = _HERE.parent
_REPO_ROOT = _BRIDGES.parent
for p in (str(_HERE), str(_BRIDGES), str(_REPO_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default=os.getenv("WEB_BRIDGE_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int,
                        default=int(os.getenv("WEB_BRIDGE_PORT", "8088")))
    parser.add_argument("--domain", type=int,
                        help="Override SPATIALDDS_DDS_DOMAIN (the bridge "
                              "uses this env var on startup)")
    args = parser.parse_args()

    if args.domain is not None:
        os.environ["SPATIALDDS_DDS_DOMAIN"] = str(args.domain)

    import uvicorn
    uvicorn.run(
        "bridges.web_bridge.server:app",
        host=args.host,
        port=args.port,
        reload=False,
        log_level="info",
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
