from __future__ import annotations

import json
from io import BytesIO
from dataclasses import replace
from datetime import datetime
from pathlib import Path
from typing import Any

import numpy as np
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
from PIL import Image
from PyQt5 import QtCore, QtGui, QtWidgets
from PyQt5.QtWidgets import QHeaderView

from parameter_identifier import __version__
from parameter_identifier.core.identification import (
    IdentificationData,
    IdentificationSettings,
    run_identification,
)
from parameter_identifier.core.material import (
    MaterialModelSpec,
    ParameterSpec,
    compose_material_code,
    default_material,
    material_prefix_text,
    material_suffix_text,
)
from parameter_identifier.core.opensees_backend import DEFAULT_OPENSEES_PATH
from parameter_identifier.core.preprocessing import (
    PreprocessResult,
    PreprocessSettings,
    load_experiment_file,
    preprocess_curve,
)
from parameter_identifier.optimizers.base import OptimizationHistory
from parameter_identifier.ui.ui_main_window import Ui_MainWindow


class Chart:
    def __init__(self, parent: QtWidgets.QWidget) -> None:
        self.figure = Figure(figsize=(4, 3), tight_layout=True)
        self.canvas = FigureCanvas(self.figure)
        layout = QtWidgets.QVBoxLayout(parent)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.canvas)

    def axis(self):
        self.figure.clear()
        return self.figure.add_subplot(111)

    def draw(self) -> None:
        self.canvas.draw_idle()


class AlgorithmSettingsDialog(QtWidgets.QDialog):
    def __init__(self, algorithm: str, values: dict[str, float | int], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle(f"{algorithm} Parameters")
        self.algorithm = algorithm.upper()
        self.specs = self._specs(self.algorithm)
        self.widgets: dict[str, QtWidgets.QDoubleSpinBox | QtWidgets.QSpinBox] = {}
        layout = QtWidgets.QVBoxLayout(self)
        form = QtWidgets.QFormLayout()
        layout.addLayout(form)

        for key, label, kind, minimum, maximum, decimals, default in self.specs:
            if kind == "int":
                widget = QtWidgets.QSpinBox()
                widget.setMinimum(int(minimum))
                widget.setMaximum(int(maximum))
                widget.setValue(int(values.get(key, default)))
            else:
                widget = QtWidgets.QDoubleSpinBox()
                widget.setDecimals(decimals)
                widget.setMinimum(float(minimum))
                widget.setMaximum(float(maximum))
                widget.setValue(float(values.get(key, default)))
            self.widgets[key] = widget
            form.addRow(label, widget)

        reset_button = QtWidgets.QPushButton("Use Defaults")
        reset_button.clicked.connect(self.reset_to_defaults)
        layout.addWidget(reset_button)

        button_layout = QtWidgets.QHBoxLayout()
        ok_button = QtWidgets.QPushButton("OK")
        cancel_button = QtWidgets.QPushButton("Cancel")
        ok_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        cancel_button.setSizePolicy(QtWidgets.QSizePolicy.Expanding, QtWidgets.QSizePolicy.Fixed)
        ok_button.clicked.connect(self.accept)
        cancel_button.clicked.connect(self.reject)
        button_layout.addWidget(ok_button)
        button_layout.addWidget(cancel_button)
        layout.addLayout(button_layout)

    @staticmethod
    def _specs(algorithm: str):
        common = [
            ("population_size", "Population size", "int", 1, 100000, 0, 30),
            ("generations", "Generations", "int", 0, 100000, 0, 50),
        ]
        if algorithm == "GA":
            common[0] = ("population_size", "Population size", "int", 2, 100000, 0, 30)
            return common + [
                ("crossover_rate", "Crossover rate", "float", 0.0, 1.0, 3, 0.85),
                ("mutation_rate", "Mutation rate", "float", 0.0, 1.0, 3, 0.12),
                ("mutation_scale", "Mutation scale", "float", 0.0, 10.0, 3, 0.08),
                ("tournament_size", "Tournament size", "int", 1, 1000, 0, 3),
                ("elite_count", "Elite count", "int", 0, 1000, 0, 1),
            ]
        return common + [
            ("inertia_start", "Initial inertia", "float", 0.0, 10.0, 3, 0.9),
            ("inertia_end", "Final inertia", "float", 0.0, 10.0, 3, 0.4),
            ("cognitive", "Cognitive factor", "float", 0.0, 10.0, 3, 2.0),
            ("social", "Social factor", "float", 0.0, 10.0, 3, 2.0),
            ("velocity_ratio", "Velocity ratio", "float", 0.0, 10.0, 3, 0.1),
        ]

    def values(self) -> dict[str, float | int]:
        result: dict[str, float | int] = {}
        for key, widget in self.widgets.items():
            result[key] = widget.value()
        return result

    def reset_to_defaults(self) -> None:
        for key, _label, _kind, _minimum, _maximum, _decimals, default in self.specs:
            self.widgets[key].setValue(default)


class CodeEditor(QtWidgets.QPlainTextEdit):
    def keyPressEvent(self, event: QtGui.QKeyEvent) -> None:
        if event.key() == QtCore.Qt.Key_Tab:
            self.insertPlainText("    ")
            return
        super().keyPressEvent(event)


class IdentificationWorker(QtCore.QThread):
    progress_changed = QtCore.pyqtSignal(int, int, float)
    finished_ok = QtCore.pyqtSignal(object, object)
    failed = QtCore.pyqtSignal(str)

    def __init__(
        self,
        data: IdentificationData,
        material: MaterialModelSpec,
        settings: IdentificationSettings,
        opensees_path: str,
    ) -> None:
        super().__init__()
        self.data = data
        self.material = material
        self.settings = settings
        self.opensees_path = opensees_path
        self._stop_requested = False

    def request_stop(self) -> None:
        self._stop_requested = True

    def run(self) -> None:
        try:
            history, parameter_specs = run_identification(
                self.data,
                [self.material],
                self.settings,
                self.opensees_path,
                progress=lambda generation, total, best: self.progress_changed.emit(generation, total, best),
                should_stop=lambda: self._stop_requested,
            )
            self.finished_ok.emit(history, parameter_specs)
        except Exception as exc:  # noqa: BLE001
            self.failed.emit(str(exc))


class MainWindow(QtWidgets.QMainWindow, Ui_MainWindow):
    ORGANIZATION_NAME = "HPI"
    APPLICATION_NAME = "Hysteresis Parameter Identification"

    def __init__(self) -> None:
        super().__init__()
        self.setupUi(self)
        QtCore.QCoreApplication.setOrganizationName(self.ORGANIZATION_NAME)
        QtCore.QCoreApplication.setApplicationName(self.APPLICATION_NAME)
        self.setWindowTitle(f"Hysteresis Parameter Identification (HPI) v{__version__}")
        self.setStyleSheet(
            """
            QWidget { font-family: "Segoe UI", "Microsoft YaHei UI", Arial, sans-serif; font-size: 14pt; }
            QPushButton { min-height: 34px; padding: 3px 12px; }
            QPushButton#btnStart, QPushButton#btnStop,
            QPushButton#btnAddParameter, QPushButton#btnRemoveParameter,
            QPushButton#btnDefaultMaterialParameters,
            QPushButton#btnSaveData { min-height: 40px; padding: 6px 14px; }
            QPushButton#btnStart, QPushButton#btnStop { min-width: 120px; }
            QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit { min-height: 34px; }
            QProgressBar { min-height: 40px; }
            QPlainTextEdit { font-family: Consolas, "Cascadia Mono", monospace; font-size: 13pt; }
            QLabel#lblMaterialPrefix, QLabel#lblMaterialSuffix {
                font-family: Consolas, "Cascadia Mono", monospace;
                font-size: 13pt;
                background: #f5f5f5;
                border: 1px solid #c8c8c8;
                padding: 6px;
            }
            """
        )

        self._configure_menu()
        self.material = default_material()
        self.preprocessed: PreprocessResult | None = None
        self.history: OptimizationHistory | None = None
        self.parameter_specs: list[ParameterSpec] = []
        self.worker: IdentificationWorker | None = None
        self.experiment_folder: Path | None = None
        self.algorithm_parameters: dict[str, dict[str, float | int]] = {
            "PSO": {
                "population_size": 30,
                "generations": 50,
                "inertia_start": 0.9,
                "inertia_end": 0.4,
                "cognitive": 2.0,
                "social": 2.0,
                "velocity_ratio": 0.1,
            },
            "GA": {
                "population_size": 30,
                "generations": 50,
                "crossover_rate": 0.85,
                "mutation_rate": 0.12,
                "mutation_scale": 0.08,
                "tournament_size": 3,
                "elite_count": 1,
            },
        }
        self._load_default_algorithm_parameters()

        self.txtMaterialCode = self._replace_material_editor(self.txtMaterialCode)
        self.experiment_chart = Chart(self.experimentChartFrame)
        self.param_chart = Chart(self.paramChartFrame)
        self.fitness_chart = Chart(self.fitnessChartFrame)
        self.curve_chart = Chart(self.curveChartFrame)

        self._configure_initial_state()
        self._configure_tables()
        self._connect_signals()
        self._load_material_to_editor()
        self._append_log("Ready.")

    def _configure_menu(self) -> None:
        menu = self.menuBar().addMenu("Menu")
        guide_menu = menu.addMenu("User Guide")
        action_user_guide_cn = guide_menu.addAction("Chinese")
        action_user_guide_en = guide_menu.addAction("English")
        defaults_menu = menu.addMenu("Default Algorithm Parameters")
        action_default_pso = defaults_menu.addAction("PSO")
        action_default_ga = defaults_menu.addAction("GA")
        action_about = menu.addAction("About")
        menu.addSeparator()
        action_exit = menu.addAction("Exit")
        action_user_guide_cn.triggered.connect(lambda: self._open_user_guide("user_guide.md"))
        action_user_guide_en.triggered.connect(lambda: self._open_user_guide("user_guide_en.md"))
        action_default_pso.triggered.connect(lambda: self._edit_default_algorithm_parameters("PSO"))
        action_default_ga.triggered.connect(lambda: self._edit_default_algorithm_parameters("GA"))
        action_about.triggered.connect(self._show_about)
        action_exit.triggered.connect(self.close)

    @staticmethod
    def _resource_path(*parts: str) -> Path:
        current = Path(__file__).resolve()
        for parent in current.parents:
            candidate = parent.joinpath(*parts)
            if candidate.exists():
                return candidate
        return current.parents[3].joinpath(*parts)

    def _settings(self) -> QtCore.QSettings:
        return QtCore.QSettings(self.ORGANIZATION_NAME, self.APPLICATION_NAME)

    def _load_default_algorithm_parameters(self) -> None:
        settings = self._settings()
        for algorithm in ("PSO", "GA"):
            raw = settings.value(f"algorithm_defaults/{algorithm}", "", type=str)
            if not raw:
                continue
            try:
                values = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(values, dict):
                self.algorithm_parameters[algorithm].update(values)

    def _save_default_algorithm_parameters(self, algorithm: str) -> None:
        self._settings().setValue(
            f"algorithm_defaults/{algorithm}",
            json.dumps(self.algorithm_parameters[algorithm], ensure_ascii=False),
        )

    def _edit_default_algorithm_parameters(self, algorithm: str) -> None:
        dialog = AlgorithmSettingsDialog(algorithm, self.algorithm_parameters[algorithm], self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.algorithm_parameters[algorithm] = dialog.values()
            self._save_default_algorithm_parameters(algorithm)
            QtWidgets.QMessageBox.information(
                self,
                "Saved",
                f"{algorithm} default parameters have been saved.",
            )

    def _replace_material_editor(self, old_editor: QtWidgets.QPlainTextEdit) -> CodeEditor:
        parent = old_editor.parentWidget()
        layout = parent.layout()
        index = layout.indexOf(old_editor)
        editor = CodeEditor(parent)
        editor.setObjectName("txtMaterialCode")
        editor.setFont(old_editor.font())
        editor.setLineWrapMode(QtWidgets.QPlainTextEdit.NoWrap)
        layout.insertWidget(index, editor)
        old_editor.deleteLater()
        return editor

    def _configure_initial_state(self) -> None:
        self.comboSkeletonMethod.setCurrentIndex(1)
        self.txtOpenSeesPath.setText(DEFAULT_OPENSEES_PATH)
        self.txtOpenSeesPath.setEnabled(False)
        self.btnBrowseOpenSees.setEnabled(False)
        self.chkUseSeed.setChecked(True)
        self.spinSeed.setEnabled(True)
        self.progressRun.setValue(0)
        self.lblMaterialPrefix.setMinimumHeight(110)
        self.lblMaterialSuffix.setMinimumHeight(44)

    def _configure_tables(self) -> None:
        for table in (self.tblParameters, self.tblBestParameters):
            table.horizontalHeader().setStretchLastSection(True)
            table.verticalHeader().setVisible(False)
        self.tblParameters.setColumnCount(3)
        self.tblParameters.setHorizontalHeaderLabels(["Name", "Lower", "Upper"])
        self.tblParameters.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.tblBestParameters.setColumnCount(3)
        self.tblBestParameters.setHorizontalHeaderLabels(["Parameter", "Generation Best", "Global Best"])
        self.tblBestParameters.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)

    def _connect_signals(self) -> None:
        self.btnBrowseExperiment.clicked.connect(self._browse_experiment)
        self.btnBrowseOpenSees.clicked.connect(self._browse_opensees)
        self.btnPreprocess.clicked.connect(self._preprocess_from_ui)
        self.chkShowSkeleton.stateChanged.connect(self._plot_experiment_preview)
        self.chkCustomOpenSees.stateChanged.connect(self._toggle_custom_opensees)
        self.chkUseSeed.stateChanged.connect(lambda: self.spinSeed.setEnabled(self.chkUseSeed.isChecked()))
        self.btnAlgorithmSettings.clicked.connect(self._open_algorithm_settings)
        self.btnAddParameter.clicked.connect(self._add_parameter)
        self.btnRemoveParameter.clicked.connect(self._remove_parameter)
        self.tblParameters.itemChanged.connect(lambda _item: self._on_parameter_table_changed())
        self.btnDefaultMaterialParameters.clicked.connect(self._reset_material_parameters_to_defaults)
        self.btnStart.clicked.connect(self._start_identification)
        self.btnStop.clicked.connect(self._stop_identification)
        self.btnSaveData.clicked.connect(self._save_data)
        self.sliderGeneration.valueChanged.connect(self._update_result_view)
        self.comboPlotParameter.currentIndexChanged.connect(self._update_result_view)

    def _browse_experiment(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select experimental data",
            str(Path.cwd()),
            "Text files (*.txt *.dat *.csv);;All files (*.*)",
        )
        if path:
            self.txtExperimentPath.setText(path)
            self._preprocess_from_ui()

    def _browse_opensees(self) -> None:
        path, _ = QtWidgets.QFileDialog.getOpenFileName(
            self,
            "Select OpenSees Python module",
            str(Path(DEFAULT_OPENSEES_PATH).parent),
            "OpenSees Python module (opensees.pyd);;All files (*.*)",
        )
        if path:
            self.txtOpenSeesPath.setText(path)

    def _toggle_custom_opensees(self) -> None:
        custom = self.chkCustomOpenSees.isChecked()
        self.txtOpenSeesPath.setEnabled(custom)
        self.btnBrowseOpenSees.setEnabled(custom)
        if not custom:
            self.txtOpenSeesPath.setText(DEFAULT_OPENSEES_PATH)

    def _open_algorithm_settings(self) -> None:
        algorithm = self.comboAlgorithm.currentText().upper()
        dialog = AlgorithmSettingsDialog(algorithm, self.algorithm_parameters[algorithm], self)
        if dialog.exec_() == QtWidgets.QDialog.Accepted:
            self.algorithm_parameters[algorithm] = dialog.values()

    def _preprocess_from_ui(self) -> PreprocessResult | None:
        try:
            experiment_path = self.txtExperimentPath.text().strip()
            if not experiment_path:
                raise ValueError("Select an experimental data file first.")
            settings = self._preprocess_settings()
            displacement, force = load_experiment_file(experiment_path, settings.force_scale)
            self.preprocessed = preprocess_curve(displacement, force, settings)
            self.experiment_folder = Path(experiment_path).resolve().parent
            self._append_log(
                f"Curve loaded: {len(self.preprocessed.displacement)} points, "
                f"{len(self.preprocessed.skeleton_indices)} skeleton points."
            )
            self._plot_experiment_preview()
            return self.preprocessed
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))
            return None

    def _preprocess_settings(self) -> PreprocessSettings:
        return PreprocessSettings(
            skeleton_method=self.comboSkeletonMethod.currentIndex() + 1,
            force_scale=self.spinForceScale.value(),
        )

    def _plot_experiment_preview(self) -> None:
        ax = self.experiment_chart.axis()
        if self.preprocessed is not None:
            ax.plot(self.preprocessed.displacement, self.preprocessed.force, label="Experimental")
            if self.chkShowSkeleton.isChecked() and len(self.preprocessed.skeleton_indices) > 0:
                idx = self.preprocessed.skeleton_indices
                ax.scatter(
                    self.preprocessed.displacement[idx],
                    self.preprocessed.force[idx],
                    s=38,
                    color="#d62728",
                    label="Skeleton",
                    zorder=4,
                )
            ax.legend()
        ax.set_title("Experimental Hysteresis Curve")
        ax.set_xlabel("Displacement")
        ax.set_ylabel("Force")
        self.experiment_chart.draw()

    def _load_material_to_editor(self) -> None:
        self.tblParameters.blockSignals(True)
        self.tblParameters.setRowCount(len(self.material.parameters))
        for row, spec in enumerate(self.material.parameters):
            self.tblParameters.setItem(row, 0, QtWidgets.QTableWidgetItem(spec.name))
            self.tblParameters.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{spec.lower:g}"))
            self.tblParameters.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{spec.upper:g}"))
        self.tblParameters.blockSignals(False)
        self.txtMaterialCode.setPlainText(self.material.code)
        self._refresh_fixed_material_text()

    def _reset_material_parameters_to_defaults(self) -> None:
        default = default_material()
        self.material = default
        self._load_material_to_editor()

    def _save_material_from_editor(self) -> MaterialModelSpec:
        parameters: list[ParameterSpec] = []
        for row in range(self.tblParameters.rowCount()):
            name_item = self.tblParameters.item(row, 0)
            lower_item = self.tblParameters.item(row, 1)
            upper_item = self.tblParameters.item(row, 2)
            if name_item is None or lower_item is None or upper_item is None:
                continue
            name = name_item.text().strip()
            if not name:
                continue
            parameters.append(
                ParameterSpec(
                    name=name,
                    lower=float(lower_item.text()),
                    upper=float(upper_item.text()),
                )
            )
        self.material = replace(
            self.material,
            code=self.txtMaterialCode.toPlainText(),
            parameters=tuple(parameters),
        )
        return self.material

    def _refresh_fixed_material_text(self) -> None:
        try:
            parameters = self._parameter_specs_from_table()
            self.lblMaterialPrefix.setText(material_prefix_text(parameters))
            self.lblMaterialSuffix.setText(material_suffix_text())
        except ValueError as exc:
            self.lblMaterialPrefix.setText(f"# {exc}")
            self.lblMaterialSuffix.setText(material_suffix_text())

    def _parameter_specs_from_table(self) -> tuple[ParameterSpec, ...]:
        specs: list[ParameterSpec] = []
        for row in range(self.tblParameters.rowCount()):
            name_item = self.tblParameters.item(row, 0)
            lower_item = self.tblParameters.item(row, 1)
            upper_item = self.tblParameters.item(row, 2)
            if name_item is None or lower_item is None or upper_item is None:
                continue
            name = name_item.text().strip()
            if name:
                specs.append(ParameterSpec(name, float(lower_item.text()), float(upper_item.text())))
        return tuple(specs)

    def _on_parameter_table_changed(self) -> None:
        self._refresh_fixed_material_text()

    def _add_parameter(self) -> None:
        row = self.tblParameters.rowCount()
        self.tblParameters.insertRow(row)
        self.tblParameters.setItem(row, 0, QtWidgets.QTableWidgetItem(f"p{row + 1}"))
        self.tblParameters.setItem(row, 1, QtWidgets.QTableWidgetItem("0"))
        self.tblParameters.setItem(row, 2, QtWidgets.QTableWidgetItem("1"))

    def _remove_parameter(self) -> None:
        row = self.tblParameters.currentRow()
        if row >= 0:
            self.tblParameters.removeRow(row)
            self._refresh_fixed_material_text()

    def _start_identification(self) -> None:
        try:
            material = self._save_material_from_editor()
            data = self.preprocessed or self._preprocess_from_ui()
            if data is None:
                return
            opensees_path = self.txtOpenSeesPath.text().strip() if self.chkCustomOpenSees.isChecked() else DEFAULT_OPENSEES_PATH
            algorithm = self.comboAlgorithm.currentText().upper()
            algorithm_parameters = self.algorithm_parameters[algorithm].copy()
            generations = int(algorithm_parameters.get("generations", 0))
            seed = self.spinSeed.value() if self.chkUseSeed.isChecked() else None
            settings = IdentificationSettings(
                algorithm=algorithm,
                population_size=int(algorithm_parameters.get("population_size", 30)),
                generations=generations,
                skeleton_weight=self.spinSkeletonWeight.value(),
                random_seed=seed,
                algorithm_parameters=algorithm_parameters,
            )
            self.txtLog.clear()
            self._write_run_header(material, settings, opensees_path)
            self.progressRun.setRange(0, max(1, generations))
            self.progressRun.setValue(0)
            id_data = IdentificationData(data.displacement, data.force, data.skeleton_indices)
            self.worker = IdentificationWorker(id_data, material, settings, opensees_path)
            self.worker.progress_changed.connect(self._on_progress)
            self.worker.finished_ok.connect(self._on_finished)
            self.worker.failed.connect(self._on_failed)
            self.worker.finished.connect(self._on_worker_finished)
            self.btnStart.setEnabled(False)
            self.btnStop.setEnabled(True)
            self._append_log("Run started.")
            self.worker.start()
        except Exception as exc:  # noqa: BLE001
            self._show_error(str(exc))

    def _write_run_header(self, material: MaterialModelSpec, settings: IdentificationSettings, opensees_path: str) -> None:
        self._append_log(f"Start time: {datetime.now().isoformat(timespec='seconds')}")
        self._append_log(f"Algorithm: {settings.algorithm}")
        self._append_log(f"OpenSees module: {opensees_path}")
        self._append_log("Parameter bounds:")
        for spec in material.parameters:
            self._append_log(f"  {spec.name}: [{spec.lower}, {spec.upper}]")

    def _stop_identification(self) -> None:
        if self.worker:
            self.worker.request_stop()
            self._append_log("Stop requested; the run will stop after the current generation.")

    def _on_progress(self, generation: int, total: int, best: float) -> None:
        self.progressRun.setMaximum(max(1, total))
        self.progressRun.setValue(min(generation, max(1, total)))
        self.statusbar.showMessage(f"Generation {generation}/{total}, global best RMSE = {best:.6g}")
        self._append_log(f"Generation {generation}/{total}, global best RMSE = {best:.6g}")

    def _on_finished(self, history: OptimizationHistory, parameter_specs: list[ParameterSpec]) -> None:
        self.history = history
        self.parameter_specs = parameter_specs
        self.comboPlotParameter.blockSignals(True)
        self.comboPlotParameter.clear()
        self.comboPlotParameter.addItems(history.parameter_names)
        self.comboPlotParameter.blockSignals(False)
        self.sliderGeneration.setMaximum(max(0, len(history.entries) - 1))
        self.sliderGeneration.setValue(max(0, len(history.entries) - 1))
        self.progressRun.setValue(self.progressRun.maximum())
        self.tabs.setCurrentWidget(self.tabResults)
        self._append_log("Run finished.")
        self._update_result_view()
        self._warn_boundary_parameters()

    def _on_failed(self, message: str) -> None:
        self._show_error(message)
        self._append_log(f"Run failed: {message}")

    def _on_worker_finished(self) -> None:
        self.btnStart.setEnabled(True)
        self.btnStop.setEnabled(False)
        self.worker = None

    def _update_result_view(self) -> None:
        if not self.history or not self.preprocessed or not self.history.entries:
            return
        generation_index = min(self.sliderGeneration.value(), len(self.history.entries) - 1)
        entry = self.history.entries[generation_index]
        self.labelGeneration.setText(f"Generation: {entry.generation}")
        parameter_index = max(0, self.comboPlotParameter.currentIndex())
        self._plot_parameter(parameter_index, generation_index)
        self._plot_fitness(generation_index)
        self._plot_curve(generation_index)
        self._populate_best_table(generation_index)

    def _plot_parameter(self, parameter_index: int, generation_index: int) -> None:
        assert self.history is not None
        ax = self.param_chart.axis()
        generations = self.history.generations
        generation_best, global_best = self.history.parameter_series(parameter_index)
        ax.plot(generations, generation_best, label="Generation best")
        ax.plot(generations, global_best, label="Global best")
        ax.scatter([generations[generation_index]], [generation_best[generation_index]], s=40)
        ax.scatter([generations[generation_index]], [global_best[generation_index]], s=40)
        ax.set_title(f"Parameter: {self.history.parameter_names[parameter_index]}")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Value")
        ax.legend()
        self.param_chart.draw()

    def _plot_fitness(self, generation_index: int) -> None:
        assert self.history is not None
        ax = self.fitness_chart.axis()
        generations = self.history.generations
        generation_best = self.history.generation_best_fitness
        global_best = self.history.global_best_fitness
        ax.plot(generations, generation_best, label="Generation best")
        ax.plot(generations, global_best, label="Global best")
        ax.scatter([generations[generation_index]], [generation_best[generation_index]], s=40)
        ax.scatter([generations[generation_index]], [global_best[generation_index]], s=40)
        ax.set_title("RMSE History")
        ax.set_xlabel("Generation")
        ax.set_ylabel("RMSE")
        ax.legend()
        self.fitness_chart.draw()

    def _plot_curve(self, generation_index: int) -> None:
        assert self.history is not None and self.preprocessed is not None
        entry = self.history.entries[generation_index]
        ax = self.curve_chart.axis()
        ax.plot(self.preprocessed.displacement, self.preprocessed.force, label="Experimental")
        ax.plot(self.preprocessed.displacement, entry.generation_best_force, label="Simulated")
        ax.set_title("Hysteresis Comparison")
        ax.set_xlabel("Displacement")
        ax.set_ylabel("Force")
        ax.legend()
        self.curve_chart.draw()

    def _populate_best_table(self, generation_index: int) -> None:
        assert self.history is not None
        entry = self.history.entries[generation_index]
        self.tblBestParameters.setRowCount(len(self.history.parameter_names))
        for row, name in enumerate(self.history.parameter_names):
            self.tblBestParameters.setItem(row, 0, QtWidgets.QTableWidgetItem(name))
            self.tblBestParameters.setItem(row, 1, QtWidgets.QTableWidgetItem(f"{entry.generation_best_params[row]:.8g}"))
            self.tblBestParameters.setItem(row, 2, QtWidgets.QTableWidgetItem(f"{entry.global_best_params[row]:.8g}"))

    def _save_data(self) -> None:
        if not self.history or not self.preprocessed:
            self._show_error("No results to save.")
            return
        default_folder = self.experiment_folder or Path.cwd()
        folder = QtWidgets.QFileDialog.getExistingDirectory(self, "Select export folder", str(default_folder))
        if not folder:
            return
        export_dir = Path(folder) / f"identification_export_{datetime.now().strftime('%Y%m%d')}"
        if export_dir.exists():
            suffix = 2
            while (Path(folder) / f"{export_dir.name}_{suffix}").exists():
                suffix += 1
            export_dir = Path(folder) / f"{export_dir.name}_{suffix}"
        export_dir.mkdir(parents=True, exist_ok=True)
        self._save_json(export_dir / "parameter_definitions.json", self._parameter_definition_payload())
        self._save_json(export_dir / "final_results.json", self._final_result_payload())
        (export_dir / "run.log").write_text(self.txtLog.toPlainText(), encoding="utf-8")
        self._export_figures(export_dir)
        self._append_log(f"Saved export to {export_dir}")
        QtWidgets.QMessageBox.information(self, "Saved", f"Results saved to:\n{export_dir}")

    @staticmethod
    def _save_json(path: Path, data: dict[str, Any]) -> None:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

    def _parameter_definition_payload(self) -> dict[str, Any]:
        material = self._save_material_from_editor()
        algorithm = self.comboAlgorithm.currentText().upper()
        return {
            "created_at": datetime.now().isoformat(timespec="seconds"),
            "experiment_path": self.txtExperimentPath.text().strip(),
            "preprocessing": {
                "skeleton_method": self.comboSkeletonMethod.currentIndex() + 1,
                "force_scale": self.spinForceScale.value(),
                "mark_skeleton_points": self.chkShowSkeleton.isChecked(),
            },
            "opensees": {
                "use_custom_module": self.chkCustomOpenSees.isChecked(),
                "module_path": self.txtOpenSeesPath.text().strip() if self.chkCustomOpenSees.isChecked() else DEFAULT_OPENSEES_PATH,
            },
            "optimization": {
                "algorithm": algorithm,
                "skeleton_weight": self.spinSkeletonWeight.value(),
                "use_fixed_seed": self.chkUseSeed.isChecked(),
                "seed": self.spinSeed.value() if self.chkUseSeed.isChecked() else None,
                "algorithm_parameters": self.algorithm_parameters[algorithm],
            },
            "material": {
                "parameters": [
                    {"name": spec.name, "lower": spec.lower, "upper": spec.upper}
                    for spec in material.parameters
                ],
                "fixed_prefix": material_prefix_text(material.parameters),
                "editable_body": material.code,
                "fixed_suffix": material_suffix_text(),
                "composed_code": compose_material_code(material.parameters, material.code),
            },
        }

    def _final_result_payload(self) -> dict[str, Any]:
        assert self.history is not None
        final = self.history.entries[-1]
        return {
            "final_generation": int(final.generation),
            "global_best_fitness": float(final.global_best_fitness),
            "parameters": {
                name: float(value)
                for name, value in zip(self.history.parameter_names, final.global_best_params)
            },
        }

    def _export_figures(self, export_dir: Path) -> None:
        assert self.history is not None and self.preprocessed is not None
        self._make_hysteresis_figure(-1).savefig(export_dir / "hysteresis_comparison.png", dpi=180)
        self._make_rmse_figure().savefig(export_dir / "rmse_history.png", dpi=180)
        self._make_experiment_figure().savefig(export_dir / "experimental_hysteresis.png", dpi=180)
        self._save_hysteresis_gif(export_dir / "hysteresis_iterations.gif")
        for index, name in enumerate(self.history.parameter_names):
            safe_name = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in name)
            self._make_parameter_figure(index).savefig(export_dir / f"parameter_{safe_name}.png", dpi=180)

    def _save_hysteresis_gif(self, path: Path) -> None:
        assert self.history is not None
        frames: list[Image.Image] = []
        max_frames = 120
        total = len(self.history.entries)
        if total <= max_frames:
            indices = list(range(total))
        else:
            indices = sorted(set(np.linspace(0, total - 1, max_frames, dtype=int).tolist()))
        for index in indices:
            fig = self._make_hysteresis_figure(index, use_global=False)
            buffer = BytesIO()
            fig.savefig(buffer, format="png", dpi=120)
            buffer.seek(0)
            frames.append(Image.open(buffer).convert("P", palette=Image.ADAPTIVE))
        if frames:
            frames[0].save(
                path,
                save_all=True,
                append_images=frames[1:],
                duration=250,
                loop=0,
            )

    def _make_experiment_figure(self) -> Figure:
        fig = Figure(figsize=(6, 4), tight_layout=True)
        ax = fig.add_subplot(111)
        assert self.preprocessed is not None
        ax.plot(self.preprocessed.displacement, self.preprocessed.force, label="Experimental")
        if self.chkShowSkeleton.isChecked() and len(self.preprocessed.skeleton_indices) > 0:
            idx = self.preprocessed.skeleton_indices
            ax.scatter(
                self.preprocessed.displacement[idx],
                self.preprocessed.force[idx],
                label="Skeleton",
                s=36,
                color="#d62728",
                zorder=4,
            )
        ax.set_title("Experimental Hysteresis Curve")
        ax.set_xlabel("Displacement")
        ax.set_ylabel("Force")
        ax.legend()
        return fig

    def _make_hysteresis_figure(self, entry_index: int, use_global: bool = True) -> Figure:
        fig = Figure(figsize=(6, 4), tight_layout=True)
        ax = fig.add_subplot(111)
        assert self.history is not None and self.preprocessed is not None
        entry = self.history.entries[entry_index]
        ax.plot(self.preprocessed.displacement, self.preprocessed.force, label="Experimental")
        simulated = entry.global_best_force if use_global else entry.generation_best_force
        ax.plot(self.preprocessed.displacement, simulated, label="Simulated")
        ax.text(
            0.02,
            0.96,
            f"Generation {entry.generation}",
            transform=ax.transAxes,
            va="top",
            ha="left",
        )
        ax.set_title("Hysteresis Comparison")
        ax.set_xlabel("Displacement")
        ax.set_ylabel("Force")
        ax.legend()
        return fig

    def _make_rmse_figure(self) -> Figure:
        fig = Figure(figsize=(6, 4), tight_layout=True)
        ax = fig.add_subplot(111)
        assert self.history is not None
        ax.plot(self.history.generations, self.history.generation_best_fitness, label="Generation best")
        ax.plot(self.history.generations, self.history.global_best_fitness, label="Global best")
        ax.set_title("RMSE History")
        ax.set_xlabel("Generation")
        ax.set_ylabel("RMSE")
        ax.legend()
        return fig

    def _make_parameter_figure(self, parameter_index: int) -> Figure:
        fig = Figure(figsize=(6, 4), tight_layout=True)
        ax = fig.add_subplot(111)
        assert self.history is not None
        generation_best, global_best = self.history.parameter_series(parameter_index)
        ax.plot(self.history.generations, generation_best, label="Generation best")
        ax.plot(self.history.generations, global_best, label="Global best")
        ax.set_title(f"Parameter: {self.history.parameter_names[parameter_index]}")
        ax.set_xlabel("Generation")
        ax.set_ylabel("Value")
        ax.legend()
        return fig

    def _append_log(self, message: str) -> None:
        self.txtLog.appendPlainText(message)

    def _show_error(self, message: str) -> None:
        QtWidgets.QMessageBox.critical(self, "Error", message)

    def _warn_boundary_parameters(self) -> None:
        if not self.history or not self.parameter_specs:
            return
        final = self.history.entries[-1]
        warnings: list[str] = []
        for spec, value in zip(self.parameter_specs, final.global_best_params):
            if np.isclose(value, spec.lower):
                warnings.append(f"{spec.name} is close to the lower bound ({spec.lower:g}).")
            elif np.isclose(value, spec.upper):
                warnings.append(f"{spec.name} is close to the upper bound ({spec.upper:g}).")
        if warnings:
            self._show_boundary_warning(
                "The following parameters reached their bounds. Adjust the bounds and identify again.\n"
                + "\n".join(warnings)
            )

    def _show_boundary_warning(self, message: str) -> None:
        box = QtWidgets.QMessageBox(self)
        box.setIcon(QtWidgets.QMessageBox.Warning)
        box.setWindowTitle("Boundary Warning")
        box.setText(message)
        box.setStandardButtons(QtWidgets.QMessageBox.Ok)
        ok_button = box.button(QtWidgets.QMessageBox.Ok)
        if ok_button is not None:
            ok_button.setMinimumWidth(180)
        button_box = box.findChild(QtWidgets.QDialogButtonBox)
        if button_box is not None:
            button_box.setCenterButtons(True)
        box.exec_()

    def _open_user_guide(self, filename: str) -> None:
        guide_path = self._resource_path("docs", filename)
        if not guide_path.exists():
            self._show_error(f"User guide not found:\n{guide_path}")
            return
        QtGui.QDesktopServices.openUrl(QtCore.QUrl.fromLocalFile(str(guide_path)))

    def _show_about(self) -> None:
        dialog = QtWidgets.QDialog(self)
        dialog.setWindowTitle("About")
        dialog.setFixedSize(820, 460)
        layout = QtWidgets.QVBoxLayout(dialog)
        frame = QtWidgets.QFrame(dialog)
        frame.setFrameShape(QtWidgets.QFrame.Box)
        frame.setFrameShadow(QtWidgets.QFrame.Sunken)
        frame_layout = QtWidgets.QHBoxLayout(frame)
        frame_layout.setContentsMargins(28, 28, 28, 28)
        frame_layout.setSpacing(32)
        icon_label = QtWidgets.QLabel(frame)
        icon_label.setFixedSize(180, 180)
        icon_path = self._resource_path("assets", "app_icon.png")
        if icon_path.exists():
            pixmap = QtGui.QPixmap(str(icon_path))
            icon_label.setPixmap(pixmap.scaled(icon_label.size(), QtCore.Qt.KeepAspectRatio, QtCore.Qt.SmoothTransformation))
        text_label = QtWidgets.QLabel(frame)
        text_label.setText(
            "<h2>Hysteresis Parameter Identification (HPI)</h2>"
            "<p>Desktop tool for identifying uniaxial material parameters from hysteresis curves.</p>"
            f"<p>Version: {__version__}<br/>Author: Wenchen Lie<br/>Email: 438171766@qq.com</p>"
            "<p>Copyright (c) 2026 Wenchen Lie. All rights reserved.</p>"
        )
        text_label.setWordWrap(True)
        frame_layout.addWidget(icon_label)
        frame_layout.addWidget(text_label, 1)
        layout.addWidget(frame, 1)
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.addStretch(1)
        ok_button = QtWidgets.QPushButton("OK", dialog)
        ok_button.setMinimumWidth(180)
        ok_button.clicked.connect(dialog.accept)
        button_layout.addWidget(ok_button)
        button_layout.addStretch(1)
        layout.addLayout(button_layout)
        dialog.exec_()
