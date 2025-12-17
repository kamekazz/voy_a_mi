# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a Django-based multi-vendor auction marketplace platform where market demand determines prices through competitive bidding (English auction model). Users can act as buyers, sellers, or both.

## Tech Stack

- **Backend**: Django 4 (Python 3.x)
- **Database**: SQLite (development), PostgreSQL (production)
- **Frontend**: Django templates with HTML/CSS/JavaScript (server-side rendering)
- **Real-time**: Django Channels with WebSockets (for live bid updates)
- **Payments**: Stripe or PayPal integration
- **Deployment**: Gunicorn + Nginx

## Common Commands

```bash
# Create Django project
django-admin startproject market_project

# Create app
python manage.py startapp auctions

# Database migrations
python manage.py makemigrations
python manage.py migrate

# Run development server
python manage.py runserver

# Create superuser for admin
python manage.py createsuperuser

# Collect static files (production)
python manage.py collectstatic
```

## Architecture

### Core Models

- **User**: Extends Django's AbstractUser; supports buyer/seller roles
- **Listing**: Auction items with title, description, starting_price, current_price, reserve_price, start_time, end_time, category, images; FK to seller (User)
- **Bid**: FK to Listing, FK to User (bidder), bid_amount, timestamp
- **Watchlist**: Many-to-many between User and Listing
- **Comment**: FK to Listing, FK to User, content, timestamp
- **Order/Transaction**: Created when auction ends; tracks payment status, shipping

### User Roles

- **Buyers**: Browse listings (no login required), bid on items (login required), manage watchlist
- **Sellers**: Create/manage listings, receive notifications on bids
- **Admins**: Full access via Django admin; manage users, listings, bids, disputes

### Key Features

1. **Auction Bidding System**: English auction where highest bidder wins at end_time
2. **Public Browsing**: Guests can browse/search without login
3. **Listing Management**: Sellers create auctions with starting price, duration, category
4. **Watchlist & Notifications**: Email alerts for outbid, auction ending, won/lost
5. **Payment Processing**: Stripe/PayPal integration for checkout after auction ends
6. **Admin Panel**: Django admin for moderation and oversight

### URL Structure (Suggested)

- `/` - Homepage with active listings
- `/listings/` - Browse/search all listings
- `/listings/<id>/` - Listing detail with bidding interface
- `/listings/create/` - Create new listing (sellers)
- `/accounts/` - User authentication (login, register, logout)
- `/profile/` - User dashboard (bids, watchlist, listings)
- `/admin/` - Django admin panel

## Development Guidelines

- Use Django's built-in authentication system
- Apply `@login_required` decorator for protected views (bidding, listing creation)
- Handle bid concurrency with database transactions
- Validate bids are higher than current price plus minimum increment
- Mark auctions as closed when end_time passes (background task or lazy evaluation)
- Use Django's CSRF protection for all forms
- Store payment credentials in environment variables, never in code
