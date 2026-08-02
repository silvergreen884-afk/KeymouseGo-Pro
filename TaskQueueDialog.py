# -*- coding: utf-8 -*-
"""
KeymouseGo Pro - Task Queue UI (UI-only first step)

This module only defines the task queue window.
It does not yet execute scripts or modify the original KeymouseGo behavior.
"""
import json

from pathlib import Path
from PySide6.QtCore import Qt
from QueueRunner import QueueRunner
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
    QMessageBox,
)


class TaskQueueDialog(QDialog):
    """Task queue configuration window."""

    COLUMN_ENABLED = 0
    COLUMN_SCRIPT = 1
    COLUMN_TIMES = 2
    COLUMN_WAIT_TYPE = 3
    COLUMN_WAIT_MIN = 4
    COLUMN_WAIT_MAX = 5
    COLUMN_FAILURE_ACTION = 6
    COLUMN_RETRY = 7
    COLUMN_NOTE = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("KeymouseGo Pro - 任务队列")
        self.resize(1180, 720)
        self.setMinimumSize(980, 600)

        self._build_ui()

        self.runner = QueueRunner(self)
        self._last_progress_text = ""

        self._connect_signals()
        self._connect_runner_signals()
        self._update_button_states()

    def _build_ui(self):
        root_layout = QVBoxLayout(self)
        root_layout.setContentsMargins(12, 12, 12, 12)
        root_layout.setSpacing(10)

        title = QLabel("任务队列")
        title.setStyleSheet("font-size: 20px; font-weight: 600;")
        root_layout.addWidget(title)

        description = QLabel(
            "每一行代表一个 Script。当前版本仅完成界面，执行、暂停、保存和载入功能将在后续步骤接入。"
        )
        description.setWordWrap(True)
        root_layout.addWidget(description)

        self.table = QTableWidget(0, 9, self)
        self.table.setHorizontalHeaderLabels(
            [
                "启用",
                "Script",
                "次数",
                "等待类型",
                "最少秒数",
                "最多秒数",
                "失败动作",
                "最大重试",
                "备注",
            ]
        )
        self.table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.table.setEditTriggers(
            QAbstractItemView.DoubleClicked
            | QAbstractItemView.SelectedClicked
            | QAbstractItemView.EditKeyPressed
        )
        self.table.setAlternatingRowColors(True)
        self.table.verticalHeader().setVisible(False)

        header = self.table.horizontalHeader()
        header.setSectionResizeMode(self.COLUMN_ENABLED, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_SCRIPT, QHeaderView.Stretch)
        header.setSectionResizeMode(self.COLUMN_TIMES, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_WAIT_TYPE, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_WAIT_MIN, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_WAIT_MAX, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_FAILURE_ACTION, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_RETRY, QHeaderView.ResizeToContents)
        header.setSectionResizeMode(self.COLUMN_NOTE, QHeaderView.Stretch)

        root_layout.addWidget(self.table, 1)

        task_buttons = QHBoxLayout()
        self.add_button = QPushButton("添加 Script")
        self.remove_button = QPushButton("删除")
        self.duplicate_button = QPushButton("复制")
        self.move_up_button = QPushButton("上移")
        self.move_down_button = QPushButton("下移")
        self.clear_button = QPushButton("清空")

        task_buttons.addWidget(self.add_button)
        task_buttons.addWidget(self.remove_button)
        task_buttons.addWidget(self.duplicate_button)
        task_buttons.addSpacing(12)
        task_buttons.addWidget(self.move_up_button)
        task_buttons.addWidget(self.move_down_button)
        task_buttons.addStretch(1)
        task_buttons.addWidget(self.clear_button)
        root_layout.addLayout(task_buttons)

        settings_row = QHBoxLayout()
        settings_row.setSpacing(10)

        loop_group = QGroupBox("整组循环")
        loop_layout = QFormLayout(loop_group)

        self.infinite_loop_checkbox = QCheckBox("无限循环")
        self.infinite_loop_checkbox.setChecked(True)

        self.loop_count_spinbox = QSpinBox()
        self.loop_count_spinbox.setRange(1, 999999)
        self.loop_count_spinbox.setValue(1)
        self.loop_count_spinbox.setEnabled(False)

        loop_layout.addRow(self.infinite_loop_checkbox)
        loop_layout.addRow("指定轮数：", self.loop_count_spinbox)
        settings_row.addWidget(loop_group)

        round_wait_group = QGroupBox("每轮完成后等待")
        round_wait_layout = QFormLayout(round_wait_group)

        self.round_wait_type_combo = QComboBox()
        self.round_wait_type_combo.addItems(["固定", "随机"])

        self.round_wait_min_spinbox = QSpinBox()
        self.round_wait_min_spinbox.setRange(0, 86400)
        self.round_wait_min_spinbox.setValue(3)
        self.round_wait_min_spinbox.setSuffix(" 秒")

        self.round_wait_max_spinbox = QSpinBox()
        self.round_wait_max_spinbox.setRange(0, 86400)
        self.round_wait_max_spinbox.setValue(3)
        self.round_wait_max_spinbox.setSuffix(" 秒")
        self.round_wait_max_spinbox.setEnabled(False)

        round_wait_layout.addRow("类型：", self.round_wait_type_combo)
        round_wait_layout.addRow("最少：", self.round_wait_min_spinbox)
        round_wait_layout.addRow("最多：", self.round_wait_max_spinbox)
        settings_row.addWidget(round_wait_group)

        config_group = QGroupBox("任务配置")
        config_layout = QVBoxLayout(config_group)

        self.config_path_edit = QLineEdit()
        self.config_path_edit.setReadOnly(True)
        self.config_path_edit.setPlaceholderText("尚未载入或保存任务配置")

        config_button_row = QHBoxLayout()
        self.save_button = QPushButton("保存配置")
        self.load_button = QPushButton("载入配置")
        config_button_row.addWidget(self.save_button)
        config_button_row.addWidget(self.load_button)

        config_layout.addWidget(self.config_path_edit)
        config_layout.addLayout(config_button_row)
        settings_row.addWidget(config_group, 1)

        root_layout.addLayout(settings_row)

        control_group = QGroupBox("运行控制")
        control_layout = QHBoxLayout(control_group)

        self.start_button = QPushButton("开始")
        self.pause_button = QPushButton("暂停")
        self.resume_button = QPushButton("继续")
        self.stop_button = QPushButton("停止")

        self.pause_button.setEnabled(False)
        self.resume_button.setEnabled(False)
        self.stop_button.setEnabled(False)

        control_layout.addWidget(self.start_button)
        control_layout.addWidget(self.pause_button)
        control_layout.addWidget(self.resume_button)
        control_layout.addWidget(self.stop_button)
        control_layout.addStretch(1)

        self.status_label = QLabel("状态：就绪")
        control_layout.addWidget(self.status_label)

        root_layout.addWidget(control_group)

    def _connect_signals(self):
        self.add_button.clicked.connect(self._choose_scripts)
        self.remove_button.clicked.connect(self._remove_selected_row)
        self.duplicate_button.clicked.connect(self._duplicate_selected_row)
        self.move_up_button.clicked.connect(lambda: self._move_selected_row(-1))
        self.move_down_button.clicked.connect(lambda: self._move_selected_row(1))
        self.clear_button.clicked.connect(self._clear_rows)

        self.table.itemSelectionChanged.connect(self._update_button_states)

        self.infinite_loop_checkbox.toggled.connect(
            lambda checked: self.loop_count_spinbox.setEnabled(not checked)
        )
        self.round_wait_type_combo.currentTextChanged.connect(
            self._on_round_wait_type_changed
        )

        # UI-only placeholders. Real save/load/run logic will be added later.
        self.save_button.clicked.connect(self._save_config)
        self.load_button.clicked.connect(self._load_config)
        self.start_button.clicked.connect(self._start_queue_simulation)
        self.pause_button.clicked.connect(self.runner.pause)
        self.resume_button.clicked.connect(self.runner.resume)
        self.stop_button.clicked.connect(self.runner.stop)

    def _choose_scripts(self):
        paths, _ = QFileDialog.getOpenFileNames(
            self,
            "选择一个或多个 KeymouseGo Script",
            "",
            "KeymouseGo Script (*.txt *.json5);;所有文件 (*.*)",
        )
        for path in paths:
            self.add_task_row(path)

    def add_task_row(
        self,
        script_path,
        times=1,
        enabled=True,
        wait_type="固定",
        wait_min=0,
        wait_max=0,
        failure_action="停止",
        max_retry=0,
        note="",
    ):
        row = self.table.rowCount()
        self.table.insertRow(row)

        enabled_item = QTableWidgetItem()
        enabled_item.setFlags(
            Qt.ItemIsSelectable | Qt.ItemIsEnabled | Qt.ItemIsUserCheckable
        )
        enabled_item.setCheckState(Qt.Checked if enabled else Qt.Unchecked)
        self.table.setItem(row, self.COLUMN_ENABLED, enabled_item)

        full_path = str(script_path)
        script_item = QTableWidgetItem(Path(full_path).name)
        script_item.setData(Qt.UserRole, full_path)
        script_item.setToolTip(full_path)
        self.table.setItem(row, self.COLUMN_SCRIPT, script_item)

        times_spinbox = QSpinBox()
        times_spinbox.setRange(1, 999999)
        times_spinbox.setValue(int(times))
        self.table.setCellWidget(row, self.COLUMN_TIMES, times_spinbox)

        wait_type_combo = QComboBox()
        wait_type_combo.addItems(["固定", "随机"])
        wait_type_combo.setCurrentText(wait_type)
        wait_type_combo.currentTextChanged.connect(
            lambda text, combo=wait_type_combo: self._update_task_wait_widgets(combo, text)
        )
        self.table.setCellWidget(row, self.COLUMN_WAIT_TYPE, wait_type_combo)

        wait_min_spinbox = QSpinBox()
        wait_min_spinbox.setRange(0, 86400)
        wait_min_spinbox.setValue(int(wait_min))
        wait_min_spinbox.setSuffix(" 秒")
        self.table.setCellWidget(row, self.COLUMN_WAIT_MIN, wait_min_spinbox)

        wait_max_spinbox = QSpinBox()
        wait_max_spinbox.setRange(0, 86400)
        wait_max_spinbox.setValue(int(wait_max))
        wait_max_spinbox.setSuffix(" 秒")
        wait_max_spinbox.setEnabled(wait_type == "随机")
        self.table.setCellWidget(row, self.COLUMN_WAIT_MAX, wait_max_spinbox)

        failure_combo = QComboBox()
        failure_combo.addItems(["停止", "重试", "跳过"])
        failure_combo.setCurrentText(failure_action)
        self.table.setCellWidget(row, self.COLUMN_FAILURE_ACTION, failure_combo)

        retry_spinbox = QSpinBox()
        retry_spinbox.setRange(0, 999)
        retry_spinbox.setValue(int(max_retry))
        self.table.setCellWidget(row, self.COLUMN_RETRY, retry_spinbox)

        note_item = QTableWidgetItem(str(note))
        self.table.setItem(row, self.COLUMN_NOTE, note_item)

        self.table.selectRow(row)
        self._update_button_states()

    def _update_task_wait_widgets(self, combo, wait_type):
        for row in range(self.table.rowCount()):
            if self.table.cellWidget(row, self.COLUMN_WAIT_TYPE) is combo:
                max_widget = self.table.cellWidget(row, self.COLUMN_WAIT_MAX)
                if max_widget is not None:
                    max_widget.setEnabled(wait_type == "随机")
                break

    def _selected_row(self):
        rows = self.table.selectionModel().selectedRows()
        return rows[0].row() if rows else -1

    def _remove_selected_row(self):
        row = self._selected_row()
        if row >= 0:
            self.table.removeRow(row)
            if self.table.rowCount() > 0:
                self.table.selectRow(min(row, self.table.rowCount() - 1))
        self._update_button_states()

    def _duplicate_selected_row(self):
        row = self._selected_row()
        if row < 0:
            return

        enabled = self.table.item(row, self.COLUMN_ENABLED).checkState() == Qt.Checked
        script_item = self.table.item(row, self.COLUMN_SCRIPT)
        script = script_item.data(Qt.UserRole) or script_item.text()
        times = self.table.cellWidget(row, self.COLUMN_TIMES).value()
        wait_type = self.table.cellWidget(row, self.COLUMN_WAIT_TYPE).currentText()
        wait_min = self.table.cellWidget(row, self.COLUMN_WAIT_MIN).value()
        wait_max = self.table.cellWidget(row, self.COLUMN_WAIT_MAX).value()
        failure_action = self.table.cellWidget(
            row, self.COLUMN_FAILURE_ACTION
        ).currentText()
        max_retry = self.table.cellWidget(row, self.COLUMN_RETRY).value()
        note_item = self.table.item(row, self.COLUMN_NOTE)
        note = note_item.text() if note_item is not None else ""

        self.add_task_row(
            script,
            times,
            enabled,
            wait_type,
            wait_min,
            wait_max,
            failure_action,
            max_retry,
            note,
        )

    def _move_selected_row(self, direction):
        row = self._selected_row()
        target = row + direction

        if row < 0 or target < 0 or target >= self.table.rowCount():
            return

        first = self._read_row(row)
        second = self._read_row(target)
        self._write_row(row, second)
        self._write_row(target, first)
        self.table.selectRow(target)
        self._update_button_states()

    def _read_row(self, row):
        note_item = self.table.item(row, self.COLUMN_NOTE)
        return {
            "enabled": self.table.item(row, self.COLUMN_ENABLED).checkState()
            == Qt.Checked,
            "script": (
            self.table.item(row, self.COLUMN_SCRIPT).data(Qt.UserRole)
            or self.table.item(row, self.COLUMN_SCRIPT).text()
            ),
            "times": self.table.cellWidget(row, self.COLUMN_TIMES).value(),
            "wait_type": self.table.cellWidget(
                row, self.COLUMN_WAIT_TYPE
            ).currentText(),
            "wait_min": self.table.cellWidget(row, self.COLUMN_WAIT_MIN).value(),
            "wait_max": self.table.cellWidget(row, self.COLUMN_WAIT_MAX).value(),
            "failure_action": self.table.cellWidget(
                row, self.COLUMN_FAILURE_ACTION
            ).currentText(),
            "max_retry": self.table.cellWidget(row, self.COLUMN_RETRY).value(),
            "note": note_item.text() if note_item is not None else "",
        }

    def _write_row(self, row, data):
        self.table.item(row, self.COLUMN_ENABLED).setCheckState(
            Qt.Checked if data["enabled"] else Qt.Unchecked
        )
        script_item = self.table.item(row, self.COLUMN_SCRIPT)
        full_path = str(data["script"])
        script_item.setText(Path(full_path).name)
        script_item.setData(Qt.UserRole, full_path)
        script_item.setToolTip(full_path)
        self.table.cellWidget(row, self.COLUMN_TIMES).setValue(data["times"])
        self.table.cellWidget(row, self.COLUMN_WAIT_TYPE).setCurrentText(
            data["wait_type"]
        )
        self.table.cellWidget(row, self.COLUMN_WAIT_MIN).setValue(data["wait_min"])
        self.table.cellWidget(row, self.COLUMN_WAIT_MAX).setValue(data["wait_max"])
        self.table.cellWidget(row, self.COLUMN_FAILURE_ACTION).setCurrentText(
            data["failure_action"]
        )
        self.table.cellWidget(row, self.COLUMN_RETRY).setValue(data["max_retry"])
        self.table.item(row, self.COLUMN_NOTE).setText(data["note"])

    def _clear_rows(self):
        self.table.setRowCount(0)
        self._update_button_states()

    def _update_button_states(self):
        row = self._selected_row()
        has_selection = row >= 0
        self.remove_button.setEnabled(has_selection)
        self.duplicate_button.setEnabled(has_selection)
        self.move_up_button.setEnabled(has_selection and row > 0)
        self.move_down_button.setEnabled(
            has_selection and row < self.table.rowCount() - 1
        )
        self.clear_button.setEnabled(self.table.rowCount() > 0)

    def _on_round_wait_type_changed(self, wait_type):
        self.round_wait_max_spinbox.setEnabled(wait_type == "随机")

    def _get_enabled_tasks(self):
        """Return enabled tasks in their current table order."""
        tasks = []

        for row in range(self.table.rowCount()):
            task = self._read_row(row)

            if not task["enabled"]:
                continue

            tasks.append(task)

        return tasks

    def _get_config_data(self):
        """Collect the current task queue settings into a serializable dict."""
        tasks = []

        for row in range(self.table.rowCount()):
            tasks.append(self._read_row(row))

        return {
            "format": "KeymouseGo Pro Task Queue",
            "version": 1,
            "loop": {
                "infinite": self.infinite_loop_checkbox.isChecked(),
                "count": self.loop_count_spinbox.value(),
            },
            "round_wait": {
                "type": self.round_wait_type_combo.currentText(),
                "min": self.round_wait_min_spinbox.value(),
                "max": self.round_wait_max_spinbox.value(),
            },
            "tasks": tasks,
        }

    def _save_config(self):
        path, _ = QFileDialog.getSaveFileName(
            self,
            "保存任务配置",
            "task_queue.json",
            "JSON 文件 (*.json)",
        )

        if not path:
            return

        if not path.lower().endswith(".json"):
            path += ".json"

        try:
            config_data = self._get_config_data()

            Path(path).write_text(
                json.dumps(
                    config_data,
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )

            self.config_path_edit.setText(path)
            self.status_label.setText("状态：任务配置已保存")

            QMessageBox.information(
                self,
                "保存成功",
                "任务配置已成功保存。",
            )

        except (OSError, TypeError, ValueError) as exc:
            QMessageBox.critical(
                self,
                "保存失败",
                f"无法保存任务配置：\n\n{exc}",
            )

    def _load_config(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "载入任务配置",
            "",
            "JSON 文件 (*.json);;所有文件 (*.*)",
        )

        if not path:
            return

        try:
            config_data = json.loads(
                Path(path).read_text(encoding="utf-8")
            )

            if not isinstance(config_data, dict):
                raise ValueError("配置文件的顶层内容必须是 JSON 对象。")

            tasks = config_data.get("tasks")

            if not isinstance(tasks, list):
                raise ValueError("配置文件中缺少有效的 tasks 列表。")

            loop_data = config_data.get("loop", {})
            round_wait_data = config_data.get("round_wait", {})

            infinite_loop = bool(loop_data.get("infinite", True))
            loop_count = int(loop_data.get("count", 1))

            round_wait_type = str(
                round_wait_data.get("type", "固定")
            )
            round_wait_min = int(
                round_wait_data.get("min", 0)
            )
            round_wait_max = int(
                round_wait_data.get("max", round_wait_min)
            )

            if round_wait_type not in ("固定", "随机"):
                round_wait_type = "固定"

            self.table.setRowCount(0)

            self.infinite_loop_checkbox.setChecked(infinite_loop)
            self.loop_count_spinbox.setValue(max(1, loop_count))

            self.round_wait_type_combo.setCurrentText(
                round_wait_type
            )
            self.round_wait_min_spinbox.setValue(
                max(0, round_wait_min)
            )
            self.round_wait_max_spinbox.setValue(
                max(0, round_wait_max)
            )

            for task in tasks:
                if not isinstance(task, dict):
                    continue

                script_path = str(task.get("script", "")).strip()

                if not script_path:
                    continue

                wait_type = str(task.get("wait_type", "固定"))
                failure_action = str(
                    task.get("failure_action", "停止")
                )

                if wait_type not in ("固定", "随机"):
                    wait_type = "固定"

                if failure_action not in ("停止", "重试", "跳过"):
                    failure_action = "停止"

                self.add_task_row(
                    script_path=script_path,
                    times=max(1, int(task.get("times", 1))),
                    enabled=bool(task.get("enabled", True)),
                    wait_type=wait_type,
                    wait_min=max(0, int(task.get("wait_min", 0))),
                    wait_max=max(0, int(task.get("wait_max", 0))),
                    failure_action=failure_action,
                    max_retry=max(0, int(task.get("max_retry", 0))),
                    note=str(task.get("note", "")),
                )

            if self.table.rowCount() > 0:
                self.table.selectRow(0)

            self.config_path_edit.setText(path)
            self.status_label.setText("状态：任务配置已载入")
            self._update_button_states()

            QMessageBox.information(
                self,
                "载入成功",
                f"已载入 {self.table.rowCount()} 个任务。",
            )

        except (
            OSError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            QMessageBox.critical(
                self,
                "载入失败",
                f"无法载入任务配置：\n\n{exc}",
            )
            
    def _preview_queue(self):
        """
        First Queue Runner milestone:
        validate and preview the enabled queue without executing scripts.
        """
        tasks = self._get_enabled_tasks()

        if not tasks:
            QMessageBox.warning(
                self,
                "无法开始",
                "任务队列中没有已启用的 Script。",
            )
            self.status_label.setText("状态：没有已启用任务")
            return

        missing_scripts = []

        for task in tasks:
            script_path = Path(task["script"])

            if not script_path.is_file():
                missing_scripts.append(str(script_path))

        if missing_scripts:
            missing_text = "\n".join(missing_scripts[:10])

            if len(missing_scripts) > 10:
                missing_text += f"\n……另外还有 {len(missing_scripts) - 10} 个文件"

            QMessageBox.critical(
                self,
                "Script 文件不存在",
                "以下 Script 文件无法找到：\n\n"
                f"{missing_text}\n\n"
                "请重新添加 Script，或载入正确的任务配置。",
            )
            self.status_label.setText("状态：部分 Script 文件不存在")
            return

        total_runs = sum(task["times"] for task in tasks)

        preview_lines = []

        for index, task in enumerate(tasks, start=1):
            script_name = Path(task["script"]).name

            preview_lines.append(
                f"{index}. {script_name} × {task['times']}"
            )

        loop_description = (
            "无限循环"
            if self.infinite_loop_checkbox.isChecked()
            else f"{self.loop_count_spinbox.value()} 轮"
        )

        preview = "\n".join(preview_lines)

        QMessageBox.information(
            self,
            "任务队列预检查通过",
            f"已启用任务：{len(tasks)} 个\n"
            f"每轮总执行次数：{total_runs}\n"
            f"循环设置：{loop_description}\n\n"
            f"执行顺序：\n{preview}\n\n"
            "当前测试版本只检查任务，不会真正执行 Script。",
        )

        self.status_label.setText(
            f"状态：预检查通过，共 {len(tasks)} 个任务，"
            f"每轮 {total_runs} 次"
        )
        
    def _connect_runner_signals(self):
        """Connect QueueRunner signals to the task queue UI."""
        self.runner.started.connect(self._on_runner_started)
        self.runner.paused.connect(self._on_runner_paused)
        self.runner.resumed.connect(self._on_runner_resumed)
        self.runner.stopped.connect(self._on_runner_stopped)
        self.runner.finished.connect(self._on_runner_finished)

        self.runner.status_changed.connect(
            self._on_runner_status_changed
        )
        self.runner.progress_changed.connect(
            self._on_runner_progress_changed
        )
        self.runner.error_occurred.connect(
            self._on_runner_error
        )
        
    def _start_queue_simulation(self):
        """
        Validate the task queue and start the simulated runner.

        This version does not operate the mouse or keyboard.
        """
        tasks = self._get_enabled_tasks()

        if not tasks:
            QMessageBox.warning(
                self,
                "无法开始",
                "任务队列中没有已启用的 Script。",
            )
            self.status_label.setText("状态：没有已启用任务")
            return

        missing_scripts = []

        for task in tasks:
            script_path = Path(task["script"])

            if not script_path.is_file():
                missing_scripts.append(str(script_path))

        if missing_scripts:
            missing_text = "\n".join(missing_scripts[:10])

            if len(missing_scripts) > 10:
                missing_text += (
                    f"\n……另外还有 "
                    f"{len(missing_scripts) - 10} 个文件"
                )

            QMessageBox.critical(
                self,
                "Script 文件不存在",
                "以下 Script 文件无法找到：\n\n"
                f"{missing_text}",
            )
            self.status_label.setText(
                "状态：部分 Script 文件不存在"
            )
            return

        try:
            self.runner.configure(
                tasks=tasks,
                infinite_loop=self.infinite_loop_checkbox.isChecked(),
                total_rounds=self.loop_count_spinbox.value(),
            )

            self.runner.start()

        except (TypeError, ValueError, RuntimeError) as exc:
            QMessageBox.critical(
                self,
                "无法开始",
                f"任务队列配置错误：\n\n{exc}",
            )
            
    def _set_runner_button_state(self, state):
        """
        Set control button availability.

        Possible states:
        idle, running, paused
        """
        if state == "running":
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(True)
            self.resume_button.setEnabled(False)
            self.stop_button.setEnabled(True)

        elif state == "paused":
            self.start_button.setEnabled(False)
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(True)
            self.stop_button.setEnabled(True)

        else:
            self.start_button.setEnabled(True)
            self.pause_button.setEnabled(False)
            self.resume_button.setEnabled(False)
            self.stop_button.setEnabled(False)

    def _on_runner_started(self):
        self._set_runner_button_state("running")
        self.status_label.setText("状态：模拟任务开始")

    def _on_runner_paused(self):
        self._set_runner_button_state("paused")

        if self._last_progress_text:
            self.status_label.setText(
                f"状态：已暂停 ｜ {self._last_progress_text}"
            )
        else:
            self.status_label.setText("状态：已暂停")

    def _on_runner_resumed(self):
        self._set_runner_button_state("running")

        if self._last_progress_text:
            self.status_label.setText(
                f"状态：继续运行 ｜ {self._last_progress_text}"
            )
        else:
            self.status_label.setText("状态：继续运行")

    def _on_runner_stopped(self):
        self._last_progress_text = ""
        self._set_runner_button_state("idle")
        self.status_label.setText("状态：已停止")

    def _on_runner_finished(self):
        self._last_progress_text = ""
        self._set_runner_button_state("idle")
        self.status_label.setText("状态：全部任务执行完成")

    def _on_runner_status_changed(self, status):
        self.status_label.setText(f"状态：{status}")

    def _on_runner_progress_changed(
        self,
        current_round,
        total_rounds,
        current_task,
        total_tasks,
        script_path,
        current_run,
        total_runs,
    ):
        script_name = Path(script_path).name

        if total_rounds == 0:
            round_text = f"第 {current_round} 轮（无限循环）"
        else:
            round_text = f"第 {current_round}/{total_rounds} 轮"

        self._last_progress_text = (
            f"{round_text} ｜ "
            f"任务 {current_task}/{total_tasks} ｜ "
            f"{script_name} ｜ "
            f"次数 {current_run}/{total_runs}"
        )

        self.status_label.setText(
            f"状态：{self._last_progress_text}"
        )

    def _on_runner_error(self, message):
        self._set_runner_button_state("idle")

        QMessageBox.critical(
            self,
            "任务执行错误",
            message,
        )
        
    def closeEvent(self, event):
        if self.runner.is_running:
            self.runner.stop()

        event.accept()


if __name__ == "__main__":
    # Allows this UI file to be tested independently during development.
    import sys
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    dialog = TaskQueueDialog()
    dialog.show()
    sys.exit(app.exec())
