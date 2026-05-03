from typing import Optional, Protocol


class ProgressCallback(Protocol):
    def __call__(
        self,
        msg: str,
        progress: Optional[float] = None,
    ) -> None: ...
