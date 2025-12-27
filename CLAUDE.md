# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django-based prediction market platform where users can trade on the outcomes of real-world events. Users buy and sell contracts (YES/NO) that pay out based on event outcomes.

## Tech Stack

- **Backend**: Django 5/6 (Python 3.x)
- **Database**: SQLite (development), PostgreSQL (production)
- **Frontend**: Django templates with HTML/CSS/JavaScript, Bootstrap 5
- **Real-time**: Django Channels with WebSockets (for live price updates)
- **Trading Engine**: Custom order book with price-time priority matching
- **Payments**: Stripe or PayPal integration
- **Deployment**: Daphne (ASGI) + Gunicorn + Nginx

## Common Commands

```bash
# Database migrations
python manage.py makemigrations
python manage.py migrate

# Run development server
python manage.py runserver

# Run matching engine (REQUIRED for trades to execute)
python manage.py run_engine

# Create superuser for admin
python manage.py createsuperuser

# Collect static files (production)
python manage.py collectstatic
```

## Architecture

### Core Models

- **User**: Extends Django's AbstractUser; has `balance` and `reserved_balance` for trading
- **Category**: Categories for organizing prediction events
- **Event**: Parent container for related markets (e.g., "2024 US Presidential Election")
- **Market**: Tradeable contracts within an event (YES/NO outcomes)
- **Order**: Orders in the orderbook (buy/sell)
- **Trade**: Matched trades between orders
- **Position**: User's holdings in a specific market (YES/NO contracts with reserved quantities)
- **Transaction**: Audit trail for all balance changes

### Order Types

- `LIMIT` - Standard limit order with specified price
- `MARKET` - Market order executed at best available price
- `MINT_SET` - Request to mint YES+NO pair for $1
- `REDEEM_SET` - Request to redeem YES+NO pair for $1

### Trade Types

- `DIRECT` - Standard matching (BUY YES vs SELL YES)
- `MINT` - Complementary buy orders matched (BUY YES + BUY NO creates shares)
- `MERGE` - Complementary sell orders matched (SELL YES + SELL NO burns shares)

### Transaction Types

`DEPOSIT`, `WITHDRAWAL`, `TRADE_BUY`, `TRADE_SELL`, `SETTLEMENT_WIN`, `SETTLEMENT_LOSS`, `ORDER_RESERVE`, `ORDER_RELEASE`, `REFUND`, `MINT`, `REDEEM`, `MINT_MATCH`, `MERGE_MATCH`

### Key Features

1. **Prediction Market Trading**: Users buy/sell YES/NO contracts on event outcomes
2. **Order Book System**: Price-time priority matching engine
3. **Complete Set Minting**: Users pay $1 to mint 1 YES + 1 NO share (Polymarket-style)
4. **Complete Set Redemption**: Users burn 1 YES + 1 NO share to receive $1
5. **Mint/Merge Matching**: Complementary orders matched automatically
6. **Portfolio Management**: Track positions, P&L, and transaction history
7. **Event Management**: Admins create events with multiple markets
8. **Market Settlement**: Contracts pay out $1 if correct, $0 if wrong
9. **Admin Panel**: Django admin for event creation and market management
10. **Real-Time Updates**: WebSocket broadcasts for live price/orderbook updates

### URL Structure

- `/` - Homepage with active markets
- `/events/` - Browse all events
- `/events/<slug>/` - Event detail with all markets
- `/market/<id>/` - Market trading interface with orderbook
- `/portfolio/` - User's positions and P&L
- `/orders/` - Order history
- `/trades/` - Trade history
- `/transactions/` - Balance transaction history
- `/login/` - User login
- `/logout/` - User logout
- `/register/` - User registration
- `/cancel_order/<id>/` - Cancel an order
- `/markets/<id>/mint/` - Mint complete set
- `/markets/<id>/redeem/` - Redeem complete set
- `/admin/` - Django admin panel

### API Endpoints

- `/api/markets/<id>/orderbook/` - Order book JSON
- `/api/markets/<id>/trades/` - Recent trades JSON
- `/api/markets/<id>/position/` - User position JSON
- `/api/markets/<id>/price-history/` - Price history JSON

### Custom Exceptions

- `InsufficientFundsError` - User lacks balance for order
- `InsufficientPositionError` - User lacks shares for sell order
- `InvalidPriceError` - Price outside 1-99 cents range
- `InvalidQuantityError` - Quantity must be positive
- `MarketNotActiveError` - Market not open for trading
- `OrderNotFoundError` - Order doesn't exist
- `OrderCancellationError` - Order cannot be cancelled
- `SelfTradeError` - User cannot trade with themselves

## Development Guidelines

- Use Django's built-in authentication system
- Apply `@login_required` decorator for protected views (trading, orders)
- Handle order matching with database transactions to prevent race conditions
- Validate orders: price must be 1-99 cents, quantity must be positive
- Update market prices cache after each trade
- Use Django's CSRF protection for all forms
- Store payment credentials in environment variables, never in code
- Run `python manage.py run_engine` in a separate terminal for order matching
