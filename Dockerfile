# Multi-stage build: node frontend → python backend
# Usage: docker build -t sinch-pa . && docker run -p 9002:9002 sinch-pa

# ── Stage 1: Build frontend ──────────────────────────────────────────────────
FROM node:20-alpine AS frontend-build

WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci --ignore-scripts
COPY frontend/ ./
RUN npm run build

# ── Stage 2: Python runtime ──────────────────────────────────────────────────
FROM python:3.12-slim AS runtime

WORKDIR /app

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Install Python dependencies
COPY pyproject.toml uv.lock* ./
RUN uv sync --frozen --no-dev

# Copy backend code
COPY backend/ ./backend/
COPY config/ ./config/

# Copy built frontend (served by FastAPI or reverse proxy)
COPY --from=frontend-build /app/frontend/dist ./frontend/dist

# Create data directories
RUN mkdir -p data/domains

# Expose port
EXPOSE 9002

# Run with uvicorn
CMD ["uv", "run", "uvicorn", "backend.main:app", "--host", "0.0.0.0", "--port", "9002"]
