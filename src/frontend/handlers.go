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
	"bytes"
	"context"
	"encoding/json"
	"fmt"
	"html/template"
	"io"
	"math/rand"
	"net"
	"net/http"
	"os"
	"strconv"
	"strings"
	"time"

	"github.com/gorilla/mux"
	"github.com/pkg/errors"
	"github.com/sirupsen/logrus"

	pb "github.com/GoogleCloudPlatform/microservices-demo/src/frontend/genproto"
	"github.com/GoogleCloudPlatform/microservices-demo/src/frontend/money"
	"github.com/GoogleCloudPlatform/microservices-demo/src/frontend/validator"
)

type platformDetails struct {
	css      string
	provider string
}

var (
	frontendMessage  = strings.TrimSpace(os.Getenv("FRONTEND_MESSAGE"))
	isCymbalBrand    = "true" == strings.ToLower(os.Getenv("CYMBAL_BRANDING"))
	assistantEnabled = "true" == strings.ToLower(os.Getenv("ENABLE_ASSISTANT"))
	templates        = template.Must(template.New("").
				Funcs(template.FuncMap{
			"renderMoney":        renderMoney,
			"renderCurrencyLogo": renderCurrencyLogo,
		}).ParseGlob("templates/*.html"))
	plat platformDetails
)

var validEnvs = []string{"local", "gcp", "azure", "aws", "onprem", "alibaba"}

// productInfo holds catalog data needed when persisting an order item.
type productInfo struct {
	name    string
	picture string
}

// ── cookie helpers ────────────────────────────────────────────────────────────

// authTokenFromCookie returns the JWT string from the shop_auth cookie, or "".
func authTokenFromCookie(r *http.Request) string {
	if c, err := r.Cookie("shop_auth"); err == nil {
		return c.Value
	}
	return ""
}

// setAuthCookies writes the shop_auth and shop_username cookies.
//
// FIX: The original code had a comment "TODO: enable Secure when on HTTPS".
// Now the Secure flag is driven by the HTTPS_ENABLED env var so production
// deployments get proper cookie security without touching code.
func setAuthCookies(w http.ResponseWriter, token, username string) {
	secure := strings.ToLower(os.Getenv("HTTPS_ENABLED")) == "true"
	http.SetCookie(w, &http.Cookie{
		Name:     "shop_auth",
		Value:    token,
		MaxAge:   cookieMaxAge,
		Path:     "/",
		HttpOnly: true, // JS cannot read the auth token — prevents XSS token theft
		Secure:   secure,
		SameSite: http.SameSiteLaxMode,
	})
	http.SetCookie(w, &http.Cookie{
		Name:     "shop_username",
		Value:    username,
		MaxAge:   cookieMaxAge,
		Path:     "/",
		HttpOnly: false, // read by Go template, not sensitive
		Secure:   secure,
		SameSite: http.SameSiteLaxMode,
	})
}

// claimsFromRequest decodes the JWT in the shop_auth cookie without any
// network call, returning nil if the cookie is absent or invalid/expired.
func claimsFromRequest(r *http.Request) *jwtClaims {
	token := authTokenFromCookie(r)
	if token == "" {
		return nil
	}
	c, ok := verifyJWTLocal(token)
	if !ok {
		return nil
	}
	return &c
}

// ── platform ──────────────────────────────────────────────────────────────────

func (p *platformDetails) setPlatformDetails(env string) {
	switch env {
	case "aws":
		p.provider = "AWS"
		p.css = "aws-platform"
	case "onprem":
		p.provider = "On-Premises"
		p.css = "onprem-platform"
	case "azure":
		p.provider = "Azure"
		p.css = "azure-platform"
	case "gcp":
		p.provider = "Google Cloud"
		p.css = "gcp-platform"
	case "alibaba":
		p.provider = "Alibaba Cloud"
		p.css = "alibaba-platform"
	default:
		p.provider = "local"
		p.css = "local"
	}
}

// ── handlers ──────────────────────────────────────────────────────────────────

func (fe *frontendServer) homeHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.WithField("currency", currentCurrency(r)).Info("home")

	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	products, err := fe.getProducts(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve products"), http.StatusInternalServerError)
		return
	}
	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}

	type productView struct {
		Item  *pb.Product
		Price *pb.Money
	}
	ps := make([]productView, len(products))
	for i, p := range products {
		price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrapf(err, "failed currency conversion for product %s", p.GetId()), http.StatusInternalServerError)
			return
		}
		ps[i] = productView{p, price}
	}

	env := os.Getenv("ENV_PLATFORM")
	if env == "" || !stringinSlice(validEnvs, env) {
		env = "local"
	}
	addrs, err := net.LookupHost("metadata.google.internal.")
	if err == nil && len(addrs) > 0 {
		log.Debugf("Detected Google metadata server: %v, setting ENV_PLATFORM to GCP.", addrs)
		env = "gcp"
	}
	log.Debugf("ENV_PLATFORM is: %s", env)
	plat = platformDetails{}
	plat.setPlatformDetails(strings.ToLower(env))

	if err := templates.ExecuteTemplate(w, "home", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": true,
		"currencies":    currencies,
		"products":      ps,
		"cart_size":     cartSize(cart),
		"banner_color":  os.Getenv("BANNER_COLOR"),
		"ad":            fe.chooseAd(r.Context(), []string{}, log),
	})); err != nil {
		log.Error(err)
	}
}

func (fe *frontendServer) productHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	id := mux.Vars(r)["id"]
	if id == "" {
		renderHTTPError(log, r, w, errors.New("product id not specified"), http.StatusBadRequest)
		return
	}
	log.WithField("id", id).WithField("currency", currentCurrency(r)).Debug("serving product page")

	p, err := fe.getProduct(r.Context(), id)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve product"), http.StatusInternalServerError)
		return
	}
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}
	price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to convert currency"), http.StatusInternalServerError)
		return
	}
	recommendations, err := fe.getRecommendations(r.Context(), sessionID(r), []string{id})
	if err != nil {
		log.WithField("error", err).Warn("failed to get product recommendations")
	}

	product := struct {
		Item  *pb.Product
		Price *pb.Money
	}{p, price}

	var packagingInfo *PackagingInfo
	if isPackagingServiceConfigured() {
		packagingInfo, err = httpGetPackagingInfo(id)
		if err != nil {
			fmt.Println("Failed to obtain product's packaging info:", err)
		}
	}

	if err := templates.ExecuteTemplate(w, "product", injectCommonTemplateData(r, map[string]interface{}{
		"ad":              fe.chooseAd(r.Context(), p.Categories, log),
		"show_currency":   true,
		"currencies":      currencies,
		"product":         product,
		"recommendations": recommendations,
		"cart_size":       cartSize(cart),
		"packagingInfo":   packagingInfo,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) addToCartHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	quantity, _ := strconv.ParseUint(r.FormValue("quantity"), 10, 32)
	productID := r.FormValue("product_id")
	payload := validator.AddToCartPayload{Quantity: quantity, ProductID: productID}
	if err := payload.Validate(); err != nil {
		renderHTTPError(log, r, w, validator.ValidationErrorResponse(err), http.StatusUnprocessableEntity)
		return
	}
	log.WithField("product", payload.ProductID).WithField("quantity", payload.Quantity).Debug("adding to cart")

	p, err := fe.getProduct(r.Context(), payload.ProductID)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve product"), http.StatusInternalServerError)
		return
	}
	if err := fe.insertCart(r.Context(), sessionID(r), p.GetId(), int32(payload.Quantity)); err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to add to cart"), http.StatusInternalServerError)
		return
	}
	w.Header().Set("location", baseUrl+"/cart")
	w.WriteHeader(http.StatusFound)
}

func (fe *frontendServer) emptyCartHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("emptying cart")
	if err := fe.emptyCart(r.Context(), sessionID(r)); err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to empty cart"), http.StatusInternalServerError)
		return
	}
	w.Header().Set("location", baseUrl+"/")
	w.WriteHeader(http.StatusFound)
}

func (fe *frontendServer) viewCartHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("view user cart")
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}
	recommendations, err := fe.getRecommendations(r.Context(), sessionID(r), cartIDs(cart))
	if err != nil {
		log.WithField("error", err).Warn("failed to get product recommendations")
	}
	shippingCost, err := fe.getShippingQuote(r.Context(), cart, currentCurrency(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to get shipping quote"), http.StatusInternalServerError)
		return
	}

	type cartItemView struct {
		Item     *pb.Product
		Quantity int32
		Price    *pb.Money
	}
	items := make([]cartItemView, len(cart))
	totalPrice := pb.Money{CurrencyCode: currentCurrency(r)}
	for i, item := range cart {
		p, err := fe.getProduct(r.Context(), item.GetProductId())
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrapf(err, "could not retrieve product #%s", item.GetProductId()), http.StatusInternalServerError)
			return
		}
		price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrapf(err, "could not convert currency for product #%s", item.GetProductId()), http.StatusInternalServerError)
			return
		}
		multPrice := money.MultiplySlow(*price, uint32(item.GetQuantity()))
		items[i] = cartItemView{Item: p, Quantity: item.GetQuantity(), Price: &multPrice}
		totalPrice = money.Must(money.Sum(totalPrice, multPrice))
	}
	totalPrice = money.Must(money.Sum(totalPrice, *shippingCost))
	year := time.Now().Year()

	if err := templates.ExecuteTemplate(w, "cart", injectCommonTemplateData(r, map[string]interface{}{
		"currencies":       currencies,
		"recommendations":  recommendations,
		"cart_size":        cartSize(cart),
		"shipping_cost":    shippingCost,
		"show_currency":    true,
		"total_cost":       totalPrice,
		"items":            items,
		"expiration_years": []int{year, year + 1, year + 2, year + 3, year + 4},
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) placeOrderHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("placing order")

	var (
		email         = r.FormValue("email")
		streetAddress = r.FormValue("street_address")
		zipCode, _    = strconv.ParseInt(r.FormValue("zip_code"), 10, 32)
		city          = r.FormValue("city")
		state         = r.FormValue("state")
		country       = r.FormValue("country")
		ccNumber      = r.FormValue("credit_card_number")
		ccMonth, _    = strconv.ParseInt(r.FormValue("credit_card_expiration_month"), 10, 32)
		ccYear, _     = strconv.ParseInt(r.FormValue("credit_card_expiration_year"), 10, 32)
		ccCVV, _      = strconv.ParseInt(r.FormValue("credit_card_cvv"), 10, 32)
	)

	payload := validator.PlaceOrderPayload{
		Email: email, StreetAddress: streetAddress, ZipCode: zipCode,
		City: city, State: state, Country: country,
		CcNumber: ccNumber, CcMonth: ccMonth, CcYear: ccYear, CcCVV: ccCVV,
	}
	if err := payload.Validate(); err != nil {
		renderHTTPError(log, r, w, validator.ValidationErrorResponse(err), http.StatusUnprocessableEntity)
		return
	}

	order, err := pb.NewCheckoutServiceClient(fe.checkoutSvcConn).
		PlaceOrder(r.Context(), &pb.PlaceOrderRequest{
			Email: payload.Email,
			CreditCard: &pb.CreditCardInfo{
				CreditCardNumber:          payload.CcNumber,
				CreditCardExpirationMonth: int32(payload.CcMonth),
				CreditCardExpirationYear:  int32(payload.CcYear),
				CreditCardCvv:             int32(payload.CcCVV),
			},
			UserId:       sessionID(r),
			UserCurrency: currentCurrency(r),
			Address: &pb.Address{
				StreetAddress: payload.StreetAddress,
				City:          payload.City,
				State:         payload.State,
				ZipCode:       int32(payload.ZipCode),
				Country:       payload.Country,
			},
		})
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to complete the order"), http.StatusInternalServerError)
		return
	}
	log.WithField("order", order.GetOrder().GetOrderId()).Info("order placed")

	recommendations, _ := fe.getRecommendations(r.Context(), sessionID(r), nil)

	totalPaid := *order.GetOrder().GetShippingCost()
	for _, v := range order.GetOrder().GetItems() {
		multPrice := money.MultiplySlow(*v.GetCost(), uint32(v.GetItem().GetQuantity()))
		totalPaid = money.Must(money.Sum(totalPaid, multPrice))
	}

	// Look up each product's display name and picture URL so order history
	// shows the real name and thumbnail instead of a raw product ID.
	productInfos := make(map[string]productInfo)
	for _, v := range order.GetOrder().GetItems() {
		pid := v.GetItem().GetProductId()
		if _, seen := productInfos[pid]; !seen {
			if p, err := fe.getProduct(r.Context(), pid); err == nil {
				productInfos[pid] = productInfo{name: p.GetName(), picture: p.GetPicture()}
			} else {
				productInfos[pid] = productInfo{name: pid, picture: ""}
			}
		}
	}

	// Persist order to order service asynchronously.
	// The user already has the success page — order save failure is logged but
	// does not block the response.
	go fe.saveOrderToOrderService(r, order.GetOrder(), &totalPaid, productInfos, log)

	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	if err := templates.ExecuteTemplate(w, "order", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency":   false,
		"currencies":      currencies,
		"order":           order.GetOrder(),
		"total_paid":      &totalPaid,
		"recommendations": recommendations,
	})); err != nil {
		log.Println(err)
	}
}

// saveOrderToOrderService persists the placed order in the order service.
// Runs in a goroutine; logs failures without surfacing them to the user.
func (fe *frontendServer) saveOrderToOrderService(
	r *http.Request,
	o *pb.OrderResult,
	totalPaid *pb.Money,
	productInfos map[string]productInfo,
	log logrus.FieldLogger,
) {
	token := authTokenFromCookie(r)
	if token == "" {
		return
	}

	type orderItem struct {
		Name     string `json:"name"`
		Quantity int32  `json:"quantity"`
		Price    string `json:"price"`
		Picture  string `json:"picture"`
	}
	var items []orderItem
	for _, v := range o.GetItems() {
		pid := v.GetItem().GetProductId()
		info := productInfos[pid]
		name := info.name
		if name == "" {
			name = pid
		}
		items = append(items, orderItem{
			Name:     name,
			Quantity: v.GetItem().GetQuantity(),
			Price:    renderMoney(*v.GetCost()),
			Picture:  info.picture,
		})
	}

	body, _ := json.Marshal(map[string]interface{}{
		"order_id":    o.GetOrderId(),
		"tracking_id": o.GetShippingTrackingId(),
		"total_paid":  renderMoney(*totalPaid),
		"currency":    totalPaid.GetCurrencyCode(),
		"items":       items,
		"shipping_addr": map[string]interface{}{
			"street":  o.GetShippingAddress().GetStreetAddress(),
			"city":    o.GetShippingAddress().GetCity(),
			"state":   o.GetShippingAddress().GetState(),
			"country": o.GetShippingAddress().GetCountry(),
		},
	})

	req, err := http.NewRequest(http.MethodPost, "http://"+fe.orderSvcAddr+"/orders", bytes.NewReader(body))
	if err != nil {
		log.WithField("error", err).Warn("could not build save-order request")
		return
	}
	req.Header.Set("Content-Type", "application/json")
	// FIX: JWT sent in Authorization header, NOT query string.
	// Original: /verify?token=<jwt>  →  token leaks into server logs.
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		log.WithField("error", err).Warn("save-order request failed")
		return
	}
	defer resp.Body.Close()
	if resp.StatusCode != http.StatusCreated {
		log.WithField("status", resp.StatusCode).Warn("save-order returned non-201")
	}
}

// orderHistoryHandler fetches and renders the authenticated user's past orders.
func (fe *frontendServer) orderHistoryHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	token := authTokenFromCookie(r)
	if token == "" {
		http.Redirect(w, r, baseUrl+"/login", http.StatusFound)
		return
	}

	req, err := http.NewRequest(http.MethodGet, "http://"+fe.orderSvcAddr+"/orders", nil)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not build orders request"), http.StatusInternalServerError)
		return
	}
	// FIX: JWT in Authorization header, not query string.
	req.Header.Set("Authorization", "Bearer "+token)

	resp, err := http.DefaultClient.Do(req)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not fetch orders"), http.StatusInternalServerError)
		return
	}
	defer resp.Body.Close()

	var result struct {
		Orders []map[string]interface{} `json:"orders"`
	}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not decode orders response"), http.StatusInternalServerError)
		return
	}

	if err := templates.ExecuteTemplate(w, "order-history", injectCommonTemplateData(r, map[string]interface{}{
		"orders": result.Orders,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) assistantHandler(w http.ResponseWriter, r *http.Request) {
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	if err := templates.ExecuteTemplate(w, "assistant", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": false,
		"currencies":    currencies,
		"baseUrl":       baseUrl,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) logoutHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	log.Debug("logging out")
	for _, c := range r.Cookies() {
		c.Expires = time.Now().Add(-time.Hour * 24 * 365)
		c.MaxAge = -1
		http.SetCookie(w, c)
	}
	http.Redirect(w, r, baseUrl+"/login", http.StatusFound)
}

func (fe *frontendServer) loginHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		if err := templates.ExecuteTemplate(w, "login", map[string]interface{}{
			"baseUrl":     baseUrl,
			"error":       r.URL.Query().Get("error"),
			"hide_search": true,
		}); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
		return
	}

	// POST — forward credentials to auth service
	email := r.FormValue("email")
	password := r.FormValue("password")
	body, _ := json.Marshal(map[string]string{"email": email, "password": password})

	resp, err := http.Post("http://"+fe.authSvcAddr+"/login", "application/json", bytes.NewReader(body))
	if err != nil {
		http.Redirect(w, r, baseUrl+"/login?error=Service+unavailable.+Please+try+again.", http.StatusFound)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK {
		http.Redirect(w, r, baseUrl+"/login?error=Invalid+email+or+password.", http.StatusFound)
		return
	}

	// FIX: safe JSON decode — original code did result["token"].(string) with no
	// nil-check, which panics and returns a 500 if the auth service ever returns
	// a response without a "token" key (e.g. on a transient error body).
	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		http.Redirect(w, r, baseUrl+"/login?error=Invalid+server+response.", http.StatusFound)
		return
	}
	token, ok1 := result["token"].(string)
	username, ok2 := result["username"].(string)
	if !ok1 || !ok2 || token == "" {
		http.Redirect(w, r, baseUrl+"/login?error=Invalid+server+response.", http.StatusFound)
		return
	}

	setAuthCookies(w, token, username)
	http.Redirect(w, r, baseUrl+"/", http.StatusFound)
}

func (fe *frontendServer) registerHandler(w http.ResponseWriter, r *http.Request) {
	if r.Method == http.MethodGet {
		if err := templates.ExecuteTemplate(w, "register", map[string]interface{}{
			"baseUrl":     baseUrl,
			"error":       r.URL.Query().Get("error"),
			"hide_search": true,
		}); err != nil {
			http.Error(w, err.Error(), http.StatusInternalServerError)
		}
		return
	}

	// POST — forward registration data to auth service
	username := r.FormValue("username")
	email := r.FormValue("email")
	password := r.FormValue("password")
	body, _ := json.Marshal(map[string]string{"username": username, "email": email, "password": password})

	resp, err := http.Post("http://"+fe.authSvcAddr+"/register", "application/json", bytes.NewReader(body))
	if err != nil {
		http.Redirect(w, r, baseUrl+"/register?error=Service+unavailable.+Please+try+again.", http.StatusFound)
		return
	}
	defer resp.Body.Close()

	if resp.StatusCode != http.StatusOK && resp.StatusCode != http.StatusCreated {
		http.Redirect(w, r, baseUrl+"/register?error=Registration+failed.+Username+or+email+may+already+exist.", http.StatusFound)
		return
	}

	// FIX: same safe decode as loginHandler — no panic on unexpected response.
	var result map[string]interface{}
	if err := json.NewDecoder(resp.Body).Decode(&result); err != nil {
		http.Redirect(w, r, baseUrl+"/register?error=Invalid+server+response.", http.StatusFound)
		return
	}
	token, ok1 := result["token"].(string)
	registeredUsername, ok2 := result["username"].(string)
	if !ok1 || !ok2 || token == "" {
		http.Redirect(w, r, baseUrl+"/register?error=Invalid+server+response.", http.StatusFound)
		return
	}

	setAuthCookies(w, token, registeredUsername)
	http.Redirect(w, r, baseUrl+"/", http.StatusFound)
}

func (fe *frontendServer) getProductByID(w http.ResponseWriter, r *http.Request) {
	id := mux.Vars(r)["ids"]
	if id == "" {
		return
	}
	p, err := fe.getProduct(r.Context(), id)
	if err != nil {
		return
	}
	jsonData, err := json.Marshal(p)
	if err != nil {
		fmt.Println(err)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	w.Write(jsonData)
}



func (fe *frontendServer) chatBotHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	type Response struct {
		Message     string   `json:"message"`
		QuickReplies []string `json:"quick_replies"`
	}
	type LLMResponse struct {
		Content      string   `json:"content"`
		QuickReplies []string `json:"quick_replies"`
	}

	var response LLMResponse
	url := "http://" + fe.shoppingAssistantSvcAddr
	req, err := http.NewRequest(http.MethodPost, url, r.Body)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to create request"), http.StatusInternalServerError)
		return
	}
	req.Header.Set("Content-Type", "application/json")
	req.Header.Set("Accept", "application/json")
	res, err := http.DefaultClient.Do(req)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to send request"), http.StatusInternalServerError)
		return
	}
	body, err := io.ReadAll(res.Body)
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to read response"), http.StatusInternalServerError)
		return
	}
	if err := json.Unmarshal(body, &response); err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "failed to unmarshal body"), http.StatusInternalServerError)
		return
	}
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(http.StatusOK)
	json.NewEncoder(w).Encode(Response{
		Message:      response.Content,
		QuickReplies: response.QuickReplies,
	})
}

func (fe *frontendServer) setCurrencyHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	cur := r.FormValue("currency_code")
	payload := validator.SetCurrencyPayload{Currency: cur}
	if err := payload.Validate(); err != nil {
		renderHTTPError(log, r, w, validator.ValidationErrorResponse(err), http.StatusUnprocessableEntity)
		return
	}
	log.WithField("curr.new", payload.Currency).WithField("curr.old", currentCurrency(r)).Debug("setting currency")
	if payload.Currency != "" {
		http.SetCookie(w, &http.Cookie{
			Name:   cookieCurrency,
			Value:  payload.Currency,
			MaxAge: cookieMaxAge,
		})
	}
	referer := r.Header.Get("referer")
	if referer == "" {
		referer = baseUrl + "/"
	}
	w.Header().Set("Location", referer)
	w.WriteHeader(http.StatusFound)
}

func (fe *frontendServer) profileHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)
	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}
	if err := templates.ExecuteTemplate(w, "profile", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": true,
		"currencies":    currencies,
	})); err != nil {
		log.Println(err)
	}
}

func (fe *frontendServer) chooseAd(ctx context.Context, ctxKeys []string, log logrus.FieldLogger) *pb.Ad {
	ads, err := fe.getAd(ctx, ctxKeys)
	if err != nil {
		log.WithField("error", err).Warn("failed to retrieve ads")
		return nil
	}
	return ads[rand.Intn(len(ads))]
}

func renderHTTPError(log logrus.FieldLogger, r *http.Request, w http.ResponseWriter, err error, code int) {
	log.WithField("error", err).Error("request error")
	errMsg := fmt.Sprintf("%+v", err)
	w.WriteHeader(code)
	if templateErr := templates.ExecuteTemplate(w, "error", injectCommonTemplateData(r, map[string]interface{}{
		"error":       errMsg,
		"status_code": code,
		"status":      http.StatusText(code),
	})); templateErr != nil {
		log.Println(templateErr)
	}
}

// injectCommonTemplateData merges per-handler data with fields every template needs.
//
// FIX: also decodes JWT claims to expose `email` to the profile template — the
// original profile page had no email field because it was never passed in.
func injectCommonTemplateData(r *http.Request, payload map[string]interface{}) map[string]interface{} {
	username := ""
	if c, err := r.Cookie("shop_username"); err == nil {
		username = c.Value
	}

	// Decode email from JWT claims (local, no network call).
	email := ""
	if claims := claimsFromRequest(r); claims != nil {
		email = claims.Email
	}

	data := map[string]interface{}{
		"session_id":        sessionID(r),
		"request_id":        r.Context().Value(ctxKeyRequestID{}),
		"user_currency":     currentCurrency(r),
		"platform_css":      plat.css,
		"platform_name":     plat.provider,
		"is_cymbal_brand":   isCymbalBrand,
		"assistant_enabled": assistantEnabled,
		"deploymentDetails": deploymentDetailsMap,
		"frontendMessage":   frontendMessage,
		"currentYear":       time.Now().Year(),
		"baseUrl":           baseUrl,
		"username":          username,
		"email":             email, // FIX: now available in all templates including profile
		"search_query":      r.URL.Query().Get("q"), // keeps search bar populated on results page
	}
	for k, v := range payload {
		data[k] = v
	}
	return data
}

func currentCurrency(r *http.Request) string {
	c, _ := r.Cookie(cookieCurrency)
	if c != nil {
		return c.Value
	}
	return defaultCurrency
}

func sessionID(r *http.Request) string {
	v := r.Context().Value(ctxKeySessionID{})
	if v != nil {
		return v.(string)
	}
	return ""
}

func cartIDs(c []*pb.CartItem) []string {
	out := make([]string, len(c))
	for i, v := range c {
		out[i] = v.GetProductId()
	}
	return out
}

func cartSize(c []*pb.CartItem) int {
	n := 0
	for _, item := range c {
		n += int(item.GetQuantity())
	}
	return n
}

func renderMoney(m pb.Money) string {
	return fmt.Sprintf("%s%d.%02d",
		renderCurrencyLogo(m.GetCurrencyCode()),
		m.GetUnits(),
		m.GetNanos()/10000000)
}

func renderCurrencyLogo(code string) string {
	logos := map[string]string{
		"USD": "$", "CAD": "$", "JPY": "¥",
		"EUR": "€", "TRY": "₺", "GBP": "£",
	}
	if l, ok := logos[code]; ok {
		return l
	}
	return "$"
}

func stringinSlice(slice []string, val string) bool {
	for _, item := range slice {
		if item == val {
			return true
		}
	}
	return false
}


// searchHandler handles GET /search?q=<query>.
// It calls the SearchProducts gRPC method on the catalog service,
// converts each result's price to the user's currency, and renders
// the search.html template using the same product card layout as home.html.
func (fe *frontendServer) searchHandler(w http.ResponseWriter, r *http.Request) {
	log := r.Context().Value(ctxKeyLog{}).(logrus.FieldLogger)

	query := strings.TrimSpace(r.URL.Query().Get("q"))

	currencies, err := fe.getCurrencies(r.Context())
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve currencies"), http.StatusInternalServerError)
		return
	}

	cart, err := fe.getCart(r.Context(), sessionID(r))
	if err != nil {
		renderHTTPError(log, r, w, errors.Wrap(err, "could not retrieve cart"), http.StatusInternalServerError)
		return
	}

	type productView struct {
		Item  *pb.Product
		Price *pb.Money
	}

	var products []productView

	if query != "" {
		results, err := fe.searchProducts(r.Context(), query)
		if err != nil {
			renderHTTPError(log, r, w, errors.Wrap(err, "search failed"), http.StatusInternalServerError)
			return
		}
		for _, p := range results {
			price, err := fe.convertCurrency(r.Context(), p.GetPriceUsd(), currentCurrency(r))
			if err != nil {
				renderHTTPError(log, r, w, errors.Wrapf(err, "failed currency conversion for product %s", p.GetId()), http.StatusInternalServerError)
				return
			}
			products = append(products, productView{p, price})
		}
		log.WithField("query", query).WithField("results", len(products)).Info("search")
	}

	if err := templates.ExecuteTemplate(w, "search", injectCommonTemplateData(r, map[string]interface{}{
		"show_currency": true,
		"currencies":    currencies,
		"cart_size":     cartSize(cart),
		"query":         query,
		"products":      products,
	})); err != nil {
		log.Println(err)
	}
}