# -*- coding: utf-8 -*-
"""
KeymouseGo Pro - Real Queue Runner

负责：
- 按顺序执行多个 Script
- 每个 Script 使用各自的运行次数
- 支持指定轮数或无限循环
- 支持暂停、继续和停止
- 复用 KeymouseGo 原版的 Script 解析与事件执行逻辑
"""

from __future__ import annotations

import random
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal, Slot

from Util.RunScriptClass import QueueScriptRunner


class QueueRunner(QObject):
    """KeymouseGo Pro 真实任务队列执行器。"""

    started = Signal()
    paused = Signal()
    resumed = Signal()
    stopped = Signal()
    finished = Signal()

    status_changed = Signal(str)

    progress_changed = Signal(
        int,   # 当前轮
        int,   # 总轮数；无限循环时为 0
        int,   # 当前任务序号
        int,   # 总任务数
        str,   # 当前 Script 路径
        int,   # 当前执行次数
        int,   # 当前任务总次数
    )

    task_started = Signal(
        int,   # 当前任务序号
        str,   # Script 路径
        int,   # 运行次数
    )

    task_finished = Signal(
        int,   # 当前任务序号
        str,   # Script 路径
    )

    round_started = Signal(int)
    round_finished = Signal(int)

    error_occurred = Signal(str)

    def __init__(self, parent: QObject | None = None):
        super().__init__(parent)

        self._tasks: list[dict[str, Any]] = []

        self._infinite_loop = False
        self._total_rounds = 1

        self._round_index = 0
        self._task_index = 0
        self._retry_count = 0

        self._running = False
        self._paused = False
        self._stop_requested = False

        self._worker: QueueScriptRunner | None = None

        self._worker_success = False
        self._worker_message = ""
        
        # Script 完成后的等待计时器。
        # 使用短间隔计时，等待期间仍然可以暂停或停止。
        self._wait_timer = QTimer(self)
        self._wait_timer.setInterval(100)
        self._wait_timer.timeout.connect(
            self._on_wait_timer_tick
        )

        self._wait_remaining_ms = 0
        self._waiting_after_task = False

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
        设置任务队列。

        运行期间不能重新设置任务。
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
            script_path = str(
                task.get("script", "")
            ).strip()

            times = int(
                task.get("times", 1)
            )

            if not script_path:
                raise ValueError(
                    "任务中存在空的 Script 路径。"
                )

            if times < 1:
                raise ValueError(
                    "Script 的运行次数必须至少为 1："
                    f"{script_path}"
                )

            task["script"] = script_path
            task["times"] = times

            task["failure_action"] = str(
                task.get(
                    "failure_action",
                    "停止",
                )
            )

            task["max_retry"] = max(
                0,
                int(
                    task.get(
                        "max_retry",
                        0,
                    )
                ),
            )

        self._tasks = enabled_tasks
        self._infinite_loop = bool(infinite_loop)
        self._total_rounds = max(
            1,
            int(total_rounds),
        )

    @Slot()
    def start(self) -> None:
        """从第一轮、第一项任务开始真实执行。"""
        if self._running:
            return

        if not self._tasks:
            self.error_occurred.emit(
                "任务队列为空，无法开始。"
            )
            return

        self._round_index = 0
        self._task_index = 0
        self._retry_count = 0

        self._wait_timer.stop()
        self._wait_remaining_ms = 0
        self._waiting_after_task = False
        
        self._running = True
        self._paused = False
        self._stop_requested = False

        self.started.emit()
        self.status_changed.emit(
            "任务队列已开始"
        )

        self._start_next_round()

    @Slot()
    def pause(self) -> None:
        """暂停当前正在执行的 Script。"""
        if not self._running:
            return

        if self._paused:
            return

        self._paused = True

        if self._worker is not None:
            self._worker.set_pause()

        self.paused.emit()
        self.status_changed.emit(
            "任务队列已暂停"
        )

    @Slot()
    def resume(self) -> None:
        """继续当前暂停的 Script。"""
        if not self._running:
            return

        if not self._paused:
            return

        self._paused = False

        if self._worker is not None:
            self._worker.resume()

        self.resumed.emit()
        self.status_changed.emit(
            "任务队列继续运行"
        )

    @Slot()
    def stop(self) -> None:
        """停止整个任务队列。"""
        if not self._running:
            return

        self._stop_requested = True
        self._paused = False
        
        self._wait_timer.stop()
        self._wait_remaining_ms = 0
        self._waiting_after_task = False

        self.status_changed.emit(
            "正在停止任务队列……"
        )

        if self._worker is not None:
            self._worker.request_stop()
        else:
            self._finish_as_stopped()

    def _start_next_round(self) -> None:
        """开始下一轮。"""
        if self._stop_requested:
            self._finish_as_stopped()
            return

        if (
            not self._infinite_loop
            and self._round_index
            >= self._total_rounds
        ):
            self._finish_normally()
            return

        self._round_index += 1
        self._task_index = 0
        self._retry_count = 0

        self.round_started.emit(
            self._round_index
        )

        self.status_changed.emit(
            f"开始第 {self._round_index} 轮"
        )

        self._start_current_task()

    def _start_current_task(self) -> None:
        """执行当前轮中的当前任务。"""
        if self._stop_requested:
            self._finish_as_stopped()
            return

        if self._task_index >= len(self._tasks):
            self._finish_current_round()
            return

        task = self._tasks[
            self._task_index
        ]

        script_path = task["script"]
        run_times = task["times"]

        self.task_started.emit(
            self._task_index + 1,
            script_path,
            run_times,
        )

        self.status_changed.emit(
            "正在执行："
            f"{script_path}"
        )

        self._worker_success = False
        self._worker_message = ""

        self._worker = QueueScriptRunner(
            script_path=script_path,
            run_times=run_times,
            parent=self,
        )

        self._worker.progressSignal.connect(
            self._on_worker_progress
        )

        self._worker.logSignal.connect(
            self._on_worker_log
        )

        self._worker.completedSignal.connect(
            self._on_worker_completed
        )

        self._worker.finished.connect(
            self._on_worker_thread_finished
        )

        self._worker.start()

    @Slot(int, int)
    def _on_worker_progress(
        self,
        current_run: int,
        total_runs: int,
    ) -> None:
        """把真实 Script 执行进度传给界面。"""
        if (
            not self._running
            or self._task_index
            >= len(self._tasks)
        ):
            return

        task = self._tasks[
            self._task_index
        ]

        total_rounds = (
            0
            if self._infinite_loop
            else self._total_rounds
        )

        self.progress_changed.emit(
            self._round_index,
            total_rounds,
            self._task_index + 1,
            len(self._tasks),
            task["script"],
            current_run,
            total_runs,
        )

    @Slot(str)
    def _on_worker_log(
        self,
        message: str,
    ) -> None:
        """
        当前阶段暂时只保留日志接口。

        后续可以把这些内容显示在任务队列日志框中。
        """
        _ = message

    @Slot(bool, str)
    def _on_worker_completed(
        self,
        success: bool,
        message: str,
    ) -> None:
        """
        记录执行结果。

        真正开始下一项任务，要等待 QThread 的 finished，
        避免上一线程仍未完全退出。
        """
        self._worker_success = bool(
            success
        )

        self._worker_message = str(
            message
        )

    @Slot()
    def _on_worker_thread_finished(
        self,
    ) -> None:
        """当前 Script 线程完全结束后的处理。"""
        finished_worker = self._worker
        self._worker = None

        if finished_worker is not None:
            finished_worker.deleteLater()

        if self._stop_requested:
            self._finish_as_stopped()
            return

        if (
            not self._running
            or self._task_index
            >= len(self._tasks)
        ):
            return

        task = self._tasks[
            self._task_index
        ]

        if self._worker_success:
            self.task_finished.emit(
                self._task_index + 1,
                task["script"],
            )

            self._retry_count = 0

            # 不要立即开始下一项，
            # 先进入等待流程。
            self._begin_task_wait(task)

            return

    def _get_task_wait_seconds(
        self,
        task: dict[str, Any],
    ) -> int:
        """计算当前任务完成后需要等待多少秒。"""
        wait_type = str(
            task.get(
                "wait_type",
                "固定",
            )
        )

        wait_min = max(
            0,
            int(
                task.get(
                    "wait_min",
                    0,
                )
            ),
        )

        wait_max = max(
            0,
            int(
                task.get(
                    "wait_max",
                    wait_min,
                )
            ),
        )

        if wait_type == "随机":
            # 防止用户把最大值设得比最小值小。
            low = min(wait_min, wait_max)
            high = max(wait_min, wait_max)

            return random.randint(
                low,
                high,
            )

        # 固定等待使用“最少秒数”这一栏。
        return wait_min

    def _begin_task_wait(
        self,
        task: dict[str, Any],
    ) -> None:
        """在当前 Script 完成后开始等待。"""
        wait_seconds = self._get_task_wait_seconds(
            task
        )

        if wait_seconds <= 0:
            self._advance_to_next_task()
            return

        self._wait_remaining_ms = (
            wait_seconds * 1000
        )
        self._waiting_after_task = True

        script_name = Path(
            task["script"]
        ).name

        self.status_changed.emit(
            f"{script_name} 已完成，"
            f"等待 {wait_seconds} 秒后执行下一任务"
        )

        self._wait_timer.start()

    @Slot()
    def _on_wait_timer_tick(self) -> None:
        """处理 Script 完成后的等待倒计时。"""
        if not self._running:
            self._wait_timer.stop()
            return

        if self._stop_requested:
            self._wait_timer.stop()
            self._wait_remaining_ms = 0
            self._waiting_after_task = False
            self._finish_as_stopped()
            return

        # 暂停期间不扣减剩余等待时间。
        if self._paused:
            return

        self._wait_remaining_ms -= (
            self._wait_timer.interval()
        )

        if self._wait_remaining_ms > 0:
            return

        self._wait_timer.stop()
        self._wait_remaining_ms = 0
        self._waiting_after_task = False

        self._advance_to_next_task()

    def _advance_to_next_task(self) -> None:
        """进入当前轮的下一个任务。"""
        if self._stop_requested:
            self._finish_as_stopped()
            return

        self._task_index += 1
        self._start_current_task()

    def _handle_task_failure(
        self,
        task: dict[str, Any],
    ) -> None:
        """根据任务设置处理执行失败。"""
        failure_action = str(
            task.get(
                "failure_action",
                "停止",
            )
        )

        max_retry = max(
            0,
            int(
                task.get(
                    "max_retry",
                    0,
                )
            ),
        )

        if (
            failure_action == "重试"
            and self._retry_count
            < max_retry
        ):
            self._retry_count += 1

            self.status_changed.emit(
                "Script 执行失败，正在重试："
                f"{self._retry_count}/"
                f"{max_retry}"
            )

            self._start_current_task()
            return

        if failure_action == "跳过":
            self.status_changed.emit(
                "Script 执行失败，已跳过："
                f"{task['script']}"
            )

            self._retry_count = 0
            self._task_index += 1

            self._start_current_task()
            return

        error_message = (
            self._worker_message
            or "Script 执行失败。"
        )

        self.error_occurred.emit(
            "任务执行失败：\n\n"
            f"{task['script']}\n\n"
            f"{error_message}"
        )

        self._finish_as_stopped()

    def _finish_current_round(self) -> None:
        """完成当前轮，然后决定下一轮或结束。"""
        self.round_finished.emit(
            self._round_index
        )

        self.status_changed.emit(
            f"第 {self._round_index} 轮完成"
        )

        if (
            not self._infinite_loop
            and self._round_index
            >= self._total_rounds
        ):
            self._finish_normally()
            return

        self._start_next_round()

    def _finish_normally(self) -> None:
        """全部任务正常完成。"""
        self._wait_timer.stop()
        self._wait_remaining_ms = 0
        self._waiting_after_task = False
        
        self._running = False
        self._paused = False
        self._stop_requested = False

        self._worker = None

        self.status_changed.emit(
            "全部任务执行完成"
        )

        self.finished.emit()

    def _finish_as_stopped(self) -> None:
        """任务被用户停止或发生错误。"""
        self._wait_timer.stop()
        self._wait_remaining_ms = 0
        self._waiting_after_task = False
        
        self._running = False
        self._paused = False
        self._stop_requested = False

        self._worker = None

        self.status_changed.emit(
            "任务队列已停止"
        )

        self.stopped.emit()