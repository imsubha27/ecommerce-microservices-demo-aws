# Shipping Service

The Shipping Service provides shipping quotes and shipment tracking information to other microservices via gRPC.
It calculates shipping costs based on item count and generates tracking IDs. By default, it listens on port 50051.

## Building Locally

The Shipping Service requires Go 1.23 (or higher).  
To install dependencies, run:
```sh
go mod download
```

To build and run the Shipping Service:
```sh
go build -o shippingservice.exe 
.\shippingservice.exe 
```

Expected Output
```sh
{"message":"Tracing enabled, but temporarily unavailable","severity":"info"}
{"message":"Shipping Service listening on port :50051","severity":"info"}
```

## Unit Testing

Basic unit tests to validate its core logic, such as shipping quote calculation and tracking ID generation.
```sh
go test .
```

Expected Output
```sh
ok      github.com/GoogleCloudPlatform/microservices-demo/src/shippingservice   0.003s
```

## Building Docker

From this Shipping Service folder, run:
```sh
docker build -t shippingservice:latest .
```

Then start the container:
```sh
docker run -p 50051:50051 shippingservice:latest
```