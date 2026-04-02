# Cart Service

CartService is a lightweight, high-performance shopping cart microservice written in .NET 9.
It uses Redis to store cart items and exposes a gRPC API.

Below is how you can build and run it using Docker.

## Building Locally

Restore dependencies:

```sh
dotnet restore
```

Build and run:

```sh
dotnet build
dotnet run
```

## Build the Docker Image

Make sure you are inside the folder where your Dockerfile and cartservice.csproj exist, then run,

```sh
docker build -t cartservice:latest .
```

## Run the Service

- Step 1: Start Redis

```sh
docker run -d --name redis -p 6379:6379 redis:7-alpine
```

- Step 2: Run CartService

```sh
docker run -p 7070:7070 -e REDIS_ADDR=host.docker.internal:6379 cartservice:latest
```
Your service is now running on port 7070.

Expected Output

```sh
info: Microsoft.Hosting.Lifetime[14]
      Now listening on: http://[::]:7070
info: cartservice.Startup[0]
      Connected to Redis at your-redis-host:6379
info: Microsoft.Hosting.Lifetime[0]
      Application started. Press Ctrl+C to shut down.
info: Microsoft.Hosting.Lifetime[0]
      Hosting environment: Production
info: Microsoft.Hosting.Lifetime[0]
      Content root path: /app
```

If you open: http://localhost:7070

You'll see..
```sh
An HTTP/1.x request was sent to an HTTP/2 only endpoint.
```

This is normal. CartService speaks gRPC, not HTTP.