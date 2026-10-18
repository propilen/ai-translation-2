import os
from pathlib import Path

import uvicorn


if __name__ == "__main__":
    project_root = Path(__file__).resolve().parent
    os.chdir(project_root)
    uvicorn.run(
        "backend.app:app",
        host=os.getenv("LINGUAFLOW_HOST", "127.0.0.1"),
        port=int(os.getenv("LINGUAFLOW_PORT", "8000")),
        reload=True,
        reload_dirs=[str(project_root)],
    )
