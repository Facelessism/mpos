"""Heap-based priority scheduler for asynchronous MicroPython processes."""

import asyncio
import heapq
import time

from proc import Process, ProcessManager

# NOTE: Error Codes
# DEPRIORITIZED: -1


class Scheduler:
    """Schedule processes for execution at specified times and intervals."""

    def __init__(self, pm: ProcessManager) -> None:
        """Initialize the scheduler.

        Args:
            pm: Process manager used to execute and terminate scheduled
                processes.
        """
        self.pm: ProcessManager = pm
        self.queue: list[tuple[int, int, int, Process, int, int]] = []
        self.seq: int = 0
        self.job_index: dict[int, tuple[int, int, int, Process, int, int]] = {}
        self.running: bool = False

    def scheduled_at(
        self,
        start_time_ms: int,
        proc: Process,
        priority: int = -1,
        repeat_count: int = 0,
        repeat_time_ms: int = 0,
    ) -> None:
        """Schedule a process to execute at a specific tick time.

        Args:
            start_time_ms: Target execution time in milliseconds according to
                the MicroPython tick clock.
            proc: Process instance to schedule.
            priority: Ordering priority for jobs with the same start time.
                Lower values are ordered first.
            repeat_count: Number of additional executions after the initial
                execution.
            repeat_time_ms: Interval in milliseconds between repeated
                executions.

        Side Effects:
            Adds the scheduled job to the heap queue and records it in
            ``job_index`` using the process ID as its key.
        """
        item = (
            start_time_ms,
            priority,
            self.seq,
            proc,
            repeat_count,
            repeat_time_ms,
        )
        self.seq += 1
        heapq.heappush(self.queue, item)
        self.job_index[proc.id] = item

    def scheduled_in(
        self,
        delay_ms: int,
        proc: Process,
        priority: int = -1,
        repeat_count: int = 0,
        repeat_time_ms: int = 0,
    ) -> None:
        """Schedule a process to execute after a specified delay.

        Args:
            delay_ms: Delay in milliseconds before the initial execution.
            proc: Process instance to schedule.
            priority: Ordering priority for jobs with the same start time.
                Lower values are ordered first.
            repeat_count: Number of additional executions after the initial
                execution.
            repeat_time_ms: Interval in milliseconds between repeated
                executions.

        Side Effects:
            Calculates the target tick time and delegates scheduling to
            ``scheduled_at``.
        """
        start_time_ms = time.ticks_add(time.ticks_ms(), delay_ms)
        self.scheduled_at(start_time_ms, proc, priority, repeat_count, repeat_time_ms)

    async def run(self) -> None:
        """Run the scheduler until it is stopped.

        The scheduler waits for the earliest scheduled job, collects all jobs
        whose execution times have been reached, and processes each valid
        job. Jobs are validated against ``job_index`` so stale heap entries
        can be ignored. Jobs with additional repetitions are rescheduled at
        their configured interval with their remaining repeat count reduced
        by one. Jobs with no repetitions remaining are removed from
        ``job_index``.

        Side Effects:
            Sets ``running`` to ``True`` while the scheduler is active.
            Removes due jobs from ``queue`` and updates ``queue`` and
            ``job_index`` when jobs are rescheduled or completed.
        """
        self.running = True
        while self.running:
            if not self.queue:
                await asyncio.sleep_ms(10)
                continue

            start_time_ms, priority, seq, proc, repeat_count, repeat_time_ms = (
                self.queue[0]
            )
            now = time.ticks_ms()
            delay = time.ticks_diff(start_time_ms, now)

            if delay > 0:
                await asyncio.sleep_ms(delay)
                continue

            due = []
            now = time.ticks_ms()
            while self.queue and time.ticks_diff(self.queue[0][0], now) <= 0:
                due.append(heapq.heappop(self.queue))

            for start_time_ms, priority, seq, proc, repeat_count, repeat_time_ms in due:
                if self.job_index.get(proc.id) != (
                    start_time_ms,
                    priority,
                    seq,
                    proc,
                    repeat_count,
                    repeat_time_ms,
                ):
                    continue

                self.pm.spawn(proc)

                if repeat_count > 1:
                    next_item = (
                        time.ticks_add(start_time_ms, repeat_time_ms),
                        priority,
                        self.seq,
                        proc,
                        repeat_count - 1,
                        repeat_time_ms,
                    )
                    self.seq += 1
                    heapq.heappush(self.queue, next_item)
                    self.job_index[proc.id] = next_item
                else:
                    self.job_index.pop(proc.id, None)

            await asyncio.sleep_ms(0)

    def stop(self) -> None:
        """Stop the scheduler and clear all pending jobs.

        Side Effects:
            Sets ``running`` to ``False`` and clears both the scheduling
            queue and job index.
        """
        self.running = False
        self.queue.clear()
        self.job_index.clear()

    async def shutdown(self) -> None:
        """Stop the scheduler and cancel all managed processes.

        The scheduler is stopped and its pending jobs are cleared before all
        processes registered with the associated process manager are
        cancelled.

        Side Effects:
            Stops scheduling, clears pending jobs, and cancels all processes
            managed by ``pm``.
        """
        self.stop()
        await self.pm.cancel_all()

    def change_priority(self, pid: int, new_priority: int) -> None:
        """Change the priority of a scheduled process.

        Args:
            pid: Identifier of the scheduled process.
            new_priority: New priority used when ordering the scheduled job.

        Side Effects:
            Updates the active job in ``job_index`` and pushes a replacement
            entry onto the heap. The previous heap entry is retained until
            it is encountered and discarded as a stale entry by ``run``.
        """
        item = self.job_index.get(pid)
        if item is None:
            return

        start_time_ms, _, seq, proc, repeat_count, repeat_time_ms = item
        new_item = (
            start_time_ms,
            new_priority,
            seq,
            proc,
            repeat_count,
            repeat_time_ms,
        )

        self.job_index[pid] = new_item
        heapq.heappush(self.queue, new_item)

    # async def status(self) -> None:
    #     for pid, proc in self.processes.items():
    #         state = "Running" if proc.running else "IDLE/Done"
    #         await safe_print(f"ID: {pid}\tNAME: {proc.name}\tState: {state}")k
