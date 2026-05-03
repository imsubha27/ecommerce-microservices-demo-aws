from flask import Flask, request, jsonify
from functools import wraps
from prometheus_flask_exporter import PrometheusMetrics
import psycopg2
import psycopg2.extras
import psycopg2.pool
import bcrypt
import jwt
import os
import re
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
# Local:  reads flat env vars from .env / docker-compose
# K8s:    sets USE_SECRETS_MANAGER=true + DB_SECRET_NAME
#         boto3 fetches creds from AWS Secrets Manager via IRSA
# =============================================================

USE_SECRETS_MANAGER = os.getenv("USE_SECRETS_MANAGER", "false").lower() == "true"
AWS_REGION          = os.getenv("AWS_REGION", "ap-south-1")
DB_SECRET_NAME      = os.getenv("DB_SECRET_NAME", "")
JWT_SECRET          = os.getenv("JWT_SECRET")

# =============================================================
# SECRETS MANAGER CACHING
# FIX: original code called get_secret_value() on every single request.
# Now we cache the secret for 5 minutes so we get 1 API call per pod
# per 5 minutes instead of 1 per request. Thread-safe via a lock.
# =============================================================

_secret_cache       = {}          # {"value": {...}, "fetched_at": float}
_secret_cache_ttl   = 300         # seconds
_secret_cache_lock  = threading.Lock()


def _get_secret_from_manager():
    """Fetch from Secrets Manager with in-memory TTL cache."""
    with _secret_cache_lock:
        now = time.time()
        if _secret_cache and now - _secret_cache["fetched_at"] < _secret_cache_ttl:
            return _secret_cache["value"]
        client = boto3.client("secretsmanager", region_name=AWS_REGION)
        secret = json.loads(
            client.get_secret_value(SecretId=DB_SECRET_NAME)["SecretString"]
        )
        _secret_cache["value"]      = secret
        _secret_cache["fetched_at"] = now
        log.info("Secrets Manager credentials refreshed")
        return secret


def get_db_config():
    """Return DB connection kwargs."""
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
        "host":     os.getenv("DB_HOST"),
        "port":     int(os.getenv("DB_PORT", 5432)),
        "dbname":   os.getenv("DB_NAME"),
        "user":     os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }


# =============================================================
# CONNECTION POOL
# FIX: original code opened a new psycopg2 connection on EVERY request,
# which is expensive (~20-50ms TLS + TCP handshake) and causes connection
# storms under load. A ThreadedConnectionPool reuses connections instead.
# minconn=2 ensures two connections are always ready; maxconn=10 caps usage.
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
            log.info("Auth DB connection pool created")
    return _pool


def get_db():
    """Borrow a connection from the pool."""
    return get_pool().getconn()


def release_db(conn):
    """Return a connection to the pool."""
    get_pool().putconn(conn)


# =============================================================
# RATE LIMITING (in-memory, per IP)
# Max 10 attempts per IP per 60 s on /login and /register.
#
# NOTE: This works correctly only on single-pod deployments.
# For multi-replica setups replace _rate_store with a Redis counter.
# =============================================================

_rate_store = {}
RATE_LIMIT  = 10
RATE_WINDOW = 60


def _rate_limit_check(ip):
    now  = time.time()
    hits = [t for t in _rate_store.get(ip, []) if now - t < RATE_WINDOW]
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


# =============================================================
# TOKEN REVOCATION BLOCKLIST
# FIX: original logout only expired the cookie client-side. The JWT itself
# remained valid until its 24 h expiry — stolen tokens could still be used.
# We now maintain an in-memory set of revoked JTIs (JWT IDs). On logout the
# token's JTI is added here; /verify rejects blocklisted tokens.
#
# Limitation: like the rate limiter, this is per-pod. For multi-replica
# deployments replace _revoked_jtis with a Redis SET with TTL.
# =============================================================

_revoked_jtis = set()
_revoked_lock = threading.Lock()


def revoke_token_jti(jti: str):
    with _revoked_lock:
        _revoked_jtis.add(jti)


def is_jti_revoked(jti: str) -> bool:
    with _revoked_lock:
        return jti in _revoked_jtis


# =============================================================
# PASSWORD STRENGTH
# FIX: original only checked len >= 6. Now we require at least one uppercase
# letter, one digit, and one special character, matching common expectations.
# =============================================================

_PASSWORD_MIN_LEN    = 8
_PASSWORD_UPPERCASE  = re.compile(r"[A-Z]")
_PASSWORD_DIGIT      = re.compile(r"[0-9]")
_PASSWORD_SPECIAL    = re.compile(r"[!@#$%^&*()\-_=+\[\]{};:',.<>/?\\|`~]")


def validate_password_strength(password: str):
    """
    Returns None if password is acceptable, or an error string.
    Rules: >= 8 chars, at least one uppercase letter, one digit, one special char.
    """
    if len(password) < _PASSWORD_MIN_LEN:
        return f"Password must be at least {_PASSWORD_MIN_LEN} characters long."
    if not _PASSWORD_UPPERCASE.search(password):
        return "Password must contain at least one uppercase letter."
    if not _PASSWORD_DIGIT.search(password):
        return "Password must contain at least one digit."
    if not _PASSWORD_SPECIAL.search(password):
        return "Password must contain at least one special character (!@#$%...)."
    return None


# =============================================================
# JWT HELPERS
# =============================================================

def _build_token(user_id: int, username: str, email: str) -> str:
    """Issue a 24-hour HS256 JWT with a unique JTI for revocation support."""
    import uuid
    return jwt.encode(
        {
            "jti":      str(uuid.uuid4()),   # unique token ID for revocation
            "user_id":  user_id,
            "username": username,
            "email":    email,
            "exp":      datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )


# =============================================================
# DB INIT
# =============================================================

def init_db():
    for i in range(10):
        try:
            conn = get_db()
            cur  = conn.cursor()
            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id            SERIAL PRIMARY KEY,
                    username      VARCHAR(100) UNIQUE NOT NULL,
                    email         VARCHAR(200) UNIQUE NOT NULL,
                    password_hash VARCHAR(200) NOT NULL,
                    created_at    TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.commit()
            cur.close()
            release_db(conn)
            log.info("Auth DB initialized successfully")
            return
        except Exception as e:
            log.warning(f"DB not ready, retrying ({i}/10): {e}")
            time.sleep(3)
    raise Exception("Could not connect to auth DB after 10 retries")


# =============================================================
# HEALTH
# =============================================================

@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


# =============================================================
# REGISTER
# =============================================================

@app.route("/register", methods=["POST"])
@rate_limited
def register():
    data     = request.get_json(force=True)
    username = (data.get("username") or "").strip()
    email    = (data.get("email")    or "").strip().lower()
    password =  data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"error": "username, email and password required"}), 400

    # FIX: stronger password validation (was only len >= 6)
    pw_error = validate_password_strength(password)
    if pw_error:
        return jsonify({"error": pw_error}), 400

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    conn = None
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
    except psycopg2.IntegrityError:
        if conn:
            conn.rollback()
        return jsonify({"error": "user already exists"}), 409
    except Exception as e:
        log.error(f"Register error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        if conn:
            release_db(conn)

    token = _build_token(user_id, username, email)
    log.info(f"New user registered: {username}")
    return jsonify({"token": token, "user_id": user_id, "username": username}), 201


# =============================================================
# LOGIN
# =============================================================

@app.route("/login", methods=["POST"])
@rate_limited
def login():
    data     = request.get_json(force=True)
    email    = (data.get("email")    or "").strip().lower()
    password =  data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    conn = None
    try:
        conn = get_db()
        cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = %s",
            (email,),
        )
        user = cur.fetchone()
        cur.close()
    except Exception as e:
        log.error(f"Login DB error: {e}")
        return jsonify({"error": "internal error"}), 500
    finally:
        if conn:
            release_db(conn)

    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        log.warning(f"Failed login attempt for email: {email}")
        return jsonify({"error": "invalid credentials"}), 401

    token = _build_token(user["id"], user["username"], user["email"])
    log.info(f"User logged in: {user['username']}")
    return jsonify({"token": token, "user_id": user["id"], "username": user["username"]}), 200


# =============================================================
# LOGOUT  POST /logout
# FIX: server-side token revocation via JTI blocklist.
# The frontend should also clear its cookies; this endpoint ensures
# the token cannot be replayed even if it was captured elsewhere.
# =============================================================

@app.route("/logout", methods=["POST"])
def logout():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip()
    if token:
        try:
            payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])
            jti = payload.get("jti")
            if jti:
                revoke_token_jti(jti)
                log.info(f"Token revoked: jti={jti}")
        except jwt.InvalidTokenError:
            pass  # already invalid — nothing to revoke
    return jsonify({"message": "logged out"}), 200


# =============================================================
# VERIFY TOKEN
# Reads from Authorization header (preferred) or query param (fallback).
# FIX: also checks the JTI revocation blocklist.
# =============================================================

@app.route("/verify", methods=["GET"])
def verify():
    auth_header = request.headers.get("Authorization", "")
    token = auth_header.replace("Bearer ", "").strip() if auth_header else request.args.get("token", "")

    if not token:
        return jsonify({"valid": False, "error": "no token"}), 400

    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=["HS256"])

        # FIX: check if this token has been revoked server-side
        jti = payload.get("jti")
        if jti and is_jti_revoked(jti):
            return jsonify({"valid": False, "error": "token revoked"}), 401

        return jsonify({
            "valid":    True,
            "user_id":  payload["user_id"],
            "username": payload["username"],
        }), 200
    except jwt.ExpiredSignatureError:
        return jsonify({"valid": False, "error": "expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"valid": False, "error": "invalid"}), 401


# =============================================================
# MAIN
# =============================================================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))
    init_db()
    app.run(host="0.0.0.0", port=port)