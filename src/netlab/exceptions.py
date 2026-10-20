"""Custom exceptions for NetLab."""


class NetLabError(Exception):
    """Base exception for all NetLab errors."""


class ConfigurationError(NetLabError):
    """Raised when the lab configuration is invalid."""


class NetworkError(NetLabError):
    """Raised on Docker network operation failures."""


class ContainerError(NetLabError):
    """Raised on Docker container operation failures."""