"""Worker pool for dispatching rule execution to threads."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from typing import Any

logger = logging.getLogger(__name__)


class WorkerPool:
    """Thread pool for executing synchronous rule logic from async context.

    Creates the async/thread boundary that makes integration non-trivial.
    Rules execute in threads but results flow back through the async bus.
    """

    def __init__(self, max_workers: int = 4) -> None:
        self._executor = ThreadPoolExecutor(max_workers=max_workers)
        self._max_workers = max_workers

    async def submit(
        self,
        func: Callable[..., Any],
        *args: Any,
        **kwargs: Any,
    ) -> Any:
        """Submit a synchronous function to run in the thread pool.

        Args:
            func: Synchronous callable.
            *args: Positional arguments.
            **kwargs: Keyword arguments.

        Returns:
            The result of the function.
        """
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            self._executor,
            lambda: func(*args, **kwargs),
        )

    def shutdown(self, wait: bool = True) -> None:
        """Shut down the worker pool."""
        self._executor.shutdown(wait=wait)

    @property
    def max_workers(self) -> int:
        return self._max_workers
