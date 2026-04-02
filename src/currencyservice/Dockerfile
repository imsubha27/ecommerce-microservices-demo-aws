# Stage 1: Builder
FROM node:20.18.1-alpine AS build

# Some packages (e.g. @google-cloud/profiler) require additional 
# dependencies for post-install scripts
RUN apk add --update --no-cache \
    python3 \
    make \
    g++

WORKDIR /app

# Copy package files
COPY package*.json ./

# Install production dependencies
RUN npm install --only=production



# Stage 2: Final minimal image
FROM alpine:latest

# Install Node.js runtime
RUN apk add --no-cache nodejs

WORKDIR /app

# Disable Google Cloud Profiler by default
# Enable it only if you are running on GCP and
# You want CPU/memory profiling for performance debugging
ENV DISABLE_PROFILER=1

COPY --from=build /app/node_modules ./node_modules
COPY . .

ENV PORT=7000
EXPOSE 7000

# Start server
ENTRYPOINT [ "node", "server.js" ]