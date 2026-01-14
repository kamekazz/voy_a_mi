# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django-based prediction market **REST API** where users can trade on the outcomes of real-world events. Users buy and sell contracts (YES/NO) that pay out based on event outcomes. This project is designed as a **backend API for mobile apps** - no frontend templates.

## Tech Stack

- **Backend**: Django 6 (Python 3.x)
- **Database**: SQLite (development), PostgreSQL (production)
- **API Framework**: Django REST Framework
- **Authentication**: JWT Tokens (djangorestframework-simplejwt)
- **Documentation**: OpenAPI/Swagger (drf-spectacular)
- **Trading Engine**: Custom order book with price-time priority matching
- **Payments**: Stripe or PayPal integration
- **Deployment**: Gunicorn + Nginx

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
```

## Architecture

### Core Models

- **User**: Extends Django's AbstractUser; has `tokens` and `reserved_tokens` for trading. New users automatically receive 500 tokens upon registration
- **Category**: Categories for organizing prediction events
- **Event**: Parent container for related markets (e.g., "2024 US Presidential Election")
- **Market**: Tradeable contracts within an event (YES/NO outcomes)
- **Order**: Orders in the orderbook (buy/sell)
- **Trade**: Matched trades between orders
- **Position**: User's holdings in a specific market (YES/NO contracts with reserved quantities)
- **Transaction**: Audit trail for all token changes

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

`DEPOSIT`, `WITHDRAWAL`, `TRADE_BUY`, `TRADE_SELL`, `SETTLEMENT_WIN`, `SETTLEMENT_LOSS`, `ORDER_RESERVE`, `ORDER_RELEASE`, `REFUND`, `MINT`, `REDEEM`, `MINT_MATCH`, `MERGE_MATCH`, `EVENT_REWARD`

### Key Features

1. **Token-Based Economy**: Users trade with tokens instead of real money. New users receive 500 tokens upon registration
2. **Event Rewards System**: Users can earn additional tokens through event-based rewards (EVENT_REWARD transaction type)
3. **Prediction Market Trading**: Users buy/sell YES/NO contracts on event outcomes
4. **Order Book System**: Price-time priority matching engine
5. **Complete Set Minting**: Users pay 1 token to mint 1 YES + 1 NO share (Polymarket-style)
6. **Complete Set Redemption**: Users burn 1 YES + 1 NO share to receive 1 token
7. **Mint/Merge Matching**: Complementary orders matched automatically
8. **Portfolio Management**: Track positions, P&L, and transaction history
9. **Event Management**: Admins create events with multiple markets
10. **Market Settlement**: Contracts pay out 1 token if correct, 0 if wrong
11. **Admin Panel**: Django admin for event creation and market management
12. **JWT Authentication**: Secure token-based authentication for mobile apps

### API Structure

```
/api/
  auth/
    register/       POST - Create new account
    login/          POST - Get JWT tokens
    refresh/        POST - Refresh access token
  user/
    profile/        GET, PATCH - User profile
    portfolio/      GET - Positions + P&L
    trades/         GET - Trade history
    transactions/   GET - Transaction history
  categories/       GET - List categories
  events/           GET - List/detail events
  markets/          GET - List/detail markets
    <id>/orderbook/ GET - Order book
    <id>/trades/    GET - Recent trades
    <id>/position/  GET - User's position
    <id>/orders/    POST - Place order
    <id>/mint/      POST - Mint complete set
    <id>/redeem/    POST - Redeem complete set
  orders/           GET - User's orders
    <id>/           DELETE - Cancel order
  docs/             GET - Swagger UI
  schema/           GET - OpenAPI schema
```

### Custom Exceptions

- `InsufficientFundsError` - User lacks tokens for order
- `InsufficientPositionError` - User lacks shares for sell order
- `InvalidPriceError` - Price outside 1-99 cents range
- `InvalidQuantityError` - Quantity must be positive
- `MarketNotActiveError` - Market not open for trading
- `OrderNotFoundError` - Order doesn't exist
- `OrderCancellationError` - Order cannot be cancelled
- `SelfTradeError` - User cannot trade with themselves

## Development Guidelines

- All endpoints use JWT authentication (except public read endpoints)
- Use `Authorization: Bearer <token>` header for authenticated requests
- Handle order matching with database transactions to prevent race conditions
- Validate orders: price must be 1-99 cents, quantity must be positive
- Update market prices cache after each trade
- Store payment credentials in environment variables, never in code
- Run `python manage.py run_engine` in a separate terminal for order matching

## API Documentation

See `API.md` for complete API documentation with request/response examples.

Interactive documentation available at `/api/docs/` when server is running.
