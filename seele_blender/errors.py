class SeeleError(Exception):
    """Stable Web-facing error with a deliberately sanitized message."""

    def __init__(self, code, message, http_status=400, retryable=False, stage=None, local_detail=None):
        super().__init__(message)
        self.code = code
        self.message = message
        self.http_status = http_status
        self.retryable = bool(retryable)
        self.stage = stage
        self.local_detail = local_detail

    def payload(self, default_stage=None):
        return {
            "code": self.code,
            "message": self.message,
            "retryable": self.retryable,
            "stage": self.stage or default_stage,
        }


class CancelledError(SeeleError):
    def __init__(self, stage=None):
        super().__init__("CANCELLED", "Transfer cancelled", 409, False, stage)
