from django.urls import path
from . import views

app_name = 'predictions'

urlpatterns = [
    # Public pages
    path('', views.index, name='index'),
    path('events/', views.event_list, name='event_list'),
    path('events/<slug:slug>/', views.event_detail, name='event_detail'),
    path('markets/<int:pk>/', views.market_detail, name='market_detail'),

    # Trading actions (require login)
    path('markets/<int:pk>/order/', views.place_order, name='place_order'),
    path('orders/<int:pk>/cancel/', views.cancel_order, name='cancel_order'),

    # User pages (require login)
    path('portfolio/', views.portfolio, name='portfolio'),
    path('orders/', views.order_history, name='order_history'),
    path('trades/', views.trade_history, name='trade_history'),
    path('transactions/', views.transactions, name='transactions'),

    # API endpoints
    path('api/markets/<int:pk>/orderbook/', views.api_orderbook, name='api_orderbook'),
    path('api/markets/<int:pk>/trades/', views.api_recent_trades, name='api_recent_trades'),
    path('api/markets/<int:pk>/position/', views.api_user_position, name='api_user_position'),

    # AMM API endpoints
    path('api/markets/<int:pk>/quote/', views.api_amm_quote, name='api_amm_quote'),
    path('api/markets/<int:pk>/prices/', views.api_amm_prices, name='api_amm_prices'),
]
