"""Custom exceptions for the prediction market trading system."""


class TradingError(Exception):
    """Base exception for trading-related errors."""
    pass


class InsufficientFundsError(TradingError):
    """Raised when user doesn't have enough tokens for an order."""
    def __init__(self, required=None, available=None, message=None):
        if message:
            super().__init__(message)
        elif required is not None and available is not None:
            self.required = required
            self.available = available
            super().__init__(
                f"Insufficient tokens: required {required:.2f}, available {available:.2f}"
            )
        else:
            super().__init__(required)  # First arg is the message


class InsufficientPositionError(TradingError):
    """Raised when user doesn't have enough contracts to sell."""
    def __init__(self, required=None, available=None, contract_type=None, message=None):
        if message:
            super().__init__(message)
        elif required is not None and available is not None and contract_type is not None:
            self.required = required
            self.available = available
            self.contract_type = contract_type
            super().__init__(
                f"Insufficient {contract_type.upper()} contracts: "
                f"required {required}, available {available}"
            )
        else:
            super().__init__(required)  # First arg is the message


class InvalidPriceError(TradingError):
    """Raised when order price is outside valid range (1-99 cents)."""
    def __init__(self, price):
        self.price = price
        super().__init__(
            f"Invalid price: {price}. Price must be between 1 and 99 cents."
        )


class InvalidQuantityError(TradingError):
    """Raised when order quantity is invalid."""
    def __init__(self, quantity):
        self.quantity = quantity
        super().__init__(
            f"Invalid quantity: {quantity}. Quantity must be a positive integer."
        )


class MarketNotActiveError(TradingError):
    """Raised when trying to trade on an inactive market."""
    def __init__(self, market=None, message=None):
        if message:
            super().__init__(message)
        elif isinstance(market, str):
            super().__init__(market)  # First arg is a message
        elif market is not None:
            self.market = market
            super().__init__(
                f"Market '{market.title}' is not active for trading. "
                f"Status: {market.status}"
            )
        else:
            super().__init__("Market is not active for trading.")


class OrderNotFoundError(TradingError):
    """Raised when order cannot be found."""
    def __init__(self, order_id):
        self.order_id = order_id
        super().__init__(f"Order with ID {order_id} not found.")


class OrderCancellationError(TradingError):
    """Raised when order cannot be cancelled."""
    def __init__(self, order, reason):
        self.order = order
        self.reason = reason
        super().__init__(f"Cannot cancel order {order.id}: {reason}")


class SelfTradeError(TradingError):
    """Raised when a user's order would match their own order."""
    def __init__(self):
        super().__init__("Self-trading is not allowed.")
