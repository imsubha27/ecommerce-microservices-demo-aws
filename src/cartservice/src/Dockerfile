# Stage 1: Builder
# restore dependencies, trim, and publish a self-contained & single-file binary.
FROM --platform=$BUILDPLATFORM mcr.microsoft.com/dotnet/sdk:9.0.101-noble AS builder

# TARGETARCH allows multi-architecture builds (amd64, arm64, etc.)
ARG TARGETARCH

WORKDIR /app

# Copy csproj first for layer caching (faster builds)
COPY cartservice.csproj .

# Restore NuGet packages for the correct CPU architecture
RUN dotnet restore cartservice.csproj -a $TARGETARCH

# Copy remaining source code
COPY . .

# Publish the app:
# - SingleFile: produce one bundled executable
# - self-contained: includes runtime inside the binary
# - PublishTrimmed: remove unused IL to reduce size
# - TrimMode=full: aggressive trimming (smallest possible)
# - OUTPUT at /cartservice
RUN dotnet publish cartservice.csproj \
    -p:PublishSingleFile=true \
    --self-contained true \
    -p:PublishTrimmed=true \
    -p:TrimMode=full \
    -a $TARGETARCH \
    -c release \
    -o /cartservice





# Stage 2: Final minimal image
FROM mcr.microsoft.com/dotnet/runtime-deps:9.0.1-noble-chiseled

WORKDIR /app

# Copy the published, trimmed, single-file output
COPY --from=builder /cartservice .

EXPOSE 7070

# Disable diagnostics to reduce overhead & attack surface
# Set ASP.NET port to 7070
ENV DOTNET_EnableDiagnostics=0 \
    ASPNETCORE_HTTP_PORTS=7070

# Run container as non-root user
USER 1000

# Start the app
ENTRYPOINT ["/app/cartservice"]