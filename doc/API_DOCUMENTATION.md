# Voy a Mi - Prediction Market API Documentation

**Version:** 1.0
**Base URL:** `http://localhost:8000/api/` (Development)
**API Type:** REST API with JWT Authentication

---

## Table of Contents

1. [Getting Started](#getting-started)
2. [Authentication](#authentication)
3. [API Endpoints](#api-endpoints)
   - [Authentication Endpoints](#authentication-endpoints)
   - [User Endpoints](#user-endpoints)
   - [Category Endpoints](#category-endpoints)
   - [Event Endpoints](#event-endpoints)
   - [Market Endpoints](#market-endpoints)
   - [Order Endpoints](#order-endpoints)
4. [Error Handling](#error-handling)
5. [Mobile App Integration Guide](#mobile-app-integration-guide)

---

## Getting Started

### Quick Start Flow

1. **Register a new user** → Receive JWT tokens
2. **Use access token** in Authorization header for all authenticated requests
3. **Browse markets** → Get events and markets (no auth required)
4. **Place orders** → Buy/Sell YES/NO contracts
5. **Track portfolio** → View positions and P&L

### Base URL

All API endpoints are prefixed with:
```
http://localhost:8000/api/
```

For production, replace with your production domain.

### Authentication Header

All authenticated requests must include:
```
Authorization: Bearer <access_token>
```

### Response Format

All responses are in JSON format.

---

## Authentication

### JWT Token System

This API uses JWT (JSON Web Tokens) for authentication:

- **Access Token:** Short-lived token (expires in 5-15 minutes) used for API requests
- **Refresh Token:** Long-lived token (expires in 7-30 days) used to get new access tokens

**Token Lifecycle:**
1. Login/Register → Get both tokens
2. Store refresh token securely
3. Use access token for API calls
4. When access token expires → Use refresh token to get new access token
5. When refresh token expires → User must login again

---

## API Endpoints

### Authentication Endpoints

#### 1. Register New User

Create a new user account and receive JWT tokens immediately.

```http
POST /api/auth/register/
```

**Authentication:** None required

**Request Body:**
```json
{
  "username": "johndoe",
  "email": "john@example.com",
  "password": "SecurePass123",
  "password_confirm": "SecurePass123",
  "first_name": "John",
  "last_name": "Doe"
}
```

**Fields:**

| Field | Type | Required | Validation |
|-------|------|----------|------------|
| username | string | Yes | Alphanumeric, unique |
| email | string | Yes | Valid email, unique |
| password | string | Yes | Min 8 chars, not too common |
| password_confirm | string | Yes | Must match password |
| first_name | string | No | Any string |
| last_name | string | No | Any string |

**Success Response (201 Created):**
```json
{
  "user": {
    "id": 1,
    "username": "johndoe",
    "email": "john@example.com",
    "first_name": "John",
    "last_name": "Doe",
    "balance": "0.00",
    "reserved_balance": "0.00",
    "available_balance": "0.00",
    "date_joined": "2026-01-14T12:00:00Z"
  },
  "tokens": {
    "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
    "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
  },
  "message": "Account created successfully."
}
```

**Error Response (400 Bad Request):**
```json
{
  "username": ["A user with this username already exists."],
  "email": ["A user with this email already exists."],
  "password": ["This password is too common."]
}
```

---

#### 2. Login

Authenticate and receive JWT tokens.

```http
POST /api/auth/login/
```

**Authentication:** None required

**Request Body:**
```json
{
  "username": "johndoe",
  "password": "SecurePass123"
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| username | string | Yes | User's username |
| password | string | Yes | User's password |

**Success Response (200 OK):**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Error Response (401 Unauthorized):**
```json
{
  "detail": "No active account found with the given credentials"
}
```

---

#### 3. Refresh Token

Get a new access token using your refresh token.

```http
POST /api/auth/refresh/
```

**Authentication:** None required (but needs refresh token)

**Request Body:**
```json
{
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| refresh | string | Yes | Valid refresh token |

**Success Response (200 OK):**
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

**Error Response (401 Unauthorized):**
```json
{
  "detail": "Token is invalid or expired",
  "code": "token_not_valid"
}
```

---

### User Endpoints

#### 4. Get User Profile

Retrieve the current authenticated user's profile information.

```http
GET /api/user/profile/
```

**Authentication:** Required

**Success Response (200 OK):**
```json
{
  "id": 1,
  "username": "johndoe",
  "email": "john@example.com",
  "first_name": "John",
  "last_name": "Doe",
  "balance": "100.00",
  "reserved_balance": "25.00",
  "available_balance": "75.00",
  "date_joined": "2026-01-14T12:00:00Z"
}
```

**Balance Fields:**
- `balance`: Total balance (available + reserved)
- `reserved_balance`: Funds locked in open orders
- `available_balance`: Funds available for new orders

---

#### 5. Update User Profile

Update user's profile information.

```http
PATCH /api/user/profile/
```

**Authentication:** Required

**Request Body:**
```json
{
  "first_name": "Johnny",
  "last_name": "Smith",
  "email": "johnny@example.com"
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| first_name | string | No | User's first name |
| last_name | string | No | User's last name |
| email | string | No | Valid email address |

**Note:** Username and balance cannot be changed via this endpoint.

**Success Response (200 OK):**
```json
{
  "id": 1,
  "username": "johndoe",
  "email": "johnny@example.com",
  "first_name": "Johnny",
  "last_name": "Smith",
  "balance": "100.00",
  "reserved_balance": "25.00",
  "available_balance": "75.00",
  "date_joined": "2026-01-14T12:00:00Z"
}
```

---

#### 6. Get Portfolio

View user's complete portfolio with all positions and P&L.

```http
GET /api/user/portfolio/
```

**Authentication:** Required

**Success Response (200 OK):**
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
    "balance": 100.00,
    "reserved_balance": 25.00,
    "available_balance": 75.00,
    "total_unrealized_pnl": 0.30,
    "total_realized_pnl": 0.00,
    "positions_count": 1
  }
}
```

**Position Fields:**
- `yes_quantity` / `no_quantity`: Shares owned
- `reserved_yes_quantity` / `reserved_no_quantity`: Shares in open sell orders
- `yes_avg_price` / `no_avg_price`: Average purchase price
- `yes_cost_basis` / `no_cost_basis`: Total amount spent
- `current_yes_price` / `current_no_price`: Current market price
- `unrealized_pnl`: Profit/Loss if sold at current price
- `realized_pnl`: Actual profit/loss from closed positions

---

#### 7. Get Trade History

View all executed trades for the user.

```http
GET /api/user/trades/
```

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| market | integer | Any market ID | Filter by specific market |
| contract_type | string | `yes`, `no` | Filter by contract type |
| trade_type | string | `direct`, `mint`, `merge` | Filter by trade type |
| page | integer | 1, 2, 3... | Pagination |

**Example Request:**
```
GET /api/user/trades/?market=50&contract_type=yes
```

**Success Response (200 OK):**
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
      "executed_at": "2026-01-14T12:00:00Z"
    }
  ]
}
```

**Trade Types:**
- `direct`: Standard trade (BUY YES matched with SELL YES)
- `mint`: Complementary buy match (BUY YES + BUY NO → mints shares)
- `merge`: Complementary sell match (SELL YES + SELL NO → burns shares)

---

#### 8. Get Transaction History

View all balance transactions (deposits, withdrawals, trades, etc.).

```http
GET /api/user/transactions/
```

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| type | string | See transaction types below | Filter by type |
| market | integer | Any market ID | Filter by market |
| page | integer | 1, 2, 3... | Pagination |

**Transaction Types:**
- `deposit` - Money added to account
- `withdrawal` - Money withdrawn
- `trade_buy` - Money spent buying contracts
- `trade_sell` - Money received selling contracts
- `settlement_win` - Payout from winning contract
- `settlement_loss` - Loss from losing contract
- `order_reserve` - Funds reserved for open order
- `order_release` - Funds released from cancelled order
- `refund` - Refund for any reason
- `mint` - Cost of minting complete set
- `redeem` - Payout from redeeming complete set
- `mint_match` - Mint through complementary buy orders
- `merge_match` - Merge through complementary sell orders

**Example Request:**
```
GET /api/user/transactions/?type=trade_buy&market=50
```

**Success Response (200 OK):**
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
      "balance_after": "96.60",
      "description": "Bought 5 YES @ $0.68",
      "market_id": 50,
      "market_title": "Will aliens be confirmed in 2025?",
      "created_at": "2026-01-14T12:00:00Z"
    }
  ]
}
```

---

### Category Endpoints

#### 9. List Categories

Get all prediction market categories.

```http
GET /api/categories/
```

**Authentication:** None required (public endpoint)

**Success Response (200 OK):**
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
      "icon": "🚨",
      "display_order": 1,
      "event_count": 10
    },
    {
      "id": 2,
      "name": "Sports",
      "slug": "sports",
      "description": "Sports events and outcomes",
      "icon": "⚽",
      "display_order": 2,
      "event_count": 15
    }
  ]
}
```

---

#### 10. Get Category Detail

Get a single category by slug with all its events.

```http
GET /api/categories/<slug>/
```

**Authentication:** None required

**Example Request:**
```
GET /api/categories/politics/
```

**Success Response (200 OK):**
```json
{
  "id": 1,
  "name": "Politics",
  "slug": "politics",
  "description": "Political events and elections",
  "icon": "🚨",
  "display_order": 1,
  "event_count": 10
}
```

---

### Event Endpoints

#### 11. List Events

Get all prediction events.

```http
GET /api/events/
```

**Authentication:** None required (public endpoint)

**Query Parameters:**

| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| category | string | Category slug | Filter by category |
| status | string | `active`, `settled`, `cancelled` | Filter by status |
| page | integer | 1, 2, 3... | Pagination |

**Example Request:**
```
GET /api/events/?category=politics&status=active
```

**Success Response (200 OK):**
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

#### 12. Get Event Detail

Get complete details of a single event including all its markets.

```http
GET /api/events/<slug>/
```

**Authentication:** None required

**Example Request:**
```
GET /api/events/2024-us-presidential-election/
```

**Success Response (200 OK):**
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
    },
    {
      "id": 51,
      "title": "Will Trump win?",
      "slug": "will-trump-win",
      "status": "active",
      "last_yes_price": 55,
      "last_no_price": 45,
      "total_volume": 12000,
      "is_trading_active": true
    }
  ],
  "created_at": "2026-01-01T00:00:00Z"
}
```

---

### Market Endpoints

#### 13. List Markets

Get all available markets for trading.

```http
GET /api/markets/
```

**Authentication:** None required (public endpoint)

**Query Parameters:**

| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| event | string | Event slug | Filter by event |
| status | string | `active`, `settled`, `cancelled` | Filter by status |
| page | integer | 1, 2, 3... | Pagination |

**Example Request:**
```
GET /api/markets/?event=2024-us-presidential-election&status=active
```

**Success Response (200 OK):**
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

**Price Format:** Prices are in cents (1-99). A price of 68 = $0.68 per share.

---

#### 14. Get Market Detail

Get detailed information about a specific market.

```http
GET /api/markets/<id>/
```

**Authentication:** None required

**Example Request:**
```
GET /api/markets/50/
```

**Success Response (200 OK):**
```json
{
  "id": 50,
  "title": "Will aliens be confirmed in 2025?",
  "slug": "will-aliens-be-confirmed-2025",
  "description": "Resolution: Official US government confirmation of alien life",
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

**Key Fields:**
- `last_yes_price` / `last_no_price`: Last trade price
- `best_yes_bid` / `best_yes_ask`: Best buy/sell prices for YES
- `best_no_bid` / `best_no_ask`: Best buy/sell prices for NO
- `resolution`: Outcome when settled (`yes`, `no`, or `null`)
- `is_trading_active`: Whether market is accepting orders

---

#### 15. Get Order Book

View the current order book (all open orders) for a market.

```http
GET /api/markets/<id>/orderbook/
```

**Authentication:** None required

**Example Request:**
```
GET /api/markets/50/orderbook/
```

**Success Response (200 OK):**
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

**Understanding Order Book:**
- `yes_bids`: Buy orders for YES (traders willing to buy YES at these prices)
- `yes_asks`: Sell orders for YES (traders willing to sell YES at these prices)
- `no_bids`: Buy orders for NO
- `no_asks`: Sell orders for NO

**Recommendation:** Poll this endpoint every 2-5 seconds when user is on trading screen.

---

#### 16. Get Recent Trades

View recent executed trades for a market.

```http
GET /api/markets/<id>/trades/
```

**Authentication:** None required

**Example Request:**
```
GET /api/markets/50/trades/
```

**Success Response (200 OK):**
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
      "executed_at": "2026-01-14T12:00:00Z"
    },
    {
      "id": 263,
      "contract_type": "no",
      "price": 32,
      "quantity": 5,
      "trade_type": "direct",
      "executed_at": "2026-01-14T11:55:00Z"
    }
  ]
}
```

**Recommendation:** Poll every 5-10 seconds for trade feed.

---

#### 17. Get Price History

Get historical price data for charts.

```http
GET /api/markets/<id>/price-history/
```

**Authentication:** None required

**Query Parameters:**

| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| period | string | `1h`, `24h`, `7d`, `30d`, `all` | Time period (default: `24h`) |

**Example Request:**
```
GET /api/markets/50/price-history/?period=7d
```

**Success Response (200 OK):**
```json
{
  "market_id": 50,
  "period": "7d",
  "data": [
    {
      "timestamp": "2026-01-08T12:00:00Z",
      "yes_price": 62,
      "no_price": 38,
      "volume": 120
    },
    {
      "timestamp": "2026-01-09T12:00:00Z",
      "yes_price": 65,
      "no_price": 35,
      "volume": 80
    },
    {
      "timestamp": "2026-01-14T12:00:00Z",
      "yes_price": 68,
      "no_price": 32,
      "volume": 146
    }
  ]
}
```

**Use Case:** Display price charts in your app. Fetch once on load and update periodically.

---

#### 18. Get User Position in Market

Get the authenticated user's position in a specific market.

```http
GET /api/markets/<id>/position/
```

**Authentication:** Required

**Example Request:**
```
GET /api/markets/50/position/
```

**Success Response (200 OK):**
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

**No Position Response (200 OK):**
```json
{
  "market_id": 50,
  "yes_quantity": 0,
  "no_quantity": 0,
  "reserved_yes_quantity": 0,
  "reserved_no_quantity": 0,
  "yes_avg_price": "0.00",
  "no_avg_price": "0.00",
  "yes_cost_basis": "0.00",
  "no_cost_basis": "0.00",
  "yes_unrealized_pnl": "0.00",
  "no_unrealized_pnl": "0.00",
  "total_unrealized_pnl": "0.00",
  "realized_pnl": "0.00"
}
```

---

#### 19. Place Order

Place a new limit or market order to buy/sell contracts.

```http
POST /api/markets/<id>/orders/
```

**Authentication:** Required

**Request Body (Limit Order):**
```json
{
  "side": "buy",
  "contract_type": "yes",
  "order_type": "limit",
  "price": 65,
  "quantity": 10
}
```

**Request Body (Market Order):**
```json
{
  "side": "buy",
  "contract_type": "yes",
  "order_type": "market",
  "quantity": 10
}
```

**Fields:**

| Field | Type | Required | Options | Description |
|-------|------|----------|---------|-------------|
| side | string | Yes | `buy`, `sell` | Buy or sell |
| contract_type | string | Yes | `yes`, `no` | YES or NO contract |
| order_type | string | Yes | `limit`, `market` | Order type |
| price | integer | If limit | 1-99 | Price in cents (limit orders only) |
| quantity | integer | Yes | > 0 | Number of contracts |

**Success Response (201 Created):**
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
    "created_at": "2026-01-14T12:00:00Z"
  },
  "message": "Order placed successfully. Pending matching."
}
```

**Order Status:**
- `open`: Order is in orderbook, waiting to be matched
- `partially_filled`: Part of the order has been filled
- `filled`: Order completely filled
- `cancelled`: Order was cancelled

**Error Response (400 Bad Request - Insufficient Funds):**
```json
{
  "error": "insufficient_funds",
  "message": "Insufficient funds. Need $6.50, have $5.00",
  "required": 6.50,
  "available": 5.00
}
```

**Error Response (400 Bad Request - Insufficient Position):**
```json
{
  "error": "insufficient_position",
  "message": "Insufficient YES shares. Need 10, have 5",
  "required": 10,
  "available": 5
}
```

**Important Notes:**
1. Orders are not executed immediately - they go into the orderbook
2. A separate matching engine process matches orders
3. Use the `/api/user/trades/` endpoint to see executed trades
4. For instant execution, use the Quick Order endpoint below

---

#### 20. Quick Order (Market Order with Amount)

Place a quick market order by specifying dollar amount to spend.

```http
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

**Fields:**

| Field | Type | Required | Options | Description |
|-------|------|----------|---------|-------------|
| side | string | Yes | `buy`, `sell` | Buy or sell |
| contract_type | string | Yes | `yes`, `no` | YES or NO contract |
| amount | decimal | Yes | > 0 | Dollar amount to spend/receive |

**Success Response (201 Created):**
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

**Use Case:** This is perfect for "Quick Buy" buttons in mobile apps where users specify an amount ($10, $25, $100) rather than quantity.

---

#### 21. Order Preview

Preview an order before placing it to see estimated costs and P&L.

```http
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

**Success Response (200 OK):**
```json
{
  "valid": true,
  "estimated_cost": 6.50,
  "estimated_avg_price": 0.65,
  "potential_profit": 3.50,
  "potential_loss": 6.50,
  "available_balance": 100.00,
  "balance_after": 93.50
}
```

**Use Case:** Call this before showing order confirmation dialog to display costs and potential returns.

---

#### 22. Mint Complete Set

Mint a complete set: Pay $1 to receive 1 YES + 1 NO share.

```http
POST /api/markets/<id>/mint/
```

**Authentication:** Required

**Request Body:**
```json
{
  "quantity": 10
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| quantity | integer | Yes | Number of sets to mint (must be > 0) |

**Success Response (201 Created):**
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

**How It Works:**
1. User pays $1 per set
2. Receives 1 YES + 1 NO share per set
3. Can sell either side independently
4. Guaranteed way to enter market with no slippage

**Example Use Case:**
- Market price: YES = $0.68, NO = $0.32
- User mints 10 sets for $10
- Sells 10 YES at $0.68 = $6.80
- Now owns 10 NO shares, net cost = $3.20 (vs $3.20 buying directly)

---

#### 23. Redeem Complete Set

Redeem a complete set: Burn 1 YES + 1 NO share to receive $1.

```http
POST /api/markets/<id>/redeem/
```

**Authentication:** Required

**Request Body:**
```json
{
  "quantity": 5
}
```

**Fields:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| quantity | integer | Yes | Number of sets to redeem (must be > 0) |

**Success Response (200 OK):**
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

**Error Response (400 Bad Request):**
```json
{
  "error": "insufficient_position",
  "message": "Need 5 YES and 5 NO shares, have 5 YES and 3 NO"
}
```

**How It Works:**
1. User must have at least 1 YES and 1 NO share
2. Both shares are burned (removed)
3. User receives $1 per set

**Example Use Case:**
- User owns 5 YES and 5 NO shares
- Redeems all 5 sets → Receives $5.00
- Guaranteed $1 per set, no slippage

---

### Order Endpoints

#### 24. List User Orders

Get all orders placed by the authenticated user.

```http
GET /api/orders/
```

**Authentication:** Required

**Query Parameters:**

| Parameter | Type | Options | Description |
|-----------|------|---------|-------------|
| status | string | `open`, `filled`, `partially_filled`, `cancelled` | Filter by status |
| market | integer | Any market ID | Filter by market |
| side | string | `buy`, `sell` | Filter by side |
| contract_type | string | `yes`, `no` | Filter by contract type |
| page | integer | 1, 2, 3... | Pagination |

**Example Request:**
```
GET /api/orders/?status=open&contract_type=yes
```

**Success Response (200 OK):**
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
      "created_at": "2026-01-14T12:00:00Z"
    }
  ]
}
```

---

#### 25. Get Order Detail

Get details of a specific order.

```http
GET /api/orders/<id>/
```

**Authentication:** Required

**Example Request:**
```
GET /api/orders/500/
```

**Success Response (200 OK):**
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
  "created_at": "2026-01-14T12:00:00Z"
}
```

---

#### 26. Cancel Order

Cancel an open or partially filled order.

```http
DELETE /api/orders/<id>/
```

**Authentication:** Required

**Example Request:**
```
DELETE /api/orders/500/
```

**Success Response (200 OK):**
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

**Notes:**
- Only `open` and `partially_filled` orders can be cancelled
- Funds reserved for the order are released back to available balance
- For partially filled orders, only unfilled quantity is cancelled

---

## Error Handling

### Error Response Format

All errors follow this consistent format:

```json
{
  "error": "error_code",
  "message": "Human readable error message",
  "field": "optional_field_name"
}
```

### HTTP Status Codes

| Status Code | Meaning | When Used |
|-------------|---------|-----------|
| 200 | OK | Successful GET, PATCH, DELETE |
| 201 | Created | Successful POST (resource created) |
| 400 | Bad Request | Validation error, business logic error |
| 401 | Unauthorized | Missing or invalid authentication token |
| 403 | Forbidden | Authenticated but not authorized |
| 404 | Not Found | Resource doesn't exist |
| 500 | Internal Server Error | Server error |

### Common Error Codes

| Error Code | Description | How to Handle |
|------------|-------------|---------------|
| `insufficient_funds` | Not enough balance | Prompt user to add funds |
| `insufficient_position` | Not enough shares | Show current position and required amount |
| `invalid_price` | Price outside 1-99 range | Validate price on client side |
| `invalid_quantity` | Quantity <= 0 | Validate quantity on client side |
| `market_not_active` | Market closed for trading | Disable trading UI, show status |
| `order_not_found` | Order doesn't exist | Refresh order list |
| `order_not_cancellable` | Order already filled/cancelled | Refresh order status |
| `self_trade_error` | User tried to trade with self | Should not happen with proper UI |
| `token_not_valid` | JWT token expired/invalid | Use refresh token to get new access token |

### Example Error Responses

**Insufficient Funds:**
```json
{
  "error": "insufficient_funds",
  "message": "Insufficient funds. Need $6.50, have $5.00",
  "required": 6.50,
  "available": 5.00
}
```

**Invalid Token:**
```json
{
  "detail": "Token is invalid or expired",
  "code": "token_not_valid"
}
```

**Validation Error:**
```json
{
  "username": ["This username is already taken."],
  "email": ["Enter a valid email address."]
}
```

---

## Mobile App Integration Guide

### Authentication Flow

```
1. App Launch
   ↓
2. Check if refresh token exists in secure storage
   ↓
   YES → Try to get new access token (POST /api/auth/refresh/)
   |      ↓
   |      SUCCESS → Store new access token → Go to Home
   |      ↓
   |      FAIL → Clear tokens → Go to Login
   ↓
   NO → Go to Login

3. Login Screen
   ↓
4. User enters credentials → POST /api/auth/login/
   ↓
5. Store both tokens securely
   ↓
6. Go to Home
```

### Token Storage Recommendations

**iOS:** Use Keychain
**Android:** Use EncryptedSharedPreferences or Android Keystore
**React Native:** Use react-native-keychain

**Never store tokens in:**
- AsyncStorage (React Native)
- SharedPreferences (Android - unencrypted)
- UserDefaults (iOS)
- LocalStorage (if using web)

### API Call Flow

```javascript
// Pseudo-code for API calls
async function apiCall(endpoint, method, data) {
  let accessToken = await getAccessToken()

  let response = await fetch(endpoint, {
    method: method,
    headers: {
      'Authorization': `Bearer ${accessToken}`,
      'Content-Type': 'application/json'
    },
    body: JSON.stringify(data)
  })

  // If 401 Unauthorized, try to refresh token
  if (response.status === 401) {
    let refreshToken = await getRefreshToken()
    let refreshResponse = await fetch('/api/auth/refresh/', {
      method: 'POST',
      body: JSON.stringify({ refresh: refreshToken })
    })

    if (refreshResponse.ok) {
      let tokens = await refreshResponse.json()
      await storeAccessToken(tokens.access)

      // Retry original request
      response = await fetch(endpoint, {
        method: method,
        headers: {
          'Authorization': `Bearer ${tokens.access}`,
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(data)
      })
    } else {
      // Refresh token expired, logout user
      await logout()
      navigateToLogin()
    }
  }

  return response
}
```

### Polling Recommendations

For real-time updates without WebSockets, poll these endpoints:

| Screen | Endpoint | Interval | Priority |
|--------|----------|----------|----------|
| Trading Screen | `/markets/<id>/orderbook/` | 2-5 sec | High |
| Trading Screen | `/markets/<id>/trades/` | 5-10 sec | Medium |
| Portfolio | `/user/portfolio/` | 10-30 sec | Medium |
| Market List | `/markets/` | 30-60 sec | Low |
| Order Book | `/user/orders/?status=open` | 5-10 sec | Medium |

**Optimization Tips:**
- Only poll when screen is active
- Use pull-to-refresh for manual updates
- Pause polling when app goes to background
- Show loading states during initial fetch
- Cache responses and show stale data while fetching

### UI/UX Best Practices

**Order Placement:**
1. Show order preview before submission
2. Display estimated cost, avg price, P&L
3. Confirm with user before placing order
4. Show success/error message after submission
5. Redirect to "Open Orders" screen

**Error Handling:**
1. Parse error codes and show user-friendly messages
2. For `insufficient_funds`, show "Add Funds" button
3. For `insufficient_position`, show current holdings
4. Always provide a way to retry failed requests

**Loading States:**
1. Skeleton screens for initial loads
2. Pull-to-refresh for manual updates
3. Infinite scroll for paginated lists
4. Disable buttons during API calls

**Offline Handling:**
1. Cache market data for offline viewing
2. Queue orders when offline (advanced)
3. Show clear "offline" indicator
4. Retry failed requests when back online

### Testing Checklist

- [ ] Register new user
- [ ] Login with username/password
- [ ] Token refresh on 401 error
- [ ] Browse markets without auth
- [ ] View user profile
- [ ] Place buy order (YES and NO)
- [ ] Place sell order (YES and NO)
- [ ] Cancel open order
- [ ] Mint complete set
- [ ] Redeem complete set
- [ ] View portfolio with positions
- [ ] View trade history
- [ ] View transaction history
- [ ] Test insufficient funds error
- [ ] Test insufficient position error
- [ ] Test expired token handling
- [ ] Test network error handling
- [ ] Test pagination

---

## API Documentation URLs

Interactive documentation is available when the server is running:

- **Swagger UI:** http://localhost:8000/api/docs/
- **ReDoc:** http://localhost:8000/api/redoc/
- **OpenAPI Schema:** http://localhost:8000/api/schema/

---

## Support & Contact

For bugs or feature requests, contact the development team.

For technical questions about integration, refer to the interactive documentation at `/api/docs/`.

---

**Last Updated:** 2026-01-14
**API Version:** 1.0
