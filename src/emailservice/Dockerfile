# Stage 1: Builder
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    gcc g++ musl-dev libffi-dev wget

WORKDIR /app

# Copy requirements and install dependencies to /install
COPY requirements.txt .
RUN pip install --upgrade pip setuptools==83.0.0 wheel
RUN pip install --prefix=/install -r requirements.txt



# Stage 2: Final minimal image
FROM python:3.11-alpine

WORKDIR /emailservice

# Install runtime dependencies for grpc-health-probe
RUN apk add --no-cache bash curl


# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY . .

# Enable unbuffered logging
ENV PYTHONUNBUFFERED=1

# Expose port
ENV PORT=8080
EXPOSE 8080

# Start server
ENTRYPOINT [ "python", "email_server.py" ]