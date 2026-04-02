# Currency Service

The Currency Service provides currency conversion for the application using gRPC.
It reads exchange-rate data from data/currency_conversion.json and exposes a gRPC service.

By default, it runs on port 7000.

## Building Locally

The Currency Service requires Node.js 18+.
To install dependencies, run:

```sh
npm install
```

To run the Currency Service locally:

```sh
node index.js
```

Before running, you must set the service port.

```sh
export PORT=7000
export DISABLE_PROFILER=true  # prevents Google Cloud Profiler crash
```
Expected Output

```sh
{"severity":"info","message":"Profiler disabled."}
{"severity":"info","message":"Tracing disabled."}
{"severity":"info","message":"Starting gRPC server on port 7000..."}
{"severity":"info","message":"CurrencyService gRPC server started on port 7000"}
```

## Test using grpcurl

List available services:

```sh
grpcurl -plaintext localhost:7000 list
```

Convert currency:

```sh
grpcurl -plaintext -d '{ "from": "USD", "to": "INR", "amount": 10 }' \
  localhost:7000 hipstershop.CurrencyService/Convert
```

Expected response:

```sh
{
  "from": "USD",
  "to": "INR",
  "convertedAmount": 702.4
}
```
Values depend on your currency_conversion.json.

## Building Docker

From inside the currencyservice folder:

```sh
docker build -t currencyservice:latest .
```

To run the container:

```sh
docker run -p 50051:50051 currencyservice:latest
```