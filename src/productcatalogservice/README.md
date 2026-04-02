# Product Catalog Service

The Product Catalog Service product information to other microservices via gRPC.
It reads product data from products.json and runs on port 3550 by default.

## Building Locally

The Product Catalog Service requires Go 1.23. To run it locally:
To install dependencies, run:

```sh
go mod download
```

To run the Product Catalog Service:

```sh
go run .
```

Expected Output

```sh
{"message":"starting grpc server at :3550","severity":"info"}
{"message":"successfully parsed product catalog json","severity":"info"}
```

We'll get expected output only in linux or macos. If you’re running on Windows, ignore SIGUSR1/SIGUSR2 signal references.

## Test using grpcurl

List services:

```sh
grpcurl -plaintext localhost:3550 list
```

List products:

```sh
grpcurl -plaintext localhost:3550 hipstershop.ProductCatalogService/ListProducts
```

You’ll get a JSON list of products from products.json.

## Building Docker

From this Product Catalog folder, run:

```sh
docker build -t productcatalogservice:latest .
```