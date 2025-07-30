import os
import uuid
import shutil
import logging
import pathlib

from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks, Request, status
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.middleware.cors import CORSMiddleware

from spleeter.separator import Separator

# Paths
HOME_DIR = pathlib.Path(__file__).parent.resolve()
OUTPUT_BASE = HOME_DIR / "output"

# Ensure that the output directory exists before mounting
os.makedirs(OUTPUT_BASE, exist_ok=True)

# FastAPI app
app = FastAPI()

# CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount static output directory at /app
app.mount(
    "/app",
    StaticFiles(directory=str(OUTPUT_BASE), html=False),
    name="output_files",
)

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# In-memory task status
processing_status = {}

def process_audio_background(file_path: str, task_id: str):
    """Run Spleeter and organize outputs, then clean up the upload."""
    try:
        basename = pathlib.Path(file_path).stem
        safe_basename = basename.lower()
        out_dir = OUTPUT_BASE / safe_basename

        # Separate stems
        separator = Separator("spleeter:2stems")
        separator.separate_to_file(file_path, str(OUTPUT_BASE))

        # After separation, Spleeter creates a folder named `basename`
        orig_dir = OUTPUT_BASE / basename
        if orig_dir.exists() and orig_dir != out_dir:
            if out_dir.exists():
                shutil.rmtree(out_dir)
            orig_dir.rename(out_dir)
            logger.info(f"Renamed {orig_dir} → {out_dir}")

        # Mark complete
        processing_status[task_id] = {
            "status": "completed",
            "safe_basename": safe_basename,
            "downloads": {
                "vocals": f"{safe_basename}/vocals.wav",
                "accompaniment": f"{safe_basename}/accompaniment.wav",
            },
        }
        logger.info(f"Task {task_id} completed")

        # Clean up original upload
        try:
            os.remove(file_path)
            logger.info(f"Removed upload: {file_path}")
        except Exception as e:
            logger.error(f"Cleanup error for {file_path}: {e}")

    except Exception as e:
        logger.exception(f"Background processing failed ({task_id}): {e}")
        processing_status[task_id] = {"status": "error", "message": str(e)}


@app.post("/process-audio/")
async def process_audio(
    request: Request,
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
):
    """
    Save the uploaded file, kick off Spleeter in the background,
    and return task info with download URLs.
    """
    try:
        # Save upload to disk
        upload_path = HOME_DIR / audio_file.filename
        with open(upload_path, "wb") as f:
            f.write(await audio_file.read())
        logger.info(f"Saved upload to {upload_path}")

        # Initialize task
        task_id = str(uuid.uuid4())
        processing_status[task_id] = {"status": "processing"}

        # Launch background processing
        background_tasks.add_task(process_audio_background, str(upload_path), task_id)

        # Build URLs (they'll be valid once processing completes)
        status_url = request.url_for("get_status", task_id=task_id)
        downloads = {
            "vocals": request.url_for("output_files", path=f"{audio_file.filename.rsplit('.',1)[0].lower()}/vocals.wav"),
            "accompaniment": request.url_for("output_files", path=f"{audio_file.filename.rsplit('.',1)[0].lower()}/accompaniment.wav"),
            "all": request.url_for("download_all", task_id=task_id),
        }

        return {
            "message": "Processing started",
            "task_id": task_id,
            "status_url": status_url,
            "downloads": downloads,
        }

    except Exception as e:
        logger.error(f"/process-audio error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/status/{task_id}")
def get_status(task_id: str):
    """Check background-job status."""
    info = processing_status.get(task_id)
    if not info:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    return info


@app.get("/download/{task_id}/all")
def download_all(task_id: str):
    """
    Zip up both stems for a completed task and return a single download.
    """
    info = processing_status.get(task_id)
    if not info:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Task not found")
    if info.get("status") != "completed":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Task not completed yet")

    safe_basename = info["safe_basename"]
    stem_dir = OUTPUT_BASE / safe_basename
    if not stem_dir.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Output files missing")

    # Prepare zip archive
    zip_path = OUTPUT_BASE / f"{safe_basename}_stems.zip"
    # Remove old zip if exists
    if zip_path.exists():
        zip_path.unlink()
    shutil.make_archive(str(zip_path.with_suffix('')), 'zip', stem_dir)

    # Stream the zip file
    return FileResponse(
        path=str(zip_path),
        filename=f"{safe_basename}_stems.zip",
        media_type="application/zip"
    )


@app.get("/ping")
def ping():
    return {"status": "alive"}


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8001)
