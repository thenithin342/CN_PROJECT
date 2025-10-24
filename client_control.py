#!/usr/bin/env python3
"""
LAN Multi-User Collaboration Client
Connects to server on TCP port 9000 and handles control messages.
"""

import asyncio
import json
import sys
import uuid
import os
from datetime import datetime
from pathlib import Path

# Optional screen sharing imports
try:
    import mss as mss_module
    from PIL import Image as PILImage
    from io import BytesIO
    import struct
    import time
    from PyQt5.QtWidgets import QApplication, QMainWindow, QLabel, QVBoxLayout, QWidget
    from PyQt5.QtCore import Qt, pyqtSignal, QObject
    from PyQt5.QtGui import QPixmap, QImage
    SCREEN_SHARE_AVAILABLE = True
except ImportError:
    SCREEN_SHARE_AVAILABLE = False
    mss_module = None
    PILImage = None


class ScreenViewerWindow(QMainWindow):
    """Qt window for displaying screen share - integrated into client."""
    
    def __init__(self, presenter_name: str = "Presenter"):
        super().__init__()
        self.presenter_name = presenter_name
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
            qimage = QImage(data, img.width, img.height, QImage.Format_RGB888)
            pixmap = QPixmap.fromImage(qimage)
            
            # Scale to fit window while maintaining aspect ratio
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


class CollaborationClient:
    def __init__(self, host: str = 'localhost', port: int = 9000, username: str = None):
        self.host = host
        self.port = port
        self.username = username or f"user_{id(self) % 10000}"
        self.reader = None
        self.writer = None
        self.running = False
        self.uid = None
        self.pending_uploads = {}  # fid -> file_path
        self.pending_downloads = {}  # fid -> save_path
        
        # Screen sharing state
        self.presenting = False
        self.presenter_writer = None
        self.presenter_reader = None
        self.presenter_task = None
        self.presenter_fps = 3
        self.presenter_quality = 70
        self.presenter_scale = 0.5
        self.viewer_window = None
        self.viewer_task = None
        self.viewer_app = None
        self.current_presentation = None  # {username, viewer_port}

    async def connect(self):
        """Establish connection to the server."""
        try:
            self.reader, self.writer = await asyncio.open_connection(self.host, self.port)
            print(f"[INFO] Connected to {self.host}:{self.port}")
            self.running = True
            return True
        except Exception as e:
            print(f"[ERROR] Failed to connect: {e}")
            return False

    async def send_message(self, message: dict):
        """Send a JSON message to the server."""
        if not self.writer:
            print("[ERROR] Not connected to server")
            return False
        
        try:
            msg_data = json.dumps(message).encode('utf-8') + b'\n'
            self.writer.write(msg_data)
            await self.writer.drain()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
            self.running = False
            return False

    async def send_login(self):
        """Send login message to server."""
        login_msg = {
            "type": "login",
            "username": self.username
        }
        print(f"[INFO] Logging in as '{self.username}'...")
        await self.send_message(login_msg)

    async def send_heartbeat(self):
        """Send periodic heartbeat messages."""
        while self.running:
            await asyncio.sleep(10)
            if self.running:
                heartbeat_msg = {
                    "type": "heartbeat",
                    "timestamp": datetime.now().isoformat()
                }
                await self.send_message(heartbeat_msg)

    async def send_logout(self):
        """Send logout message to server."""
        logout_msg = {
            "type": "logout"
        }
        print("[INFO] Sending logout...")
        await self.send_message(logout_msg)

    async def send_chat(self, message: str):
        """Send a chat message."""
        chat_msg = {
            "type": "chat",
            "text": message
        }
        await self.send_message(chat_msg)

    async def send_broadcast(self, message: str):
        """Send a broadcast message to all users."""
        broadcast_msg = {
            "type": "broadcast",
            "text": message
        }
        await self.send_message(broadcast_msg)

    async def send_unicast(self, target_uid: int, message: str):
        """Send a private message to a specific user."""
        unicast_msg = {
            "type": "unicast",
            "target_uid": target_uid,
            "text": message
        }
        await self.send_message(unicast_msg)

    async def request_history(self):
        """Request chat history from server."""
        history_msg = {
            "type": "get_history"
        }
        await self.send_message(history_msg)

    async def upload_file(self, file_path: str):
        """Upload a file to the server."""
        path = Path(file_path)
        
        if not path.exists():
            print(f"[ERROR] File not found: {file_path}")
            return False
        
        if not path.is_file():
            print(f"[ERROR] Not a file: {file_path}")
            return False
        
        # Generate unique file ID
        fid = str(uuid.uuid4())
        filename = path.name
        size = path.stat().st_size
        
        print(f"[UPLOAD] Offering file: {filename} ({size} bytes, fid={fid})")
        
        # Store pending upload
        self.pending_uploads[fid] = str(path.absolute())
        
        # Send file offer
        offer_msg = {
            "type": "file_offer",
            "fid": fid,
            "filename": filename,
            "size": size
        }
        await self.send_message(offer_msg)
        
        # Wait for upload port response
        # This will be handled by the message handler
        return fid
    
    async def do_file_upload(self, fid: str, file_path: str, upload_port: int):
        """Perform the actual file upload to the given port."""
        path = Path(file_path)
        
        if not path.exists():
            print(f"[ERROR] File disappeared: {file_path}")
            return False
        
        try:
            print(f"[UPLOAD] Connecting to upload port {upload_port}...")
            reader, writer = await asyncio.open_connection(self.host, upload_port)
            
            size = path.stat().st_size
            bytes_sent = 0
            
            print(f"[UPLOAD] Uploading {path.name}...")
            
            with open(path, 'rb') as f:
                while True:
                    data = f.read(8192)
                    if not data:
                        break
                    
                    writer.write(data)
                    await writer.drain()
                    bytes_sent += len(data)
                    
                    # Show progress every 1MB
                    if bytes_sent % (1024 * 1024) < 8192 or bytes_sent == size:
                        progress = (bytes_sent / size) * 100
                        print(f"[UPLOAD] Progress: {bytes_sent}/{size} bytes ({progress:.1f}%)")
            
            writer.close()
            await writer.wait_closed()
            
            print(f"[UPLOAD] Upload complete: {path.name}")
            return True
        
        except Exception as e:
            print(f"[ERROR] Upload failed: {e}")
            return False
    
    async def download_file(self, fid: str, save_path: str = None):
        """Download a file from the server."""
        print(f"[DOWNLOAD] Requesting file with fid={fid}")
        
        # Send file request
        request_msg = {
            "type": "file_request",
            "fid": fid
        }
        await self.send_message(request_msg)
        
        # Store download info for when we receive the port
        # The actual download will be triggered by the message handler
        return True
    
    async def do_file_download(self, fid: str, filename: str, size: int, download_port: int, save_path: str = None):
        """Perform the actual file download from the given port."""
        if save_path is None:
            # Default: save to downloads directory
            save_path = os.path.join("downloads", filename)
        
        # Ensure downloads directory exists
        save_dir = Path(save_path).parent
        save_dir.mkdir(parents=True, exist_ok=True)
        print(f"[DOWNLOAD] Saving to: {save_path}")
        
        try:
            print(f"[DOWNLOAD] Connecting to download port {download_port}...")
            reader, writer = await asyncio.open_connection(self.host, download_port)
            
            bytes_received = 0
            
            print(f"[DOWNLOAD] Downloading {filename}...")
            
            with open(save_path, 'wb') as f:
                while bytes_received < size:
                    data = await reader.read(8192)
                    if not data:
                        break
                    
                    f.write(data)
                    bytes_received += len(data)
                    
                    # Show progress every 1MB
                    if bytes_received % (1024 * 1024) < 8192 or bytes_received == size:
                        progress = (bytes_received / size) * 100
                        print(f"[DOWNLOAD] Progress: {bytes_received}/{size} bytes ({progress:.1f}%)")
            
            writer.close()
            await writer.wait_closed()
            
            if bytes_received == size:
                print(f"[DOWNLOAD] Download complete: {save_path}")
                return True
            else:
                print(f"[ERROR] Incomplete download: {bytes_received}/{size} bytes")
                # Clean up incomplete file
                Path(save_path).unlink(missing_ok=True)
                return False
        
        except Exception as e:
            print(f"[ERROR] Download failed: {e}")
            Path(save_path).unlink(missing_ok=True)
            return False

    async def start_presentation(self, fps: int = 3, quality: int = 70):
        """Start screen sharing presentation."""
        if not SCREEN_SHARE_AVAILABLE:
            print("[ERROR] Screen sharing not available. Install: pip install mss Pillow PyQt5")
            return False
        
        if self.presenting:
            print("[ERROR] Already presenting")
            return False
        
        print("[PRESENT] Starting screen share...")
        
        # Send present_start to server
        await self.send_message({
            "type": "present_start",
            "topic": f"{self.username}'s Screen"
        })
        
        return True
    
    async def do_start_presentation(self, presenter_port: int, fps: int = 3, quality: int = 70):
        """Actually start presenting after receiving port from server."""
        print(f"[PRESENT] Received presenter port: {presenter_port}")
        
        try:
            # Connect to presenter port
            self.presenter_reader, self.presenter_writer = await asyncio.open_connection(
                self.host, presenter_port
            )
            print(f"[PRESENT] Connected! Starting capture at {fps} FPS...")
            
            self.presenting = True
            self.presenter_fps = fps
            self.presenter_quality = quality
            
            # Start screen capture task
            self.presenter_task = asyncio.create_task(self._capture_and_stream())
            return True
        
        except Exception as e:
            print(f"[PRESENT] Failed to connect: {e}")
            return False
    
    async def _capture_and_stream(self):
        """Capture screen and stream frames."""
        frame_interval = 1.0 / self.presenter_fps
        frame_count = 0
        start_time = time.time()
        
        print(f"[PRESENTER] Starting screen capture at {self.presenter_fps} FPS")
        print(f"[PRESENTER] Quality: {self.presenter_quality}, Scale: {self.presenter_scale}")
        
        try:
            with mss_module.mss() as sct:
                while self.presenting:
                    loop_start = time.time()
                    
                    try:
                        # Capture primary monitor
                        monitor = sct.monitors[1]
                        screenshot = sct.grab(monitor)
                        
                        # Convert to PIL Image
                        img = PILImage.frombytes('RGB', screenshot.size, screenshot.rgb)
                        
                        # Scale down if needed
                        if self.presenter_scale != 1.0:
                            new_width = int(img.width * self.presenter_scale)
                            new_height = int(img.height * self.presenter_scale)
                            img = img.resize((new_width, new_height), PILImage.Resampling.LANCZOS)
                        
                        # Compress to JPEG
                        buffer = BytesIO()
                        img.save(buffer, format='JPEG', quality=self.presenter_quality, optimize=True)
                        frame_data = buffer.getvalue()
                        
                        # Send frame: [4 bytes length][frame data]
                        frame_length = len(frame_data)
                        header = struct.pack('!I', frame_length)
                        
                        self.presenter_writer.write(header + frame_data)
                        await self.presenter_writer.drain()
                        
                        frame_count += 1
                        
                        # Log every 30 frames
                        if frame_count % 30 == 0:
                            elapsed = time.time() - start_time
                            actual_fps = frame_count / elapsed if elapsed > 0 else 0
                            frame_size_kb = len(frame_data) / 1024
                            print(f"[PRESENTER] Frames: {frame_count}, "
                                  f"FPS: {actual_fps:.1f}, "
                                  f"Frame size: {frame_size_kb:.1f} KB")
                    
                    except Exception as e:
                        print(f"[PRESENTER] Frame capture error: {e}")
                    
                    # Sleep to maintain target FPS
                    elapsed = time.time() - loop_start
                    sleep_time = max(0, frame_interval - elapsed)
                    await asyncio.sleep(sleep_time)
        
        except asyncio.CancelledError:
            print("[PRESENTER] Streaming cancelled")
        except Exception as e:
            print(f"[PRESENTER] Streaming error: {e}")
        finally:
            print(f"[PRESENTER] Stopped. Total frames sent: {frame_count}")
    
    async def stop_presentation(self):
        """Stop screen sharing."""
        if not self.presenting:
            print("[ERROR] Not currently presenting")
            return
        
        print("[PRESENT] Stopping screen share...")
        
        # Send present_stop to server
        await self.send_message({
            "type": "present_stop"
        })
        
        # Stop streaming
        self.presenting = False
        
        if self.presenter_task:
            self.presenter_task.cancel()
            try:
                await self.presenter_task
            except asyncio.CancelledError:
                pass
            self.presenter_task = None
        
        # Close presenter connection
        if self.presenter_writer:
            try:
                self.presenter_writer.close()
                await self.presenter_writer.wait_closed()
            except Exception:
                pass
            self.presenter_writer = None
        
        print("[PRESENT] Stopped")
    
    async def view_presentation(self, viewer_port: int, presenter_name: str):
        """Start viewing a presentation."""
        if not SCREEN_SHARE_AVAILABLE:
            print("[ERROR] Screen sharing not available. Install: pip install mss Pillow PyQt5")
            return
        
        print(f"[VIEW] Opening {presenter_name}'s screen...")
        
        # Create Qt application if not exists
        if not self.viewer_app:
            self.viewer_app = QApplication(sys.argv)
        
        # Create viewer window
        self.viewer_window = ScreenViewerWindow(presenter_name)
        self.viewer_window.show()
        
        # Start receiving frames
        self.viewer_task = asyncio.create_task(
            self._receive_and_display_frames(viewer_port, presenter_name)
        )
    
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
                    
                    # Display frame in Qt window
                    self.viewer_window.display_frame(frame_data)
                    
                    # Process Qt events
                    self.viewer_app.processEvents()
                    
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
            
            if self.viewer_window:
                self.viewer_window.on_connection_closed()
            
            print(f"[VIEWER] Connection closed. Total frames: {frame_count}")
        
        except Exception as e:
            print(f"[VIEWER] Failed to connect or display: {e}")

    async def listen_for_messages(self):
        """Listen for incoming messages from server."""
        try:
            while self.running:
                data = await self.reader.readline()
                if not data:
                    print("[INFO] Server closed connection")
                    self.running = False
                    break
                
                try:
                    message = json.loads(data.decode('utf-8').strip())
                    await self.handle_message(message)
                except json.JSONDecodeError as e:
                    print(f"[ERROR] Malformed JSON received: {e}")
                except Exception as e:
                    print(f"[ERROR] Error processing message: {e}")
        
        except asyncio.CancelledError:
            print("[INFO] Listener cancelled")
        except Exception as e:
            print(f"[ERROR] Connection error: {e}")
            self.running = False

    async def handle_message(self, message: dict):
        """Handle different types of messages from server."""
        msg_type = message.get('type', '')
        
        if msg_type == 'login_success':
            self.uid = message.get('uid')
            username = message.get('username')
            print(f"[SUCCESS] Logged in as '{username}' with uid={self.uid}")
            # Request chat history after successful login
            await self.request_history()
        
        elif msg_type == 'participant_list':
            participants = message.get('participants', [])
            print(f"[INFO] Current participants ({len(participants)}):")
            for p in participants:
                print(f"  - {p.get('username')} (uid={p.get('uid')})")
        
        elif msg_type == 'history':
            messages = message.get('messages', [])
            count = message.get('count', 0)
            if count > 0:
                print(f"\n[HISTORY] Loading {count} previous message(s):")
                print("-" * 50)
                # Display messages in chronological order (they're already sorted)
                for msg in messages:
                    uid = msg.get('uid')
                    username = msg.get('username', 'unknown')
                    text = msg.get('text', msg.get('message', ''))
                    timestamp = msg.get('timestamp', '')
                    # Show all messages including our own in history
                    print(f"[{timestamp[:19]}] {username}: {text}")
                print("-" * 50)
            else:
                print("[HISTORY] No previous messages")
        
        elif msg_type == 'user_joined':
            uid = message.get('uid')
            username = message.get('username')
            if uid != self.uid:  # Don't print our own join
                print(f"[EVENT] User '{username}' joined (uid={uid})")
        
        elif msg_type == 'user_left':
            uid = message.get('uid')
            username = message.get('username')
            print(f"[EVENT] User '{username}' left (uid={uid})")
        
        elif msg_type == 'heartbeat_ack':
            # Silently acknowledge heartbeat
            pass
        
        elif msg_type == 'chat':
            uid = message.get('uid')
            username = message.get('username')
            # Support both "text" and "message" fields
            text = message.get('text', message.get('message', ''))
            timestamp = message.get('timestamp', '')
            if uid != self.uid:  # Don't echo our own messages
                print(f"[CHAT] {username}: {text}")
        
        elif msg_type == 'broadcast':
            uid = message.get('uid')
            username = message.get('username')
            text = message.get('text', message.get('message', ''))
            timestamp = message.get('timestamp', '')
            if uid != self.uid:  # Don't echo our own broadcasts
                print(f"📢 [BROADCAST] {username}: {text}")
        
        elif msg_type == 'unicast':
            from_uid = message.get('from_uid')
            from_username = message.get('from_username')
            to_uid = message.get('to_uid')
            to_username = message.get('to_username')
            text = message.get('text', message.get('message', ''))
            timestamp = message.get('timestamp', '')
            if to_uid == self.uid:  # This message is for us
                print(f"📨 [PRIVATE] {from_username} → {to_username}: {text}")
        
        elif msg_type == 'unicast_sent':
            to_uid = message.get('to_uid')
            to_username = message.get('to_username')
            print(f"✓ [SENT] Private message delivered to {to_username} (uid={to_uid})")
        
        elif msg_type == 'file_upload_port':
            fid = message.get('fid')
            port = message.get('port')
            print(f"[UPLOAD] Received upload port {port} for fid={fid}")
            
            # Get the pending upload file path
            file_path = self.pending_uploads.get(fid)
            if file_path:
                # Start upload in background
                asyncio.create_task(self.do_file_upload(fid, file_path, port))
                # Remove from pending after starting
                del self.pending_uploads[fid]
            else:
                print(f"[ERROR] No pending upload for fid={fid}")
        
        elif msg_type == 'file_download_port':
            fid = message.get('fid')
            filename = message.get('filename')
            size = message.get('size')
            port = message.get('port')
            print(f"[DOWNLOAD] Received download port {port} for {filename}")
            
            # Get the save path if specified
            save_path = self.pending_downloads.get(fid)
            
            # Start download in background
            asyncio.create_task(self.do_file_download(fid, filename, size, port, save_path))
            
            # Remove from pending after starting
            if fid in self.pending_downloads:
                del self.pending_downloads[fid]
        
        elif msg_type == 'file_available':
            fid = message.get('fid')
            filename = message.get('filename')
            size = message.get('size')
            uploader = message.get('uploader')
            print(f"[FILE] Available: {filename} ({size} bytes) from {uploader} [fid={fid}]")
        
        elif msg_type == 'screen_share_ports':
            # Server assigned ports for our presentation
            presenter_port = message.get('presenter_port')
            viewer_port = message.get('viewer_port')
            print(f"[PRESENT] Server assigned ports - Presenter: {presenter_port}, Viewer: {viewer_port}")
            # Start the actual presentation
            await self.do_start_presentation(presenter_port)
        
        elif msg_type == 'present_start':
            uid = message.get('uid')
            username = message.get('username')
            topic = message.get('topic')
            viewer_port = message.get('viewer_port')
            
            if uid == self.uid:
                print(f"[PRESENT] Your presentation '{topic}' is now live!")
            else:
                print(f"[PRESENT] 🎬 {username} started presentation: {topic}")
                print(f"[PRESENT] Type '/view' to watch")
                # Store current presentation info
                self.current_presentation = {
                    'username': username,
                    'viewer_port': viewer_port,
                    'topic': topic
                }
        
        elif msg_type == 'present_stop':
            uid = message.get('uid')
            username = message.get('username')
            print(f"[PRESENT] {username} stopped presentation")
            self.current_presentation = None
        
        elif msg_type == 'error':
            error_msg = message.get('message', 'Unknown error')
            print(f"[ERROR] Server error: {error_msg}")
        
        else:
            print(f"[DEBUG] Unknown message type: {msg_type}")
            print(f"[DEBUG] Message: {message}")

    async def handle_user_input(self, user_input: str):
        """Handle user input - commands or chat messages."""
        if user_input.startswith('/'):
            # Parse command
            parts = user_input.split(maxsplit=2)
            command = parts[0].lower()
            
            if command == '/help':
                print("\n[HELP] Available commands:")
                print("  /upload <file_path>        - Upload a file")
                print("  /download <fid> [path]     - Download a file by fid")
                print("                               (saves to downloads/ by default)")
                print("  /present                   - Start screen sharing")
                print("  /view                      - View current presentation")
                print("  /stopshare                 - Stop your screen sharing")
                print("  /broadcast <message>       - Send message to all users")
                print("  /unicast <uid> <message>   - Send private message to user")
                print("  /help                      - Show this help")
                print("  (anything else)            - Send as chat message\n")
            
            elif command == '/upload':
                if len(parts) < 2:
                    print("[ERROR] Usage: /upload <file_path>")
                else:
                    file_path = parts[1]
                    await self.upload_file(file_path)
            
            elif command == '/download':
                if len(parts) < 2:
                    print("[ERROR] Usage: /download <fid> [save_path]")
                    print("[INFO] Files are saved to downloads/ directory by default")
                else:
                    fid = parts[1]
                    save_path = parts[2] if len(parts) > 2 else None
                    if save_path:
                        self.pending_downloads[fid] = save_path
                    await self.download_file(fid, save_path)
            
            elif command == '/present':
                if not SCREEN_SHARE_AVAILABLE:
                    print("[ERROR] Screen sharing requires: pip install mss Pillow PyQt5")
                else:
                    await self.start_presentation()
            
            elif command == '/view':
                if not SCREEN_SHARE_AVAILABLE:
                    print("[ERROR] Screen sharing requires: pip install mss Pillow PyQt5")
                elif not self.current_presentation:
                    print("[ERROR] No active presentation to view")
                else:
                    await self.view_presentation(
                        self.current_presentation['viewer_port'],
                        self.current_presentation['username']
                    )
            
            elif command == '/stopshare':
                await self.stop_presentation()
            
            elif command == '/broadcast':
                if len(parts) < 2:
                    print("[ERROR] Usage: /broadcast <message>")
                else:
                    message = parts[1]
                    await self.send_broadcast(message)
            
            elif command == '/unicast':
                if len(parts) < 3:
                    print("[ERROR] Usage: /unicast <uid> <message>")
                    print("[INFO] Use participant list to see available UIDs")
                else:
                    try:
                        target_uid = int(parts[1])
                        message = parts[2]
                        await self.send_unicast(target_uid, message)
                    except ValueError:
                        print("[ERROR] UID must be a number")
            
            else:
                print(f"[ERROR] Unknown command: {command}. Type /help for help.")
        else:
            # Regular chat message
            await self.send_chat(user_input)

    async def run(self):
        """Main client loop."""
        if not await self.connect():
            return
        
        # Send login message
        await self.send_login()
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self.send_heartbeat())
        
        # Start listening for messages
        listener_task = asyncio.create_task(self.listen_for_messages())
        
        # Wait for listener to finish (on disconnect or error)
        try:
            await listener_task
        except asyncio.CancelledError:
            pass
        finally:
            # Cancel heartbeat
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            
            # Close connection
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
            
            print("[INFO] Disconnected from server")

    async def interactive_mode(self):
        """Run client with interactive chat input."""
        if not await self.connect():
            return
        
        # Send login message
        await self.send_login()
        
        # Start heartbeat task
        heartbeat_task = asyncio.create_task(self.send_heartbeat())
        
        # Start listening for messages
        listener_task = asyncio.create_task(self.listen_for_messages())
        
        # Read user input from stdin
        print("[INFO] Type messages to chat (Ctrl+C to exit)")
        print("[INFO] Commands: /upload /download /present /view /stopshare /help")
        
        try:
            while self.running:
                # Get user input (blocking, but that's ok for demo)
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, sys.stdin.readline
                    )
                    if user_input.strip():
                        await self.handle_user_input(user_input.strip())
                except EOFError:
                    break
        except asyncio.CancelledError:
            pass
        finally:
            # Send logout
            await self.send_logout()
            await asyncio.sleep(0.5)  # Give server time to process
            
            # Cancel tasks
            listener_task.cancel()
            heartbeat_task.cancel()
            
            try:
                await listener_task
            except asyncio.CancelledError:
                pass
            
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass
            
            # Close connection
            if self.writer:
                self.writer.close()
                await self.writer.wait_closed()
            
            print("[INFO] Disconnected from server")


async def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter username: ").strip() or "anonymous"
    
    client = CollaborationClient(
        host='localhost',
        port=9000,
        username=username
    )
    
    try:
        await client.interactive_mode()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    except Exception as e:
        print(f"[ERROR] Client error: {e}")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Client terminated")

