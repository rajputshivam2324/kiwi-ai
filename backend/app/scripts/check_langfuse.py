"""Run from backend: python -m app.scripts.check_langfuse (never prints keys)."""
from app.services.observability import get_langfuse, observation, shutdown_langfuse


def main():
    client = get_langfuse()
    if client is None:
        raise SystemExit("Tracing is disabled or credentials are missing; check LANGFUSE_* settings")
    try:
        if not client.auth_check():
            raise SystemExit("Langfuse authentication failed")
        with observation("kiwi.integration-check", metadata={"documents": 0}):
            pass
        client.flush()
        print("Langfuse authentication succeeded; integration-check trace submitted")
    finally:
        shutdown_langfuse()


if __name__ == "__main__":
    main()
