"""
Screen viewer module.

This module handles client-side screen viewing functionality.
"""

import asyncio
import struct
import sys
from typing import Optional, Callable

# Optional screen sharing imports
# Try PyQt6 first (project standard), fallback to PyQt5
HAS_PYQT6 = False
HAS_PYQT5 = False

try:
    from PIL import Image as PILImage
    from io import BytesIO
except ImportError:
    PILImage = None

# Try PyQt6 first
try:
    from PyQt6.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
    from PyQt6.QtCore import Qt, QObject, pyqtSignal
    from PyQt6.QtGui import QPixmap, QImage
    HAS_PYQT6 = True
except ImportError:
    try:
        from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
        from PyQt5.QtCore import Qt, pyqtSignal, QObject
        from PyQt5.QtGui import QPixmap, QImage
        HAS_PYQT5 = True
        print("[WARNING] PyQt6 not available, using PyQt5 fallback for screen viewer.")
    except ImportError:
        print("[WARNING] PyQt not installed. Screen sharing requires PyQt6 or PyQt5.")
        print("Install with: pip install PyQt6 (recommended) or pip install PyQt5")

# Determine if screen sharing is fully available (needs both PIL and PyQt)
SCREEN_SHARE_AVAILABLE = (PILImage is not None) and (HAS_PYQT6 or HAS_PYQT5)

from common.constants import MessageTypes


if HAS_PYQT6 or HAS_PYQT5:
    # Only define GUI classes if PyQt is available
    class FrameUpdateSignal(QObject):
        """Signal handler for thread-safe frame updates."""
        frame_data = pyqtSignal(bytes)
        connection_closed = pyqtSignal()
    
    class ScreenViewerWindow(QMainWindow):
        """Qt window for displaying screen share - integrated into client."""
        
        def __init__(self, presenter_name: str = "Presenter"):
            super().__init__()
            self.presenter_name = presenter_name
            self.signal_handler = FrameUpdateSignal(parent=self)
            self.signal_handler.frame_data.connect(self.display_frame)
            self.signal_handler.connection_closed.connect(self.on_connection_closed)
            self.init_ui()
        
        def init_ui(self):
            """Initialize the user interface."""
            self.setWindowTitle(f"Screen Share - {self.presenter_name}")
            self.setGeometry(100, 100, 1024, 768)
            
            # Create central widget
            central_widget = QWidget()
            self.setCentralWidget(central_widget)
            
            # Create layout
            layout = QVBoxLayout()
            central_widget.setLayout(layout)
            
            # Create label for displaying frames
            self.image_label = QLabel()
            # PyQt6 uses Alignment enum, PyQt5 uses constant
            if HAS_PYQT6:
                self.image_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            else:
                self.image_label.setAlignment(Qt.AlignCenter)
            self.image_label.setStyleSheet("background-color: black; color: white;")
            self.image_label.setText(f"Connecting to {self.presenter_name}'s screen...")
            self.image_label.setScaledContents(False)
            
            layout.addWidget(self.image_label)
            
            # Status bar
            self.statusBar().showMessage("Initializing...")
            self.frame_count = 0
        
        def display_frame(self, frame_data: bytes):
            """Display a received frame."""
            try:
                # Load JPEG from bytes
                img = PILImage.open(BytesIO(frame_data))
                
                # Convert PIL Image to QPixmap
                img_rgb = img.convert('RGB')
                data = img_rgb.tobytes('raw', 'RGB')
                # PyQt6 uses Format enum, PyQt5 uses constant
                if HAS_PYQT6:
                    qimage = QImage(data, img.width, img.height, QImage.Format.Format_RGB888)
                else:
                    qimage = QImage(data, img.width, img.height, QImage.Format_RGB888)
                pixmap = QPixmap.fromImage(qimage)
                
                # Scale to fit window while maintaining aspect ratio
                if HAS_PYQT6:
                    scaled_pixmap = pixmap.scaled(
                        self.image_label.size(),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation
                    )
                else:
                    scaled_pixmap = pixmap.scaled(
                        self.image_label.size(),
                        Qt.KeepAspectRatio,
                        Qt.SmoothTransformation
                    )
                
                self.image_label.setPixmap(scaled_pixmap)
                self.frame_count += 1
                self.statusBar().showMessage(
                    f"Viewing {self.presenter_name}'s screen | "
                    f"Resolution: {img.width}x{img.height} | "
                    f"Frames: {self.frame_count}"
                )
            
            except Exception as e:
                print(f"[VIEWER] Error displaying frame: {e}")
        
        def on_connection_closed(self):
            """Handle connection closure."""
            self.image_label.setText(
                f"{self.presenter_name} stopped sharing.\n\n"
                "Close this window."
            )
            self.statusBar().showMessage("Presentation ended")
else:
    # Stub class to prevent import-time NameError
    class ScreenViewerWindow:
        """Stub class when PyQt is not available."""
        pass


class ScreenViewer:
    """Client-side screen viewing functionality."""
    
    def __init__(self, writer: Optional[asyncio.StreamWriter] = None):
        self.writer = writer
        self.host = 'localhost'
        self.viewer_window = None
        self.viewer_task = None
        self.viewer_app = None
        self.current_presentation = None  # {username, viewer_port}
        self.message_handler: Optional[Callable] = None
    
    def set_writer(self, writer: asyncio.StreamWriter):
        """Set the writer for sending messages."""
        self.writer = writer
    
    def set_host(self, host: str):
        """Set the server host for screen viewing."""
        self.host = host
    
    def set_message_handler(self, handler: Callable):
        """Set the message handler for incoming messages."""
        self.message_handler = handler
    
    async def view_presentation(self, viewer_port: int, presenter_name: str) -> bool:
        """Start viewing a presentation."""
        if not SCREEN_SHARE_AVAILABLE:
            print("[ERROR] Screen sharing not available. Install: pip install PyQt6 (or pip install PyQt5)")
            return False        
        
        print(f"[VIEW] Opening {presenter_name}'s screen...")
        
        # Don't create a new QApplication - use the existing one
        # Get the existing application instance
        if not self.viewer_app:
            self.viewer_app = QApplication.instance()
            if not self.viewer_app:
                # Fallback: create a new application (shouldn't happen in GUI)
                self.viewer_app = QApplication(sys.argv)
        
        # Create viewer window
        self.viewer_window = ScreenViewerWindow(presenter_name)
        self.viewer_window.show()
        
        # Start receiving frames
        self.viewer_task = asyncio.create_task(
            self._receive_and_display_frames(viewer_port, presenter_name)
        )
        
        return True
    
    async def _receive_and_display_frames(self, viewer_port: int, presenter_name: str):
        """Receive frames from server and display in Qt window."""
        try:
            # Connect to viewer port
            reader, writer = await asyncio.open_connection(self.host, viewer_port)
            print(f"[VIEWER] Connected to viewer port {viewer_port}")
            
            frame_count = 0
            
            while self.viewer_window and self.viewer_window.isVisible():
                try:
                    # Read 4-byte frame length header
                    length_data = await reader.readexactly(4)
                    frame_length = struct.unpack('!I', length_data)[0]
                    
                    # Read frame data
                    frame_data = await reader.readexactly(frame_length)
                    
                    frame_count += 1
                    
                    # Emit signal for thread-safe frame update
                    if self.viewer_window and self.viewer_window.signal_handler:
                        self.viewer_window.signal_handler.frame_data.emit(frame_data)
                    
                    # Log every 30 frames
                    if frame_count % 30 == 0:
                        frame_size_kb = len(frame_data) / 1024
                        print(f"[VIEWER] Frames received: {frame_count}, "
                              f"Last frame: {frame_size_kb:.1f} KB")
                    
                    # Small delay for UI responsiveness
                    await asyncio.sleep(0.01)
                
                except asyncio.IncompleteReadError:
                    print("[VIEWER] Connection closed by server")
                    break
                except Exception as e:
                    print(f"[VIEWER] Error receiving frame: {e}")
                    break
            
            # Close connection
            writer.close()
            await writer.wait_closed()
            
            # Emit signal for thread-safe connection closed handling
            if self.viewer_window and self.viewer_window.signal_handler:
                self.viewer_window.signal_handler.connection_closed.emit()
            
            print(f"[VIEWER] Connection closed. Total frames: {frame_count}")
        
        except Exception as e:
            print(f"[VIEWER] Failed to connect or display: {e}")
    
    async def handle_message(self, message: dict):
        """Handle different types of screen sharing messages from server."""
        msg_type = message.get('type', '')
        
        if msg_type == MessageTypes.PRESENT_START_BROADCAST:
            await self._handle_present_start(message)
        elif msg_type == MessageTypes.PRESENT_STOP_BROADCAST:
            await self._handle_present_stop(message)
    
    async def _handle_present_start(self, message: dict):
        """Handle present start broadcast."""
        uid = message.get('uid')
        username = message.get('username')
        topic = message.get('topic')
        viewer_port = message.get('viewer_port')
        
        if hasattr(self, 'uid') and uid != self.uid:
            print(f"[PRESENT] 🎬 {username} started presentation: {topic}")
            print(f"[PRESENT] Type '/view' to watch")
            # Store current presentation info
            self.current_presentation = {
                'username': username,
                'viewer_port': viewer_port,
                'topic': topic
            }
    
    async def _handle_present_stop(self, message: dict):
        """Handle present stop broadcast."""
        uid = message.get('uid')
        username = message.get('username')
        print(f"[PRESENT] {username} stopped presentation")
        self.current_presentation = None
    
    def get_current_presentation(self):
        """Get current presentation info."""
        return self.current_presentation
    
    def set_uid(self, uid: int):
        """Set the client's UID for message filtering."""
        self.uid = uid
