from flask import Flask, request, jsonify
from prometheus_flask_exporter import PrometheusMetrics
import psycopg2
import psycopg2.extras
import jwt
import os
import datetime
import time
import json
import logging
import boto3

app = Flask(__name__)
metrics = PrometheusMetrics(app)

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
log = logging.getLogger(__name__)

# =============================================================
# CONFIG
# Local:  reads flat env vars (ORDER_DB_HOST, etc.)
# K8s:    USE_SECRETS_MANAGER=true, ORDER_DB_SECRET_NAME set
#         boto3 fetches creds from AWS Secrets Manager via IRSA
# =============================================================

USE_SECRETS_MANAGER  = os.getenv("USE_SECRETS_MANAGER", "false").lower() == "true"
AWS_REGION           = os.getenv("AWS_REGION", "ap-south-1")
ORDER_DB_SECRET_NAME = os.getenv("ORDER_DB_SECRET_NAME", "")
JWT_SECRET           = os.getenv("JWT_SECRET")  # shared with authservice


def get_db_config():
    """Return DB connection kwargs. Fetches from Secrets Manager on k8s."""
    if USE_SECRETS_MANAGER:
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        secret = json.loads(
            client.get_secret_value(SecretId=ORDER_DB_SECRET_NAME)["SecretString"]
        )
        return {
            "host":     secret["host"],
            "port":     int(secret.get("port", 5432)),
            "dbname":   secret["dbname"],
            "user":     secret["username"],
            "password": secret["password"],
        }
    else:
        return {
            "host":     os.getenv("ORDER_DB_HOST"),
            "port":     int(os.getenv("ORDER_DB_PORT", 5432)),
            "dbname":   os.getenv("ORDER_DB_NAME"),
            "user":     os.getenv("ORDER_DB_USER"),
            "password": os.getenv("ORDER_DB_PASSWORD"),
        }


def get_db():
    return psycopg2.connect(**get_db_config())


# =============================================================
# DB INIT — orders table only
# =============================================================

def init_db():
    for i in range(10):
        try:
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id            SERIAL PRIMARY KEY,
                    user_id       INT NOT NULL,
                    order_id      VARCHAR(100) NOT NULL,
                    tracking_id   VARCHAR(100),
                    total_paid    VARCHAR(50),
                    currency      VARCHAR(10),
                    items         JSONB,
                    shipping_addr JSONB,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            # Index for fast user order lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)
            """)
            conn.commit()
            cur.close()
            conn.close()
            log.info("Order DB initialized successfully")
            return
        except Exception as e:
            log.warning(f"Order DB not ready, retrying ({i}/10): {e}")
            time.sleep(3)
    raise Exception("Could not connect to order DB after 10 retries")


# =============================================================
# TOKEN HELPER
# orderservice verifies the JWT itself using the shared secret
# so it doesn't need to call authservice on every request
# =============================================================

def verify_token(request):
    """Returns user_id from JWT or raises ValueError."""
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        raise ValueError("no token")
    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    return payload["user_id"]


# =============================================================
# HEALTH
# =============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================
# SAVE ORDER  POST /orders
# Called by frontend after a successful checkout
# =============================================================

@app.route("/orders", methods=["POST"])
def save_order():
    try:
        user_id = verify_token(request)
    except (ValueError, jwt.InvalidTokenError) as e:
        return jsonify({"error": str(e)}), 401

    data          = request.get_json(force=True)
    order_id      = data.get("order_id", "")
    tracking_id   = data.get("tracking_id", "")
    total_paid    = data.get("total_paid", "")
    currency      = data.get("currency", "USD")
    items         = data.get("items", [])
    shipping_addr = data.get("shipping_addr", {})

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders
                (user_id, order_id, tracking_id, total_paid, currency, items, shipping_addr)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
            """,
            (user_id, order_id, tracking_id, total_paid, currency,
             json.dumps(items), json.dumps(shipping_addr)),
        )
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"Save order error: {e}")
        return jsonify({"error": "internal error"}), 500

    log.info(f"Order saved — user_id={user_id} order_id={order_id}")
    return jsonify({"message": "order saved"}), 201


# =============================================================
# GET ORDERS  GET /orders
# Returns order history for the authenticated user
# =============================================================

@app.route("/orders", methods=["GET"])
def get_orders():
    try:
        user_id = verify_token(request)
    except (ValueError, jwt.InvalidTokenError) as e:
        return jsonify({"error": str(e)}), 401

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT order_id, tracking_id, total_paid, currency,
                   items, shipping_addr, created_at
            FROM   orders
            WHERE  user_id = %s
            ORDER  BY created_at DESC
            """,
            (user_id,),
        )
        rows = cur.fetchall()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"Get orders error: {e}")
        return jsonify({"error": "internal error"}), 500

    orders = []
    for row in rows:
        orders.append({
            "order_id":      row["order_id"],
            "tracking_id":   row["tracking_id"],
            "total_paid":    row["total_paid"],
            "currency":      row["currency"],
            "items":         row["items"] if isinstance(row["items"], list) else [],
            "shipping_addr": row["shipping_addr"] if isinstance(row["shipping_addr"], dict) else {},
            "created_at":    row["created_at"].strftime("%d %b %Y, %H:%M"),
        })

    return jsonify({"orders": orders}), 200


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8082))
    init_db()
    app.run(host="0.0.0.0", port=port)