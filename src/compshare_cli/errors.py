class CLIError(Exception):
    """A user-facing command-line error."""


class ConfigError(CLIError):
    """Raised when CLI configuration is missing or invalid."""


class UsageError(CLIError):
    """Raised when a combination of command options is invalid."""
