"""Lightweight asynchronous process management for MicroPython."""

import asyncio
import gc
import time
import micropython

# NOTE: Implement
# Preloading methods
# Pre-allocating memory
# All local variables

# NOTE: Error codes
# UNREGISTERED: 0
# FAILURE: -1


class Process:
    """Represent an asynchronously executed coroutine and its lifecycle state."""

    @micropython.native
    def __init__(
        self,
        coroutine: callable,
        name: str,
        max_restarts: int = 0,
    ) -> None:
        """Initialize a process.

        Args:
            coroutine: Asynchronous callable executed by the process.
            name: Human-readable name assigned to the process.
            max_restarts: Maximum number of restart attempts permitted after
                an unexpected exception.
        """
        self.id: int = 0
        self.name: str = name
        self.coroutine: callable = coroutine
        self.task: asyncio.Task[None] | None = None
        self.created_at: float = time.time()
        self.running: bool = False
        self.restart_count: int = 0
        self.max_restarts: int = max_restarts

    async def run(self) -> None:
        """Execute the process coroutine with automatic restart handling.

        Execution ends when the coroutine completes successfully or when the
        configured restart limit is reached. Cancellation is propagated
        immediately and does not consume a restart attempt.

        Side Effects:
            Sets ``running`` to ``True`` while execution is active and back
            to ``False`` when execution ends. Increments ``restart_count``
            after an unexpected exception when another restart is permitted.

        Raises:
            asyncio.CancelledError: If execution is cancelled.
        """
        self.running = True
        coroutine = self.coroutine
        max_restarts = self.max_restarts
        try:
            while True:
                try:
                    await coroutine()
                    break
                except asyncio.CancelledError:
                    raise
                except Exception:
                    restart_count = self.restart_count
                    if restart_count >= max_restarts:
                        break
                    self.restart_count = restart_count + 1
                    await asyncio.sleep_ms(0)

        finally:
            self.running = False

    async def kill(self) -> None:
        """Cancel the process task and wait for its termination.

        If an active task exists, it is cancelled and awaited. Cancellation
        raised by the task is treated as expected termination.

        Side Effects:
            Sets ``running`` to ``False``.
        """
        task = self.task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self.running = False


class ProcessManager:
    """Manage the registration, execution, and termination of processes."""

    @micropython.native
    def __init__(
        self,
        max_process: int = 5,
        min_free_memory: int = 2048,
    ) -> None:
        """Initialize the process manager.

        Args:
            max_process: Maximum number of processes that may be registered
                simultaneously.
            min_free_memory: Minimum free memory required before spawning
                another process.
        """
        self.processes: dict[int, Process] = {}
        self.next_id: int = 1
        self.max_process: int = max_process
        self.min_free_memory: int = min_free_memory

    @micropython.native
    def _can_spawn(self) -> bool:
        """Check whether process-count and memory limits permit spawning.

        Returns:
            ``True`` when another process can be spawned; otherwise ``False``.
        """
        processes = self.processes
        if len(processes) >= self.max_process:
            return False
        return gc.mem_free() >= self.min_free_memory

    async def spawn(self, proc: Process) -> int:
        """Register and start a process when resource limits permit.

        Args:
            proc: Process instance to register and execute.

        Returns:
            The assigned process ID when the process is registered and
            scheduled for execution. When either the process-count or free
            memory limit is exceeded, the method returns the configured
            failure value.
        """
        processes = self.processes
        if len(processes) >= self.max_process:
            return FAILURE
        if gc.mem_free() < self.min_free_memory:
            return FAILURE
        pid = self.next_id
        proc.id = pid
        self.next_id = pid + 1
        processes[pid] = proc
        proc.task = asyncio.create_task(proc.run())
        return pid

    async def kill(self, pid: int) -> bool:
        """Terminate and unregister a process by its process ID.

        Args:
            pid: Identifier of the process to terminate.

        Returns:
            ``True`` if the process exists and is removed; otherwise ``False``.

        Side Effects:
            Cancels an active process task, sets its running state to
            ``False``, and removes it from the process registry.
        """
        processes = self.processes
        proc = processes.get(pid)
        if proc is None:
            return False
        task = proc.task

        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        proc.running = False
        del processes[pid]
        return True

    async def cancel_all(self) -> None:
        """Cancel all registered process tasks and clear the process registry.

        Active tasks are cancelled and the event loop is yielded before the
        registry is cleared.

        Side Effects:
            Cancels all active process tasks and removes all registered
            processes from ``processes``.
        """
        processes = self.processes
        if not processes:
            return
        for proc in processes.values():
            task = proc.task

            if task is not None and not task.done():
                task.cancel()
        await asyncio.sleep_ms(0)
        processes.clear()

    # async def status(self) -> None:
    #     for pid, proc in self.processes.items():
    #         state = "Running" if proc.running else "IDLE/Done"
    #         await safe_print(f"ID: {pid}\tNAME: {proc.name}\tState: {state}")
