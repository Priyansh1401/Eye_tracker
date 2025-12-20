import cv2
import numpy as np
from PyQt5 import QtCore


class EyeTrackerWorker(QtCore.QObject):
    """
    Runs webcam-based blink detection in a background thread and emits
    real-time blink counts to the UI.

    Uses OpenCV Haar cascades for eye detection (MediaPipe solutions API was removed in v0.10+).
    """

    blink_count_updated = QtCore.pyqtSignal(int)
    status_message = QtCore.pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._running = False
        self._blink_count = 0

        self._cap = None

        # OpenCV Haar cascade setup for eye detection
        self.eye_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_eye.xml')

        # Blink detection parameters
        self._closed_consec_frames = 0
        self._closed_frames_threshold = 2
        self._eyes_were_open = True

    def start(self):
        if self._running:
            return

        self._running = True
        self._blink_count = 0
        self.status_message.emit("Opening webcam...")

        self._cap = cv2.VideoCapture(0)
        if not self._cap or not self._cap.isOpened():
            self.status_message.emit("Error: Cannot open webcam")
            self._running = False
            return

        self.status_message.emit("Tracking with webcam")

        frame_index = 0

        while self._running:
            ret, frame = self._cap.read()
            if not ret:
                self.status_message.emit("Error: Failed to read frame")
                break

            # Flip the frame horizontally for a later selfie-view display
            frame = cv2.flip(frame, 1)

            # Convert to grayscale for Haar cascade
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)

            # Detect eyes using Haar cascade
            eyes = self.eye_cascade.detectMultiScale(gray, 1.3, 5)

            eyes_open = len(eyes) >= 2  # Assume at least 2 eyes detected means eyes are open

            if not eyes_open:
                self._closed_consec_frames += 1
            else:
                # If eyes were closed for a few frames and then open again,
                # count that as a blink.
                if (
                    self._closed_consec_frames >= self._closed_frames_threshold
                    and self._eyes_were_open is False
                ):
                    self._blink_count += 1
                    self.blink_count_updated.emit(self._blink_count)

                self._closed_consec_frames = 0

            self._eyes_were_open = eyes_open

            # Lightweight debug log every 10 frames
            frame_index += 1
            if frame_index % 10 == 0:
                print(
                    f"[EyeTracker] frames_closed={self._closed_consec_frames}, "
                    f"eyes_open={eyes_open}, blink_count={self._blink_count}"
                )

            # Tiny sleep to avoid maxing out CPU
            cv2.waitKey(1)

        self._cleanup()
        self.status_message.emit("Stopped tracking")

    def _get_eye_aspect_ratio(self, landmarks, eye_indices):
        """Calculate the eye aspect ratio (EAR) for blink detection."""
        # Get the coordinates of the eye landmarks
        eye_points = []
        for idx in eye_indices:
            point = landmarks.landmark[idx]
            eye_points.append((point.x, point.y))

        # Calculate distances
        # Vertical distances
        v1 = np.linalg.norm(np.array(eye_points[1]) - np.array(eye_points[5]))
        v2 = np.linalg.norm(np.array(eye_points[2]) - np.array(eye_points[4]))

        # Horizontal distance
        h = np.linalg.norm(np.array(eye_points[0]) - np.array(eye_points[3]))

        # Eye aspect ratio
        ear = (v1 + v2) / (2.0 * h)
        return ear

    def stop(self):
        self._running = False

    def _cleanup(self):
        if self._cap is not None:
            self._cap.release()
            self._cap = None


