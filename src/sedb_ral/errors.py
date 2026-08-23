from __future__ import annotations


class RALValidationError(ValueError):
    def __init__(self, code: str, message: str, path: tuple[str, ...] = ()):
        self.code = code
        self.path = path
        super().__init__(f"{code}: {message}")
