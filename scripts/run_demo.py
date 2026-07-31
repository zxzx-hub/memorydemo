"""Foundation-stage demo: verify liveness and dependency readiness."""

import argparse

import httpx


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    args = parser.parse_args()

    with httpx.Client(base_url=args.base_url, timeout=5) as client:
        health = client.get("/health")
        health.raise_for_status()
        print("health:", health.json())

        readiness = client.get("/ready")
        print("ready:", readiness.status_code, readiness.json())


if __name__ == "__main__":
    main()
