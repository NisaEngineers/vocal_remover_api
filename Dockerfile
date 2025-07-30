
FROM python:3.9

# Install ffmpeg
RUN apt-get update && apt-get install -y ffmpeg && apt-get clean

# Set working directory
WORKDIR /app

# Copy requirements and install
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Create a dummy audio file (empty silence)
RUN ffmpeg -f lavfi -i anullsrc=r=44100:cl=mono -t 1 -q:a 9 -acodec libmp3lame dummy.mp3

# Force model downloads via dummy separation
RUN python3 -m spleeter separate -i dummy.mp3 -p spleeter:4stems -o out || true
RUN python3 -m spleeter separate -i dummy.mp3 -p spleeter:2stems -o out || true

# Clean up dummy data
RUN rm -rf out dummy.mp3

# Copy the full project
COPY . .

# Expose FastAPI port
EXPOSE 8000

# Start server
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]
