# Voy a Mi

[![Python](https://img.shields.io/badge/Python-3.x-blue.svg)](https://www.python.org/)
[![Django](https://img.shields.io/badge/Django-4.x-green.svg)](https://www.djangoproject.com/)
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

- **Automated Market Maker (AMM)**: LMSR-based automated market maker provides instant liquidity for markets, ensuring markets are always tradeable.

- **Portfolio & Account Management**: Track positions, calculate profit/loss, review open orders, trade history, and transaction logs.

- **Events & Categories**: Markets organized into Events with categories (Politics, Sports, Finance, etc.) for easy browsing.

- **Market Settlement**: Admins can settle markets when outcomes are known, automatically resolving contracts.

- **Admin Panel**: Secure Django admin interface for managing categories, events, markets, and users.

- **Real-Time Updates**: Django Channels and WebSockets push live updates - prices and order books update instantly.

- **Analytics (Planned)**: Market volume, price charts, and leaderboards for top forecasters.

## Tech Stack

| Component | Technology |
|-----------|------------|
| **Backend** | Django 4 (Python 3) |
| **Database** | SQLite (dev) / PostgreSQL (prod) |
| **Frontend** | Django Templates, Bootstrap 5, Bootstrap Icons |
| **Real-Time** | Django Channels, WebSockets, Daphne (ASGI) |
| **Trading Engine** | Custom order book + LMSR-based AMM |
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

### 6. (Optional) Load Sample Data

```bash
python manage.py create_test_markets
```

This populates the database with example categories, events, and markets (~20 events, ~40 markets).

### 7. Run the Development Server

```bash
python manage.py runserver
```

Open http://localhost:8000/ in your browser.

## URL Structure

| Path | Description |
|------|-------------|
| `/` | Homepage with active markets |
| `/events/` | Browse all events |
| `/events/<slug>/` | Event detail with all markets |
| `/markets/<id>/` | Market trading interface with orderbook |
| `/portfolio/` | User's positions and P&L |
| `/orders/` | Order history |
| `/trades/` | Trade history |
| `/transactions/` | Balance transaction history |
| `/admin/` | Django admin panel |

## Production Deployment

For production setups:

1. Configure environment variables (secret keys, Stripe/PayPal keys, database URL)
2. Use PostgreSQL instead of SQLite
3. Run with Daphne (ASGI) and Gunicorn (WSGI) behind Nginx
4. Use the included `voy_a_mi.service` systemd file for deployment
5. Run `python manage.py collectstatic` for static files

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
