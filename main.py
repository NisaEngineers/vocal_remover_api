from fastapi import FastAPI, UploadFile, File, HTTPException, BackgroundTasks
from fastapi.responses import FileResponse
from fastapi.middleware.cors import CORSMiddleware

from spleeter.separator import Separator
import os
import logging
import pathlib

# FastAPI app
app = FastAPI()

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Constants
HOME_DIR = str(pathlib.Path(__file__).parent.resolve())
OUTPUT_BASE = os.path.join(HOME_DIR, "output")

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Utility to normalize Windows paths
def normalize_path(path: str) -> str:
    return path.replace("\\", "/")

class VocalRemover:
    def __init__(self, input_path: str, task: str = "spleeter:2stems"):
        self.input_path = input_path
        self.task = task
        self.separator = Separator(self.task)

    def separate_audio(self):
        """
        Separates audio using Spleeter into:
            output/<basename>/
                - vocals.wav
                - accompaniment.wav
        """
        os.makedirs(OUTPUT_BASE, exist_ok=True)
        self.separator.separate_to_file(self.input_path, OUTPUT_BASE)

    def run(self):
        self.separate_audio()
        logger.info("Separation completed")

@app.post("/process-audio/")
async def process_audio(
    background_tasks: BackgroundTasks,
    audio_file: UploadFile = File(...),
):
    """
    1. Save the uploaded file to HOME_DIR
    2. Launch Spleeter in background
    3. Return expected download URLs under output/<basename>/
    """
    try:
        # 1. Persist upload
        file_path = os.path.join(HOME_DIR, audio_file.filename)
        with open(file_path, "wb") as f:
            f.write(await audio_file.read())
        logger.info(f"Saved upload: {file_path}")

        # 2. Background separation
        background_tasks.add_task(VocalRemover(file_path).run)

        # 3. Compute download paths
        basename = os.path.splitext(os.path.basename(file_path))[0]
        rel_dir = normalize_path(f"output/{basename}")
        return {
            "message": "Uploaded. Separation is in progress.",
            "download_paths": [
                f"{rel_dir}/vocals.wav",
                f"{rel_dir}/accompaniment.wav"
            ]
        }

    except Exception as e:
        logger.error(f"Processing error: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/download/{full_path:path}")
async def download_file(full_path: str):
    """
    Only serve files under the `output/` directory.
    """
    # Prevent path traversal by enforcing prefix
    normalized = normalize_path(full_path)
    if not normalized.startswith("output/"):
        raise HTTPException(status_code=400, detail="Invalid file path")

    abs_path = os.path.abspath(os.path.join(HOME_DIR, normalized))
    allowed_base = os.path.abspath(OUTPUT_BASE)

    # Verify the resolved path is still under OUTPUT_BASE
    if not abs_path.startswith(allowed_base):
        raise HTTPException(status_code=400, detail="Invalid file path")

    if os.path.isfile(abs_path):
        return FileResponse(abs_path)
    else:
        raise HTTPException(status_code=404, detail="File not found")

@app.get("/ping")
def ping():
    return {"status": "alive"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000)