from __future__ import annotations

import uvicorn

from ainovel_py.internal_api.settings import load_settings


def main() -> int:
    settings = load_settings()
    uvicorn.run("ainovel_py.internal_api.app:app", host=settings.host, port=settings.port, reload=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
