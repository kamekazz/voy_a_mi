"""
API URL routes for Voy a Mi Prediction Market.

All endpoints are prefixed with /api/ in the main urls.py
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenObtainPairView, TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from predictions.api.views.auth import RegisterView
from predictions.api.views.markets import CategoryViewSet, EventViewSet, MarketViewSet
from predictions.api.views.trading import OrderViewSet
from predictions.api.views.user import (
    UserProfileView,
    PortfolioView,
    UserTradesView,
    UserTransactionsView,
)

# Create router and register viewsets
router = DefaultRouter()
router.register('categories', CategoryViewSet, basename='category')
router.register('events', EventViewSet, basename='event')
router.register('markets', MarketViewSet, basename='market')
router.register('orders', OrderViewSet, basename='order')

urlpatterns = [
    # Router URLs (categories, events, markets, orders)
    path('', include(router.urls)),

    # Authentication endpoints
    path('auth/register/', RegisterView.as_view(), name='auth-register'),
    path('auth/login/', TokenObtainPairView.as_view(), name='auth-login'),
    path('auth/refresh/', TokenRefreshView.as_view(), name='auth-refresh'),

    # User endpoints
    path('user/profile/', UserProfileView.as_view(), name='user-profile'),
    path('user/portfolio/', PortfolioView.as_view(), name='user-portfolio'),
    path('user/trades/', UserTradesView.as_view(), name='user-trades'),
    path('user/transactions/', UserTransactionsView.as_view(), name='user-transactions'),

    # API Documentation
    path('schema/', SpectacularAPIView.as_view(), name='schema'),
    path('docs/', SpectacularSwaggerView.as_view(url_name='schema'), name='swagger-ui'),
    path('redoc/', SpectacularRedocView.as_view(url_name='schema'), name='redoc'),
]
