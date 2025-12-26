# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django-based prediction market platform where users can trade on the outcomes of real-world events. Users buy and sell contracts (YES/NO) that pay out based on event outcomes.

## Tech Stack

- **Backend**: Django 4 (Python 3.x)
- **Database**: SQLite (development), PostgreSQL (production)
- **Frontend**: Django templates with HTML/CSS/JavaScript (server-side rendering)
- **Real-time**: Django Channels with WebSockets (for live price updates)
- **Payments**: Stripe or PayPal integration
- **Deployment**: Gunicorn + Nginx

## Common Commands

```bash
# Database migrations
python manage.py makemigrations
python manage.py migrate

# Run development server
python manage.py runserver

# Run matching engine
python manage.py run_engine

# Create superuser for admin
python manage.py createsuperuser

# Collect static files (production)
python manage.py collectstatic
```

## Architecture

### Core Models

- **User**: Extends Django's AbstractUser; has balance and reserved_balance for trading
- **Category**: Categories for organizing prediction events
- **Event**: Parent container for related markets (e.g., "2024 US Presidential Election")
- **Market**: Tradeable contracts within an event (YES/NO outcomes)
- **Order**: Limit orders in the orderbook (buy/sell)
- **Trade**: Matched trades between orders
- **Position**: User's holdings in a specific market (YES/NO contracts)
- **Transaction**: Audit trail for all balance changes

### Key Features

1. **Prediction Market Trading**: Users buy/sell YES/NO contracts on event outcomes
2. **Order Book System**: Price-time priority matching engine
3. **Portfolio Management**: Track positions, P&L, and transaction history
4. **Event Management**: Admins create events with multiple markets
5. **Market Settlement**: Contracts pay out $1 if correct, $0 if wrong
6. **Admin Panel**: Django admin for event creation and market management

### URL Structure

- `/` - Homepage with active markets
- `/events/` - Browse all events
- `/events/<slug>/` - Event detail with all markets
- `/markets/<id>/` - Market trading interface with orderbook
- `/portfolio/` - User's positions and P&L
- `/orders/` - Order history
- `/trades/` - Trade history
- `/transactions/` - Balance transaction history
- `/admin/` - Django admin panel

## Development Guidelines

- Use Django's built-in authentication system
- Apply `@login_required` decorator for protected views (trading, orders)
- Handle order matching with database transactions to prevent race conditions
- Validate orders: price must be 1-99 cents, quantity must be positive
- Update market prices cache after each trade
- Use Django's CSRF protection for all forms
- Store payment credentials in environment variables, never in code
