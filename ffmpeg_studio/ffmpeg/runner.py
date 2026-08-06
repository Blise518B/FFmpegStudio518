"""Run job plans sequentially with live progress.

Uses QProcess from the GUI thread — it is fully asynchronous (signal driven),
so the UI stays responsive without any extra threads. Progress comes from
``-progress pipe:1``: ffmpeg prints ``out_time_us=…`` blocks on stdout which
we turn into a percentage using the plan's known duration.
"""
from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

from PySide6.QtCore import QObject, QProcess, Signal

from .command import JobPlan


@dataclass
class Job:
    src: Path
    plan: JobPlan
    row: int                       # caller's handle (file-list row)
    status: str = "pending"        # pending|running|done|error|cancelled
    message: str = ""
    log: list[str] = field(default_factory=list)


class JobRunner(QObject):
    job_started = Signal(int)                 # row
    job_progress = Signal(int, float, str)    # row, 0..100, "1.7x" speed
    job_log = Signal(int, str)                # row, text chunk
    job_finished = Signal(int, bool, str)     # row, ok, message
    queue_finished = Signal(int, int, int)    # done, failed, cancelled

    def __init__(self, ffmpeg: Path, parent: QObject | None = None):
        super().__init__(parent)
        self.ffmpeg = ffmpeg
        self._jobs: list[Job] = []
        self._index = -1
        self._pass = 0
        self._proc: QProcess | None = None
        self._cancelled = False
        self._stdout_buf = ""
        self.running = False

    # -- public ----------------------------------------------------------
    def start(self, jobs: list[Job]) -> None:
        if self.running or not jobs:
            return
        self._jobs = jobs
        self._index = -1
        self._cancelled = False
        self.running = True
        self._next_job()

    def cancel(self) -> None:
        if not self.running:
            return
        self._cancelled = True
        if self._proc is not None and \
                self._proc.state() != QProcess.ProcessState.NotRunning:
            self._proc.kill()      # its finished signal wraps the queue up
        else:
            self._finish_queue()

    # -- queue stepping --------------------------------------------------
    def _next_job(self) -> None:
        self._index += 1
        if self._cancelled or self._index >= len(self._jobs):
            self._finish_queue()
            return
        job = self._jobs[self._index]
        job.status = "running"
        self._pass = 0
        self.job_started.emit(job.row)
        self._start_pass(job)

    def _start_pass(self, job: Job) -> None:
        # progress flags go FIRST: some ffmpeg versions ignore trailing
        # options after the output file. -nostdin keeps ffmpeg from reading
        # the inherited stdin, the classic batch-loop hang.
        args = ["-progress", "pipe:1", "-nostats", "-nostdin"] \
            + list(job.plan.passes[self._pass])
        self._stdout_buf = ""

        proc = QProcess(self)
        self._proc = proc
        proc.readyReadStandardOutput.connect(self._on_stdout)
        proc.readyReadStandardError.connect(self._on_stderr)
        proc.finished.connect(self._on_finished)
        proc.errorOccurred.connect(self._on_proc_error)
        self.job_log.emit(job.row, "$ ffmpeg " + " ".join(args) + "\n")
        proc.start(str(self.ffmpeg), args)

    # -- process events --------------------------------------------------
    def _current(self) -> Job | None:
        if 0 <= self._index < len(self._jobs):
            return self._jobs[self._index]
        return None

    def _on_stdout(self) -> None:
        job, proc = self._current(), self._proc
        if job is None or proc is None:
            return
        self._stdout_buf += bytes(proc.readAllStandardOutput()).decode(
            "utf-8", "replace")
        *lines, self._stdout_buf = self._stdout_buf.split("\n")
        out_time_us = None
        speed = ""
        for line in lines:
            key, _, value = line.strip().partition("=")
            if key in ("out_time_us", "out_time_ms"):
                # both are microseconds (ffmpeg quirk); prefer either
                try:
                    out_time_us = int(value)
                except ValueError:
                    pass
            elif key == "speed":
                speed = value.strip()
        if out_time_us is not None and job.plan.duration:
            frac = max(0.0, min(1.0, (out_time_us / 1e6) / job.plan.duration))
            npasses = len(job.plan.passes)
            pct = (self._pass + frac) / npasses * 100.0
            self.job_progress.emit(job.row, pct, speed)

    def _on_stderr(self) -> None:
        job, proc = self._current(), self._proc
        if job is None or proc is None:
            return
        text = bytes(proc.readAllStandardError()).decode("utf-8", "replace")
        if text:
            job.log.append(text)
            if len(job.log) > 400:            # keep memory bounded
                del job.log[:100]
            self.job_log.emit(job.row, text)

    def _on_proc_error(self, err) -> None:
        # FailedToStart never emits finished — handle it here
        if self._proc is not None and err == QProcess.ProcessError.FailedToStart:
            self._end_job(False, "ffmpeg failed to start")

    def _on_finished(self, code: int, _status) -> None:
        job = self._current()
        if job is None:
            return
        if self._cancelled:
            self._end_job(False, "cancelled")
            return
        if code != 0:
            tail = "".join(job.log)[-400:].strip()
            last = tail.splitlines()[-1] if tail else f"exit code {code}"
            self._end_job(False, last)
            return
        if self._pass + 1 < len(job.plan.passes):
            self._pass += 1
            self._start_pass(job)
            return
        self._end_job(True, "done")

    # -- wrap-up ---------------------------------------------------------
    def _end_job(self, ok: bool, message: str) -> None:
        job = self._current()
        if job is None:
            return
        self._proc = None
        job.status = "done" if ok else (
            "cancelled" if self._cancelled else "error")
        job.message = message
        self._cleanup(job, keep_output=ok)
        self.job_finished.emit(job.row, ok, message)
        self._next_job()

    def _cleanup(self, job: Job, keep_output: bool) -> None:
        if not keep_output:
            try:
                job.plan.output.unlink(missing_ok=True)
            except OSError:
                pass
        if job.plan.passlog:
            for f in glob.glob(glob.escape(job.plan.passlog) + "*"):
                try:
                    os.unlink(f)
                except OSError:
                    pass

    def _finish_queue(self) -> None:
        if not self.running:
            return
        self.running = False
        self._proc = None
        done = sum(1 for j in self._jobs if j.status == "done")
        failed = sum(1 for j in self._jobs if j.status == "error")
        cancelled = sum(1 for j in self._jobs
                        if j.status in ("cancelled", "pending", "running"))
        self.queue_finished.emit(done, failed, cancelled)
