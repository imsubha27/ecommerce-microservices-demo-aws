# Payment Service

The Payment Service handles mock payment authorization and charging requests over gRPC.
It loads its API definition from protobuf files under the proto/ directory and listens on port 50051 by default.

## Building Locally

The Payment Service requires Node.js 18+.
To install dependencies, run:

```sh
npm install
```

To run the Payment Service locally:

```sh
node index.js
```

Expected Output

```sh
{"severity":"info","message":"Profiler disabled."}
{"severity":"info","message":"Tracing disabled."}
{"severity":"info","message":"starting gRPC server on port 50051"}
```

Profiler will only work on Linux or macOS.
If you’re running on Windows, profiling is automatically disabled (ignore pprof-related logs).

## Test using grpcurl

List services:

```sh
grpcurl -plaintext localhost:50051 list
```

Invoke the Charge RPC:

```sh
grpcurl -plaintext -d '{}' localhost:50051 hipstershop.PaymentService/Charge
```

You should get a mock transaction response.

## Building Docker

From the Payment Service folder, run:

```sh
docker build -t paymentservice:latest .
```

To run the container:

```sh
docker run -p 50051:50051 paymentservice:latest
```