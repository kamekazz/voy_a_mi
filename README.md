# Voy a Mi

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-6.x-green.svg)](https://www.djangoproject.com/)
[![DRF](https://img.shields.io/badge/DRF-3.14-red.svg)](https://www.django-rest-framework.org/)
[![License](https://img.shields.io/badge/License-Open%20Source-brightgreen.svg)](#license)

**Voy a Mi** is an open-source prediction market **REST API** built with Django. It provides a backend for mobile apps where users can trade on the outcomes of real-world events by buying and selling YES/NO contracts.

> *"Voy a Mi"* roughly means "I bet on myself" in Spanish, capturing the spirit of confidence in your predictions!

## Overview

Voy a Mi empowers users to trade on real-world events in a stock-market-like environment. Users can buy and sell shares in an event's outcome (for example, "Will candidate X win the election?") and profit if they predict correctly.

Each market uses **YES/NO contracts** that settle at:
- **$1** if the answer is YES (outcome happens)
- **$0** if NO (outcome doesn't happen)

### Key Goals

- **Mobile-First API**: Pure REST API designed for mobile app integration
- **Accessible Prediction Markets**: Make it easy for anyone to participate in markets for events in politics, sports, finance, etc.
- **Secure Authentication**: JWT token-based authentication for mobile apps
- **Transparency and Learning**: Offer a clear view of how prediction markets work
- **Open Collaboration**: Build this as a community-driven, non-profit project

## Features

- **Trade on Event Outcomes**: Buy and sell shares (YES or NO contracts) on event outcomes. Correct predictions pay out $1 each.

- **Order Book Matching Engine**: Full limit order book system similar to a stock exchange. Orders are matched based on price and time priority.

- **Complete Set Minting**: Polymarket-style minting - pay $1 to create 1 YES + 1 NO share pair. This ensures market liquidity.

- **Complete Set Redemption**: Burn 1 YES + 1 NO share pair to receive $1 back.

- **Mint/Merge Matching**: Complementary orders are automatically matched - BUY YES + BUY NO creates shares, SELL YES + SELL NO burns shares.

- **Portfolio & Account Management**: Track positions, calculate profit/loss, review open orders, trade history, and transaction logs.

- **Events & Categories**: Markets organized into Events with categories (Politics, Sports, Finance, etc.) for easy browsing.

- **Market Settlement**: Admins can settle markets when outcomes are known, automatically resolving contracts.

- **Admin Panel**: Secure Django admin interface for managing categories, events, markets, and users.

- **JWT Authentication**: Secure token-based authentication for mobile apps.

- **OpenAPI Documentation**: Interactive Swagger UI documentation at `/api/docs/`.

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Django 6 (Python 3) |
| **API Framework** | Django REST Framework |
| **Authentication** | JWT (djangorestframework-simplejwt) |
| **Documentation** | OpenAPI/Swagger (drf-spectacular) |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Trading Engine** | Custom order book with price-time priority matching |
| **Payments** | Stripe & PayPal SDK (integration ready) |
| **Deployment** | Gunicorn, Nginx, Whitenoise |
| **Config** | python-dotenv for environment variables |

## Installation & Setup

### 1. Clone the Repository

```bash
git clone https://github.com/kamekazz/voy_a_mi.git
cd voy_a_mi
```

### 2. Create a Virtual Environment

```bash
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Apply Database Migrations

```bash
python manage.py migrate
```

### 5. Create a Superuser (Admin Account)

```bash
python manage.py createsuperuser
```

### 6. Run the Development Server

```bash
python manage.py runserver
```

API available at http://localhost:8000/api/

### 7. Run the Matching Engine (Important!)

The application uses a separate process to match orders. Without this running, orders will sit in the order book but trades won't execute.

Open a **new terminal**, activate your virtual environment, and run:

```bash
python manage.py run_engine
```

You should see output indicating the engine is starting and processing trades.

## API Endpoints

| Method | Endpoint | Auth | Description |
|--------|----------|------|-------------|
| POST | `/api/auth/register/` | No | Create new account |
| POST | `/api/auth/login/` | No | Get JWT tokens |
| POST | `/api/auth/refresh/` | No | Refresh access token |
| GET | `/api/user/profile/` | Yes | Get user profile |
| PATCH | `/api/user/profile/` | Yes | Update user profile |
| GET | `/api/user/portfolio/` | Yes | Get positions + P&L |
| GET | `/api/user/trades/` | Yes | Get trade history |
| GET | `/api/user/transactions/` | Yes | Get transaction history |
| GET | `/api/categories/` | No | List all categories |
| GET | `/api/events/` | No | List all events |
| GET | `/api/events/<slug>/` | No | Get event details |
| GET | `/api/markets/` | No | List all markets |
| GET | `/api/markets/<id>/` | No | Get market details |
| GET | `/api/markets/<id>/orderbook/` | No | Get order book |
| GET | `/api/markets/<id>/trades/` | No | Get recent trades |
| GET | `/api/markets/<id>/position/` | Yes | Get user's position |
| GET | `/api/markets/<id>/price-history/` | No | Get price history |
| POST | `/api/markets/<id>/orders/` | Yes | Place an order |
| POST | `/api/markets/<id>/quick-order/` | Yes | Quick bet |
| POST | `/api/markets/<id>/order-preview/` | Yes | Preview order |
| POST | `/api/markets/<id>/mint/` | Yes | Mint complete set |
| POST | `/api/markets/<id>/redeem/` | Yes | Redeem complete set |
| GET | `/api/orders/` | Yes | List user's orders |
| DELETE | `/api/orders/<id>/` | Yes | Cancel an order |
| GET | `/api/docs/` | No | Swagger UI docs |
| GET | `/api/schema/` | No | OpenAPI schema |

See `API.md` for complete API documentation with request/response examples.

## Authentication

This API uses JWT (JSON Web Tokens) for authentication.

### Getting Tokens

```bash
# Login to get tokens
curl -X POST http://localhost:8000/api/auth/login/ \
  -H "Content-Type: application/json" \
  -d '{"username": "your_username", "password": "your_password"}'
```

Response:
```json
{
  "access": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9...",
  "refresh": "eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
}
```

### Using Tokens

Include the access token in the Authorization header:

```bash
curl http://localhost:8000/api/user/profile/ \
  -H "Authorization: Bearer eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9..."
```

### Token Lifetime

- **Access Token**: 60 minutes
- **Refresh Token**: 7 days

## Production Deployment

For production setups:

1. Configure environment variables (secret keys, Stripe/PayPal keys, database URL)
2. Use PostgreSQL instead of SQLite
3. Run with Gunicorn behind Nginx
4. Use the included `voy_a_mi.service` systemd file for deployment
5. Run `python manage.py collectstatic` for static files

## Development Workflow

### Merging and Updating

When working on features, follow this standard git workflow to keep your branch up to date and merge changes:

1.  **Fetch latest changes:**
    ```bash
    git fetch origin
    ```

2.  **Merge main into your branch** (to resolve conflicts):
    ```bash
    git merge origin/main
    ```

3.  **Push your changes:**
    ```bash
    git push origin your-branch-name
    ```

4.  **Create a Pull Request** on GitHub to merge into `main`.

### Common Commands

-   **Make Migrations:** `python manage.py makemigrations`
-   **Migrate:** `python manage.py migrate`
-   **Run Engine:** `python manage.py run_engine`
-   **Run Server:** `python manage.py runserver`

## Contributing

Contributions are highly appreciated! As a community-driven and nonprofit project, Voy a Mi thrives on the ideas and support of developers.

**Ways to contribute:**

- **Fork & Submit PRs**: For new features or bug fixes
- **Report Issues**: Use GitHub Issues for bugs, feature requests, or questions
- **Discuss & Brainstorm**: Open issues to discuss project direction and ideas
- **Spread the Word**: Star the repo and share it with others

This project is **non-profit and open-source** - we're building it for the community and for learning.

## License

This project is intended to be open-source. License information will be added once decided.

---

**Join us in making prediction markets accessible and fun for everyone!**
