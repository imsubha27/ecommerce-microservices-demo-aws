# Stage 1: Builder
FROM python:3.11-alpine AS builder

# Install build dependencies
RUN apk add --no-cache --virtual .build-deps \
    gcc g++ musl-dev libffi-dev wget

WORKDIR /app

# Copy requirements and install dependencies to /install
COPY shoppingassistantservice/requirements.txt .
RUN pip install --upgrade pip
RUN pip install --prefix=/install -r requirements.txt



# Stage 2: Final minimal image
FROM python:3.11-alpine

WORKDIR /shoppingassistantservice

# Install runtime dependencies for grpc-health-probe
RUN apk add --no-cache bash curl

# Download gRPC health probe for Kubernetes health checks
ENV GRPC_HEALTH_PROBE_VERSION=v0.4.18
RUN wget -qO /bin/grpc_health_probe https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64 && \
    chmod +x /bin/grpc_health_probe

# Copy installed Python packages from builder
COPY --from=builder /install /usr/local

# Copy application code
COPY shoppingassistantservice/ . 

# Copy products.json from productcatalogservice, so that seeder can find the file
COPY productcatalogservice/products.json .

# Enable unbuffered logging
ENV PYTHONUNBUFFERED=1

# Expose port
ENV PORT=8090
EXPOSE 8090

# Start server
ENTRYPOINT ["python", "shoppingassistantservice.py"]

# Docker Build Command:
# docker build -t ecommerce/shoppingassistantservice:latest -f src/shoppingassistantservice/Dockerfile src/