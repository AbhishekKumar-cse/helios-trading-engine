"""Serve generated HTML reports only, on localhost; no DB/filesystem write routes."""

import html
import re
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "reports_out"


class Handler(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        if self.path == "/":
            links = [
                f'<li><a href="/{p.parent.name}/report.html">{html.escape(p.parent.name)}</a></li>'
                for p in sorted(ROOT.glob("*/report.html"))
            ]
            body = (
                "<h1>HELIOS registered alpha reports</h1>"
                "<p>BACKTEST research · hash-verified source evidence</p><ul>"
                + "".join(links)
                + "</ul>"
            ).encode()
        elif re.fullmatch(r"/[a-z][a-z0-9_]{2,63}/report\.html", self.path):
            path = ROOT / self.path.lstrip("/")
            if not path.is_file():
                self.send_error(404)
                return
            body = path.read_bytes()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)


if __name__ == "__main__":
    print("HELIOS alpha reports: http://localhost:8766", flush=True)
    ThreadingHTTPServer(("127.0.0.1", 8766), Handler).serve_forever()
