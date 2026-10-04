# Lightweight Process Management Framework for MicroPython

A lightweight process-management framework for MicroPython applications specifically running on resource-constrained microcontrollers. It provides structured asynchronous execution, process lifecycle management, restart handling, resource-aware process creation, and time-based scheduling without requiring an operating-system process model.

## Overview

MicroPython makes it possible to build capable applications on relatively small microcontrollers, but as an application grows, managing multiple independent tasks through a single execution flow can become increasingly difficult. Sensor acquisition, communication, control logic, data processing, logging, and periodic operations may all need to run concurrently while sharing the same limited CPU and memory resources.

This framework introduces a lightweight process-management layer for structuring such applications. Instead of treating every asynchronous coroutine as an unmanaged task, application components can be represented as managed processes with explicit identities, lifecycle state, restart behavior, scheduling information, and resource constraints.

The framework is designed primarily for resource-constrained, single-core microcontrollers running MicroPython. These platforms provide low-cost, low-power, compact hardware suitable for distributed embedded deployments while operating within considerably tighter resource limits than conventional computing systems. Their constrained resources and single execution core make lightweight cooperative concurrency, explicit scheduling, and resource-aware process management a practical architectural choice.

The framework uses MicroPython's cooperative asynchronous execution model rather than threads or multiprocessing. Managed coroutines share the same runtime and memory space, so each process must yield control through asynchronous operations to allow other processes to execute. This keeps the execution model lightweight while allowing multiple independent application components to coexist within the same MCU. The broader architecture is intended to provide more than task scheduling alone. Process management can serve as the foundation for higher-level services, logical process containers, inter-processor communication, configuration-driven startup, resource monitoring, fault handling, watchdog integration, and system supervision.

Therefore, the framework aims to provide a practical middle ground between an unstructured collection of asynchronous tasks and a full operating-system process model that would be unnecessarily expensive or unavailable on small microcontrollers.

## Architecture

```text
                         +----------------------+
                         |   System Supervisor  |
                         +----------+-----------+
                                    |
             +----------------------+----------------------+
             |          |            |          |           |
             v          v            v          v           v
      +----------+ +----------+ +----------+ +----------+ +----------+
      |   Boot   | | Process  | |  Memory  | | Watchdog | | Logging  |
      |  Manager | | Manager  | |  Monitor | |  Manager | |  Manager |
      +----------+ +----+-----+ +----------+ +----------+ +----------+
                         |
          +--------------+--------------+
          |              |              |
          v              v              v
     +----------+   +----------+   +----------+
     |Container |   |Container |   |Container |
     |    A     |   |    B     |   |    C     |
     +----+-----+   +----+-----+   +----+-----+
          |              |              |
       +--+--+        +--+--+           |
       |     |        |     |           |
       v     v        v     v           v
    +-----+ +-----+ +-----+ +-----+ +-----+
    |Svc A1| |Svc A2| |Svc B1| |Svc B2| |Svc C1|
    +-----+ +-----+ +-----+ +-----+ +-----+
```

The current implementation provides the process-management and scheduling foundation through `Process`, `ProcessManager`, and `Scheduler`.

The architecture shown above represents the broader framework toward which the implementation is progressing. Higher-level components extend the process-management foundation toward service management, logical process containers, inter-processor communication, resource monitoring, fault handling, configuration-driven startup, watchdog integration, logging, and system supervision.

Process containers are intended as logical management boundaries rather than operating-system containers or independently isolated processes. All managed components ultimately operate within the same MicroPython runtime and share its available resources.

## Core Components

### `Process`

`Process` represents an application coroutine together with the state required to manage its execution.

A process stores its identity, name, coroutine, creation time, running state, restart count, and configured restart limit. Its execution wrapper is responsible for running the coroutine and handling failures according to the configured restart limit.

This gives application code an explicit lifecycle boundary around an otherwise ordinary asynchronous coroutine.

Key responsibilities:

* Identifying a managed coroutine
* Tracking process lifecycle state
* Executing the coroutine
* Detecting execution failures
* Restarting failed processes within the configured limit
* Handling explicit cancellation
* Tracking restart attempts

### `ProcessManager`

`ProcessManager` provides the central registry and control layer for managed processes.

Before creating a process, it can enforce global resource constraints such as the maximum number of registered processes and the minimum amount of free memory required for another process.

It also provides operations for terminating individual processes and shutting down all managed processes, giving the framework a single point through which process lifecycle can be controlled.

Key responsibilities:

* Registering processes
* Assigning process IDs
* Enforcing process-count limits
* Checking available memory before spawning
* Starting managed processes
* Terminating individual processes
* Cancelling all managed processes
* Maintaining the active process registry

### `Scheduler`

`Scheduler` provides time-based execution control for managed processes.

It maintains scheduled jobs in a heap-based priority queue, allowing processes to be scheduled for a specific time or after a specified delay. Jobs can also be repeated using a configurable repeat interval and execution count.

When multiple jobs become due together, their scheduled time, priority, and insertion sequence determine their execution order. The scheduler also maintains job state so outdated entries can be detected and ignored when scheduling information changes.

Key responsibilities:

* Scheduling processes for a specific time
* Scheduling processes after a delay
* Ordering jobs by time and priority
* Maintaining deterministic insertion ordering
* Supporting repeated jobs
* Tracking scheduled jobs
* Handling stale scheduled entries
* Changing scheduled-job priority
* Starting and stopping the scheduler
* Coordinating scheduler shutdown with the process manager

## Scheduling

The framework uses cooperative scheduling rather than preemptive threads.

Processes execute through MicroPython's asynchronous runtime, allowing multiple application components to share the same execution core without introducing native-thread or multiprocessing overhead.

Scheduled jobs are ordered using:

```text
Scheduled Time
      ↓
Priority
      ↓
Sequence
```

This provides deterministic ordering when multiple jobs become eligible for execution at the same time.

The scheduler supports both one-time and repeated execution, making it suitable for periodic operations such as sensor sampling, telemetry transmission, maintenance tasks, and other time-driven application logic.

Because execution is cooperative, a process performing long-running or blocking work can prevent other processes from receiving execution time. Application coroutines must therefore yield appropriately to preserve system responsiveness.

## Process Lifecycle

A managed process follows a lightweight lifecycle:

```text
        +-----------+
        |  Created  |
        +-----+-----+
              |
              v
        +-----------+
        | Registered|
        +-----+-----+
              |
              v
        +-----------+
        |  Running  |
        +-----+-----+
          /    |    \
         /     |     \
        v      v      v
 Completed   Failed  Cancelled
              |
              v
       Restart Available?
          /          \
        Yes           No
         |             |
         v             v
      Restart       Terminated
```

When a process coroutine fails, the process can restart according to its configured restart limit. Restart attempts are tracked so repeated failures can eventually terminate the process instead of causing unlimited restart loops.

Cancellation is handled separately from ordinary failures, allowing intentional shutdown to terminate a process without treating cancellation as an execution error.

## Resource Management

The framework treats resource availability as part of process management rather than assuming that every requested process can always be created.

The current process manager provides admission checks for:

* Maximum number of managed processes
* Minimum amount of free memory required before spawning

These checks provide lightweight application-level resource control without attempting to provide operating-system-level memory isolation.

The broader architecture can extend this approach to additional resource policies such as queue depth, message buffers, concurrent tasks, restart frequency, and other resources whose uncontrolled growth could affect system stability.

## Examples

The framework is intended for embedded applications where multiple independent functions must coexist within the same MicroPython runtime.

### IoT Gateway

Separate processes can handle sensor collection, network communication, data processing, and logging while sharing the same MCU.

### Robotics Controller

Independent processes can manage sensors, actuator control, telemetry, and periodic control tasks without requiring a full operating-system process model.

### Industrial Monitoring

Monitoring, threshold evaluation, event handling, and communication can be represented as independently managed application processes.

### Environmental Monitoring

Sensor acquisition, data aggregation, storage, and periodic transmission can operate as scheduled asynchronous processes on a low-power embedded node.

## Milestones

The milestone checklist represents the major implementation stages of the framework.

* [x] Core process management (Process abstraction, lifecycle state, identification, cancellation, and restart handling)
* [x] Resource-aware process management (Process-count limits and free-memory admission checks)
* [x] Cooperative scheduling (Asynchronous execution using MicroPython's cooperative concurrency model)
* [x] Time-based scheduling (Scheduled and delayed execution using a heap-based scheduler)
* [x] Priority and repeated scheduling (Priority ordering, repeated jobs, scheduled-job tracking, and scheduler lifecycle control)
* [x] Watchdog management (Hardware watchdog integration and health-aware watchdog servicing)
* [ ] Fault handling architecture (Structured failure reporting, restart policies, failure history, back-off, retry limits, and escalation)
* [ ] Inter-processor communication (Communication mechanisms for exchanging data between processors)
* [ ] Memory monitoring (Continuous memory tracking, thresholds, garbage-collection policies, and resource-state handling)
* [ ] Dynamic service management (Filesystem-based service loading, controlled service replacement, and resource cleanup)
* [ ] Configuration-driven startup (Configuration-based service selection, startup ordering, dependencies, and runtime parameters)
* [ ] Logging and diagnostics (Centralized structured logging, severity levels, timestamps, and diagnostic output)
* [ ] System supervision (Centralized health monitoring, failure escalation, and overall system coordination)
