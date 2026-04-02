# Stage 1: Build stage to install dependencies
FROM python:3.11-alpine AS build

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    gcc g++ musl-dev libffi-dev wget

WORKDIR /app

# Copy requirements and install dependencies to /install
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --prefix=/install -r requirements.txt



# Stage 2: Final stage
FROM python:3.11-alpine

WORKDIR /loadgenerator

# Copy installed Python packages from build stage
COPY --from=build /install /usr/local

# Copy application code
COPY locustfile.py .

COPY start.sh .
RUN chmod +x start.sh

# Enable unbuffered logging
ENV PYTHONUNBUFFERED=1

# Enable gevent support
ENV GEVENT_SUPPORT=True

# Expose port
ENV PORT=8090

EXPOSE 8090

# Default command (runs Locust web UI)
# CMD ["locust", "-f", "locustfile.py", "--host=http://frontend:8080"]

# Run Locust headlessly using FRONTEND_ADDR as target host and USERS for load level
ENTRYPOINT ["./start.sh"]
