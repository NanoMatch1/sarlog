"""Exceptions shared by every layer of the application."""


class ValidationError(ValueError):
    """Raised when user-supplied data cannot be stored.

    The message is written for the person entering data, because the web
    interface shows it to them directly.
    """


class NotFoundError(LookupError):
    """Raised when a requested record does not exist."""
