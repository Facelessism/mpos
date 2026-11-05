"""Lightweight asynchronous process management for MicroPython."""

import asyncio
import gc
import time
import micropython

# mypy: disable-error-code=untyped-decorator,name-defined

# NOTE: Implement
# Preloading methods
# Pre-allocating memory
# All local variables

# NOTE: Error codes
# UNREGISTERED: 0
# FAILURE: -1

print_lock = asyncio.Lock()


async def safe_print(*args: object) -> None:
    async with print_lock:
        print(*args)



class Watchdog:
    """Monitor registered processes and maintain hardware watchdog health."""
    @micropython.native
    def __init__(self, hw_timeout_ms: int = 8000) -> None:
        """Initialize the hardware and software watchdog.
        Args:
            hw_timeout_ms: Hardware watchdog timeout in milliseconds.
                If the hardware watchdog is not fed within this interval,
                the device may be reset.
        Side Effects:
            Initializes the hardware watchdog and creates an empty
            heartbeat registry. Sets the watchdog running state to ``False``.
        """
        self.wdt = machine.WDT(timeout=hw_timeout_ms)
        self.beats: dict[int, int] = {}
        self.running: bool = False
    @micropython.native
    def feed_hw(self) -> None:
        """Feed the hardware watchdog to prevent a device reset.
        Side Effects:
            Resets the hardware watchdog countdown.
        """
        self.wdt.feed()
    @micropython.native
    def beat(self, pid: int) -> None:
        """Register or update the heartbeat timestamp of a process.
        Args:
            pid: Identifier of the process whose heartbeat is being updated.

        Side Effects:
            Stores the current system tick count against the process ID,
            marking the process as recently active.
        """
        self.beats[pid] = time.ticks_ms()

    @micropython.native
    def stale(self, pid: int, timeout_ms: int) -> bool:
        """Check whether a process heartbeat has exceeded its timeout.

        Args:
            pid: Identifier of the process to check.
            timeout_ms: Maximum permitted interval between heartbeats,
                in milliseconds.

        Returns:
            ``True`` if the process has no registered heartbeat or its
            last heartbeat exceeds the specified timeout; otherwise
            ``False``.
        """
        last = self.beats.get(pid)
        if last is None:
            return True
        return time.ticks_diff(time.ticks_ms(), last) > timeout_ms

    @micropython.native
    def remove(self, pid: int) -> None:
        """Remove a process heartbeat from the watchdog registry.

        Args:
            pid: Identifier of the process whose heartbeat is to be removed.

        Side Effects:
            Deletes the process heartbeat entry if it exists.
        """
        if pid in self.beats:
            del self.beats[pid]

    @micropython.native
    def clear(self) -> None:
        """Remove all registered process heartbeats.

        Side Effects:
            Clears the heartbeat registry, removing all tracked process
            activity timestamps.
        """
        self.beats.clear()

    async def run(
        self, pm: "ProcessManager", timeout_ms: int = 3000, interval_ms: int = 1000
    ) -> None:
        """Monitor registered processes and enforce heartbeat timeouts.

        Periodically feeds the hardware watchdog and checks the heartbeat
        status of registered processes. Processes that are still marked
        as running but have exceeded the permitted heartbeat timeout are
        terminated through the process manager.

        Args:
            pm: Process manager containing the processes to monitor.
            timeout_ms: Maximum permitted interval between process
                heartbeats, in milliseconds. Processes exceeding this
                interval are considered stale.
            interval_ms: Delay between consecutive monitoring cycles,
                in milliseconds.

        Side Effects:
            Sets ``running`` to ``True`` while monitoring is active.
            Feeds the hardware watchdog during each monitoring cycle.
            Terminates stale running processes through ``pm.kill()``.
            Sets ``running`` to ``False`` when monitoring stops or exits.

        Raises:
            asyncio.CancelledError: If the monitoring task is cancelled.
                Cancellation is propagated after the running state is reset
                in the ``finally`` block.
        """
        self.running = True
        try:
            while self.running:
                self.feed_hw()

                for pid in list(pm.processes.keys()):
                    proc = pm.processes.get(pid)
                    if (
                        proc is not None
                        and proc.running
                        and self.stale(pid, timeout_ms)
                    ):
                        _ = await pm.kill(pid)

                await asyncio.sleep_ms(interval_ms)
        finally:
            self.running = False

    @micropython.native
    def stop(self) -> None:
        """Request termination of the watchdog monitoring loop.

        The monitoring loop exits after the current monitoring cycle
        completes and control returns to its loop condition.

        Side Effects:
            Sets ``running`` to ``False``. Does not directly cancel the
            monitoring task or disable the hardware watchdog.
        """
        self.running = False


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
        self, watchdog: Watchdog, max_process: int = 5, min_free_memory: int = 2048
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
        self.watchdog = watchdog

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
            return -1
        if gc.mem_free() < self.min_free_memory:
            return -1

        pid = self.next_id
        proc.id = pid
        self.next_id = pid + 1
        processes[pid] = proc

        self.watchdog.beat(pid)
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
        self.watchdog.remove(pid)
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

        for pid in list(processes.keys()):
            self.watchdog.remove(pid)

        processes.clear()
