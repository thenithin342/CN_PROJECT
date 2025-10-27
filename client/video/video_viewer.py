#!/usr/bin/env python3
"""
Video Viewer - Receives and displays video streams in a PyQt grid.

This module implements a PyQt-based viewer that receives video frames via UDP
and displays them in a dynamic grid layout. Supports resizing and fullscreen view.
"""

import cv2
import socket
import argparse
import threading
import time
import struct
import numpy as np
from typing import Dict, Tuple, Optional
from collections import deque
from datetime import datetime

# Try PyQt6 first (project standard), fallback to PyQt5
HAS_PYQT6 = False
HAS_PYQT5 = False

try:
    from PyQt6.QtWidgets import QApplication, QWidget, QGridLayout, QLabel, QPushButton, QVBoxLayout, QHBoxLayout
    from PyQt6.QtCore import Qt, QTimer
    from PyQt6.QtGui import QImage, QPixmap
    HAS_PYQT6 = True
except ImportError:
    try:
        from PyQt5.QtWidgets import QApplication, QWidget, QGridLayout, QLabel, QPushButton, QVBoxLayout, QHBoxLayout
        from PyQt5.QtCore import Qt, QTimer
        from PyQt5.QtGui import QImage, QPixmap
        HAS_PYQT5 = True
        print("[WARNING] PyQt6 not available, using PyQt5 fallback.")
    except ImportError:
        print("[WARNING] PyQt not installed. Video viewer requires PyQt6 or PyQt5.")
        print("Install with: pip install PyQt6 (recommended) or pip install PyQt5")


class VideoStream:
    """Represents a video stream from a specific user."""
    
    def __init__(self, uid: int):
        """Initialize video stream."""
        self.uid = uid
        self.frame_buffer = deque(maxlen=3)  # Keep last 3 frames
        self.last_frame_time = time.time()
        self.fps = 0
        self.frame_count = 0
        self.last_fps_time = time.time()


class VideoViewer:
    """Client-side video viewer that receives and displays video streams."""
    
    def __init__(self, port: int = 10001):
        """
        Initialize the video viewer.
        
        Args:
            port: UDP port to receive video frames on
        """
        self.port = port
        self.socket = None
        self.running = False
        self.receive_thread = None
        
        # Stream management
        self.streams: Dict[int, VideoStream] = {}
        self.streams_lock = threading.Lock()
        
        # UI components (initialized when start_viewer is called)
        self.app = None
        self.window = None
        self.layout = None
        self.labels: Dict[int, QLabel] = {}
    
    def start_receiving(self):
        """Start receiving video frames on UDP port."""
        if self.running:
            return
        
        try:
            # Create UDP socket
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.bind(('', self.port))
            self.socket.settimeout(1.0)  # 1 second timeout
            
            self.running = True
            
            # Start receive thread
            self.receive_thread = threading.Thread(target=self._receive_loop, daemon=True)
            self.receive_thread.start()
            
            print(f"[VIDEO VIEWER] Receiving video on port {self.port}")
            
        except Exception as e:
            print(f"[VIDEO VIEWER] Error starting receiver: {e}")
            raise
    
    def _receive_loop(self):
        """Main receive loop running in separate thread."""
        while self.running:
            try:
                # Receive frame data (complete JPEG frames from server)
                data, addr = self.socket.recvfrom(65536)
                
                # For simplicity, assume we receive complete frames
                # In production, you'd need to handle chunking here too
                self._process_frame(data, addr)
                
            except socket.timeout:
                # Expected timeout, continue
                continue
            except Exception as e:
                if self.running:
                    print(f"[VIDEO VIEWER] Error receiving: {e}")
    
    def _process_frame(self, frame_data: bytes, addr: Tuple[str, int]):
        """
        Process received frame data with broadcast header.
        
        Args:
            frame_data: Broadcast header (12 bytes) + JPEG-encoded frame data
            addr: Source address
        """
        try:
            # Parse broadcast header: uid (4 bytes) + timestamp (8 bytes)
            if len(frame_data) < 12:
                # Fallback for frames without header
                uid = hash(addr) % 0xFFFFFFFF
                frame_only = frame_data
            else:
                header = frame_data[:12]
                frame_only = frame_data[12:]
                uid, timestamp = struct.unpack('>I Q', header)
            
            # Decode JPEG frame
            nparr = np.frombuffer(frame_only, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is None:
                return
            
            # Update stream
            with self.streams_lock:
                if uid not in self.streams:
                    self.streams[uid] = VideoStream(uid)
                
                stream = self.streams[uid]
                stream.frame_buffer.append(frame)
                stream.frame_count += 1
                
                # Calculate FPS
                current_time = time.time()
                if current_time - stream.last_fps_time >= 1.0:
                    elapsed = current_time - stream.last_fps_time
                    stream.fps = stream.frame_count / elapsed
                    stream.frame_count = 0
                    stream.last_fps_time = current_time
                
                stream.last_frame_time = current_time
            
            print(f"[VIDEO VIEWER] Received frame from uid={uid}, size={len(frame_data)} bytes")
            
        except Exception as e:
            print(f"[VIDEO VIEWER] Error processing frame: {e}")
    
    def start_viewer(self):
        """Start the PyQt viewer GUI."""
        if not HAS_PYQT6 and not HAS_PYQT5:
            print("[ERROR] PyQt is required for video viewer")
            print("Install with: pip install PyQt6 (recommended) or pip install PyQt5")
            return
        
        # Create QApplication
        import sys
        self.app = QApplication(sys.argv)
        
        # Create main window
        self.window = QWidget()
        self.window.setWindowTitle("Video Viewer")
        self.window.resize(800, 600)
        
        # Create layout
        main_layout = QVBoxLayout()
        self.layout = QGridLayout()
        
        # Control buttons
        button_layout = QHBoxLayout()
        
        refresh_btn = QPushButton("Refresh")
        refresh_btn.clicked.connect(self._refresh_grid)
        
        fullscreen_btn = QPushButton("Toggle Fullscreen")
        fullscreen_btn.clicked.connect(self._toggle_fullscreen)
        
        button_layout.addWidget(refresh_btn)
        button_layout.addWidget(fullscreen_btn)
        button_layout.addStretch()
        
        main_layout.addLayout(button_layout)
        main_layout.addLayout(self.layout)
        
        self.window.setLayout(main_layout)
        
        # Setup update timer
        self.timer = QTimer()
        self.timer.timeout.connect(self._update_display)
        self.timer.start(33)  # ~30 FPS update rate
        
        # Show window
        self.window.show()
        
        # Run app (compatible with both PyQt5 and PyQt6)
        exec_method = getattr(self.app, "exec", getattr(self.app, "exec_", None))
        if exec_method:
            exec_method()
        else:
            raise RuntimeError("Could not find exec method for QApplication")
    
    def _refresh_grid(self):
        """Refresh the grid layout with current streams."""
        with self.streams_lock:
            stream_uids = list(self.streams.keys())
        
        # Clear existing labels
        for label in self.labels.values():
            self.layout.removeWidget(label)
            label.deleteLater()
        self.labels.clear()
        
        # Add new labels
        cols = max(1, int(np.ceil(np.sqrt(len(stream_uids)))))
        
        for idx, uid in enumerate(stream_uids):
            row = idx // cols
            col = idx % cols
            
            label = QLabel(f"Stream {uid}")
            label.setMinimumSize(320, 240)
            label.setStyleSheet("border: 1px solid black;")
            
            self.labels[uid] = label
            self.layout.addWidget(label, row, col)
        
        print(f"[VIDEO VIEWER] Grid refreshed with {len(stream_uids)} streams")
    
    def _update_display(self):
        """Update display with latest frames from all streams."""
        with self.streams_lock:
            for uid, stream in self.streams.items():
                if len(stream.frame_buffer) > 0 and uid in self.labels:
                    # Get latest frame
                    frame = stream.frame_buffer[-1].copy()
                    
                    # Draw FPS on the frame
                    fps_text = f"Stream {uid} | FPS: {stream.fps:.1f}"
                    cv2.putText(frame, fps_text, (10, 30),
                               cv2.FONT_HERSHEY_SIMPLEX, 1, (0, 255, 0), 2)
                    
                    # Convert to QImage
                    height, width, channel = frame.shape
                    bytes_per_line = 3 * width
                    # PyQt6 uses Format, PyQt5 uses same namespace
                    if HAS_PYQT6:
                        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
                    else:
                        q_image = QImage(frame.data, width, height, bytes_per_line, QImage.Format_RGB888)
                    
                    # Flip RGB (OpenCV uses BGR, Qt uses RGB)
                    q_image = q_image.rgbSwapped()
                    
                    # Convert to QPixmap and scale to label size
                    pixmap = QPixmap.fromImage(q_image)
                    label = self.labels[uid]
                    # PyQt6 uses KeepAspectRatio, PyQt5 uses the same but check for compatibility
                    if HAS_PYQT6:
                        scaled_pixmap = pixmap.scaled(label.size(), Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
                    else:
                        scaled_pixmap = pixmap.scaled(label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
                    
                    # Update label
                    label.setPixmap(scaled_pixmap)
    
    def _toggle_fullscreen(self):
        """Toggle fullscreen mode."""
        if self.window.isFullScreen():
            self.window.showNormal()
        else:
            self.window.showFullScreen()
    
    def stop(self):
        """Stop receiving video."""
        self.running = False
        
        # Wait for receive thread
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        # Close socket
        if self.socket:
            self.socket.close()
        
        print("[VIDEO VIEWER] Stopped receiving")
    
    def cleanup(self):
        """Clean up resources."""
        self.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Video Viewer - Receives and displays video streams')
    parser.add_argument('--port', type=int, default=10001,
                       help='UDP port to receive video on (default: 10001)')
    
    args = parser.parse_args()
    
    viewer = VideoViewer(port=args.port)
    
    try:
        # Start receiving
        viewer.start_receiving()
        
        # Start viewer UI (blocking)
        viewer.start_viewer()
        
    except KeyboardInterrupt:
        print("\n[VIDEO VIEWER] Stopping...")
    finally:
        viewer.cleanup()


if __name__ == "__main__":
    main()
