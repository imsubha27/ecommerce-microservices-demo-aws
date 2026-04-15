from flask import Flask, request, jsonify
import psycopg2
import psycopg2.extras
import bcrypt
import jwt
import os
import datetime
import time

app = Flask(__name__)

# =========================
# CONFIG (LOCAL)
# =========================

DB_HOST = os.getenv("DB_HOST")
DB_PORT = os.getenv("DB_PORT")
DB_NAME = os.getenv("DB_NAME")
DB_USER = os.getenv("DB_USER")
DB_PASSWORD = os.getenv("DB_PASSWORD")

JWT_SECRET = os.getenv("JWT_SECRET")


# =========================
# DB CONNECTION (RETRY LOGIC)
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
            cur = conn.cursor()

            cur.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    id SERIAL PRIMARY KEY,
                    username VARCHAR(100) UNIQUE NOT NULL,
                    email VARCHAR(200) UNIQUE NOT NULL,
                    password_hash VARCHAR(200) NOT NULL,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
            cur.close()
            conn.close()

            print("✅ Database initialized")
            return

        except Exception as e:
            print(f"DB not ready, retrying... {i}")
            time.sleep(3)

    raise Exception("❌ Could not connect to DB")


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
def register():
    data = request.get_json(force=True)

    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not username or not email or not password:
        return jsonify({"error": "username, email and password required"}), 400

    if len(password) < 6:
        return jsonify({"error": "password must be >= 6 chars"}), 400

    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

    try:
        conn = get_db()
        cur = conn.cursor()

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
        return jsonify({"error": str(e)}), 500

    token = jwt.encode(
        {
            "user_id": user_id,
            "username": username,
            "email": email,
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    return jsonify({
        "token": token,
        "user_id": user_id,
        "username": username
    }), 201


# =========================
# LOGIN
# =========================

@app.route("/login", methods=["POST"])
def login():
    data = request.get_json(force=True)

    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""

    if not email or not password:
        return jsonify({"error": "email and password required"}), 400

    try:
        conn = get_db()
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        cur.execute(
            "SELECT id, username, email, password_hash FROM users WHERE email = %s",
            (email,),
        )

        user = cur.fetchone()

        cur.close()
        conn.close()

    except Exception as e:
        return jsonify({"error": str(e)}), 500

    if not user or not bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return jsonify({"error": "invalid credentials"}), 401

    token = jwt.encode(
        {
            "user_id": user["id"],
            "username": user["username"],
            "email": user["email"],
            "exp": datetime.datetime.utcnow() + datetime.timedelta(hours=24),
        },
        JWT_SECRET,
        algorithm="HS256",
    )

    return jsonify({
        "token": token,
        "user_id": user["id"],
        "username": user["username"]
    }), 200


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
            "valid": True,
            "user_id": payload["user_id"],
            "username": payload["username"]
        }), 200

    except jwt.ExpiredSignatureError:
        return jsonify({"valid": False, "error": "expired"}), 401
    except jwt.InvalidTokenError:
        return jsonify({"valid": False, "error": "invalid"}), 401


# =========================
# MAIN
# =========================

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8081))

    init_db()

    app.run(host="0.0.0.0", port=port)