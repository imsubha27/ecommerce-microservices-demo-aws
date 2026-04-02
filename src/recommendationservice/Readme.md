# Recommendation Service

The Recommendation Service provides product recommendations based on input product IDs.
If no input product IDs are provided, it returns random recommendations.

## Building Locally

The Recommendation Service requires Python 3.11. To build and run locally:
To install dependencies, run:

```sh
pip install -r requirements.txt
```

To run the Recommendation Service:

```sh
export PRODUCT_CATALOG_SERVICE_ADDR="localhost:3550"

python recommendation_server.py
```

## Test the service with client

Open a new window, navigate to service folder, and run (keep the server running):

```sh
python client.py
```

Expected Output

```sh
Recommended product IDs: ['3', '5', '7', '8', '10']
```

If Product Catalog is not running, the client may fail. You can mock product IDs in recommendation_server.py for local testing.


## Building Docker

From this recommendationservice folder, run:

```sh
docker build -t recommendation-service:latest .
```