import sys
from datetime import datetime, timezone

from PyQt5 import QtCore, QtWidgets
import psutil

from eye_tracker import EyeTrackerWorker
from api_client import ApiClient


class MainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Wellness at Work - Eye Tracker (Prototype)")
        self.resize(800, 500)

        # TODO: With more time, implement real-time sync via WebSockets
        # instead of periodic sync. Current approach is simpler for MVP but less responsive.

        # TODO: With more time, add exponential backoff retry logic for failed sync attempts
        # Current implementation fails immediately on network issues.

        # State
        self.blink_count = 0
        self.tracking = False

        # Eye tracker thread/worker
        self.tracker_thread = None
        self.tracker_worker = None

        # Backend API client
        self.api = ApiClient()

        # Per-session metrics
        self._session_start: datetime | None = None
        self._cpu_samples: list[float] = []
        self._mem_samples: list[float] = []

        # UI
        self._setup_ui()

        # Timers
        self.perf_timer = QtCore.QTimer(self)
        self.perf_timer.timeout.connect(self.update_performance_stats)
        self.perf_timer.start(1000)  # every 1s

        # Blink rate monitoring timer
        self.blink_check_timer = QtCore.QTimer(self)
        self.blink_check_timer.timeout.connect(self.check_blink_rate)
        self.blink_check_timer.start(60000)  # every 1 minute

    def _setup_ui(self):
        central = QtWidgets.QWidget()
        layout = QtWidgets.QVBoxLayout(central)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(16)

        # Auth row
        auth_row = QtWidgets.QHBoxLayout()
        self.email_input = QtWidgets.QLineEdit()
        self.email_input.setPlaceholderText("Email")
        self.password_input = QtWidgets.QLineEdit()
        self.password_input.setPlaceholderText("Password")
        self.password_input.setEchoMode(QtWidgets.QLineEdit.Password)
        self.login_btn = QtWidgets.QPushButton("Login")
        self.login_btn.clicked.connect(self.handle_login)
        auth_row.addWidget(self.email_input)
        auth_row.addWidget(self.password_input)
        auth_row.addWidget(self.login_btn)

        # Status and sync indicator
        self.status_label = QtWidgets.QLabel("Status: Not tracking")
        self.status_label.setStyleSheet("color: #FFFFFF; font-size: 16px;")

        self.sync_label = QtWidgets.QLabel("Sync: Online")
        self.sync_label.setStyleSheet("color: #4CAF50; font-size: 14px;")

        self.blink_label = QtWidgets.QLabel("Blink count: 0")
        self.blink_label.setStyleSheet(
            "color: #FFFFFF; font-size: 24px; font-weight: bold;"
        )

        # Performance stats
        self.cpu_label = QtWidgets.QLabel("CPU: - %")
        self.mem_label = QtWidgets.QLabel("Memory: - MB")
        self.energy_label = QtWidgets.QLabel("Energy impact: approx -")
        for lbl in (self.cpu_label, self.mem_label, self.energy_label):
            lbl.setStyleSheet("color: #CCCCCC; font-size: 14px;")

        # Buttons
        btn_row = QtWidgets.QHBoxLayout()
        self.start_btn = QtWidgets.QPushButton("Start Tracking")
        self.stop_btn = QtWidgets.QPushButton("Stop Tracking")
        self.stop_btn.setEnabled(False)
        self.start_btn.clicked.connect(self.start_tracking)
        self.stop_btn.clicked.connect(self.stop_tracking)
        btn_row.addWidget(self.start_btn)
        btn_row.addWidget(self.stop_btn)

        # Assemble layout
        layout.addLayout(auth_row)
        layout.addWidget(self.status_label)
        layout.addWidget(self.sync_label)
        layout.addWidget(self.blink_label)
        layout.addSpacing(12)
        layout.addWidget(self.cpu_label)
        layout.addWidget(self.mem_label)
        layout.addWidget(self.energy_label)
        layout.addStretch(1)
        layout.addLayout(btn_row)

        # Dark theme
        self.setStyleSheet(
            "QMainWindow { background-color: #1E1E1E; }"
            "QWidget { background-color: #1E1E1E; color: #FFFFFF; }"
            "QPushButton { background-color: #2D2D2D; color: #FFFFFF; padding: 8px 16px; border-radius: 4px; }"
            "QPushButton:disabled { background-color: #444444; }"
            "QPushButton:hover:!disabled { background-color: #3A3A3A; }"
        )

        self.setCentralWidget(central)

        # System tray
        self.setup_system_tray()

    def setup_system_tray(self):
        # Create system tray icon
        self.tray_icon = QtWidgets.QSystemTrayIcon(self)
        self.tray_icon.setIcon(QtWidgets.QApplication.style().standardIcon(QtWidgets.QStyle.SP_ComputerIcon))
        
        # Create tray menu
        tray_menu = QtWidgets.QMenu()
        
        show_action = tray_menu.addAction("Show")
        show_action.triggered.connect(self.show)
        
        hide_action = tray_menu.addAction("Hide")
        hide_action.triggered.connect(self.hide)
        
        tray_menu.addSeparator()
        
        quit_action = tray_menu.addAction("Quit")
        quit_action.triggered.connect(QtWidgets.QApplication.quit)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        # Connect tray icon activation
        self.tray_icon.activated.connect(self.on_tray_activated)

    def on_tray_activated(self, reason):
        if reason == QtWidgets.QSystemTrayIcon.DoubleClick:
            self.show()
            self.raise_()
            self.activateWindow()

    def closeEvent(self, event):
        # Minimize to tray instead of closing
        if self.tray_icon.isVisible():
            self.hide()
            self.tray_icon.showMessage(
                "Wellness at Work",
                "Application minimized to tray",
                QtWidgets.QSystemTrayIcon.Information,
                2000
            )
            event.ignore()
        else:
            event.accept()

    def handle_login(self):
        email = self.email_input.text().strip()
        password = self.password_input.text().strip()
        if not email or not password:
            self.status_label.setText("Status: Enter email and password")
            return

        self.status_label.setText("Status: Logging in...")
        self.login_btn.setEnabled(False)
        self.login_btn.setText("Logging in...")
        QtWidgets.QApplication.processEvents()

        ok = self.api.login(email=email, password=password)
        
        self.login_btn.setEnabled(True)
        self.login_btn.setText("Login")

        if ok:
            self.status_label.setText("Status: Logged in successfully")
            self.sync_label.setText("Sync: Online")
            self.sync_label.setStyleSheet("color: #4CAF50; font-size: 14px;")
        else:
            self.status_label.setText("Status: Login failed - check credentials and connection")
            self.sync_label.setText("Sync: Offline")
            self.sync_label.setStyleSheet("color: #F44336; font-size: 14px;")

    def start_tracking(self):
        if self.tracking:
            return
        if not self.api.has_token:
            self.status_label.setText("Status: Please login first")
            return
        self.tracking = True
        self.status_label.setText("Status: Starting webcam tracking...")
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)

        # Reset UI counter
        self.blink_count = 0
        self.blink_label.setText("Blink count: 0")

        # Session metrics
        self._session_start = datetime.now(timezone.utc)
        self._cpu_samples = []
        self._mem_samples = []

        # Setup worker in background thread
        self.tracker_thread = QtCore.QThread(self)
        self.tracker_worker = EyeTrackerWorker()
        self.tracker_worker.moveToThread(self.tracker_thread)

        # Connect signals
        self.tracker_thread.started.connect(self.tracker_worker.start)
        self.tracker_worker.blink_count_updated.connect(self.on_blink_count_updated)
        self.tracker_worker.status_message.connect(self.on_tracker_status)
        self.tracker_thread.finished.connect(self.tracker_worker.deleteLater)

        self.tracker_thread.start()

    def stop_tracking(self):
        if not self.tracking:
            return

        self.tracking = False

        if self.tracker_worker is not None:
            self.tracker_worker.stop()
        if self.tracker_thread is not None:
            self.tracker_thread.quit()
            self.tracker_thread.wait()
            self.tracker_thread = None
            self.tracker_worker = None

        # Persist session and sync
        if self._session_start is not None:
            self.sync_label.setText("Sync: Syncing...")
            self.sync_label.setStyleSheet("color: #FF9800; font-size: 14px;")

            try:
                ended_at = datetime.now()
                avg_cpu = (
                    sum(self._cpu_samples) / len(self._cpu_samples)
                    if self._cpu_samples
                    else 0.0
                )
                avg_mem = (
                    sum(self._mem_samples) / len(self._mem_samples)
                    if self._mem_samples
                    else 0.0
                )

                self.api.buffer_session(
                    started_at=self._session_start,
                    ended_at=ended_at,
                    blink_count=self.blink_count,
                    avg_cpu=avg_cpu,
                    avg_mem=avg_mem,
                )

                synced = self.api.sync_buffer()
                if synced > 0:
                    self.status_label.setText(
                        f"Status: Not tracking (synced {synced} sessions)"
                    )
                    self.sync_label.setText("Sync: Online")
                    self.sync_label.setStyleSheet("color: #4CAF50; font-size: 14px;")
                else:
                    self.status_label.setText("Status: Not tracking (offline - buffered)")
                    self.sync_label.setText("Sync: Offline")
                    self.sync_label.setStyleSheet("color: #F44336; font-size: 14px;")
            except Exception as e:
                self.status_label.setText("Status: Not tracking (sync failed)")
                self.sync_label.setText("Sync: Error")
                self.sync_label.setStyleSheet("color: #F44336; font-size: 14px;")
                print(f"Sync error: {e}")  # Add logging for debugging
        else:
            self.status_label.setText("Status: Not tracking")

        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

    @QtCore.pyqtSlot(int)
    def on_blink_count_updated(self, count: int):
        self.blink_count = count
        self.blink_label.setText(f"Blink count: {self.blink_count}")

    @QtCore.pyqtSlot(str)
    def on_tracker_status(self, message: str):
        self.status_label.setText(f"Status: {message}")

    def update_performance_stats(self):
        # CPU in %
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().used / (1024 * 1024)  # MB

        if self.tracking:
            self._cpu_samples.append(cpu)
            self._mem_samples.append(mem)

        # Power usage estimation (placeholder - would need OS-specific APIs for actual power monitoring)
        # Windows: Could use WMI, macOS: ioreg, Linux: /sys/class/power_supply/
        # For MVP, we use CPU-based approximation
        # TODO: With more time, implement platform-specific power monitoring APIs
        if cpu < 20:
            energy = "Low"
        elif cpu < 60:
            energy = "Medium"
        else:
            energy = "High"

        self.cpu_label.setText(f"CPU: {cpu:.1f} %")
        self.mem_label.setText(f"Memory: {mem:.0f} MB")
        self.energy_label.setText(f"Energy impact: approx {energy}")

    def check_blink_rate(self):
        if not self.tracking or self._session_start is None:
            return
        
        # Calculate blinks per minute
        session_duration_minutes = (datetime.now(timezone.utc) - self._session_start).total_seconds() / 60
        if session_duration_minutes > 0:
            blink_rate = self.blink_count / session_duration_minutes
            
            # Alert if blink rate is below 10 blinks per minute (considered low)
            if blink_rate < 10:
                if self.tray_icon.isVisible():
                    self.tray_icon.showMessage(
                        "Low Blink Rate Alert",
                        f"Your current blink rate is {blink_rate:.1f} blinks/min. Consider taking a break!",
                        QtWidgets.QSystemTrayIcon.Warning,
                        5000
                    )


def main():
    app = QtWidgets.QApplication(sys.argv)
    window = MainWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
