# Base Python Image
FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    LLM_PROVIDER=mock \
    HOST=0.0.0.0 \
    PORT=8000

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files (backend and frontend)
COPY backend/ ./backend/
COPY frontend/ ./frontend/

# Expose FastAPI application port
EXPOSE 8000

# Run FastAPI with uvicorn in production mode
CMD ["uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "8000"]
