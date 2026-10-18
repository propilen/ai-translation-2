"""UTF-8 JSON Lines worker. stdout is reserved for protocol responses."""

from __future__ import annotations

import json
import sys
import traceback
from contextlib import redirect_stdout
from pathlib import Path

# Source runs from a subdirectory; compiled imports stay inside the distribution.
if "__compiled__" not in globals():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from protocol import ProtocolError, WorkerProtocol  # noqa: E402


def main() -> int:
    sys.stdin.reconfigure(encoding="utf-8", errors="replace")
    sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    protocol = WorkerProtocol()
    for line in sys.stdin:
        request_id = None
        try:
            request = json.loads(line)
            if isinstance(request, dict) and isinstance(request.get("id"), (str, int)) and not isinstance(request.get("id"), bool):
                request_id = request["id"]
            with redirect_stdout(sys.stderr):
                response, shutdown = protocol.dispatch(request)
        except json.JSONDecodeError as error:
            response, shutdown = {"id": None, "ok": False, "error": {"code": "INVALID_JSON", "message": str(error)}}, False
        except ProtocolError as error:
            response, shutdown = {"id": request_id, "ok": False, "error": {"code": error.code, "message": str(error)}}, False
        except Exception:
            traceback.print_exc(file=sys.stderr)
            response, shutdown = {"id": request_id, "ok": False, "error": {"code": "INTERNAL_ERROR", "message": "Internal NLP worker error"}}, False
        sys.stdout.write(json.dumps(response, ensure_ascii=False, separators=(",", ":")) + "\n")
        sys.stdout.flush()
        if shutdown:
            return 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
