# Voy a Mi

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-5.x-green.svg)](https://www.djangoproject.com/)
[![License](https://img.shields.io/badge/License-Open%20Source-brightgreen.svg)](#license)

**Voy a Mi** is an open-source prediction market platform built with Django. It allows users to trade on the outcomes of real-world events by buying and selling YES/NO contracts that pay out based on the event results.

> *"Voy a Mi"* roughly means "I bet on myself" in Spanish, capturing the spirit of confidence in your predictions!

## Overview

Voy a Mi empowers users to trade on real-world events in a stock-market-like environment. Users can buy and sell shares in an event's outcome (for example, "Will candidate X win the election?") and profit if they predict correctly.

Each market uses **YES/NO contracts** that settle at:
- **$1** if the answer is YES (outcome happens)
- **$0** if NO (outcome doesn't happen)

### Key Goals

- **Accessible Prediction Markets**: Make it easy for anyone to create or participate in markets for events in politics, sports, finance, etc.
- **Real-Time Trading**: Provide up-to-the-second updates on prices and trades using WebSockets
- **Transparency and Learning**: Offer a clear view of how prediction markets work for educational and experimental purposes
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

- **Real-Time Updates**: Django Channels and WebSockets push live updates - prices and order books update instantly.

- **Analytics (Planned)**: Market volume, price charts, and leaderboards for top forecasters.

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Django 5/6 (Python 3) |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Frontend** | Django Templates, Bootstrap 5, Bootstrap Icons |
| **Real-Time** | Django Channels, WebSockets, Daphne (ASGI) |
| **Trading Engine** | Custom order book with price-time priority matching |
| **Payments** | Stripe & PayPal SDK (integration ready) |
| **Deployment** | Gunicorn, Daphne, Nginx, Whitenoise |
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

Open http://localhost:8000/ in your browser.


### 7. Run the Matching Engine (Important!)

The application uses a separate process to match orders. Without this running, orders will sit in the order book but trades won't execute.

Open a **new terminal**, activate your virtual environment, and run:

```bash
python manage.py run_engine
```

You should see output indicating the engine is starting and processing trades.

## URL Structure

| Path | Description |
|------|-------------|
| `/` | Homepage with active markets |
| `/events/` | Browse all events |
| `/events/<slug>/` | Event detail with all markets |
| `/market/<id>/` | Market trading interface with orderbook |
| `/portfolio/` | User's positions and P&L |
| `/orders/` | Order history |
| `/trades/` | Trade history |
| `/transactions/` | Balance transaction history |
| `/login/` | User login |
| `/logout/` | User logout |
| `/register/` | User registration |
| `/cancel_order/<id>/` | Cancel an order |
| `/markets/<id>/mint/` | Mint complete set (1 YES + 1 NO) |
| `/markets/<id>/redeem/` | Redeem complete set for $1 |
| `/admin/` | Django admin panel |

## API Endpoints

| Path | Description |
|------|-------------|
| `/api/markets/<id>/orderbook/` | Order book JSON |
| `/api/markets/<id>/trades/` | Recent trades JSON |
| `/api/markets/<id>/position/` | User position JSON |
| `/api/markets/<id>/price-history/` | Price history JSON |

## Production Deployment

For production setups:

1. Configure environment variables (secret keys, Stripe/PayPal keys, database URL)
2. Use PostgreSQL instead of SQLite
3. Run with Daphne (ASGI) and Gunicorn (WSGI) behind Nginx
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

-   **Run Tests:** `python manage.py test`
-   **Make Migrations:** `python manage.py makemigrations`
-   **Migrate:** `python manage.py migrate`
-   **Run Engine:** `python manage.py run_engine`

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
