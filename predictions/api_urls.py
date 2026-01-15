"""
API URL routes for Voy a Mi Prediction Market.

All endpoints are prefixed with /api/ in the main urls.py
"""

from django.urls import path, include
from rest_framework.routers import DefaultRouter
from rest_framework_simplejwt.views import TokenRefreshView
from drf_spectacular.views import (
    SpectacularAPIView,
    SpectacularSwaggerView,
    SpectacularRedocView,
)

from predictions.api.views.markets import CategoryViewSet, EventViewSet, MarketViewSet
from predictions.api.views.trading import OrderViewSet
from predictions.api.views.user import (
    UserProfileView,
    PortfolioView,
    UserTradesView,
    UserTransactionsView,
)
from predictions.api.views.verification import (
    StartRegistrationView,
    ConfirmRegistrationView,
    StartLoginView,
    ConfirmLoginView,
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

    # Phone verification authentication endpoints
    path('auth/register/start/', StartRegistrationView.as_view(), name='register-start'),
    path('auth/register/confirm/', ConfirmRegistrationView.as_view(), name='register-confirm'),
    path('auth/login/start/', StartLoginView.as_view(), name='login-start'),
    path('auth/login/confirm/', ConfirmLoginView.as_view(), name='login-confirm'),
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
