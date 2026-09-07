"""Content-free failure vocabulary for the optional local scorer."""

REASONS = frozenset(
    {
        "capacity_timeout",
        "out_of_memory",
        "model_unavailable",
        "inference_failure",
        "invalid_scores",
    }
)


class RerankerFailure(ValueError):
    def __init__(self, reason):
        if reason not in REASONS:
            raise ValueError("unknown scorer failure category")
        self.reason = reason
        super().__init__(f"Reranker failure: {reason}.")


def failure_reason(exc):
    if isinstance(exc, TimeoutError):
        return "capacity_timeout"
    if isinstance(exc, MemoryError) or type(exc).__name__ == "OutOfMemoryError":
        return "out_of_memory"
    if isinstance(exc, (FileNotFoundError, ImportError)):
        return "model_unavailable"
    return "inference_failure"
