#!/usr/bin/env python3
"""
Client GUI - Comprehensive PyQt6 Application

This module integrates all client functionality into a single-file GUI application.
Features:
- Video grid for local and remote feeds
- Participant list with mute controls
- Presenter controls (start/stop share)
- Chat interface with file upload
- Audio/video controls
- Screen sharing viewer
"""

import sys
import asyncio
import threading
import json
import socket
import struct
import time
import os
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from datetime import datetime
from collections import deque

# PyQt6 imports
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QGridLayout, QLabel, QPushButton, QTextEdit, QTextBrowser, QLineEdit, QListWidget,
    QListWidgetItem, QProgressBar, QFileDialog, QMessageBox, QInputDialog, QSizePolicy,
    QMenu, QDialog
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QSize, QTimer, QMutex, QUrl
from PyQt6.QtGui import QImage, QPixmap, QFont, QPalette, QColor

# OpenCV for video
try:
    import cv2
    import numpy as np
    HAS_OPENCV = True
except ImportError:
    HAS_OPENCV = False
    print("[WARNING] OpenCV not available. Video features disabled.")

# Audio imports
try:
    import sounddevice as sd
    import numpy as np
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False

try:
    from opuslib import Encoder, Decoder
    HAS_OPUS = True
except (ImportError, Exception) as e:
    HAS_OPUS = False
    print(f"[WARNING] Opus library not available: {e}")
    print("Audio encoding will be disabled.")

# Screen sharing imports
try:
    import mss
    from PIL import Image as PILImage
    from io import BytesIO
    HAS_SCREEN_SHARE = True
except ImportError:
    HAS_SCREEN_SHARE = False

# Protocol imports
sys.path.append(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
from common.protocol_definitions import (
    create_login_message, create_heartbeat_message, create_logout_message
)
from common.constants import MessageTypes

# Import existing client modules
from client.audio.audio_client import AudioClient
from client.video.video_client import VideoClient
from client.files.file_client import FileClient
from client.chat.chat_client import ChatClient
from client.screen.screen_presenter import ScreenPresenter
from client.screen.screen_viewer import ScreenViewer


# ============================================================================
# VIDEO GRID WIDGET
# ============================================================================

class VideoFrame(QLabel):
    """Individual video frame widget."""
    
    def __init__(self, uid: int, username: str = None):
        super().__init__()
        self.uid = uid
        self.username = username or f"User {uid}"
        self.current_frame = None
        # Lock the draw size after the first frame to prevent any zooming
        self._locked_draw_size = None  # type: Optional[QSize]
        self.setup_ui()
    
    def setup_ui(self):
        """Setup the UI for video frame."""
        # Responsive sizing so the grid layout remains balanced
        self.setMinimumSize(320, 240)
        self.setMaximumSize(640, 480)
        self.setStyleSheet("""
            QLabel {
                border: 2px solid #2C3E50;
                border-radius: 8px;
                background-color: #1A1A1A;
                color: white;
            }
        """)
        self.setText(f"{self.username}")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
    
    def update_frame(self, frame: np.ndarray):
        """Update with new frame data."""
        try:
            if frame is None or frame.size == 0:
                return
                
            self.current_frame = frame
            
            # Convert OpenCV BGR to RGB
            frame_rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
            height, width, channel = frame_rgb.shape
            
            if height <= 0 or width <= 0:
                print(f"[VIDEO FRAME] Invalid frame dimensions: {width}x{height}")
                return
            
            bytes_per_line = 3 * width
            
            # Create QImage
            q_image = QImage(frame_rgb.data, width, height, bytes_per_line, QImage.Format.Format_RGB888)
            
            # Create QPixmap
            pixmap = QPixmap.fromImage(q_image)
            
            # Determine and lock the draw size on first frame to avoid any zooming later
            if self._locked_draw_size is None:
                # Compute the largest size that fits inside the current label size with aspect preserved
                target_size = self.size()
                if target_size.width() <= 0 or target_size.height() <= 0:
                    # Fallback to a sane default
                    target_size = QSize(640, 360)
                self._locked_draw_size = target_size
            
            # Scale to the locked draw size, keeping aspect ratio, using fast transform to avoid smoothing/animation
            scaled_pixmap = pixmap.scaled(
                self._locked_draw_size,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.FastTransformation
            )
            self.setPixmap(scaled_pixmap)
            
        except Exception as e:
            print(f"[VIDEO FRAME] Error updating frame for uid={self.uid}: {e}")
            # Don't print full traceback for every frame error to avoid spam
            if not hasattr(self, '_last_error_time') or (time.time() - self._last_error_time) > 5:
                import traceback
                traceback.print_exc()
                self._last_error_time = time.time()

    def clear_display(self):
        """Reset label to placeholder without any image."""
        try:
            self.current_frame = None
            self.setPixmap(QPixmap())
            self.setText(f"{self.username}")
            self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        except Exception as e:
            print(f"[VIDEO FRAME] Error clearing display for uid={self.uid}: {e}")


class VideoGridWidget(QWidget):
    """Grid layout for video feeds."""
    
    frame_received = pyqtSignal(int, object)  # uid, frame
    
    def __init__(self):
        super().__init__()
        self.video_frames: Dict[int, VideoFrame] = {}
        self.is_video_active = False  # Track if we're receiving active video
        self.last_frame_time = {}  # Track last frame time per uid
        self.setup_ui()
        # Periodic timer to clear stale feeds (when a sender stops video)
        self._stale_check_timer = QTimer(self)
        self._stale_check_timer.timeout.connect(self._check_stale_feeds)
        self._stale_check_timer.start(1000)
    
    def setup_ui(self):
        """Setup the video grid layout."""
        layout = QGridLayout()
        layout.setSpacing(10)
        layout.setContentsMargins(10, 10, 10, 10)
        self.setLayout(layout)
        self.setStyleSheet("""
            QWidget {
                background-color: #1A1A1A;
            }
        """)
    
    def add_video_feed(self, uid: int, username: str):
        """Add a new video feed to the grid."""
        if uid in self.video_frames:
            return
        
        frame = VideoFrame(uid, username)
        self.video_frames[uid] = frame
        self.update_grid_layout()
    
    def remove_video_feed(self, uid: int):
        """Remove a video feed from the grid."""
        if uid not in self.video_frames:
            return
        
        try:
            frame = self.video_frames[uid]
            self.layout().removeWidget(frame)
            frame.deleteLater()
            del self.video_frames[uid]
            
            # Reset video active flag if no feeds remain
            if uid in self.last_frame_time:
                del self.last_frame_time[uid]
            if not self.last_frame_time:
                self.is_video_active = False
            
            self.update_grid_layout()
        except Exception as e:
            print(f"[VIDEO GRID] Error removing video feed for uid={uid}: {e}")
            # Try to clean up anyway
            if uid in self.video_frames:
                del self.video_frames[uid]
            if uid in self.last_frame_time:
                del self.last_frame_time[uid]
    
    def update_grid_layout(self):
        """Update the grid layout based on number of feeds."""
        layout = self.layout()
        
        # Clear existing layout
        for i in reversed(range(layout.count())):
            layout.itemAt(i).widget().setParent(None)
        
        # Add video frames to grid
        uids = list(self.video_frames.keys())
        num_feeds = len(uids)
        
        if num_feeds == 0:
            return
        
        # Calculate grid dimensions
        cols = 2 if num_feeds <= 4 else 3
        rows = (num_feeds + cols - 1) // cols  # Ceiling division
        
        # Add frames to grid
        for idx, uid in enumerate(uids):
            row = idx // cols
            col = idx % cols
            layout.addWidget(self.video_frames[uid], row, col)
    
    def update_frame(self, uid: int, frame: np.ndarray):
        """Update frame for a specific user."""
        if uid in self.video_frames:
            try:
                self.is_video_active = True
                self.last_frame_time[uid] = time.time()
                self.video_frames[uid].update_frame(frame)
            except Exception as e:
                print(f"[VIDEO GRID] Error updating frame for uid={uid}: {e}")
                # Don't fail silently, but don't spam either
                import traceback
                traceback.print_exc()

    def reset_feed(self, uid: int):
        """Reset a user's feed to the placeholder state."""
        try:
            if uid in self.video_frames:
                self.video_frames[uid].clear_display()
                if uid in self.last_frame_time:
                    del self.last_frame_time[uid]
                # Do not remove the tile; just reset visuals
        except Exception as e:
            print(f"[VIDEO GRID] Error resetting feed for uid={uid}: {e}")

    def _check_stale_feeds(self):
        """Clear tiles that haven't received frames recently."""
        try:
            now = time.time()
            stale_threshold = 2.5  # seconds with no frames -> consider stopped
            stale_uids = []
            for uid, last_time in list(self.last_frame_time.items()):
                if now - last_time > stale_threshold:
                    stale_uids.append(uid)
            for uid in stale_uids:
                self.reset_feed(uid)
        except Exception as e:
            print(f"[VIDEO GRID] Error during stale feed check: {e}")


# ============================================================================
# PARTICIPANT LIST WIDGET
# ============================================================================

class ParticipantItem(QWidget):
    """Widget for individual participant entry."""
    
    mute_clicked = pyqtSignal(int)  # uid
    
    def __init__(self, uid: int, username: str, is_self: bool = False):
        super().__init__()
        self.uid = uid
        self.is_self = is_self
        self._is_muted = False
        self.setup_ui(username)
    
    def setup_ui(self, username: str):
        """Setup participant item UI."""
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Username label
        name_label = QLabel(username)
        if self.is_self:
            name_label.setText(f"{username} (You)")
            name_label.setStyleSheet("font-weight: bold; color: #3498DB;")
        else:
            name_label.setStyleSheet("color: #ECF0F1;")
        
        layout.addWidget(name_label)
        layout.addStretch()
        
        # Mute button (disabled for self)
        self.mute_btn = QPushButton("🔇" if not self.is_muted else "🔊")
        self.mute_btn.setMaximumWidth(40)
        self.mute_btn.setEnabled(not self.is_self)
        if not self.is_self:
            self.mute_btn.clicked.connect(lambda: self.mute_clicked.emit(self.uid))
        
        layout.addWidget(self.mute_btn)
        self.setLayout(layout)
    
    @property
    def is_muted(self):
        return self._is_muted
    
    def toggle_mute(self):
        """Toggle mute state and update button text."""
        self._is_muted = not self._is_muted
        self.mute_btn.setText("🔊" if self._is_muted else "🔇")


class ParticipantPanel(QWidget):
    """Panel showing participant list and controls."""
    
    def __init__(self):
        super().__init__()
        self.participants: Dict[int, ParticipantItem] = {}
        self.setup_ui()
    
    def setup_ui(self):
        """Setup participant panel UI."""
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(10, 10, 10, 10)
        
        # Title
        title = QLabel("Participants")
        title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        title.setStyleSheet("color: #ECF0F1; padding: 5px;")
        layout.addWidget(title)
        
        # Participant list
        self.participant_list = QListWidget()
        self.participant_list.setStyleSheet("""
            QListWidget {
                background-color: #2C3E50;
                border: 1px solid #34495E;
                border-radius: 5px;
                color: #ECF0F1;
            }
            QListWidget::item {
                padding: 5px;
            }
        """)
        # Set minimum height to ensure visibility
        self.participant_list.setMinimumHeight(100)
        layout.addWidget(self.participant_list)
        
        # Controls section
        controls_title = QLabel("Controls")
        controls_title.setFont(QFont("Arial", 12, QFont.Weight.Bold))
        controls_title.setStyleSheet("color: #ECF0F1; padding: 5px; margin-top: 10px;")
        layout.addWidget(controls_title)
        
        # Store parent reference for callbacks
        self.parent_window = None
        
        # Audio button
        self.audio_btn = QPushButton("🎤 Mute Audio")
        self.audio_btn.clicked.connect(self.toggle_audio)
        layout.addWidget(self.audio_btn)
        
        # Video button
        self.video_btn = QPushButton("📹 Start Video")
        self.video_btn.clicked.connect(self.toggle_video)
        layout.addWidget(self.video_btn)
        
        # Screen share button
        self.share_btn = QPushButton("🖥️ Start Screen Share")
        self.share_btn.clicked.connect(self.toggle_screen_share)
        layout.addWidget(self.share_btn)
        
        layout.addStretch()
        self.setLayout(layout)
        
        # Styling
        self.setStyleSheet("""
            QWidget {
                background-color: #34495E;
            }
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                padding: 10px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
            QPushButton:pressed {
                background-color: #1F618D;
            }
        """)
    
    def add_participant(self, uid: int, username: str, is_self: bool = False):
        """Add a participant to the list."""
        item = ParticipantItem(uid, username, is_self)
        self.participants[uid] = item
        
        # Connect the mute_clicked signal to the parent window handler
        if self.parent_window:
            item.mute_clicked.connect(self.parent_window.on_participant_mute_clicked)
        
        list_item = QListWidgetItem()
        list_item.setSizeHint(item.sizeHint())
        self.participant_list.addItem(list_item)
        self.participant_list.setItemWidget(list_item, item)
    
    def remove_participant(self, uid: int):
        """Remove a participant from the list."""
        if uid in self.participants:
            # Find and remove the item
            for i in range(self.participant_list.count()):
                item = self.participant_list.item(i)
                if item:
                    widget = self.participant_list.itemWidget(item)
                    if widget and widget.uid == uid:
                        self.participant_list.takeItem(i)
                        break
            del self.participants[uid]
    
    def toggle_audio(self):
        """Toggle audio streaming."""
        if self.parent_window:
            self.parent_window.on_toggle_audio()
    
    def toggle_video(self):
        """Toggle video streaming."""
        if self.parent_window:
            self.parent_window.on_toggle_video()
    
    def toggle_screen_share(self):
        """Toggle screen sharing."""
        if self.parent_window:
            self.parent_window.on_toggle_screen_share()


# ============================================================================
# CHAT INTERFACE WIDGET
# ============================================================================

class ChatWidget(QWidget):
    """Chat interface with text area and input."""
    
    message_sent = pyqtSignal(str)  # message text
    file_upload = pyqtSignal(str)  # file path
    broadcast_sent = pyqtSignal(str)  # message text
    unicast_sent = pyqtSignal(int, str)  # target_uid, message text
    multicast_sent = pyqtSignal(object, str)  # target_uids(list[int]) or None to select, message text
    file_download_requested = pyqtSignal(str, str)  # fid, filename
    
    def __init__(self):
        super().__init__()
        # Initialize file links storage with TTL-based cleanup
        self._file_links = {}  # fid -> {'filename': str, 'size': str, 'timestamp': float}
        self._file_links_max_size = 100  # Max number of file links to store
        self._file_links_ttl_seconds = 3600  # 1 hour TTL
        self.setup_ui()
        # Setup periodic cleanup timer
        self._setup_file_links_cleanup_timer()
    
    def _setup_file_links_cleanup_timer(self):
        """Setup periodic timer to clean up old file links."""
        self._file_links_cleanup_timer = QTimer(parent=self)  # Set parent for proper cleanup
        self._file_links_cleanup_timer.timeout.connect(self._prune_file_links)
        self._file_links_cleanup_timer.start(600000)  # Run every 10 minutes
    
    def _prune_file_links(self):
        """Periodically prune old file links based on TTL."""
        current_time = time.time()
        expired_fids = []
        
        for fid, info in self._file_links.items():
            timestamp = info.get('timestamp', 0)
            if current_time - timestamp > self._file_links_ttl_seconds:
                expired_fids.append(fid)
        
        for fid in expired_fids:
            del self._file_links[fid]
        
        if expired_fids:
            print(f"[CHAT] Pruned {len(expired_fids)} expired file links")
    
    def _evict_lru_file_link(self):
        """Evict least recently used file link if at max capacity."""
        if len(self._file_links) >= self._file_links_max_size:
            # Remove the oldest entry
            oldest_fid = min(self._file_links.keys(), 
                           key=lambda fid: self._file_links[fid].get('timestamp', 0))
            del self._file_links[oldest_fid]
            print(f"[CHAT] Evicted oldest file link (max size reached)")
    
    def setup_ui(self):
        """Setup chat interface UI."""
        layout = QVBoxLayout()
        layout.setSpacing(5)
        layout.setContentsMargins(5, 5, 5, 5)
        
        # Chat text area (using QTextBrowser for link support)
        self.chat_text = QTextBrowser()
        self.chat_text.setReadOnly(True)
        self.chat_text.setOpenExternalLinks(False)  # Handle links ourselves
        self.chat_text.setStyleSheet("""
            QTextBrowser {
                background-color: #2C2C2C;
                color: #ECF0F1;
                border: 1px solid #34495E;
                border-radius: 5px;
                padding: 5px;
                font-size: 10pt;
            }
            QTextBrowser a {
                color: #3498DB;
                text-decoration: none;
            }
        """)
        # Connect anchor clicked signal to handle downloads
        self.chat_text.anchorClicked.connect(self._on_anchor_clicked)
        layout.addWidget(self.chat_text)
        
        # Input area
        input_layout = QHBoxLayout()
        
        self.input_field = QLineEdit()
        self.input_field.setPlaceholderText("Type a message...")
        self.input_field.setStyleSheet("""
            QLineEdit {
                background-color: #34495E;
                color: #ECF0F1;
                border: 1px solid #2C3E50;
                border-radius: 5px;
                padding: 5px;
            }
        """)
        self.input_field.returnPressed.connect(self.send_message)
        input_layout.addWidget(self.input_field)
        
        # Send button
        send_btn = QPushButton("Send")
        send_btn.clicked.connect(self.send_message)
        send_btn.setStyleSheet("""
            QPushButton {
                background-color: #3498DB;
                color: white;
                border: none;
                padding: 8px 15px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #2980B9;
            }
        """)
        input_layout.addWidget(send_btn)
        
        # File upload button
        file_btn = QPushButton("📎")
        file_btn.setToolTip("Upload File")
        file_btn.clicked.connect(self.upload_file)
        file_btn.setMaximumWidth(50)
        file_btn.setStyleSheet("""
            QPushButton {
                background-color: #27AE60;
                color: white;
                border: none;
                padding: 8px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #229954;
            }
        """)
        input_layout.addWidget(file_btn)
        
        # Send-To menu button for accessibility: Unicast, Multicast, Broadcast
        send_to_btn = QPushButton("Send To ▾")
        send_to_btn.setToolTip("Choose recipients: Unicast, Multicast, Broadcast")
        send_to_btn.setStyleSheet("""
            QPushButton {
                background-color: #2ECC71;
                color: white;
                border: none;
                padding: 8px 12px;
                border-radius: 5px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #27AE60;
            }
        """)
        menu = QMenu(send_to_btn)
        menu.addAction("Broadcast", self.send_broadcast)
        menu.addAction("Private (Unicast)", self.send_private)
        menu.addAction("Multicast", self.send_multicast)
        send_to_btn.setMenu(menu)
        input_layout.addWidget(send_to_btn)
        
        layout.addLayout(input_layout)
        
        # Progress bar for file uploads
        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)
        
        self.setLayout(layout)
    
    def send_message(self):
        """Send chat message."""
        text = self.input_field.text().strip()
        if text:
            self.message_sent.emit(text)
            self.input_field.clear()
    
    def upload_file(self):
        """Upload file."""
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select file to upload", "", "All Files (*)"
        )
        if file_path:
            self.file_upload.emit(file_path)
    
    def send_broadcast(self):
        """Send broadcast message."""
        text = self.input_field.text().strip()
        if text:
            self.broadcast_sent.emit(text)
            self.input_field.clear()
    
    def send_private(self):
        """Send private message."""
        text = self.input_field.text().strip()
        if text:
            # Signal that will be handled by parent to select recipient
            self.unicast_sent.emit(None, text)  # None means need to select
            self.input_field.clear()
    
    def send_multicast(self):
        """Send multicast message (select multiple recipients)."""
        text = self.input_field.text().strip()
        if text:
            # None for targets indicates the main window should prompt for selection
            self.multicast_sent.emit(None, text)
            self.input_field.clear()
    
    def add_message(self, username: str, message: str, is_system: bool = False):
        """Add message to chat."""
        timestamp = datetime.now().strftime("%H:%M")
        if is_system:
            self.chat_text.append(f'<span style="color: #95A5A6;">[{timestamp}] {message}</span>')
        else:
            self.chat_text.append(f'<span style="color: #3498DB;">{username}:</span> {message}')
        
        # Auto scroll to bottom
        scrollbar = self.chat_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def add_file_notification(self, message: str, fid: str, filename: str, size_display: str):
        """Add file notification with download button."""
        timestamp = datetime.now().strftime("%H:%M")
        
        # Insert into chat
        scrollbar = self.chat_text.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 10
        
        # Add as a custom HTML widget with a clickable link style
        notification_html = f'''
        <div style="background-color: #2C3E50; padding: 8px; border-radius: 5px; margin: 5px 0;">
            <span style="color: #95A5A6;">[{timestamp}]</span> {message}
            <a href="download://{fid}" style="color: #3498DB; text-decoration: none; font-weight: bold; margin-left: 10px;">
                ⬇️ Download
            </a>
        </div>
        '''
        
        self.chat_text.append(notification_html)
        
        # Store the fid for later lookup with timestamp
        # Evict oldest entry if at max capacity
        self._evict_lru_file_link()
        
        self._file_links[fid] = {
            'filename': filename, 
            'size': size_display,
            'timestamp': time.time()
        }
        
        # Auto scroll to bottom
        if at_bottom:
            scrollbar.setValue(scrollbar.maximum())
    
    def _on_anchor_clicked(self, url):
        """Handle anchor link clicks (for download links)."""
        try:
            print(f"[CHAT] Anchor clicked: {url.toString()}")
            if url.scheme() == "download":
                # Extract fid from URL (it's stored in the host component)
                fid = url.host()
                print(f"[CHAT] Processing download for fid: {fid}")
                # Get filename from stored links (handle missing entry gracefully)
                if fid in self._file_links:
                    filename = self._file_links[fid]['filename']
                    print(f"[CHAT] File found: {filename}, emitting signal...")
                    self.file_download_requested.emit(fid, filename)
                    # Immediately remove entry to prevent memory leak
                    del self._file_links[fid]
                    print(f"[CHAT] File link removed from storage")
                else:
                    # Entry missing (possibly expired or already downloaded)
                    print(f"[CHAT] Warning: File link for fid={fid} not found (may have been cleaned up)")
                    self.add_message("System", "File download link expired or already used", is_system=True)
        except Exception as e:
            print(f"[CHAT] Error handling download link: {e}")
            import traceback
            traceback.print_exc()
            self.add_message("System", f"Error starting download: {e}", is_system=True)
    
    def show_progress(self, value: int):
        """Show file upload progress."""
        self.progress_bar.setValue(value)
        self.progress_bar.setVisible(value < 100)
    
    def hide_progress(self):
        """Hide progress bar."""
        self.progress_bar.setVisible(False)
        self.progress_bar.setValue(0)
    
    def closeEvent(self, event):
        """Clean up resources when widget is closing."""
        # Stop and clean up the file links cleanup timer
        if hasattr(self, '_file_links_cleanup_timer') and self._file_links_cleanup_timer:
            self._file_links_cleanup_timer.stop()
            self._file_links_cleanup_timer.timeout.disconnect()
            self._file_links_cleanup_timer.deleteLater()
            self._file_links_cleanup_timer = None
        
        # Call parent closeEvent
        super().closeEvent(event)


# ============================================================================
# MAIN WINDOW
# ============================================================================

class ClientMainWindow(QMainWindow):
    """Main application window."""
    
    # Signal to marshal video frames to the GUI thread
    frame_received_signal = pyqtSignal(int, object)  # uid, frame

    def __init__(self, server_host: str = 'localhost', server_port: int = 9000):
        super().__init__()
        self.server_host = server_host
        self.server_port = server_port
        self.username = None
        self.uid = None
        
        # Networking components
        self.reader = None
        self.writer = None
        self.network_thread = None
        self.video_receiver_thread = None
        
        # Client modules (initialized after connection)
        self.audio_client = None
        self.video_client = None
        self.file_client = None
        self.chat_client = None
        self.screen_presenter = None
        self.screen_viewer = None
        
        # State
        self.participants: Dict[int, dict] = {}
        self.video_streams: Dict[int, np.ndarray] = {}
        self.running = False
        self.available_files = {}  # Store available files for download
        
        # Worker storage (to prevent garbage collection)
        self.upload_worker = None
        self.screen_share_start_worker = None
        self.screen_share_stop_worker = None
        self.active_workers = []  # Track all active workers for proper cleanup
        
        # Setup UI
        self.setup_ui()
        self.setup_connections()
        
        # Set parent reference in participant panel
        self.participant_panel.parent_window = self
        
        # Connect video receiver
        self.setup_video_receiver()

        # Connect cross-thread frame signal to a main-thread slot
        self.frame_received_signal.connect(self._enqueue_frame_main_thread)
        
        # Setup heartbeat timer to keep participants synced
        self.setup_heartbeat_timer()
    
    def setup_ui(self):
        """Setup the main window UI."""
        self.setWindowTitle("LAN Collaboration Client")
        self.setGeometry(100, 100, 1400, 900)
        
        # Central widget and main layout
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # Main vertical layout for top video area and bottom chat
        main_layout = QVBoxLayout()
        main_layout.setSpacing(5)
        main_layout.setContentsMargins(10, 10, 10, 10)
        
        # Top area: Video grid and participant panel (horizontal)
        top_area = QHBoxLayout()
        
        # Video grid (left, takes most space)
        self.video_grid = VideoGridWidget()
        top_area.addWidget(self.video_grid, stretch=3)
        
        # Right panel (participants and controls)
        self.participant_panel = ParticipantPanel()
        top_area.addWidget(self.participant_panel, stretch=1)
        
        # Add top area to main layout
        main_layout.addLayout(top_area, stretch=3)
        
        # Chat widget (bottom area) - Fixed size to prevent layout issues
        self.chat_widget = ChatWidget()
        self.chat_widget.setMinimumHeight(200)
        self.chat_widget.setMaximumHeight(250)
        self.chat_widget.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)
        main_layout.addWidget(self.chat_widget, stretch=0)
        
        # Set main layout
        central_widget.setLayout(main_layout)
        
        # Set dark theme
        self.apply_dark_theme()
    
    def setup_connections(self):
        """Setup signal-slot connections."""
        self.chat_widget.message_sent.connect(self.on_send_message)
        self.chat_widget.file_upload.connect(self.on_upload_file)
        self.chat_widget.broadcast_sent.connect(self.on_send_broadcast)
        self.chat_widget.unicast_sent.connect(self.on_send_unicast)
        self.chat_widget.multicast_sent.connect(self.on_send_multicast)
        self.chat_widget.file_download_requested.connect(self.on_download_file)
    
    def connect_signals(self):
        """Connect signals from participant panel."""
        # Connect directly to methods (participant panel doesn't have signals)
        pass
    
    def apply_dark_theme(self):
        """Apply dark theme styling."""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #1A1A1A;
            }
            QWidget {
                background-color: #1A1A1A;
                color: #ECF0F1;
            }
        """)
    
    def setup_heartbeat_timer(self):
        """Setup periodic heartbeat timer."""
        self.heartbeat_timer = QTimer()
        self.heartbeat_timer.timeout.connect(self.send_heartbeat)
        self.heartbeat_timer.setInterval(10000)  # 10 seconds
        self.heartbeat_timer.start()
    
    def send_heartbeat(self):
        """Send heartbeat message to server."""
        if self.network_thread and self.network_thread.writer:
            try:
                message = create_heartbeat_message()
                self.network_thread.send_message(message)
            except Exception as e:
                print(f"[GUI] Error sending heartbeat: {e}")
    
    # ========================================================================
    # CONNECTION & NETWORKING
    # ========================================================================
    
    def connect_to_server(self):
        """Connect to the server."""
        from PyQt6.QtWidgets import QInputDialog
        
        # Prompt for server IP
        default_host = getattr(self, 'server_host', 'localhost') or 'localhost'
        host_text, ok = QInputDialog.getText(self, 'Server Address', 'Enter server IP/hostname:', text=default_host)
        if not ok or not host_text:
            QMessageBox.warning(self, "Error", "Server IP/hostname required")
            return False
        self.server_host = host_text.strip()

        # Prompt for server port
        default_port_str = str(getattr(self, 'server_port', 9000) or 9000)
        port_text, ok = QInputDialog.getText(self, 'Server Port', 'Enter server port:', text=default_port_str)
        if not ok or not port_text.strip().isdigit():
            QMessageBox.warning(self, "Error", "Valid server port required")
            return False
        self.server_port = int(port_text.strip())

        # Always show dialog to enter username (use existing as default if present)
        default_username = getattr(self, 'username', '') or ''
        text, ok = QInputDialog.getText(self, 'Login', 'Enter your username:', text=default_username)
        
        if not ok or not text:
            QMessageBox.warning(self, "Error", "Username required")
            return False
        
        self.username = text
        print(f"[GUI] Connecting as: {self.username}")
        
        # Show connecting status
        self.chat_widget.add_message("System", f"Connecting to {self.server_host}:{self.server_port}...", is_system=True)
        self.setWindowTitle(f"LAN Collaboration Client - Connecting...")
        
        # Start network thread
        self.network_thread = NetworkThread(self.server_host, self.server_port, self.username)
        self.network_thread.message_received.connect(self.handle_message)
        self.network_thread.connected.connect(self.on_connected)
        self.network_thread.disconnected.connect(self.on_disconnected)
        self.network_thread.start()
        
        return True
    
    def setup_video_receiver(self):
        """Setup video receiver for remote feeds."""
        # Note: Video receiver is now handled by video_client itself using ephemeral ports
        # We don't need a separate VideoReceiverThread anymore
        print("[GUI] Video receiving is handled by video_client using ephemeral ports")
        self.video_receiver_thread = None  # Not used anymore
        
        # Create a QTimer for thread-safe frame updates
        self.video_update_timer = QTimer()
        self.video_update_timer.timeout.connect(self._process_pending_frames)
        self.pending_frames = {}  # uid -> frame queue
        self.frame_lock = threading.Lock()
    
    def _on_frame_received(self, uid, frame):
        """Called from background thread; relay to main thread via signal."""
        try:
            self.frame_received_signal.emit(uid, frame)
        except Exception as e:
            print(f"[GUI] Error emitting frame signal for uid={uid}: {e}")
            import traceback
            traceback.print_exc()

    def _enqueue_frame_main_thread(self, uid, frame):
        """Main-thread slot to enqueue frame and ensure GUI timer runs."""
        try:
            with self.frame_lock:
                self.pending_frames[uid] = frame
            if not self.video_update_timer.isActive():
                self.video_update_timer.start(16)
                print(f"[GUI] Started video update timer for uid={uid}")
        except Exception as e:
            print(f"[GUI] Error enqueuing frame on main thread for uid={uid}: {e}")
            import traceback
            traceback.print_exc()
    
    def _process_pending_frames(self):
        """Process pending frames on the main GUI thread."""
        try:
            # Get all pending frames in a thread-safe way
            frames_to_process = {}
            with self.frame_lock:
                if not self.pending_frames:
                    # No pending frames, stop timer
                    self.video_update_timer.stop()
                    return
                frames_to_process = self.pending_frames.copy()
                self.pending_frames.clear()
            
            # Process each frame on the main thread
            for uid, frame in frames_to_process.items():
                # Ensure the video feed exists in the grid
                if uid not in self.video_grid.video_frames:
                    # Get username from participants
                    username = self.get_username_by_uid(uid) if uid in self.participants else f"User {uid}"
                    # Mark it as "You" if it's our own feed
                    if uid == self.uid and "(You)" not in username:
                        username = f"{username} (You)"
                    self.video_grid.add_video_feed(uid, username)
                
                # Update the frame on the main thread
                self.video_grid.update_frame(uid, frame)
                
        except Exception as e:
            print(f"[GUI] Error processing pending frames: {e}")
            import traceback
            traceback.print_exc()
    
    def stop_video_receiver(self):
        """Stop receiving video."""
        # Stop the video update timer
        if hasattr(self, 'video_update_timer'):
            self.video_update_timer.stop()
        
        # Clear pending frames
        with self.frame_lock:
            self.pending_frames.clear()
        
        # Video receiver is now part of video_client, which will be cleaned up separately
        pass
    
    def initialize_client_modules(self):
        """Initialize client modules after successful login."""
        if not self.network_thread or not self.network_thread.writer:
            print("[ERROR] Writer not available, cannot initialize client modules")
            self.chat_widget.add_message("System", "Failed to initialize client modules - connection issue", is_system=True)
            return
        
        # Verify UID is set before initializing video client
        if not self.uid:
            print("[ERROR] UID not set, cannot initialize video client")
            self.chat_widget.add_message("System", "Failed to initialize - UID not set", is_system=True)
            return
        
        # Get writer from network thread
        writer = self.network_thread.writer
        
        try:
            # Initialize client modules
            print(f"[GUI] Initializing client modules for uid={self.uid}")
            self.audio_client = AudioClient(server_ip=self.server_host, server_port=11000, uid=self.uid)
            self.video_client = VideoClient(server_ip=self.server_host, server_port=10000, uid=self.uid)
            
            # Ensure UID is set on video client (should already be set from constructor, but double-check)
            self.video_client.set_uid(self.uid)
            print(f"[GUI] Video client UID set to {self.uid}")
            
            # Set up frame received callback - when video client receives a frame from another client, display it
            self.video_client.set_frame_received_callback(self._on_frame_received)
            print(f"[GUI] Frame callback set on video client")

            # Start passive receiving so we can view others even if we don't stream
            try:
                self.video_client.start_receiving()
            except Exception as e:
                print(f"[GUI] Failed to start passive video receiver: {e}")

            # Also start a compatibility UDP receiver on the fixed broadcast port (10001)
            # as a fallback path to ensure frames are displayed even if ephemeral port path fails.
            try:
                if not self.video_receiver_thread:
                    self.video_receiver_thread = VideoReceiverThread(self.server_host, 10001)
                    self.video_receiver_thread.frame_received.connect(lambda uid, frame: self._on_frame_received(uid, frame))
                    self.video_receiver_thread.start()
                    print("[GUI] Started fallback VideoReceiverThread on port 10001")
            except Exception as e:
                print(f"[GUI] Failed to start fallback VideoReceiverThread: {e}")
            
            self.file_client = FileClient()
            self.chat_client = ChatClient(writer)
            self.screen_presenter = ScreenPresenter(writer)
            self.screen_viewer = ScreenViewer(writer)
            
            # Set UID for modules that need it
            self.screen_viewer.set_uid(self.uid)
            print(f"[GUI] Screen viewer UID set to {self.uid}")
            
            # Set hosts and writer for modules that need it
            self.file_client.set_host(self.server_host)
            self.file_client.set_writer(writer)
            self.screen_presenter.set_host(self.server_host)
            self.screen_viewer.set_host(self.server_host)
            
            print("[GUI] Client modules initialized successfully")
            self.chat_widget.add_message("System", "✓ Client modules initialized", is_system=True)
            
        except Exception as e:
            print(f"[GUI] Error initializing client modules: {e}")
            import traceback
            traceback.print_exc()
            self.chat_widget.add_message("System", f"Failed to initialize client modules: {e}", is_system=True)
            
    def on_connected(self):
        """Handle successful connection."""
        self.chat_widget.add_message("System", "✓ Connected to server", is_system=True)
        self.setWindowTitle(f"LAN Collaboration Client - {self.username} (Connected)")
    
    def on_disconnected(self):
        """Handle disconnection."""
        self.chat_widget.add_message("System", "✗ Disconnected from server", is_system=True)
        self.setWindowTitle("LAN Collaboration Client (Disconnected)")
    
    def handle_message(self, message: dict):
        """Handle incoming message from server."""
        try:
            msg_type = message.get('type', '')
            
            if msg_type == MessageTypes.LOGIN_SUCCESS:
                self.uid = message.get('uid')
                self.chat_widget.add_message("System", f"Logged in as {self.username} (uid={self.uid})", is_system=True)
                
                # Initialize client modules
                self.initialize_client_modules()
                
                # Request participant list
                self.request_participant_list()
            
            elif msg_type == MessageTypes.PARTICIPANT_LIST:
                participants_data = message.get('participants', [])
                print(f"[GUI] Received participant_list message with {len(participants_data)} participants")
                print(f"[GUI] Message data: {message}")
                print(f"[GUI] Current self.uid: {self.uid}")
                if self.uid is None:
                    print("[GUI] Warning: Received participant list before setting UID, ignoring")
                    return
                self.update_participants(participants_data)
            
            elif msg_type == MessageTypes.USER_JOINED:
                uid = message.get('uid')
                username = message.get('username')
                print(f"[GUI] Received user_joined: uid={uid}, username={username}")
                self.chat_widget.add_message("System", f"{username} joined", is_system=True)
                # Note: Participant list should be updated via PARTICIPANT_LIST message
            
            elif msg_type == MessageTypes.USER_LEFT:
                uid = message.get('uid')
                username = message.get('username')
                self.chat_widget.add_message("System", f"{username} left", is_system=True)
                
                # Remove from participants
                if uid in self.participants:
                    self.participant_panel.remove_participant(uid)
                    del self.participants[uid]
                
                # Remove video feed (only if it's not active)
                if uid in self.video_grid.video_frames:
                    # Keep the video feed for a bit in case they reconnect
                    # Only remove if they haven't sent a frame in the last 30 seconds
                    if uid in self.video_grid.last_frame_time:
                        time_since_last_frame = time.time() - self.video_grid.last_frame_time[uid]
                        if time_since_last_frame > 30:
                            self.video_grid.remove_video_feed(uid)
                    else:
                        # No recent frames, remove immediately
                        self.video_grid.remove_video_feed(uid)
            
            elif msg_type == MessageTypes.CHAT:
                self.handle_chat_message(message)
            
            elif msg_type == MessageTypes.BROADCAST:
                self.handle_broadcast_message(message)
            
            elif msg_type == MessageTypes.FILE_AVAILABLE:
                print(f"[GUI] Received FILE_AVAILABLE message: {message}")
                self.handle_file_available(message)
            
            elif msg_type == MessageTypes.FILE_UPLOAD_PORT:
                if self.file_client and self.network_thread:
                    import asyncio
                    asyncio.run_coroutine_threadsafe(
                        self.file_client.handle_message(message),
                        self.network_thread.loop
                    )
            
            elif msg_type == MessageTypes.FILE_DOWNLOAD_PORT:
                self.handle_file_download_port(message)
            
            elif msg_type == MessageTypes.UNICAST:
                self.handle_unicast_message(message)
            
            elif msg_type == MessageTypes.UNICAST_SENT:
                to_username = message.get('to_username', 'unknown')
                self.chat_widget.add_message("System", f"Private message delivered to {to_username}", is_system=True)
            
            elif msg_type == MessageTypes.SCREEN_SHARE_PORTS:
                if self.screen_presenter:
                    import asyncio
                    asyncio.run_coroutine_threadsafe(
                        self.screen_presenter.handle_message(message),
                        self.network_thread.loop
                    )
            
            elif msg_type == MessageTypes.PRESENT_START_BROADCAST:
                self.handle_present_start_broadcast(message)
            
            elif msg_type == MessageTypes.PRESENT_STOP_BROADCAST:
                self.handle_present_stop_broadcast(message)
            
            elif msg_type == MessageTypes.ERROR:
                error_msg = message.get('message', 'Unknown error')
                self.chat_widget.add_message("System", f"Error: {error_msg}", is_system=True)
        except Exception as e:
            print(f"[GUI] Error handling message: {e}")
            import traceback
            traceback.print_exc()
    
    def request_participant_list(self):
        """Request updated participant list."""
        # Send a heartbeat to server which should trigger participant list update
        if self.network_thread:
            try:
                message = create_heartbeat_message()
                self.network_thread.send_message(message)
            except Exception as e:
                print(f"[GUI] Error requesting participant list: {e}")
    
    def update_participants(self, participants: List[dict]):
        """Update participant list."""
        print(f"[GUI] Updating participants list with {len(participants)} participants")
        print(f"[GUI] Participants data: {participants}")
        
        # Clear existing
        for uid in list(self.participants.keys()):
            self.participant_panel.remove_participant(uid)
            # Don't remove video feeds - they should persist if video is active
            # self.video_grid.remove_video_feed(uid)
        
        # Add new participants
        for p in participants:
            uid = p.get('uid')
            username = p.get('username')
            if uid is None or username is None:
                print(f"[GUI] Warning: Invalid participant data: {p}")
                continue
            self.participants[uid] = p
            self.participant_panel.add_participant(uid, username, uid == self.uid)
            print(f"[GUI] Added participant uid={uid}, username={username}")
            # Add video feed placeholder for all participants
            if uid not in self.video_grid.video_frames:
                self.video_grid.add_video_feed(uid, username)
                print(f"[GUI] Added video feed placeholder for participant uid={uid}, username={username}")
    
    def handle_chat_message(self, message: dict):
        """Handle incoming chat message."""
        uid = message.get('uid')
        username = message.get('username')
        text = message.get('text', '')
        is_broadcast = message.get('broadcast', False)
        
        if uid != self.uid:  # Don't echo our own messages
            if is_broadcast:
                self.chat_widget.add_message(username, f"[BROADCAST] {text}")
            else:
                self.chat_widget.add_message(username, text)
    
    def handle_broadcast_message(self, message: dict):
        """Handle incoming broadcast message."""
        uid = message.get('uid')
        username = message.get('username')
        text = message.get('text', '')
        
        # Don't echo our own broadcasts
        if uid != self.uid:
            self.chat_widget.add_message(username, f"[BROADCAST] {text}")
    
    def handle_file_available(self, message: dict):
        """Handle file available notification."""
        if not self.file_client:
            return
        
        fid = message.get('fid')
        filename = message.get('filename')
        size = message.get('size')
        uploader = message.get('uploader')
        
        print(f"[FILE AVAILABLE] Received notification: fid={fid}, filename={filename}, size={size}, uploader={uploader}, my_username={self.username}")
        
        # Don't notify about files we uploaded ourselves
        if uploader == self.username:
            print(f"[FILE AVAILABLE] Skipping own file from {uploader}")
            return
        
        # Format file size
        if size < 1024:
            size_str = f"{size} bytes"
        elif size < 1024 * 1024:
            size_str = f"{size / 1024:.1f} KB"
        else:
            size_str = f"{size / (1024 * 1024):.1f} MB"
        
        # Format size with proper suffix
        try:
            if size >= 1024 * 1024 * 1024:
                size_display = f"{size / (1024 * 1024 * 1024):.2f} GB"
            elif size >= 1024 * 1024:
                size_display = f"{size / (1024 * 1024):.2f} MB"
            elif size >= 1024:
                size_display = f"{size / 1024:.2f} KB"
            else:
                size_display = f"{size} bytes"
        except:
            size_display = size_str
        
        # Add notification with download button
        download_msg = f"📥 New File: <b>{filename}</b> ({size_display}) from <b>{uploader}</b>"
        
        # Store file info for potential download
        if not hasattr(self, 'available_files'):
            self.available_files = {}
        self.available_files[fid] = {
            'filename': filename,
            'size': size,
            'uploader': uploader
        }
        
        # Add message with a download action
        self.chat_widget.add_file_notification(download_msg, fid, filename, size_display)
    
    # ========================================================================
    # USER ACTIONS
    # ========================================================================
    
    def on_send_message(self, text: str):
        """Send chat message."""
        if not self.network_thread or not self.network_thread.writer:
            return
        
        message = {
            'type': MessageTypes.CHAT,
            'text': text
        }
        self.network_thread.send_message(message)
        self.chat_widget.add_message(self.username, text)
    
    def on_upload_file(self, file_path: str):
        """Handle file upload."""
        if not self.file_client:
            self.chat_widget.add_message("System", "File client not initialized", is_system=True)
            return
        
        try:
            import asyncio
            self.chat_widget.add_message("System", f"Uploading file: {os.path.basename(file_path)}", is_system=True)
            if self.network_thread and self.network_thread.loop:
                future = asyncio.run_coroutine_threadsafe(self.file_client.upload_file(file_path), self.network_thread.loop)
                result = future.result(timeout=10)
                if result:
                    self._on_upload_complete_with_result(True, None, result)
                else:
                    self._on_upload_complete_with_result(False, "Upload failed", None)
            else:
                self._on_upload_complete_with_result(False, "Network thread not available", None)
        except Exception as e:
            self._on_upload_complete_with_result(False, str(e), None)
    
    def _on_upload_complete_with_result(self, success: bool, error: str, result, completing_worker=None):
        """Handle upload completion result from worker."""
        if success:
            self.chat_widget.add_message("System", "File uploaded successfully", is_system=True)
            # Use result if available
            if result is not None:
                self.chat_widget.add_message("System", f"Upload result: {result}", is_system=True)
        else:
            self.chat_widget.add_message("System", f"File upload failed: {error}", is_system=True)
        self.chat_widget.hide_progress()
        # Only clear worker reference if it's the same instance (prevents race condition)
        if completing_worker is not None and self.upload_worker is completing_worker:
            self.upload_worker = None
        # Schedule the worker for deletion
        if completing_worker:
            completing_worker.deleteLater()
    
    def on_download_file(self, fid: str, filename: str):
        """Handle file download request from chat."""
        print(f"[DOWNLOAD] on_download_file called: fid={fid}, filename={filename}")
        try:
            if not self.file_client:
                print("[DOWNLOAD] File client not available")
                self.chat_widget.add_message("System", "File client not initialized", is_system=True)
                return
            
            # Check if this file is available
            if not hasattr(self, 'available_files') or fid not in self.available_files:
                print(f"[DOWNLOAD] File {filename} not available")
                self.chat_widget.add_message("System", f"File {filename} is no longer available", is_system=True)
                return
            
            # Ask user where to save the file
            print(f"[DOWNLOAD] Opening save dialog for {filename}")
            from PyQt6.QtWidgets import QFileDialog
            save_path, _ = QFileDialog.getSaveFileName(
                self,
                "Save File",
                filename,
                "All Files (*)"
            )
            
            if not save_path:
                print("[DOWNLOAD] User cancelled")
                return  # User cancelled
            
            print(f"[DOWNLOAD] Save path selected: {save_path}")
            
            # Start download in background
            self.chat_widget.add_message("System", f"Preparing to download {filename}...", is_system=True)
            
            # Store the save path in pending downloads
            # The actual download will be triggered when we receive the download port
            self.file_client.pending_downloads[fid] = save_path
            
            # Send file request message to server
            message = {
                'type': MessageTypes.FILE_REQUEST,
                'fid': fid
            }
            print(f"[DOWNLOAD] Sending FILE_REQUEST message for fid={fid}")
            self.network_thread.send_message(message)
            
            self.chat_widget.add_message("System", f"Download request sent for {filename}", is_system=True)
            
        except Exception as e:
            print(f"[ERROR] Error in on_download_file: {e}")
            import traceback
            traceback.print_exc()
            try:
                self.chat_widget.add_message("System", f"Failed to start download: {e}", is_system=True)
            except:
                # If we can't even add a message, something is seriously wrong
                print("[ERROR] Cannot even add error message to chat")
    
    def _on_download_complete(self, success: bool, error: str, result, filename: str, sender=None):
        """Handle download completion."""
        if success:
            self.chat_widget.add_message("System", f"📥 Download complete: {filename}", is_system=True)
        else:
            self.chat_widget.add_message("System", f"Download failed: {error}", is_system=True)
        
        # Wait for thread to finish before scheduling deletion
        if sender:
            sender.quit()  # Signal the thread to exit
            if not sender.wait(3000):  # Wait up to 3 seconds
                print(f"[DOWNLOAD] Thread did not exit within timeout, forcing termination")
                sender.terminate()
                sender.wait(1000)  # Wait for termination to complete
            sender.deleteLater()  # Schedule for deletion
            
            # Remove from active workers list
            if sender in self.active_workers:
                self.active_workers.remove(sender)
    
    def on_send_broadcast(self, text: str):
        """Send broadcast message."""
        if not self.network_thread or not self.network_thread.writer:
            self.chat_widget.add_message("System", "Not connected to server", is_system=True)
            return
        
        message = {
            'type': MessageTypes.BROADCAST,
            'text': text
        }
        self.network_thread.send_message(message)
        # Show in chat that we're broadcasting
        self.chat_widget.add_message("You", f"[BROADCAST] {text}")
    
    def on_send_unicast(self, target_uid: int, text: str):
        """Send private (unicast) message."""
        if not self.network_thread or not self.network_thread.writer:
            self.chat_widget.add_message("System", "Not connected to server", is_system=True)
            return
        
        # If no target_uid provided, show dialog to select recipient
        if target_uid is None:
            target_uid = self.select_recipient()
            if target_uid is None:
                self.chat_widget.add_message("System", "No recipient selected", is_system=True)
                return  # User cancelled
        
        message = {
            'type': MessageTypes.UNICAST,
            'target_uid': target_uid,
            'text': text
        }
        self.network_thread.send_message(message)
        
        # Show in chat that we're sending a private message
        target_username = self.get_username_by_uid(target_uid)
        self.chat_widget.add_message("You", f"(→ {target_username}) {text}")

    def on_send_multicast(self, target_uids: object, text: str):
        """Send a message to multiple selected recipients (multicast).
        If target_uids is None, prompt the user to select multiple recipients, then
        send individual unicast messages to each selected user.
        """
        if not self.network_thread or not self.network_thread.writer:
            self.chat_widget.add_message("System", "Not connected to server", is_system=True)
            return
        
        # Select recipients if not provided
        if target_uids is None:
            target_uids = self.select_multiple_recipients()
            if not target_uids:
                self.chat_widget.add_message("System", "No recipients selected", is_system=True)
                return
        
        # Send as multiple unicasts for compatibility with existing server
        for uid in target_uids:
            message = {
                'type': MessageTypes.UNICAST,
                'target_uid': uid,
                'text': text
            }
            self.network_thread.send_message(message)
            target_username = self.get_username_by_uid(uid)
            self.chat_widget.add_message("You", f"(→ {target_username}) {text}")
    
    def select_recipient(self) -> Optional[int]:
        """Show dialog to select message recipient."""
        # Build list of recipients (exclude self)
        recipients = []
        for uid, participant in self.participants.items():
            if uid != self.uid:
                username = participant.get('username', f'User {uid}')
                recipients.append(f"{uid} - {username}")
        
        if not recipients:
            QMessageBox.warning(self, "No Recipients", "No other participants available")
            return None
        
        item, ok = QInputDialog.getItem(
            self, 
            "Select Recipient", 
            "Choose who to send a private message to:",
            recipients,
            0, 
            False
        )
        
        if ok and item:
            # Extract UID from selection
            uid_str = item.split(' - ')[0]
            return int(uid_str)
        
        return None

    def select_multiple_recipients(self) -> Optional[List[int]]:
        """Show dialog to select multiple recipients for multicast."""
        # Build list of recipients (exclude self)
        choices = []
        uid_map = []
        for uid, participant in self.participants.items():
            if uid != self.uid:
                username = participant.get('username', f'User {uid}')
                choices.append(f"{uid} - {username}")
                uid_map.append(uid)
        
        if not choices:
            QMessageBox.warning(self, "No Recipients", "No other participants available")
            return None
        
        # Use a simple multi-select dialog using QInputDialog in a loop-like fashion
        # For better UX we'd build a custom QDialog with a QListWidget in multi-selection mode.
        dialog = QDialog(self)
        dialog.setWindowTitle("Select Recipients")
        from PyQt6.QtWidgets import QVBoxLayout, QListWidget, QPushButton
        layout = QVBoxLayout(dialog)
        list_widget = QListWidget(dialog)
        list_widget.addItems(choices)
        list_widget.setSelectionMode(QListWidget.SelectionMode.MultiSelection)
        layout.addWidget(list_widget)
        ok_btn = QPushButton("OK", dialog)
        ok_btn.clicked.connect(dialog.accept)
        layout.addWidget(ok_btn)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return None
        
        selected = list_widget.selectedIndexes()
        if not selected:
            return None
        
        selected_uids = []
        for index in selected:
            if 0 <= index.row() < len(uid_map):
                selected_uids.append(uid_map[index.row()])
        return selected_uids
    
    def get_username_by_uid(self, uid: int) -> str:
        """Get username by UID."""
        participant = self.participants.get(uid, {})
        return participant.get('username', f'User {uid}')
    
    def handle_file_download_port(self, message: dict):
        """Handle file download port message from server."""
        fid = message.get('fid')
        filename = message.get('filename')
        size = message.get('size')
        port = message.get('port')
        
        # Get the save path from pending downloads
        save_path = self.file_client.pending_downloads.get(fid) if self.file_client else None
        
        if not save_path:
            self.chat_widget.add_message("System", f"No save path found for {filename}", is_system=True)
            return
        
        # Start download in background using worker
        try:
            # Create download worker
            worker = AsyncTaskWorker(
                self.file_client.do_file_download,
                fid,
                filename,
                size,
                port,
                save_path
            )
            # Track worker for cleanup
            self.active_workers.append(worker)
            # Connect with sender so we can clean it up
            worker.task_done.connect(lambda success, error, result: self._on_download_complete(success, error, result, filename, worker))
            worker.start()
            
            # Remove from pending after starting download (not before)
            if fid in self.file_client.pending_downloads:
                del self.file_client.pending_downloads[fid]
        except Exception as e:
            self.chat_widget.add_message("System", f"Failed to start download: {e}", is_system=True)
            import traceback
            traceback.print_exc()
    
    def handle_unicast_message(self, message: dict):
        """Handle incoming unicast (private) message."""
        from_uid = message.get('from_uid')
        from_username = message.get('from_username', 'unknown')
        text = message.get('text', '')
        
        # Display as private message
        self.chat_widget.add_message(
            f"[PRIVATE] {from_username}", 
            text
        )
    
    def on_participant_mute_clicked(self, uid: int):
        """Handle participant mute button click."""
        # Toggle the mute state in the UI
        participant_item = self.participant_panel.participants.get(uid)
        if participant_item:
            participant_item.toggle_mute()
            
            # Perform actual mute logic with audio client
            if self.audio_client:
                if participant_item.is_muted:
                    self.audio_client.mute_participant(uid)
                    self.chat_widget.add_message("System", f"Muted user {uid}", is_system=True)
                else:
                    self.audio_client.unmute_participant(uid)
                    self.chat_widget.add_message("System", f"Unmuted user {uid}", is_system=True)
            else:
                if participant_item.is_muted:
                    self.chat_widget.add_message("System", f"Muted user {uid} (audio client not available)", is_system=True)
                else:
                    self.chat_widget.add_message("System", f"Unmuted user {uid} (audio client not available)", is_system=True)
    
    def on_toggle_audio(self):
        """Toggle audio streaming."""
        if not self.audio_client:
            self.chat_widget.add_message("System", "Audio client not initialized", is_system=True)
            return
        
        is_muted = "Unmute" in self.participant_panel.audio_btn.text()
        
        if is_muted:
            # Unmute (start) audio
            try:
                self.audio_client.start_recording()
                self.participant_panel.audio_btn.setText("🎤 Mute Audio")
                self.chat_widget.add_message("System", "Audio unmuted", is_system=True)
            except Exception as e:
                self.chat_widget.add_message("System", f"Failed to start audio: {e}", is_system=True)
        else:
            # Mute (stop) audio
            try:
                self.audio_client.stop_recording()
                self.participant_panel.audio_btn.setText("🎤 Unmute Audio")
                self.chat_widget.add_message("System", "Audio muted", is_system=True)
            except Exception as e:
                self.chat_widget.add_message("System", f"Failed to stop audio: {e}", is_system=True)
    
    def on_toggle_video(self):
        """Toggle video streaming."""
        if not self.video_client:
            self.chat_widget.add_message("System", "Video client not initialized", is_system=True)
            return
        
        is_streaming = "Stop" in self.participant_panel.video_btn.text()
        
        if is_streaming:
            # Stop video
            try:
                self.video_client.stop_streaming()
                self.participant_panel.video_btn.setText("📹 Start Video")
                self.chat_widget.add_message("System", "Video stopped", is_system=True)
                # Stop local video capture timer
                if hasattr(self, 'local_video_timer'):
                    self.local_video_timer.stop()
                    self.local_video_timer.deleteLater()
                    self.local_video_timer = None
                # Clear any queued local frames so the tile resets immediately
                try:
                    with self.frame_lock:
                        if hasattr(self, 'pending_frames') and self.uid in self.pending_frames:
                            del self.pending_frames[self.uid]
                        # Stop the GUI update timer if nothing to process
                        if hasattr(self, 'video_update_timer') and not self.pending_frames:
                            self.video_update_timer.stop()
                except Exception:
                    pass
                # Reset our own tile back to placeholder state
                if self.uid is not None:
                    self.video_grid.reset_feed(self.uid)
            except Exception as e:
                print(f"[GUI] Error stopping video: {e}")
                import traceback
                traceback.print_exc()
                self.chat_widget.add_message("System", f"Failed to stop video: {e}", is_system=True)
        else:
            # Start video
            try:
                self.video_client.start_streaming()
                self.participant_panel.video_btn.setText("📹 Stop Video")
                self.chat_widget.add_message("System", "Video started", is_system=True)
                # Start local video capture for GUI display
                self._start_local_video_display()
            except Exception as e:
                print(f"[GUI] Error starting video: {e}")
                import traceback
                traceback.print_exc()
                self.chat_widget.add_message("System", f"Failed to start video: {e}", is_system=True)
    
    def on_toggle_screen_share(self):
        """Toggle screen sharing."""
        if not self.screen_presenter:
            self.chat_widget.add_message("System", "Screen presenter not initialized", is_system=True)
            return
        
        is_sharing = "Stop" in self.participant_panel.share_btn.text()
        
        if is_sharing:
            # Stop screen share
            try:
                if self.network_thread and self.network_thread.loop:
                    future = asyncio.run_coroutine_threadsafe(self.screen_presenter.stop_presentation(), self.network_thread.loop)
                    result = future.result(timeout=5)
                    if result:
                        self._on_screen_share_stopped()
                    else:
                        self._on_screen_share_stopped("Failed to stop screen share")
                else:
                    self._on_screen_share_stopped("Network thread not available")
            except Exception as e:
                self._on_screen_share_stopped(str(e))
        else:
            # Start screen share
            try:
                if self.network_thread and self.network_thread.loop:
                    future = asyncio.run_coroutine_threadsafe(self.screen_presenter.start_presentation(), self.network_thread.loop)
                    result = future.result(timeout=5)
                    if result:
                        self._on_screen_share_started()
                    else:
                        self._on_screen_share_started("Failed to start screen share")
                else:
                    self._on_screen_share_started("Network thread not available")
            except Exception as e:
                self._on_screen_share_started(str(e))
            finally:
                self.screen_share_start_worker = None
    
    def _on_screen_share_started_with_result(self, success: bool, error: str, result, completing_worker=None):
        """Handle screen share started result from worker."""
        self._on_screen_share_started(error if not success else None)
        # Only clear worker reference if it's the same instance (prevents race condition)
        if completing_worker is not None and self.screen_share_start_worker is completing_worker:
            self.screen_share_start_worker = None
        # Schedule the worker for deletion
        if completing_worker:
            completing_worker.deleteLater()
    
    def _on_screen_share_stopped_with_result(self, success: bool, error: str, result, completing_worker=None):
        """Handle screen share stopped result from worker."""
        self._on_screen_share_stopped(error if not success else None)
        # Only clear worker reference if it's the same instance (prevents race condition)
        if completing_worker is not None and self.screen_share_stop_worker is completing_worker:
            self.screen_share_stop_worker = None
        # Schedule the worker for deletion
        if completing_worker:
            completing_worker.deleteLater()
    
    def _on_screen_share_started(self, error: str = None):
        """Handle screen share started."""
        if error:
            self.chat_widget.add_message("System", f"Failed to start screen share: {error}", is_system=True)
        else:
            self.participant_panel.share_btn.setText("🖥️ Stop Screen Share")
            self.chat_widget.add_message("System", "Screen share started", is_system=True)
    
    def _on_screen_share_stopped(self, error: str = None):
        """Handle screen share stopped."""
        if error:
            self.chat_widget.add_message("System", f"Failed to stop screen share: {error}", is_system=True)
        else:
            self.participant_panel.share_btn.setText("🖥️ Start Screen Share")
            self.chat_widget.add_message("System", "Screen share stopped", is_system=True)
    
    def handle_present_start_broadcast(self, message: dict):
        """Handle present start broadcast from another user."""
        uid = message.get('uid')
        username = message.get('username')
        topic = message.get('topic', 'Screen Share')
        viewer_port = message.get('viewer_port')
        
        # Don't show notification for our own presentation
        if uid == self.uid:
            return
        
        self.chat_widget.add_message("System", f"🎬 {username} started screen sharing: {topic}", is_system=True)
        
        # Store presentation info for potential viewing
        if not hasattr(self, 'active_presentations'):
            self.active_presentations = {}
        
        self.active_presentations[uid] = {
            'username': username,
            'topic': topic,
            'viewer_port': viewer_port,
            'uid': uid
        }
        
        # Show dialog to ask if user wants to watch
        reply = QMessageBox.question(
            self,
            'Screen Share Available',
            f'{username} is sharing their screen.\n\nWould you like to watch?',
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes
        )
        
        if reply == QMessageBox.StandardButton.Yes:
            self._watch_screen_share(uid, viewer_port, username)
    
    def _watch_screen_share(self, uid: int, viewer_port: int, username: str):
        """Start watching a screen share."""
        try:
            if not self.screen_viewer:
                self.chat_widget.add_message("System", "Screen viewer not initialized", is_system=True)
                return
            
            self.chat_widget.add_message("System", f"Opening {username}'s screen...", is_system=True)
            
            # Import here to avoid circular imports
            from PyQt6.QtWidgets import QApplication
            from client.screen.screen_viewer import ScreenViewerWindow, SCREEN_SHARE_AVAILABLE
            
            # Create the viewer window in the GUI thread
            if not SCREEN_SHARE_AVAILABLE:
                self.chat_widget.add_message("System", "Screen sharing not available", is_system=True)
                return
            
            # Get or create QApplication instance
            app = QApplication.instance()
            if not app:
                app = QApplication(sys.argv)
            
            # Set the app instance for the viewer
            self.screen_viewer.viewer_app = app
            
            # Create viewer window (must be done in GUI thread)
            self.screen_viewer.viewer_window = ScreenViewerWindow(username)
            self.screen_viewer.viewer_window.show()
            
            # Start receiving frames in a worker thread (network operations only)
            worker = AsyncTaskWorker(
                self.screen_viewer._receive_and_display_frames,
                viewer_port,
                username
            )
            worker.task_done.connect(
                lambda success, error, result: self._on_screen_view_complete(success, error, result, username, worker)
            )
            worker.start()
            
        except Exception as e:
            self.chat_widget.add_message("System", f"Failed to start screen viewing: {e}", is_system=True)
            import traceback
            traceback.print_exc()
    
    def _on_screen_view_complete(self, success: bool, error: str, result, username: str, sender=None):
        """Handle screen view completion."""
        if success:
            self.chat_widget.add_message("System", f"Viewing {username}'s screen", is_system=True)
        else:
            self.chat_widget.add_message("System", f"Failed to view {username}'s screen: {error}", is_system=True)
        # Schedule the sender thread for deletion
        if sender:
            sender.deleteLater()
    
    def handle_present_stop_broadcast(self, message: dict):
        """Handle present stop broadcast from another user."""
        uid = message.get('uid')
        username = message.get('username')
        
        # Don't show notification for our own presentation
        if uid == self.uid:
            return
        
        self.chat_widget.add_message("System", f"{username} stopped screen sharing", is_system=True)
        
        # Remove from active presentations
        if hasattr(self, 'active_presentations') and uid in self.active_presentations:
            del self.active_presentations[uid]
    
    def _start_local_video_display(self):
        """Start displaying local webcam feed in GUI."""
        if not HAS_OPENCV or not self.video_client:
            return
        
        # Create timer to capture and display local video
        self.local_video_timer = QTimer()
        self.local_video_timer.timeout.connect(self._update_local_video)
        self.local_video_timer.start(100)  # ~10 FPS for local display (to reduce CPU load)
        print("[GUI] Started local video display timer")
    
    def _update_local_video(self):
        """Update local video feed in GUI."""
        try:
            if not self.video_client or not self.video_client.cap or not self.video_client.is_streaming:
                # Stop timer if video client is not available
                if hasattr(self, 'local_video_timer'):
                    self.local_video_timer.stop()
                    self.local_video_timer.deleteLater()
                    self.local_video_timer = None
                return
            
            # Capture frame from webcam
            ret, frame = self.video_client.cap.read()
            if not ret:
                return
            
            # Resize to match video client settings
            frame = cv2.resize(frame, (self.video_client.width, self.video_client.height))
            
            # Display in GUI (use own UID) - add to pending frames
            if self.uid:
                # Use thread-safe method to add frame
                with self.frame_lock:
                    self.pending_frames[self.uid] = frame
                
                # Ensure timer is running
                if not self.video_update_timer.isActive():
                    self.video_update_timer.start(16)
        
        except Exception as e:
            print(f"[GUI] Error updating local video: {e}")
            import traceback
            traceback.print_exc()
    
    # ========================================================================
    # CLEANUP
    # ========================================================================
    
    def closeEvent(self, event):
        """Handle window close event."""
        # Stop heartbeat timer
        if hasattr(self, 'heartbeat_timer'):
            self.heartbeat_timer.stop()
        
        # Stop video update timer
        if hasattr(self, 'video_update_timer'):
            self.video_update_timer.stop()
        
        # Clean up all active workers
        for worker in self.active_workers[:]:  # Copy list to avoid modification during iteration
            worker.quit()
            if not worker.wait(2000):  # Wait up to 2 seconds
                print(f"[CLEANUP] Worker did not exit, forcing termination")
                worker.terminate()
                worker.wait(1000)
            worker.deleteLater()
        
        # Stop video receiver
        self.stop_video_receiver()
        
        # Clean up audio/video clients
        if self.audio_client:
            try:
                self.audio_client.cleanup()
            except Exception as e:
                print(f"[CLEANUP] Error cleaning up audio client: {e}")
        if self.video_client:
            try:
                self.video_client.cleanup()
            except Exception as e:
                print(f"[CLEANUP] Error cleaning up video client: {e}")
        
        # Stop network thread
        if self.network_thread:
            self.network_thread.stop()
            self.network_thread.wait()
        
        event.accept()


# ============================================================================
# VIDEO RECEIVER THREAD (for remote feeds via UDP)
# ============================================================================

class VideoReceiverThread(QThread):
    """Thread for receiving video frames via UDP and displaying them."""
    
    frame_received = pyqtSignal(int, object)  # uid, frame
    
    def __init__(self, server_ip: str, server_port: int = 10001):
        super().__init__()
        self.server_ip = server_ip
        self.server_port = server_port  # Port to receive video broadcasts
        self.socket = None
        self.running = False
    
    def run(self):
        """Run the video receiver loop."""
        if not HAS_OPENCV:
            print("[VIDEO RECEIVER] OpenCV not available")
            return
        
        try:
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            # Try to bind to the specified port
            try:
                self.socket.bind(('', self.server_port))
                print(f"[VIDEO RECEIVER] Listening on port {self.server_port}")
            except OSError as e:
                # If binding fails, use an ephemeral port instead
                self.socket.bind(('', 0))  # Let OS choose port
                actual_port = self.socket.getsockname()[1]
                print(f"[VIDEO RECEIVER] Could not bind to port {self.server_port}, using ephemeral port {actual_port}")
            self.socket.settimeout(1.0)
            self.running = True
            
            while self.running:
                try:
                    data, addr = self.socket.recvfrom(65536)
                    self._process_frame(data, addr)
                except socket.timeout:
                    continue
                except Exception as e:
                    if self.running:
                        print(f"[VIDEO RECEIVER] Error: {e}")
        finally:
            self.cleanup()
    
    def _process_frame(self, frame_data: bytes, addr: Tuple[str, int]):
        """Process received frame data."""
        try:
            # Parse broadcast header if present: uid (4 bytes) + timestamp (8 bytes) = 12 bytes
            if len(frame_data) < 12:
                # No header, treat entire data as frame
                uid = hash(addr) % 0xFFFFFFFF
                frame_only = frame_data
            else:
                # Parse the 12-byte broadcast header: uid (4 bytes) + timestamp (8 bytes)
                header = frame_data[:12]
                frame_only = frame_data[12:]
                try:
                    uid, timestamp = struct.unpack('>I Q', header)
                except struct.error as e:
                    print(f"[VIDEO RECEIVER] Error parsing header: {e}")
                    # Fallback: hash the address
                    uid = hash(addr) % 0xFFFFFFFF
            
            # Decode JPEG frame
            nparr = np.frombuffer(frame_only, np.uint8)
            frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
            
            if frame is not None:
                self.frame_received.emit(uid, frame)
                print(f"[VIDEO RECEIVER] Successfully decoded and displaying frame from uid={uid}")
        
        except Exception as e:
            print(f"[VIDEO RECEIVER] Frame processing error: {e}")
            import traceback
            traceback.print_exc()
    
    def stop(self):
        """Stop the receiver."""
        self.running = False
    
    def cleanup(self):
        """Clean up resources."""
        if self.socket:
            self.socket.close()
            self.socket = None


# ============================================================================
# ASYNC TASK WORKER
# ============================================================================

class AsyncTaskWorker(QThread):
    """Worker thread for running async tasks."""
    
    task_done = pyqtSignal(bool, str, object)  # success, error, result
    
    def __init__(self, async_func, *args, **kwargs):
        super().__init__()
        self.async_func = async_func
        self.args = args
        self.kwargs = kwargs
    
    def run(self):
        """Run the async task in this thread's event loop."""
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        try:
            result = loop.run_until_complete(self.async_func(*self.args, **self.kwargs))
            self.task_done.emit(True, None, result)
        except Exception as e:
            self.task_done.emit(False, str(e), None)
        finally:
            # Clean up all tasks before closing the loop
            try:
                # Cancel all remaining tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                
                # Wait for all tasks to be cancelled
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            except Exception as e:
                print(f"[WORKER] Error cleaning up tasks: {e}")
            finally:
                loop.close()


# ============================================================================
# NETWORK THREAD
# ============================================================================

class NetworkThread(QThread):
    """Thread for handling network communication."""
    
    message_received = pyqtSignal(dict)
    connected = pyqtSignal()
    disconnected = pyqtSignal()
    
    def __init__(self, host: str, port: int, username: str):
        super().__init__()
        self.host = host
        self.port = port
        self.username = username
        self.writer = None
        self.reader = None
        self.running = False
        self.loop = None
        self.loop_ready = threading.Event()
    
    def run(self):
        """Run network loop."""
        self.loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self.loop)
        self.loop_ready.set()
        self.loop.run_until_complete(self._connect_and_listen())
    
    async def _connect_and_listen(self):
        """Connect to server and listen for messages."""
        try:
            print(f"[NETWORK] Attempting to connect to {self.host}:{self.port}...")
            
            # Add connection timeout
            self.reader, self.writer = await asyncio.wait_for(
                asyncio.open_connection(self.host, self.port),
                timeout=10.0
            )
            
            print(f"[NETWORK] Successfully connected to {self.host}:{self.port}")
            self.connected.emit()
            self.running = True
            
            # Send login
            login_msg = create_login_message(self.username)
            await self.send_message_async(login_msg)
            print(f"[NETWORK] Login message sent for user: {self.username}")
            
            # Listen for messages
            while self.running:
                data = await self.reader.readline()
                if not data:
                    print("[NETWORK] Received empty data, connection closed by server")
                    break
                
                try:
                    message = json.loads(data.decode('utf-8').strip())
                    self.message_received.emit(message)
                except json.JSONDecodeError:
                    pass
        
        except asyncio.TimeoutError:
            print(f"[NETWORK] Connection timeout: Could not connect to {self.host}:{self.port} within 10 seconds")
            print(f"[NETWORK] Make sure:")
            print(f"  1. Server is running on {self.host}:{self.port}")
            print(f"  2. Server IP address is correct (not 'localhost' if connecting from another computer)")
            print(f"  3. Firewall allows connections on port {self.port}")
        except ConnectionRefusedError:
            print(f"[NETWORK] Connection refused: Server at {self.host}:{self.port} is not accepting connections")
            print(f"[NETWORK] Make sure the server is running and listening on the correct IP/port")
        except OSError as e:
            print(f"[NETWORK] Network error: {e}")
            print(f"[NETWORK] Check that you can reach {self.host}:{self.port}")
        except Exception as e:
            print(f"[NETWORK] Unexpected error: {e}")
            import traceback
            traceback.print_exc()
        finally:
            self.disconnected.emit()
            print("[NETWORK] Disconnected from server")
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
    
    async def send_message_async(self, message: dict):
        """Send message asynchronously."""
        if not self.writer:
            return
        
        try:
            msg_data = json.dumps(message).encode('utf-8') + b'\n'
            self.writer.write(msg_data)
            await self.writer.drain()
        except Exception as e:
            print(f"[NETWORK] Send error: {e}")
    
    def send_message(self, message: dict):
        """Send message from main thread."""
        # Wait for event loop to be ready before sending
        if not self.loop_ready.wait(timeout=5.0):
            print("[NETWORK] Warning: Event loop not ready, message may not be sent")
            return
        
        if self.loop:
            asyncio.run_coroutine_threadsafe(self.send_message_async(message), self.loop)
    
    def stop(self):
        """Stop network thread."""
        self.running = False


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

def main():
    """Main entry point."""
    app = QApplication(sys.argv)
    
    # Get server IP from environment or use default
    server_host = os.environ.get('SERVER_IP', 'localhost')
    server_port = int(os.environ.get('SERVER_PORT', '9000'))
    
    # Create and show window
    window = ClientMainWindow(server_host, server_port)
    window.show()
    
    # Connect to server
    if not window.connect_to_server():
        sys.exit(1)
    
    # Run application
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
