# Checkout Service

The Checkout Service handles the end-to-end checkout process by communicating with multiple backend services via gRPC.
It retrieves cart items, calculates total prices (including currency conversion and shipping), processes payments, and sends order confirmations. By default, it listens on port 5050.

## Building Locally

The Checkout Service requires Go 1.23 (or higher). 
To install dependencies, run:
```sh
go mod download
```

To build and run the Checkout Service:
```sh
go build -o checkoutservice.exe
.\checkoutservice.exe
```

If you see an error about missing environment variables, set the following before running:
```sh
$env:PRODUCT_CATALOG_SERVICE_ADDR="localhost:3550"
$env:CART_SERVICE_ADDR="localhost:7070"
$env:CURRENCY_SERVICE_ADDR="localhost:7000"
$env:PAYMENT_SERVICE_ADDR="localhost:50051"
$env:SHIPPING_SERVICE_ADDR="localhost:50052"
$env:EMAIL_SERVICE_ADDR="localhost:8082"
```

Expected Output
```sh
{"message":"Tracing disabled.","severity":"info"}
{"message":"Profiling disabled.","severity":"info"}
{"message":"starting to listen on tcp: \"[::]:5050\"","severity":"info"}
```

## Unit Testing

Basic unit tests are available under the money package to validate money-related calculations and conversion logic.
```sh
go test .
```

Expected Output
```sh
ok      github.com/GoogleCloudPlatform/microservices-demo/src/checkoutservice/money   0.002s
```

## Building Docker

From this Checkout Service folder, run:
```sh
docker build -t checkoutservice:latest .
```

Then start the container:
```sh
docker run -p 5050:5050 checkoutservice:latest
```