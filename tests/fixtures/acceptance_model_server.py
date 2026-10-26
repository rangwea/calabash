"""Loopback-only HTTPS model fixture. Never contacts real model providers."""

import argparse
import ipaddress
import json
import ssl
from datetime import UTC, datetime, timedelta
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID


def certificate(root):
    root.mkdir(parents=True, exist_ok=True)
    root.chmod(0o700)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name(
        [x509.NameAttribute(NameOID.COMMON_NAME, "Calabash Local Acceptance")]
    )
    now = datetime.now(UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - timedelta(minutes=1))
        .not_valid_after(now + timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=True, path_length=None), critical=True)
        .add_extension(
            x509.SubjectAlternativeName(
                [x509.IPAddress(ipaddress.ip_address("127.0.0.1"))]
            ),
            critical=False,
        )
        .sign(key, hashes.SHA256())
    )
    private = root / "server.key"
    private.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.PKCS8,
            serialization.NoEncryption(),
        )
    )
    private.chmod(0o600)
    public = root / "server.pem"
    public.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    return public, private


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_args):
        pass

    def send(self, status, body, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path == "/v1/models":
            self.send(200, b'{"data":[{"id":"acceptance-model"}]}')
        else:
            self.send(404, b"{}")

    def do_POST(self):
        size = int(self.headers.get("Content-Length", "0"))
        if size > 2_000_000 or self.path != "/v1/chat/completions":
            self.send(400, b"{}")
            return
        data = json.loads(self.rfile.read(size))
        if data.get("model") != "acceptance-model":
            self.send(400, b"{}")
            return
        # Fixed synthetic response; no prompt bodies or credentials are logged.
        packet = {
            "choices": [
                {
                    "delta": {
                        "content": "Local acceptance response. No external model was contacted."
                    }
                }
            ]
        }
        self.send(
            200,
            ("data: " + json.dumps(packet) + "\n\ndata: [DONE]\n\n").encode(),
            "text/event-stream",
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    public, private = certificate(args.root)
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(public, private)
    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    server.socket = context.wrap_socket(server.socket, server_side=True)
    print(
        json.dumps(
            {
                "url": f"https://127.0.0.1:{server.server_port}/v1",
                "certificate": str(public),
            }
        ),
        flush=True,
    )
    server.serve_forever()
