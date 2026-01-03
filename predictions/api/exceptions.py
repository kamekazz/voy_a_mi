from rest_framework.views import exception_handler
from rest_framework.response import Response
from rest_framework import status
from predictions.exceptions import (
    InsufficientFundsError,
    InsufficientPositionError,
    InvalidPriceError,
    InvalidQuantityError,
    MarketNotActiveError,
    OrderNotFoundError,
    OrderCancellationError,
    SelfTradeError,
)


def custom_exception_handler(exc, context):
    """
    Custom exception handler that converts domain exceptions to API responses.
    """
    # Call REST framework's default exception handler first
    response = exception_handler(exc, context)

    if response is not None:
        return response

    # Handle trading exceptions
    if isinstance(exc, InsufficientFundsError):
        return Response({
            'error': 'insufficient_funds',
            'message': str(exc),
            'required': float(exc.required) if hasattr(exc, 'required') else None,
            'available': float(exc.available) if hasattr(exc, 'available') else None,
        }, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, InsufficientPositionError):
        return Response({
            'error': 'insufficient_position',
            'message': str(exc),
            'contract_type': exc.contract_type if hasattr(exc, 'contract_type') else None,
            'available': exc.available if hasattr(exc, 'available') else None,
        }, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, InvalidPriceError):
        return Response({
            'error': 'invalid_price',
            'message': str(exc),
        }, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, InvalidQuantityError):
        return Response({
            'error': 'invalid_quantity',
            'message': str(exc),
        }, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, MarketNotActiveError):
        return Response({
            'error': 'market_not_active',
            'message': str(exc),
        }, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, OrderNotFoundError):
        return Response({
            'error': 'order_not_found',
            'message': str(exc),
        }, status=status.HTTP_404_NOT_FOUND)

    if isinstance(exc, OrderCancellationError):
        return Response({
            'error': 'order_cancellation_error',
            'message': str(exc),
        }, status=status.HTTP_400_BAD_REQUEST)

    if isinstance(exc, SelfTradeError):
        return Response({
            'error': 'self_trade_error',
            'message': str(exc),
        }, status=status.HTTP_400_BAD_REQUEST)

    # Return None for unhandled exceptions (will use default handling)
    return None
