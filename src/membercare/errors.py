"""Expected lab failures. These are data or permission results, not crashes."""


class LabError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
