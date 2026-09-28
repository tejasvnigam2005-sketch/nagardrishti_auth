import sys
from pathlib import Path

# Ensure backend root is on sys.path for serverless runtimes
sys.path.insert(0, str(Path(__file__).resolve().parent))

from fastapi import FastAPI, HTTPException, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from app.config import CORS_ORIGINS, UPLOAD_DIR
from app.routers import complaints_router, dashboard_router, departments_router

app = FastAPI(
    title="NagarDrishti AI Authority Backend",
    description="Municipal Civic Intelligence REST API for NagarDrishti AI Authority Portal.",
    version="1.0.0",
)

# Cross-Origin Resource Sharing configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS if CORS_ORIGINS else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Ensure local upload directory exists
upload_path = Path(UPLOAD_DIR)
try:
    upload_path.mkdir(parents=True, exist_ok=True)
except OSError:
    upload_path = Path("/tmp/uploads")
    upload_path.mkdir(parents=True, exist_ok=True)

# Mount local upload directory for static image serving (matching user site)
app.mount("/storage", StaticFiles(directory=str(upload_path)), name="storage")

# Mount API Routers
app.include_router(complaints_router)
app.include_router(dashboard_router)
app.include_router(departments_router)


@app.get("/api/complaints/image/{filename}")
def get_complaint_image(filename: str):
    """Serve complaint photograph directly from upload storage."""
    file_path = upload_path / filename
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image not found.")
    ext = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
    }
    media_type = media_types.get(ext, "image/jpeg")
    with open(file_path, "rb") as f:
        return Response(content=f.read(), media_type=media_type)


@app.get("/")
def root():
    return {
        "service": "NagarDrishti AI Authority Backend",
        "status": "online",
        "version": "1.0.0",
        "docs_url": "/docs",
        "user_site_connected": True,
    }


@app.get("/health")
def health_check():
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=True)

