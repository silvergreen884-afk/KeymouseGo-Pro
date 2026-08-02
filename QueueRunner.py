# -*- coding: utf-8 -*-
"""
KeymouseGo Pro - Queue Runner

目前是模拟执行版本：
- 不会操作鼠标或键盘
- 按任务次数逐项推进
- 支持指定轮数或无限循环
- 支持暂停、继续和停止
"""

from __future__ import annotations

from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot


class QueueRunner(QObject):
    """异步任务队列模拟执行器。"""

    started = Signal()
    paused = Signal()
    resumed = Signal()
    stopped = Signal()
    finished = Signal()

    status_changed = Signal(str)

    progress_changed = Signal(
        int,  # 当前轮
        int,  # 总轮数；无限循环时为 0
        int,  # 当前任务序号
        int,  # 总任务数
        str,  # 当前 Script 路径
        int,  # 当前执行次数
        int,  # 当前任务总次数
    )

    task_started = Signal(int, str, int)
    task_finished = Signal(int, str)
    round_started = Signal(int)
    round_finished = Signal(int)

    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._advance)

        self._tasks: list[dict[str, Any]] = []

        self._infinite_loop = False
        self._total_rounds = 1

        self._round_index = 0
        self._task_index = 0
        self._run_index = 0

        self._running = False
        self._paused = False
        self._stop_requested = False

        # 模拟执行间隔，后面接入真实脚本后会移除。
        self._simulation_interval_ms = 150

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def is_paused(self) -> bool:
        return self._paused

    def configure(
        self,
        tasks: list[dict[str, Any]],
        infinite_loop: bool,
        total_rounds: int,
    ) -> None:
        """
        设置待执行任务。

        configure() 只能在未运行时调用。
        """
        if self._running:
            raise RuntimeError("任务正在运行，不能重新配置。")

        enabled_tasks = [
            dict(task)
            for task in tasks
            if bool(task.get("enabled", True))
        ]

        if not enabled_tasks:
            raise ValueError("没有可执行的任务。")

        for task in enabled_tasks:
            script_path = str(task.get("script", "")).strip()
            times = int(task.get("times", 1))

            if not script_path:
                raise ValueError("任务中存在空的 Script 路径。")

            if times < 1:
                raise ValueError(
                    f"Script 的运行次数必须至少为 1：{script_path}"
                )

            task["script"] = script_path
            task["times"] = times

        self._tasks = enabled_tasks
        self._infinite_loop = bool(infinite_loop)
        self._total_rounds = max(1, int(total_rounds))

    @Slot()
    def start(self) -> None:
        if self._running:
            return

        if not self._tasks:
            self.error_occurred.emit("任务队列为空，无法开始。")
            return

        self._round_index = 0
        self._task_index = 0
        self._run_index = 0

        self._running = True
        self._paused = False
        self._stop_requested = False

        self.started.emit()
        self.status_changed.emit("任务队列已开始")

        self._start_round()

    @Slot()
    def pause(self) -> None:
        if not self._running or self._paused:
            return

        self._paused = True
        self._timer.stop()

        self.paused.emit()
        self.status_changed.emit("任务队列已暂停")

    @Slot()
    def resume(self) -> None:
        if not self._running or not self._paused:
            return

        self._paused = False

        self.resumed.emit()
        self.status_changed.emit("任务队列继续运行")

        self._schedule_next_step()

    @Slot()
    def stop(self) -> None:
        if not self._running:
            return

        self._stop_requested = True
        self._timer.stop()
        self._finish_as_stopped()

    def _start_round(self) -> None:
        if self._should_finish():
            self._finish_normally()
            return

        self._round_index += 1
        self._task_index = 0
        self._run_index = 0

        self.round_started.emit(self._round_index)
        self.status_changed.emit(
            f"开始第 {self._round_index} 轮"
        )

        self._start_task()

    def _start_task(self) -> None:
        if self._stop_requested:
            self._finish_as_stopped()
            return

        if self._task_index >= len(self._tasks):
            self._finish_round()
            return

        task = self._tasks[self._task_index]
        self._run_index = 0

        self.task_started.emit(
            self._task_index + 1,
            task["script"],
            task["times"],
        )

        self.status_changed.emit(
            f"正在执行：{task['script']}"
        )

        self._schedule_next_step()

    def _schedule_next_step(self) -> None:
        if not self._running:
            return

        if self._paused or self._stop_requested:
            return

        self._timer.start(self._simulation_interval_ms)

    def _advance(self) -> None:
        if not self._running:
            return

        if self._paused:
            return

        if self._stop_requested:
            self._finish_as_stopped()
            return

        task = self._tasks[self._task_index]
        total_times = task["times"]

        self._run_index += 1

        total_rounds = 0 if self._infinite_loop else self._total_rounds

        self.progress_changed.emit(
            self._round_index,
            total_rounds,
            self._task_index + 1,
            len(self._tasks),
            task["script"],
            self._run_index,
            total_times,
        )

        if self._run_index >= total_times:
            self.task_finished.emit(
                self._task_index + 1,
                task["script"],
            )

            self._task_index += 1
            self._start_task()
            return

        self._schedule_next_step()

    def _finish_round(self) -> None:
        self.round_finished.emit(self._round_index)
        self.status_changed.emit(
            f"第 {self._round_index} 轮完成"
        )

        if self._should_finish():
            self._finish_normally()
            return

        self._start_round()

    def _should_finish(self) -> bool:
        if self._infinite_loop:
            return False

        return self._round_index >= self._total_rounds

    def _finish_normally(self) -> None:
        self._timer.stop()

        self._running = False
        self._paused = False
        self._stop_requested = False

        self.status_changed.emit("全部任务执行完成")
        self.finished.emit()

    def _finish_as_stopped(self) -> None:
        self._timer.stop()

        self._running = False
        self._paused = False
        self._stop_requested = False

        self.status_changed.emit("任务队列已停止")
        self.stopped.emit()