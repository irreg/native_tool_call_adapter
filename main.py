import os

import uvicorn

TOOL_CALL_ADAPTER_HOST = os.getenv("TOOL_CALL_ADAPTER_HOST", "0.0.0.0")
TOOL_CALL_ADAPTER_PORT = int(os.getenv("TOOL_CALL_ADAPTER_PORT", "8000"))


def main():
    uvicorn.run(
        "app:app",
        host=TOOL_CALL_ADAPTER_HOST,
        port=TOOL_CALL_ADAPTER_PORT,
        log_level="info",
    )


if __name__ == "__main__":
    main()
