from flask import Flask, request, jsonify
from prometheus_flask_exporter import PrometheusMetrics
from functools import wraps
import psycopg2
import psycopg2.extras
import bcrypt
import jwt
import os
import datetime
import time
import json
import logging

app = Flask(__name__)
metrics = PrometheusMetrics(app)  # exposes /metrics automatically

logging.basicConfig(
    level=logging.INFO,
    format='{"time":"%(asctime)s","level":"%(levelname)s","msg":"%(message)s"}',
    datefmt='%Y-%m-%dT%H:%M:%SZ'
)
log = logging.getLogger(__name__)

# =========================
# CONFIG
# =========================

DB_HOST     = os.getenv("DB_HOST")
DB_PORT     = os.getenv("DB_PORT")
DB_NAME     = os.getenv("DB_NAME")
DB_USER     = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")
JWT_SECRET  = os.getenv("JWT_SECRET")

# =========================
# RATE LIMITING (in-memory, per IP)
# Simple sliding-window: max 10 attempts per IP per 60s on auth routes
# =========================

_rate_store = {}  # { ip: [timestamp, ...] }
RATE_LIMIT   = 10
RATE_WINDOW  = 60  # seconds

def _rate_limit_check(ip):
    now   = time.time()
    hits  = _rate_store.get(ip, [])
    hits  = [t for t in hits if now - t < RATE_WINDOW]
    if len(hits) >= RATE_LIMIT:
        return False
    hits.append(now)
    _rate_store[ip] = hits
    return True

def rate_limited(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        ip = request.headers.get("X-Forwarded-For", request.remote_addr)
        if not _rate_limit_check(ip):
            log.warning(f"Rate limit hit for IP {ip} on {request.path}")
            return jsonify({"error": "Too many requests. Please try again later."}), 429
        return f(*args, **kwargs)
    return decorated

# =========================
# DB CONNECTION
# =========================

def get_db():
    return psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        dbname=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )


def init_db():
    for i in range(10):
        try:
            conn = get_db()
            cur  = conn.cursor()

            # Users table
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      VARCHAR(100) UNIQUE NOT NULL,
                    email         VARCHAR(200) UNIQUE NOT NULL,
                    password_hash VARCHAR(200) NOT NULL,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            # Orders table — stores a snapshot of each placed order per user
            cur.execute("""
                CREATE TABLE IF NOT EXISTS orders (
                    id           SERIAL PRIMARY KEY,
                    user_id      INT NOT NULL REFERENCES users(id) ON DELETE CASCADE,
                    order_id     VARCHAR(100) NOT NULL,
                    tracking_id  VARCHAR(100),
                    total_paid   VARCHAR(50),
                    currency     VARCHAR(10),
                    items        JSONB,
                    shipping_addr JSONB,
                    created_at   TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            cur.close()
            conn.close()
            log.info("Database initialized successfully")
            return

        except Exception as e:
            log.warning(f"DB not ready, retrying ({i}/10): {e}")
            time.sleep(3)

    raise Exception("Could not connect to DB after 10 retries")


# =========================
# HEALTH CHECK
# =========================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =========================
# REGISTER
# =========================

@app.route("/register", methods=["POST"])
@rate_limited
def register():
    data = request.get_json(force=True)

    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip().lower()
    password =  data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"error": "username, email and password required"}), 400

    if len(password) < 6:
        return jsonify({"error": "password must be >= 6 chars"}), 400

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    try:
        conn = get_db()
        cur  = conn.cursor()
        cur.execute(
            "INSERT INTO users (username, email, password_hash) VALUES (%s, %s, %s) RETURNING id",
            (username, email, pw_hash),
        )
        user_id = cur.fetchone()[0]
        conn.commit()
        cur.close()
        conn.close()
    except psycopg2.IntegrityError:
        return jsonify({"error": "user already exists"}), 409
    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({"error": "internal error"}), 500

    token = jwt.encode(
        {
            "user_id":  user_id,
            "username": username,
            "email":    email,
            "exp":      datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    log.info(f"New user registered: {username}")
    return jsonify({"token": token, "user_id": user_id, "username": username}), 201


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["POST"])
@rate_limited
def login():
    data = request.get_json(force=True)

    email    = (data.get("email")    or "").strip().lower()
    password =  data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = %s",
            (email,),
        )
        user = cur.fetchone()
        cur.close()
        conn.close()
    except Exception as e:
        log.error(f"Login DB error: {e}")
        return jsonify({"error": "internal error"}), 500

    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        log.warning(f"Failed login attempt for email: {email}")
        return jsonify({"error": "invalid credentials"}), 401

    token = jwt.encode(
        {
            "user_id":  user["id"],
            "username": user["username"],
            "email":    user["email"],
            "exp":      datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    log.info(f"User logged in: {user['username']}")
    return jsonify({"token": token, "user_id": user["id"], "username": user["username"]}), 200


# =========================
# VERIFY TOKEN
# =========================

@app.route("/verify", methods=["GET"])
def verify():
    token = request.args.get("token", "")

    if not token:
        return jsonify({"valid": False, "error": "no token"}), 400

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        return jsonify({
            "valid":    True,
            "user_id":  payload["user_id"],
            "username": payload["username"],
        }), 200
    except jwt.ExpiredSignatureError:
        return jsonify({"valid": False, "error": "expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"valid": False, "error": "invalid"}), 401


# =========================
# SAVE ORDER
# Called by frontend after a successful checkout
# =========================

@app.route("/orders", methods=["POST"])
def save_order():
    # Verify the caller is authenticated
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return jsonify({"error": "unauthorized"}), 401

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload["user_id"]
    except jwt.InvalidTokenError:
        return jsonify({"error": "invalid token"}), 401

    data = request.get_json(force=True)

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
            INSERT INTO orders (user_id, order_id, tracking_id, total_paid, currency, items, shipping_addr)
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

    log.info(f"Order saved for user_id={user_id} order_id={order_id}")
    return jsonify({"message": "order saved"}), 201


# =========================
# GET ORDERS
# Returns order history for the authenticated user
# =========================

@app.route("/orders", methods=["GET"])
def get_orders():
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if not token:
        return jsonify({"error": "unauthorized"}), 401

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
        user_id = payload["user_id"]
    except jwt.InvalidTokenError:
        return jsonify({"error": "invalid token"}), 401

    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            """
            SELECT order_id, tracking_id, total_paid, currency, items, shipping_addr, created_at
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
            "order_id":     row["order_id"],
            "tracking_id":  row["tracking_id"],
            "total_paid":   row["total_paid"],
            "currency":     row["currency"],
            "items":        row["items"] if isinstance(row["items"], list) else [],
            "shipping_addr": row["shipping_addr"] if isinstance(row["shipping_addr"], dict) else {},
            "created_at":   row["created_at"].strftime("%d %b %Y, %H:%M"),
        })

    return jsonify({"orders": orders}), 200


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    init_db()
    app.run(host="0.0.0.0", port=port)