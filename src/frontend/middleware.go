// Copyright 2018 Google LLC
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//      http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

package main

import (
	"context"
	"crypto/hmac"
	"crypto/sha256"
	"encoding/base64"
	"encoding/json"
	"fmt"
	"net/http"
	"os"
	"strings"
	"time"

	"github.com/google/uuid"
	"github.com/sirupsen/logrus"
)

type ctxKeyLog struct{}
type ctxKeyRequestID struct{}

type logHandler struct {
	log  *logrus.Logger
	next http.Handler
}

type responseRecorder struct {
	b      int
	status int
	w      http.ResponseWriter
}

func (r *responseRecorder) Header() http.Header { return r.w.Header() }
func (r *responseRecorder) WriteHeader(statusCode int) {
	r.status = statusCode
	r.w.WriteHeader(statusCode)
}
func (r *responseRecorder) Write(p []byte) (int, error) {
	if r.status == 0 {
		r.status = http.StatusOK
	}
	n, err := r.w.Write(p)
	r.b += n
	return n, err
}

func (lh *logHandler) ServeHTTP(w http.ResponseWriter, r *http.Request) {
	ctx := r.Context()
	requestID, _ := uuid.NewRandom()
	ctx = context.WithValue(ctx, ctxKeyRequestID{}, requestID.String())

	start := time.Now()
	rr := &responseRecorder{w: w}
	lg := lh.log.WithFields(logrus.Fields{
		"http.req.path":   r.URL.Path,
		"http.req.method": r.Method,
		"http.req.id":     requestID.String(),
	})
	if v, ok := r.Context().Value(ctxKeySessionID{}).(string); ok {
		lg = lg.WithField("session", v)
	}
	lg.Debug("request started")
	defer func() {
		lg.WithFields(logrus.Fields{
			"http.resp.took_ms": int64(time.Since(start) / time.Millisecond),
			"http.resp.status":  rr.status,
			"http.resp.bytes":   rr.b,
		}).Debugf("request complete")
	}()

	ctx = context.WithValue(ctx, ctxKeyLog{}, lg)
	r = r.WithContext(ctx)
	lh.next.ServeHTTP(rr, r)
}

func ensureSessionID(next http.Handler) http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		var sessionID string
		c, err := r.Cookie(cookieSessionID)
		if err == http.ErrNoCookie {
			if os.Getenv("ENABLE_SINGLE_SHARED_SESSION") == "true" {
				sessionID = "12345678-1234-1234-1234-123456789123"
			} else {
				u, _ := uuid.NewRandom()
				sessionID = u.String()
			}
			http.SetCookie(w, &http.Cookie{
				Name:   cookieSessionID,
				Value:  sessionID,
				MaxAge: cookieMaxAge,
			})
		} else if err != nil {
			return
		} else {
			sessionID = c.Value
		}
		ctx := context.WithValue(r.Context(), ctxKeySessionID{}, sessionID)
		r = r.WithContext(ctx)
		next.ServeHTTP(w, r)
	}
}

// securityHeaders adds standard defensive HTTP response headers on every reply.
func securityHeaders(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("X-Content-Type-Options", "nosniff")
		w.Header().Set("X-Frame-Options", "DENY")
		w.Header().Set("Referrer-Policy", "strict-origin-when-cross-origin")
		w.Header().Set("Content-Security-Policy",
			"default-src 'self'; "+
				// 'unsafe-inline' is required for the inline <script> blocks and event
				// handlers (onchange, onerror, onmouseover) in the existing templates.
				// To remove it in future: move all inline JS to external .js files.
				"script-src 'self' 'unsafe-inline' https://stackpath.bootstrapcdn.com; "+
				"style-src 'self' https://stackpath.bootstrapcdn.com https://fonts.googleapis.com 'unsafe-inline'; "+
				"font-src 'self' https://fonts.gstatic.com; "+
				"img-src 'self' data:;")
		next.ServeHTTP(w, r)
	})
}

// jwtClaims mirrors the payload written by auth_server.py.
type jwtClaims struct {
	UserID   float64 `json:"user_id"`
	Username string  `json:"username"`
	Email    string  `json:"email"`
	Exp      float64 `json:"exp"`
}

// verifyJWTLocal validates a HS256 JWT using Go stdlib only —
// no external library, no network call, no change to go.mod.
// Returns (claims, true) on success; (zero-value, false) on any failure.
//
// Requires JWT_SECRET env var to be set on the frontend container.
// Add to docker-compose.yml under frontend.environment:
//
//	- JWT_SECRET=${JWT_SECRET}
//
// If JWT_SECRET is empty every token will fail — this produces a
// startup warning so the misconfiguration is immediately visible in logs.
func verifyJWTLocal(tokenStr string) (jwtClaims, bool) {
	if tokenStr == "" {
		return jwtClaims{}, false
	}
	secret := os.Getenv("JWT_SECRET")
	if secret == "" {
		// Misconfiguration: JWT_SECRET not set on this container.
		// Log once to stderr so it shows up in docker logs / kubectl logs.
		fmt.Fprintln(os.Stderr, "[WARN] JWT_SECRET env var is not set on the frontend container — "+
			"all token verifications will fail. Add JWT_SECRET to docker-compose.yml "+
			"under the frontend service environment block.")
		return jwtClaims{}, false
	}

	parts := strings.Split(tokenStr, ".")
	if len(parts) != 3 {
		return jwtClaims{}, false
	}

	// 1. Verify HMAC-SHA256 signature
	mac := hmac.New(sha256.New, []byte(secret))
	mac.Write([]byte(parts[0] + "." + parts[1]))
	expected := base64.RawURLEncoding.EncodeToString(mac.Sum(nil))
	if !hmac.Equal([]byte(expected), []byte(parts[2])) {
		return jwtClaims{}, false
	}

	// 2. Decode payload
	payload, err := base64.RawURLEncoding.DecodeString(parts[1])
	if err != nil {
		return jwtClaims{}, false
	}
	var claims jwtClaims
	if err := json.Unmarshal(payload, &claims); err != nil {
		return jwtClaims{}, false
	}

	// 3. Check expiry
	if claims.Exp == 0 || time.Now().Unix() > int64(claims.Exp) {
		return jwtClaims{}, false
	}

	return claims, true
}

// isPublicPath returns true for paths that never require authentication.
func isPublicPath(path string) bool {
	return path == baseUrl+"/_healthz" ||
		path == baseUrl+"/robots.txt" ||
		strings.HasPrefix(path, baseUrl+"/static/")
}

// requireAuth is the authentication middleware.
//
// Improvements vs original:
//  1. JWT verified locally via HMAC-SHA256 (stdlib, no new dependency) —
//     original called http.Get(".../verify?token=<jwt>") on every request,
//     which leaks the JWT into server access logs and adds latency.
//  2. /login and /register redirect already-authenticated users to home.
//  3. Expired or invalid cookies are cleared before redirecting to /login
//     so the browser doesn't loop on a stale cookie.
//
// CSRF: we rely on SameSite=Lax on the shop_auth cookie (set in
// setAuthCookies) rather than Origin/Referer header inspection.
// SameSite=Lax prevents cross-site POSTs from including the auth cookie,
// which is the correct and reliable defence for this architecture.
func (fe *frontendServer) requireAuth(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		path := r.URL.Path

		// Always-public: static files, health check, robots.txt
		if isPublicPath(path) {
			next.ServeHTTP(w, r)
			return
		}

		// /login and /register: redirect already-authenticated users home
		if path == baseUrl+"/login" || path == baseUrl+"/register" {
			if c, err := r.Cookie("shop_auth"); err == nil && c.Value != "" {
				if _, ok := verifyJWTLocal(c.Value); ok {
					http.Redirect(w, r, baseUrl+"/", http.StatusFound)
					return
				}
			}
			// Not authenticated — serve the login/register page normally
			next.ServeHTTP(w, r)
			return
		}

		// All other routes require a valid, non-expired JWT in the cookie
		c, err := r.Cookie("shop_auth")
		if err != nil || c.Value == "" {
			http.Redirect(w, r, baseUrl+"/login", http.StatusFound)
			return
		}
		if _, ok := verifyJWTLocal(c.Value); !ok {
			// Clear the stale/expired cookie before redirecting
			http.SetCookie(w, &http.Cookie{Name: "shop_auth", MaxAge: -1, Path: "/"})
			http.SetCookie(w, &http.Cookie{Name: "shop_username", MaxAge: -1, Path: "/"})
			http.Redirect(w, r, baseUrl+"/login", http.StatusFound)
			return
		}

		next.ServeHTTP(w, r)
	})
}