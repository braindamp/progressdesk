"""ask_laya -- ask CLEANING_LAYA one decision and get a probability back.

A decision is a *named port*: a question, and the probability at or above which
the answer is yes. The ports live in ports.json beside this file so they can be
steered without editing code.

She is a decision model. She is handed a state and a typed question, and she
returns a number. She generates nothing, so there is no text to parse and no
format for her to disobey. Callers that need words must go through a role that
writes them, not through this.

Two ways in:

    from ask_laya import ask, decided
    decided("change", visp_text)

    python ask_laya.py change --file VISPs/proposal.md
    python ask_laya.py serve --port 8792

The service form exists so a program that does not share this directory -- and
progressDesk in particular -- can ask without importing from an arbitrary path,
and without growing a dependency.
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
PORTS_FILE = HERE / "ports.json"

# Where the model is served. The decision service that hosts the model is a
# separate thing from this one; this is the vocabulary, that is the weights.
DEFAULT_ENDPOINT = os.environ.get(
    "ASK_LAYA_ENDPOINT", "http://127.0.0.1:8000/v1/systemone"
)
TIMEOUT = 30


@dataclass(frozen=True)
class Decision:
    """One answer. `yes` is the port's threshold applied to the probability."""

    port: str
    probability: float
    threshold: float
    workshop: bool
    question: str

    @property
    def yes(self) -> bool:
        return self.probability >= self.threshold

    def to_dict(self) -> dict:
        return {
            "port": self.port,
            "probability": round(self.probability, 4),
            "threshold": self.threshold,
            "workshop": self.workshop,
            "question": self.question,
            "yes": self.yes,
        }


class PortError(ValueError):
    """A decision was asked that is not configured."""


class Unreachable(RuntimeError):
    """Nobody answered. Not a low probability -- the absence of one."""


def load_ports(path: Path = PORTS_FILE) -> dict[str, Decision]:
    table = json.loads(Path(path).read_text(encoding="utf-8")).get("ports") or {}
    if not isinstance(table, dict) or not table:
        raise PortError(f"{path} names no ports")
    out: dict[str, Decision] = {}
    for name, spec in table.items():
        question, threshold = spec.get("question"), spec.get("threshold")
        if not isinstance(question, str) or not question.strip():
            raise PortError(f"port {name!r} needs a question")
        if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
            raise PortError(f"port {name!r} needs a numeric threshold")
        out[name] = Decision(
            port=name, question=question, threshold=float(threshold),
            workshop=bool(spec.get("workshop", False)), probability=0.0,
        )
    return out


PORTS = load_ports()


def ask(port: str, state: str, *, endpoint: str = DEFAULT_ENDPOINT) -> Decision:
    """Ask one configured question about one state. Raises if nobody answered."""
    if port not in PORTS:
        raise PortError(f"no decision port named {port!r}")
    spec = PORTS[port]
    body = json.dumps({
        "state": state,
        "questions": {port: {"type": "noul", "instructions": spec.question}},
    }).encode("utf-8")
    request = urllib.request.Request(
        endpoint, data=body, headers={"Content-Type": "application/json"}, method="POST"
    )
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            payload = json.loads(response.read().decode("utf-8"))
        probability = float(payload["answers"][port]["noul"])
    except (urllib.error.URLError, OSError, KeyError, ValueError) as exc:
        raise Unreachable(f"{port}: nobody answered ({exc})") from exc
    return Decision(
        port=port, question=spec.question, threshold=spec.threshold,
        workshop=spec.workshop, probability=probability,
    )


def decided(port: str, state: str, *, endpoint: str = DEFAULT_ENDPOINT) -> bool:
    """`ask`, reduced to the answer the port's threshold gives."""
    return ask(port, state, endpoint=endpoint).yes


def _serve(host: str, port: int) -> None:
    class Handler(BaseHTTPRequestHandler):
        def do_POST(self) -> None:  # noqa: N802
            length = int(self.headers.get("Content-Length", 0))
            try:
                body = json.loads(self.rfile.read(length) or b"{}")
                answer = ask(str(body["port"]), str(body["state"]))
            except (KeyError, ValueError) as exc:
                self._reply({"error": str(exc)}, 400)
            except Unreachable as exc:
                self._reply({"error": str(exc)}, 503)
            else:
                self._reply(answer.to_dict())

        def do_GET(self) -> None:  # noqa: N802
            self._reply({
                "service": "ask_laya",
                "ports": {n: p.to_dict() for n, p in PORTS.items()},
            })

        def _reply(self, payload: dict, code: int = 200) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *_: object) -> None:
            pass

    print(f"ask_laya on http://{host}:{port}  ports: {', '.join(sorted(PORTS))}", flush=True)
    HTTPServer((host, port), Handler).serve_forever()


if __name__ == "__main__":
    argv = sys.argv[1:]
    if argv and argv[0] == "serve":
        _serve(argv[1] if len(argv) > 1 else "127.0.0.1", int(argv[2]) if len(argv) > 2 else 8792)
    elif argv:
        text = (
            Path(argv[1]).read_text(encoding="utf-8") if len(argv) > 1 and Path(argv[1]).exists()
            else " ".join(argv[1:])
        )
        result = ask(argv[0], text)
        print(json.dumps(result.to_dict(), indent=2))
    else:
        print(__doc__)