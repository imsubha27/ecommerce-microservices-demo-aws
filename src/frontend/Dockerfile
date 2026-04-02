# Stage 1: Build the Go binary
FROM golang:1.23.0-alpine AS build

WORKDIR /app

# Install git (required for Go modules that come from gitHub or other sources)
RUN apk add --no-cache git

COPY go.mod go.sum ./

# Download all Go dependencies
RUN go mod download

COPY . .

# Optional: Skaffold uses this variable to inject debugging flags during dev builds
ARG SKAFFOLD_GO_GCFLAGS

# Build the Go application binary
# - 'CGO_ENABLED=0' makes the binary fully static (no libc dependency)
# - '-o frontendservice' sets the output binary name
RUN go build -gcflags="$SKAFFOLD_GO_GCFLAGS" -o frontendservice .



# Stage 2: Runtime image
FROM alpine:latest

WORKDIR /app

RUN apk add --no-cache ca-certificates curl bash

# Download gRPC health probe for Kubernetes health checks
ENV GRPC_HEALTH_PROBE_VERSION=v0.4.18
RUN wget -qO /bin/grpc_health_probe https://github.com/grpc-ecosystem/grpc-health-probe/releases/download/${GRPC_HEALTH_PROBE_VERSION}/grpc_health_probe-linux-amd64 && \
    chmod +x /bin/grpc_health_probe

# Copy the compiled binary from the 'build' stage
COPY --from=build /app/frontendservice .

# Copy templates and static files
COPY ./templates ./templates
COPY ./static ./static

# The gRPC server listens on port 3550
ENV PORT=8080

# Disable GCP profiler for local or non-GCP environments
ENV DISABLE_PROFILER=1

# GOTRACEBACK=single shows a stack trace if the app crashes
# You can set 'all' for full goroutine dump (useful in debugging)
ENV GOTRACEBACK=single

EXPOSE 8080

ENTRYPOINT ["./frontendservice"]