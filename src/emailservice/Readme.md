# Email Service 
This microservice is responsible for sending order confirmation emails in the microservices demo application.  

## Running Locally

The Email Service requires Python 3.11. to build and run locally.

To install dependencies, run:

```sh
pip install -r requirements.txt
```

To run the Email Service:

```sh
python email_server.py
```

Expected Output

```sh
{"severity": "INFO", "name": "emailservice-server", "message": "listening on port: 8080"}
```

## Test the service with client

Open a new window, navigate to emailservice folder, and run (keep the email_server running):

```sh
python email_client.py
```

Expected Output

```sh
{"severity": "INFO", "name": "emailservice-client", "message": "Client for email service."}
```

## Building Docker

From this recommendationservice folder, run:

```sh
docker build -t email-service:latest .
```