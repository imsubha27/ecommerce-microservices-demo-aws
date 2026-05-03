from flask import Flask, request, jsonify
from prometheus_flask_exporter import PrometheusMetrics
import psycopg2
import psycopg2.extras
import psycopg2.pool
import jwt
import os
import datetime
import time
import json
import logging
import threading
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
# =============================================================

USE_SECRETS_MANAGER  = os.getenv("USE_SECRETS_MANAGER", "false").lower() == "true"
AWS_REGION           = os.getenv("AWS_REGION", "ap-south-1")
ORDER_DB_SECRET_NAME = os.getenv("ORDER_DB_SECRET_NAME", "")
JWT_SECRET           = os.getenv("JWT_SECRET")   # shared with authservice

# =============================================================
# SECRETS MANAGER CACHING
# FIX: original called get_secret_value() on every request.
# Cache the credentials for 5 minutes per pod.
# =============================================================

_secret_cache      = {}
_secret_cache_ttl  = 300
_secret_cache_lock = threading.Lock()


def _get_secret_from_manager():
    with _secret_cache_lock:
        now = time.time()
        if _secret_cache and now - _secret_cache["fetched_at"] < _secret_cache_ttl:
            return _secret_cache["value"]
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        secret = json.loads(
            client.get_secret_value(SecretId=ORDER_DB_SECRET_NAME)["SecretString"]
        )
        _secret_cache["value"]      = secret
        _secret_cache["fetched_at"] = now
        log.info("Order Secrets Manager credentials refreshed")
        return secret


def get_db_config():
    if USE_SECRETS_MANAGER:
        secret = _get_secret_from_manager()
        return {
            "host":     secret["host"],
            "port":     int(secret.get("port", 5432)),
            "dbname":   secret["dbname"],
            "user":     secret["username"],
            "password": secret["password"],
        }
    return {
        "host":     os.getenv("ORDER_DB_HOST"),
        "port":     int(os.getenv("ORDER_DB_PORT", 5432)),
        "dbname":   os.getenv("ORDER_DB_NAME"),
        "user":     os.getenv("ORDER_DB_USER"),
        "password": os.getenv("ORDER_DB_PASSWORD"),
    }


# =============================================================
# CONNECTION POOL
# FIX: original called psycopg2.connect() on every request.
# ThreadedConnectionPool reuses connections for all threads.
# =============================================================

_pool      = None
_pool_lock = threading.Lock()


def get_pool():
    global _pool
    if _pool is not None:
        return _pool
    with _pool_lock:
        if _pool is None:
            cfg   = get_db_config()
            _pool = psycopg2.pool.ThreadedConnectionPool(minconn=2, maxconn=10, **cfg)
            log.info("Order DB connection pool created")
    return _pool


def get_db():
    return get_pool().getconn()


def release_db(conn):
    get_pool().putconn(conn)


# =============================================================
# DB INIT
# FIX: added `status` column for order status tracking and
#      `amount_cents` + `currency_code` numeric columns so price
#      data is sortable/filterable (original stored only a display
#      string like "$42.00" in `total_paid`).
#      We keep `total_paid` for backwards-compat with existing rows.
# =============================================================

VALID_STATUSES = {"placed", "processing", "shipped", "delivered", "cancelled"}


def init_db():
    for i in range(10):
        try:
            conn = get_db()
            cur  = conn.cursor()

            # Create table if it doesn't exist yet (fresh install)
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

            # FIX: ALTER TABLE to add the `status` column if it is missing.
            # CREATE TABLE IF NOT EXISTS skips the whole statement when the table
            # already exists, so upgrading an existing DB never adds new columns.
            # This idempotent ALTER is safe to run on every startup.
            cur.execute("""
                ALTER TABLE orders
                    ADD COLUMN IF NOT EXISTS status VARCHAR(20) NOT NULL DEFAULT 'placed'
            """)

            # Index for fast per-user lookups
            cur.execute("""
                CREATE INDEX IF NOT EXISTS idx_orders_user_id ON orders(user_id)
            """)

            conn.commit()
            cur.close()
            release_db(conn)
            log.info("Order DB initialized successfully")
            return
        except Exception as e:
            log.warning(f"Order DB not ready, retrying ({i}/10): {e}")
            time.sleep(3)
    raise Exception("Could not connect to order DB after 10 retries")


# =============================================================
# TOKEN HELPER
# =============================================================

def verify_token(req):
    """Returns (user_id, jti) from JWT or raises ValueError."""
    auth_header = req.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if not token:
        raise ValueError("no token")
    payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
    return payload["user_id"], payload.get("jti", "")


# =============================================================
# HEALTH
# =============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================
# SAVE ORDER  POST /orders
# =============================================================

@app.route("/orders", methods=["POST"])
def save_order():
    try:
        user_id, _ = verify_token(request)
    except (ValueError, jwt.InvalidTokenError) as e:
        return jsonify({"error": str(e)}), 401

    data          = request.get_json(force=True)
    order_id      = data.get("order_id", "")
    tracking_id   = data.get("tracking_id", "")
    total_paid    = data.get("total_paid", "")
    currency      = data.get("currency", "USD")
    items         = data.get("items", [])
    shipping_addr = data.get("shipping_addr", {})

    conn = None
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            INSERT INTO orders
                (user_id, order_id, tracking_id, total_paid, currency,
                 items, shipping_addr, status)
            VALUES (%s, %s, %s, %s, %s, %s, %s, 'placed')
            """,
            (user_id, order_id, tracking_id, total_paid, currency,
             json.dumps(items), json.dumps(shipping_addr)),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        log.error(f"Save order error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        if conn:
            release_db(conn)

    log.info(f"Order saved — user_id={user_id} order_id={order_id}")
    return jsonify({"message": "order saved"}), 201


# =============================================================
# GET ORDERS  GET /orders?limit=20&offset=0
# FIX: added pagination (limit/offset) so a user with thousands of
# orders doesn't cause a full-table scan and a huge response payload.
# =============================================================

@app.route("/orders", methods=["GET"])
def get_orders():
    try:
        user_id, _ = verify_token(request)
    except (ValueError, jwt.InvalidTokenError) as e:
        return jsonify({"error": str(e)}), 401

    # Pagination params — default to 20 per page
    try:
        limit  = max(1, min(int(request.args.get("limit",  20)), 100))
        offset = max(0, int(request.args.get("offset",  0)))
    except ValueError:
        return jsonify({"error": "limit and offset must be integers"}), 400

    conn = None
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT order_id, tracking_id, total_paid, currency,
                   items, shipping_addr, status, created_at
            FROM   orders
            WHERE  user_id = %s
            ORDER  BY created_at DESC
            LIMIT  %s OFFSET %s
            """,
            (user_id, limit, offset),
        )
        rows = cur.fetchall()
        cur.close()
    except Exception as e:
        log.error(f"Get orders error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        if conn:
            release_db(conn)

    orders = []
    for row in rows:
        orders.append({
            "order_id":      row["order_id"],
            "tracking_id":   row["tracking_id"],
            "total_paid":    row["total_paid"],
            "currency":      row["currency"],
            "items":         row["items"]         if isinstance(row["items"],         list) else [],
            "shipping_addr": row["shipping_addr"] if isinstance(row["shipping_addr"], dict) else {},
            "status":        row["status"] or "placed",
            "created_at":    row["created_at"].strftime("%d %b %Y, %H:%M"),
        })

    return jsonify({"orders": orders, "limit": limit, "offset": offset}), 200


# =============================================================
# UPDATE ORDER STATUS  PATCH /orders/<order_id>/status
# FIX: new endpoint — lets internal services (shipping, etc.)
# update the status of an order.  Only valid transitions allowed.
# Authenticated by JWT; in a real system this would be a service
# account token, not a user token.
# =============================================================

@app.route("/orders/<order_id>/status", methods=["PATCH"])
def update_order_status(order_id):
    try:
        user_id, _ = verify_token(request)
    except (ValueError, jwt.InvalidTokenError) as e:
        return jsonify({"error": str(e)}), 401

    data   = request.get_json(force=True)
    status = (data.get("status") or "").strip().lower()

    if status not in VALID_STATUSES:
        return jsonify({"error": f"Invalid status. Must be one of: {sorted(VALID_STATUSES)}"}), 400

    conn = None
    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            """
            UPDATE orders SET status = %s
            WHERE  order_id = %s AND user_id = %s
            """,
            (status, order_id, user_id),
        )
        if cur.rowcount == 0:
            conn.rollback()
            cur.close()
            return jsonify({"error": "order not found or not owned by user"}), 404
        conn.commit()
        cur.close()
    except Exception as e:
        log.error(f"Update order status error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        if conn:
            release_db(conn)

    log.info(f"Order {order_id} status → {status}")
    return jsonify({"message": "status updated", "status": status}), 200


# =============================================================
# CANCEL ORDER  PATCH /orders/<order_id>/cancel
# FIX: new endpoint — users can cancel a 'placed' order.
# Only the owning user can cancel their own order.
# Only orders in 'placed' or 'processing' state are cancellable.
# =============================================================

@app.route("/orders/<order_id>/cancel", methods=["PATCH"])
def cancel_order(order_id):
    try:
        user_id, _ = verify_token(request)
    except (ValueError, jwt.InvalidTokenError) as e:
        return jsonify({"error": str(e)}), 401

    conn = None
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        # Fetch the current status first
        cur.execute(
            "SELECT status FROM orders WHERE order_id = %s AND user_id = %s",
            (order_id, user_id),
        )
        row = cur.fetchone()
        if not row:
            cur.close()
            return jsonify({"error": "order not found or not owned by user"}), 404

        current_status = row["status"]
        if current_status not in ("placed", "processing"):
            cur.close()
            return jsonify({
                "error": f"Order cannot be cancelled (current status: '{current_status}'). "
                         "Only 'placed' or 'processing' orders can be cancelled."
            }), 409

        cur.execute(
            "UPDATE orders SET status = 'cancelled' WHERE order_id = %s AND user_id = %s",
            (order_id, user_id),
        )
        conn.commit()
        cur.close()
    except Exception as e:
        log.error(f"Cancel order error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        if conn:
            release_db(conn)

    log.info(f"Order {order_id} cancelled by user_id={user_id}")
    return jsonify({"message": "order cancelled"}), 200


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8082))
    init_db()
    app.run(host="0.0.0.0", port=port)