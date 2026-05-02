FROM python:3.11-alpine AS builder

RUN apk add --no-cache --virtual .build-deps \
    gcc g++ musl-dev libffi-dev wget

WORKDIR /app
COPY requirements.txt .
RUN pip install --upgrade pip
RUN pip install --prefix=/install -r requirements.txt


FROM python:3.11-alpine

WORKDIR /orderservice

RUN apk add --no-cache bash curl

COPY --from=builder /install /usr/local
COPY . .

ENV PYTHONUNBUFFERED=1
ENV PORT=8082
EXPOSE 8082

ENTRYPOINT ["python", "order_server.py"]