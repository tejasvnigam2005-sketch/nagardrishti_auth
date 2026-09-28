import os
from pathlib import Path

PORT = int(os.getenv("PORT", "8000"))
HOST = os.getenv("HOST", "0.0.0.0")
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
CORS_ORIGINS = [
    origin.strip()
    for origin in os.getenv(
        "CORS_ORIGINS",
        "*,http://localhost:5173,http://localhost:5174,http://127.0.0.1:5173,http://127.0.0.1:5174"
    ).split(",")
    if origin.strip()
]

# Connection to user site (NagarDrishti-AI)
USER_SITE_REPO_PATH = os.getenv(
    "USER_SITE_REPO_PATH",
    "/Users/tejasvnigam/nagardrishti/NagarDrishti-AI"
)
USER_SITE_API_URL = os.getenv("USER_SITE_API_URL", "").rstrip("/")

# Shared database JSON path (connecting authority portal directly to user site data)
SHARED_DB_PATH = os.getenv(
    "SHARED_DB_PATH",
    os.path.join(USER_SITE_REPO_PATH, "backend", "data", "complaints_db.json")
    if os.path.exists(USER_SITE_REPO_PATH)
    else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "complaints_db.json")
)

LOCAL_BACKUP_DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "complaints_db.json"
)

# Uploads directory from user site
UPLOAD_DIR = os.getenv(
    "UPLOAD_DIR",
    os.path.join(USER_SITE_REPO_PATH, "backend", "uploads")
    if os.path.exists(USER_SITE_REPO_PATH)
    else os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads")
)

