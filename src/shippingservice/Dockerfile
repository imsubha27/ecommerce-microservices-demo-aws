# Stage 1: Build the Go binary
FROM golang:1.24.3-alpine AS build

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
# - '-o shippingservice' sets the output binary name
RUN go build -gcflags="$SKAFFOLD_GO_GCFLAGS" -o shippingservice .



# Stage 2: Runtime image
FROM alpine:latest

RUN apk add --no-cache ca-certificates curl bash

WORKDIR /app

# Copy the compiled binary from the 'build' stage
COPY --from=build /app/shippingservice .

# The gRPC server listens on port 50051
ENV PORT=50051

# Disable GCP profiler for local or non-GCP environments
ENV DISABLE_PROFILER=1

# GOTRACEBACK=single shows a stack trace if the app crashes
# You can set 'all' for full goroutine dump (useful in debugging)
ENV GOTRACEBACK=single

EXPOSE 50051

ENTRYPOINT ["./shippingservice"]