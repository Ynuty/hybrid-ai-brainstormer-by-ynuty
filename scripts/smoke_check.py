"""Quick smoke test against a running API (default http://127.0.0.1:8765)."""

import io
import json
import sys
import urllib.error
import urllib.request

BASE = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8765"


def get(path: str) -> dict:
    with urllib.request.urlopen(f"{BASE}{path}", timeout=10) as resp:
        return json.loads(resp.read().decode())


def post_json(path: str, payload: dict) -> dict:
    data = json.dumps(payload).encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def post_multipart(path: str, filename: str, content: bytes) -> dict:
    boundary = "----smokeboundary"
    body = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="file"; filename="{filename}"\r\n'
        f"Content-Type: application/octet-stream\r\n\r\n"
    ).encode() + content + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        f"{BASE}{path}",
        data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        return json.loads(resp.read().decode())


def main() -> int:
    errors: list[str] = []

    try:
        health = get("/health")
        print(f"GET /health -> status={health.get('status')}, types={len(health.get('supported_context_types', []))}")
        if not health.get("supported_context_types"):
            errors.append("supported_context_types empty")
    except Exception as exc:
        errors.append(f"/health: {exc}")

    try:
        extracted = post_multipart("/context/extract", "smoke.txt", b"smoke test content")
        text = extracted.get("text", "")
        print(f"POST /context/extract -> text_len={len(text)}")
        if "smoke test" not in text:
            errors.append("extract text mismatch")
    except Exception as exc:
        errors.append(f"/context/extract: {exc}")

    try:
        imported = post_json(
            "/context/import",
            {"urls": [], "youtube_urls": ["https://www.youtube.com/watch?v=notvalid12345"]},
        )
        print(f"POST /context/import -> sources={len(imported.get('sources', []))}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()[:200]
        errors.append(f"/context/import HTTP {exc.code}: {body}")
    except Exception as exc:
        errors.append(f"/context/import: {exc}")

    if errors:
        print("FAILURES:")
        for item in errors:
            print(" -", item)
        return 1

    print("Smoke check OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
