# Loadgenerator Service

This service is responsible for **load testing** the microservices demo application using [Locust](https://locust.io/).
The **Load Generator** simulates real user behavior to test how the system performs under different traffic conditions.  

## Setup & Usage

Install Dependencies

```sh
pip install -r requirements.txt
```

Run Locust

```sh
locust -f locustfile.py --host=http://<target-service-url>
```
Example

```sh
locust -f locustfile.py --host=http://frontend:8080
```

## Building Docker

From this loadgenerator folder, run:

```sh
docker build -t loadgenerator:latest .
```