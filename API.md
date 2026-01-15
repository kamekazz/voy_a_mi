# Voy a Mi API Documentation

Base URL: `http://localhost:8000/api/`

## Authentication

All authenticated endpoints require a JWT token in the Authorization header:

```
Authorization: Bearer <access_token>
```

This API uses **passwordless phone authentication** via SMS verification codes powered by Twilio Verify.

---

## Authentication Endpoints

### Start Registration

Begin registration by sending a verification code to the user's phone.

```
POST /api/auth/register/start/
```

**Authentication:** None required

**Request Body:**
```json
{
  "username": "johndoe",
  "phone_number": "+18456307620"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | string | Yes | Unique username (3-30 chars, alphanumeric + underscore) |
| phone_number | string | Yes | Phone number (any format, normalized to E.164) |

**Response (201 Created):**
```json
{
  "message": "Verification code sent",
  "phone_number": "+18456307620",
  "expires_in": 600
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `username_taken` | Username already exists |
| 400 | `phone_registered` | Phone number already registered |
| 400 | `invalid_phone` | Invalid phone number format |
| 429 | `rate_limit_exceeded` | Too many requests (max 5/hour) |
| 429 | `cooldown_active` | Must wait before requesting another code |

---

### Confirm Registration

Verify the code and create the user account.

```
POST /api/auth/register/confirm/
```

**Authentication:** None required

**Request Body:**
```json
{
  "phone_number": "+18456307620",
  "code": "123456"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| phone_number | string | Yes | Phone number used in start registration |
| code | string | Yes | 6-digit verification code from SMS |

**Response (201 Created):**
```json
{
  "user": {
    "id": 1,
    "username": "johndoe",
    "phone_number": "+18456307620",
    "tokens": "500.00",
    "available_tokens": "500.00"
  },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
  }
}
```

**Note:** New users automatically receive **500 tokens** as a registration bonus.

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_code` | Verification code is incorrect |
| 400 | `code_expired` | Verification code has expired (10 min limit) |
| 400 | `username_taken` | Username was taken during verification |
| 404 | `verification_not_found` | No pending verification found |

---

### Start Login

Begin login by sending a verification code to an existing user's phone.

```
POST /api/auth/login/start/
```

**Authentication:** None required

**Request Body:**
```json
{
  "phone_number": "+18456307620"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| phone_number | string | Yes | Phone number of existing account |

**Response (200 OK):**
```json
{
  "message": "Verification code sent",
  "phone_number": "+18456307620",
  "expires_in": 600
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `user_not_found` | No account with this phone number |
| 400 | `invalid_phone` | Invalid phone number format |
| 429 | `rate_limit_exceeded` | Too many requests (max 5/hour) |
| 429 | `cooldown_active` | Must wait before requesting another code |

---

### Confirm Login

Verify the code and receive JWT tokens.

```
POST /api/auth/login/confirm/
```

**Authentication:** None required

**Request Body:**
```json
{
  "phone_number": "+18456307620",
  "code": "123456"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| phone_number | string | Yes | Phone number used in start login |
| code | string | Yes | 6-digit verification code from SMS |

**Response (200 OK):**
```json
{
  "user": {
    "id": 1,
    "username": "johndoe",
    "phone_number": "+18456307620",
    "tokens": "500.00",
    "available_tokens": "500.00"
  },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
  }
}
```

**Error Responses:**

| Status | Code | Description |
|--------|------|-------------|
| 400 | `invalid_code` | Verification code is incorrect |
| 400 | `code_expired` | Verification code has expired (10 min limit) |
| 404 | `verification_not_found` | No pending verification found |
| 404 | `user_not_found` | User account not found |

---

### Refresh Token

Get a new access token using a refresh token.

```
POST /api/auth/refresh/
```

**Authentication:** None required

**Request Body:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| refresh | string | Yes | Valid refresh token |

**Response (200 OK):**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

---

## User Endpoints

### Get User Profile

Get the current user's profile information.

```
GET /api/user/profile/
```

**Authentication:** Required

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "johndoe",
  "phone_number": "+18456307620",
  "email": null,
  "first_name": "",
  "last_name": "",
  "tokens": "500.00",
  "reserved_tokens": "25.00",
  "available_tokens": "475.00",
  "date_joined": "2026-01-14T12:00:00Z"
}
```

---

### Update User Profile

Update the current user's profile.

```
PATCH /api/user/profile/
```

**Authentication:** Required

**Request Body:**
```json
{
  "first_name": "John",
  "last_name": "Doe",
  "email": "john@example.com"
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| first_name | string | No | User's first name |
| last_name | string | No | User's last name |
| email | string | No | Valid email address |

**Response (200 OK):**
```json
{
  "id": 1,
  "username": "johndoe",
  "phone_number": "+18456307620",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "tokens": "500.00",
  "reserved_tokens": "25.00",
  "available_tokens": "475.00",
  "date_joined": "2026-01-14T12:00:00Z"
}
```

---

### Get Portfolio

Get user's positions with P&L summary.

```
GET /api/user/portfolio/
```

**Authentication:** Required

**Response (200 OK):**
```json
{
  "positions": [
    {
      "id": 1,
      "market_id": 50,
      "market_title": "Will aliens be confirmed in 2025?",
      "market_slug": "will-aliens-be-confirmed-2025",
      "yes_quantity": 10,
      "no_quantity": 0,
      "reserved_yes_quantity": 0,
      "reserved_no_quantity": 0,
      "yes_avg_price": "0.65",
      "no_avg_price": "0.00",
      "yes_cost_basis": "6.50",
      "no_cost_basis": "0.00",
      "current_yes_price": 68,
      "current_no_price": 32,
      "yes_unrealized_pnl": "0.30",
      "no_unrealized_pnl": "0.00",
      "total_unrealized_pnl": "0.30",
      "realized_pnl": "0.00"
    }
  ],
  "summary": {
    "tokens": 500.00,
    "reserved_tokens": 25.00,
    "available_tokens": 475.00,
    "total_unrealized_pnl": 0.30,
    "total_realized_pnl": 0.00,
    "positions_count": 1
  }
}
```

---

### Get Trade History

Get user's trade history.

```
GET /api/user/trades/
```

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| market | integer | Filter by market ID |
| contract_type | string | Filter by `yes` or `no` |
| trade_type | string | Filter by `direct`, `mint`, or `merge` |

**Response (200 OK):**
```json
{
  "count": 25,
  "next": "http://localhost:8000/api/user/trades/?page=2",
  "previous": null,
  "results": [
    {
      "id": 100,
      "market_id": 50,
      "market_title": "Will aliens be confirmed in 2025?",
      "contract_type": "yes",
      "price": 68,
      "quantity": 5,
      "trade_type": "direct",
      "is_buyer": true,
      "executed_at": "2026-01-03T12:00:00Z"
    }
  ]
}
```

---

### Get Transaction History

Get user's token transaction history.

```
GET /api/user/transactions/
```

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| type | string | Filter by transaction type |
| market | integer | Filter by market ID |

**Transaction Types:** `deposit`, `withdrawal`, `trade_buy`, `trade_sell`, `settlement_win`, `settlement_loss`, `order_reserve`, `order_release`, `refund`, `mint`, `redeem`, `mint_match`, `merge_match`, `event_reward`

**Response (200 OK):**
```json
{
  "count": 50,
  "next": "http://localhost:8000/api/user/transactions/?page=2",
  "previous": null,
  "results": [
    {
      "id": 200,
      "type": "trade_buy",
      "amount": "-3.40",
      "tokens_after": "496.60",
      "description": "Bought 5 YES @ $0.68",
      "market_id": 50,
      "market_title": "Will aliens be confirmed in 2025?",
      "created_at": "2026-01-03T12:00:00Z"
    }
  ]
}
```

---

## Category Endpoints

### List Categories

Get all categories.

```
GET /api/categories/
```

**Authentication:** None required

**Response (200 OK):**
```json
{
  "count": 5,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 1,
      "name": "Politics",
      "slug": "politics",
      "description": "Political events and elections",
      "icon": "fa-landmark",
      "display_order": 1,
      "event_count": 10
    }
  ]
}
```

---

### Get Category Detail

Get a single category by slug.

```
GET /api/categories/<slug>/
```

**Authentication:** None required

**Response (200 OK):**
```json
{
  "id": 1,
  "name": "Politics",
  "slug": "politics",
  "description": "Political events and elections",
  "icon": "fa-landmark",
  "display_order": 1,
  "event_count": 10
}
```

---

## Event Endpoints

### List Events

Get all events.

```
GET /api/events/
```

**Authentication:** None required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| category | string | Filter by category slug |
| status | string | Filter by `active`, `settled`, `cancelled` |

**Response (200 OK):**
```json
{
  "count": 20,
  "next": "http://localhost:8000/api/events/?page=2",
  "previous": null,
  "results": [
    {
      "id": 1,
      "title": "2024 US Presidential Election",
      "slug": "2024-us-presidential-election",
      "description": "Predict the next US President",
      "category": "politics",
      "category_name": "Politics",
      "status": "active",
      "thumbnail_url": "http://localhost:8000/media/events/election.jpg",
      "market_count": 5,
      "total_volume": 50000,
      "created_at": "2026-01-01T00:00:00Z"
    }
  ]
}
```

---

### Get Event Detail

Get a single event with all its markets.

```
GET /api/events/<slug>/
```

**Authentication:** None required

**Response (200 OK):**
```json
{
  "id": 1,
  "title": "2024 US Presidential Election",
  "slug": "2024-us-presidential-election",
  "description": "Predict the next US President",
  "category": "politics",
  "category_name": "Politics",
  "status": "active",
  "thumbnail_url": "http://localhost:8000/media/events/election.jpg",
  "markets": [
    {
      "id": 50,
      "title": "Will Biden win?",
      "slug": "will-biden-win",
      "status": "active",
      "last_yes_price": 45,
      "last_no_price": 55,
      "total_volume": 10000,
      "is_trading_active": true
    }
  ],
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

## Market Endpoints

### List Markets

Get all active markets.

```
GET /api/markets/
```

**Authentication:** None required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| event | string | Filter by event slug |
| status | string | Filter by `active`, `settled`, `cancelled` |

**Response (200 OK):**
```json
{
  "count": 50,
  "next": "http://localhost:8000/api/markets/?page=2",
  "previous": null,
  "results": [
    {
      "id": 50,
      "title": "Will aliens be confirmed in 2025?",
      "slug": "will-aliens-be-confirmed-2025",
      "event_title": "Alien Disclosure Events",
      "event_slug": "alien-disclosure-events",
      "status": "active",
      "last_yes_price": 68,
      "last_no_price": 32,
      "total_volume": 346,
      "is_trading_active": true,
      "yes_probability": "0.68",
      "thumbnail_url": "http://localhost:8000/media/events/aliens.jpg"
    }
  ]
}
```

---

### Get Market Detail

Get detailed information about a market.

```
GET /api/markets/<id>/
```

**Authentication:** None required

**Response (200 OK):**
```json
{
  "id": 50,
  "title": "Will aliens be confirmed in 2025?",
  "slug": "will-aliens-be-confirmed-2025",
  "description": "Resolution: Official US government confirmation",
  "event": {
    "id": 10,
    "title": "Alien Disclosure Events",
    "slug": "alien-disclosure-events"
  },
  "status": "active",
  "resolution": null,
  "last_yes_price": 68,
  "last_no_price": 32,
  "best_yes_bid": 67,
  "best_yes_ask": 69,
  "best_no_bid": 31,
  "best_no_ask": 33,
  "total_volume": 346,
  "is_trading_active": true,
  "yes_probability": "0.68",
  "created_at": "2025-12-01T00:00:00Z",
  "resolved_at": null
}
```

---

### Get Order Book

Get the current order book for a market.

```
GET /api/markets/<id>/orderbook/
```

**Authentication:** None required

**Response (200 OK):**
```json
{
  "market_id": 50,
  "last_yes_price": 68,
  "last_no_price": 32,
  "best_yes_bid": 67,
  "best_yes_ask": 69,
  "best_no_bid": 31,
  "best_no_ask": 33,
  "orderbook": {
    "yes_bids": [
      {"price": 67, "quantity": 100},
      {"price": 65, "quantity": 50},
      {"price": 60, "quantity": 200}
    ],
    "yes_asks": [
      {"price": 69, "quantity": 75},
      {"price": 70, "quantity": 120}
    ],
    "no_bids": [
      {"price": 31, "quantity": 80},
      {"price": 30, "quantity": 150}
    ],
    "no_asks": [
      {"price": 33, "quantity": 60},
      {"price": 35, "quantity": 100}
    ]
  }
}
```

---

### Get Recent Trades

Get recent trades for a market.

```
GET /api/markets/<id>/trades/
```

**Authentication:** None required

**Response (200 OK):**
```json
{
  "market_id": 50,
  "trades": [
    {
      "id": 264,
      "contract_type": "yes",
      "price": 68,
      "quantity": 10,
      "trade_type": "direct",
      "executed_at": "2026-01-03T12:00:00Z"
    }
  ]
}
```

---

### Get Price History

Get price history for charts.

```
GET /api/markets/<id>/price-history/
```

**Authentication:** None required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| period | string | `1h`, `24h`, `7d`, `30d`, `all` (default: `24h`) |

**Response (200 OK):**
```json
{
  "market_id": 50,
  "period": "24h",
  "data": [
    {
      "timestamp": "2026-01-02T12:00:00Z",
      "yes_price": 65,
      "no_price": 35,
      "volume": 50
    },
    {
      "timestamp": "2026-01-03T12:00:00Z",
      "yes_price": 68,
      "no_price": 32,
      "volume": 25
    }
  ]
}
```

---

### Get User Position

Get the current user's position in a market.

```
GET /api/markets/<id>/position/
```

**Authentication:** Required

**Response (200 OK):**
```json
{
  "market_id": 50,
  "yes_quantity": 10,
  "no_quantity": 0,
  "reserved_yes_quantity": 0,
  "reserved_no_quantity": 0,
  "yes_avg_price": "0.65",
  "no_avg_price": "0.00",
  "yes_cost_basis": "6.50",
  "no_cost_basis": "0.00",
  "yes_unrealized_pnl": "0.30",
  "no_unrealized_pnl": "0.00",
  "total_unrealized_pnl": "0.30",
  "realized_pnl": "0.00"
}
```

---

### Place Order

Place a new order in a market.

```
POST /api/markets/<id>/orders/
```

**Authentication:** Required

**Request Body:**
```json
{
  "side": "buy",
  "contract_type": "yes",
  "order_type": "limit",
  "price": 65,
  "quantity": 10
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| side | string | Yes | `buy` or `sell` |
| contract_type | string | Yes | `yes` or `no` |
| order_type | string | Yes | `limit` or `market` |
| price | integer | Limit only | Price in cents (1-99) |
| quantity | integer | Yes | Number of contracts |

**Response (201 Created):**
```json
{
  "order": {
    "id": 500,
    "market_id": 50,
    "side": "buy",
    "contract_type": "yes",
    "order_type": "limit",
    "price": 65,
    "quantity": 10,
    "filled_quantity": 0,
    "status": "open",
    "created_at": "2026-01-03T12:00:00Z"
  },
  "message": "Order placed successfully. Pending matching."
}
```

**Error Response (400 Bad Request):**
```json
{
  "error": "insufficient_funds",
  "message": "Insufficient funds. Need $6.50, have $5.00",
  "required": 6.50,
  "available": 5.00
}
```

---

### Quick Order

Place a quick bet (market order).

```
POST /api/markets/<id>/quick-order/
```

**Authentication:** Required

**Request Body:**
```json
{
  "side": "buy",
  "contract_type": "yes",
  "amount": 10.00
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| side | string | Yes | `buy` or `sell` |
| contract_type | string | Yes | `yes` or `no` |
| amount | decimal | Yes | Dollar amount to spend |

**Response (201 Created):**
```json
{
  "order": {
    "id": 501,
    "status": "filled",
    "filled_quantity": 15
  },
  "trades": [
    {
      "price": 66,
      "quantity": 10
    },
    {
      "price": 67,
      "quantity": 5
    }
  ],
  "message": "Order filled. Bought 15 YES contracts."
}
```

---

### Order Preview

Preview an order before placing it.

```
POST /api/markets/<id>/order-preview/
```

**Authentication:** Required

**Request Body:**
```json
{
  "side": "buy",
  "contract_type": "yes",
  "order_type": "limit",
  "price": 65,
  "quantity": 10
}
```

**Response (200 OK):**
```json
{
  "valid": true,
  "estimated_cost": 6.50,
  "estimated_avg_price": 0.65,
  "potential_profit": 3.50,
  "potential_loss": 6.50,
  "available_tokens": 500.00,
  "tokens_after": 493.50
}
```

---

### Mint Complete Set

Mint 1 YES + 1 NO share for $1.

```
POST /api/markets/<id>/mint/
```

**Authentication:** Required

**Request Body:**
```json
{
  "quantity": 10
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| quantity | integer | Yes | Number of sets to mint |

**Response (201 Created):**
```json
{
  "message": "Minted 10 complete sets for $10.00",
  "quantity": 10,
  "cost": 10.00,
  "position": {
    "yes_quantity": 10,
    "no_quantity": 10
  }
}
```

---

### Redeem Complete Set

Redeem 1 YES + 1 NO share for $1.

```
POST /api/markets/<id>/redeem/
```

**Authentication:** Required

**Request Body:**
```json
{
  "quantity": 5
}
```

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| quantity | integer | Yes | Number of sets to redeem |

**Response (200 OK):**
```json
{
  "message": "Redeemed 5 complete sets for $5.00",
  "quantity": 5,
  "payout": 5.00,
  "position": {
    "yes_quantity": 5,
    "no_quantity": 5
  }
}
```

---

## Order Endpoints

### List User Orders

Get all orders for the current user.

```
GET /api/orders/
```

**Authentication:** Required

**Query Parameters:**
| Parameter | Type | Description |
|-----------|------|-------------|
| status | string | Filter by `open`, `filled`, `partially_filled`, `cancelled` |
| market | integer | Filter by market ID |
| side | string | Filter by `buy` or `sell` |
| contract_type | string | Filter by `yes` or `no` |

**Response (200 OK):**
```json
{
  "count": 10,
  "next": null,
  "previous": null,
  "results": [
    {
      "id": 500,
      "market_id": 50,
      "market_title": "Will aliens be confirmed in 2025?",
      "side": "buy",
      "contract_type": "yes",
      "order_type": "limit",
      "price": 65,
      "quantity": 10,
      "filled_quantity": 5,
      "status": "partially_filled",
      "created_at": "2026-01-03T12:00:00Z"
    }
  ]
}
```

---

### Get Order Detail

Get a single order.

```
GET /api/orders/<id>/
```

**Authentication:** Required

**Response (200 OK):**
```json
{
  "id": 500,
  "market_id": 50,
  "market_title": "Will aliens be confirmed in 2025?",
  "side": "buy",
  "contract_type": "yes",
  "order_type": "limit",
  "price": 65,
  "quantity": 10,
  "filled_quantity": 5,
  "status": "partially_filled",
  "created_at": "2026-01-03T12:00:00Z"
}
```

---

### Cancel Order

Cancel an open or partially filled order.

```
DELETE /api/orders/<id>/
```

**Authentication:** Required

**Response (200 OK):**
```json
{
  "message": "Order cancelled successfully.",
  "order": {
    "id": 500,
    "status": "cancelled",
    "filled_quantity": 5,
    "refunded": 3.25
  }
}
```

**Error Response (400 Bad Request):**
```json
{
  "error": "order_not_cancellable",
  "message": "Order cannot be cancelled. Current status: filled"
}
```

---

## Error Responses

All error responses follow this format:

```json
{
  "error": "error_code",
  "message": "Human readable message",
  "field": "optional field name"
}
```

### Common Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `insufficient_funds` | 400 | User lacks tokens for order |
| `insufficient_position` | 400 | User lacks shares for sell |
| `invalid_price` | 400 | Price outside 1-99 cents |
| `invalid_quantity` | 400 | Quantity must be positive |
| `market_not_active` | 400 | Market is not open for trading |
| `order_not_found` | 404 | Order doesn't exist |
| `order_not_cancellable` | 400 | Order cannot be cancelled |
| `self_trade_error` | 400 | Cannot trade with yourself |

### Authentication Error Codes

| Code | HTTP Status | Description |
|------|-------------|-------------|
| `username_taken` | 400 | Username already exists |
| `phone_registered` | 400 | Phone already registered |
| `user_not_found` | 400/404 | No account with this phone |
| `invalid_phone` | 400 | Invalid phone number format |
| `invalid_code` | 400 | Verification code incorrect |
| `code_expired` | 400 | Code expired (10 min limit) |
| `verification_not_found` | 404 | No pending verification |
| `rate_limit_exceeded` | 429 | Too many requests |
| `cooldown_active` | 429 | Must wait before retrying |

---

## Rate Limits

### Authentication Endpoints
| Limit | Description |
|-------|-------------|
| 5 requests/hour | Per phone number for verification codes |
| 30 second cooldown | Between code requests |

### Other Endpoints
Currently no rate limits are enforced. This may change in production.

---

## Polling Recommendations

Since this API uses polling instead of WebSockets:

| Data | Recommended Interval |
|------|---------------------|
| Orderbook | 2-5 seconds (on trading screen) |
| Recent trades | 5-10 seconds |
| Portfolio | 10-30 seconds |
| Market list | 30-60 seconds |
| Price history | 60 seconds |

---

## Interactive Documentation

Swagger UI is available at `/api/docs/` when the server is running.

OpenAPI schema available at `/api/schema/`.
