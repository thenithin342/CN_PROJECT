"""
Screen presenter module.

This module handles client-side screen capture and streaming functionality.
"""

import asyncio
import struct
import time
from typing import Optional, Callable

# Optional screen sharing imports
try:
    import mss as mss_module
    from PIL import Image as PILImage
    from io import BytesIO
    SCREEN_SHARE_AVAILABLE = True
except ImportError:
    SCREEN_SHARE_AVAILABLE = False
    mss_module = None
    PILImage = None

from common.constants import MessageTypes, FRAME_HEADER_SIZE
from common.protocol_definitions import create_present_start_message, create_present_stop_message


class ScreenPresenter:
    """Client-side screen sharing presenter functionality."""
    
    def __init__(self, writer: Optional[asyncio.StreamWriter] = None):
        self.writer = writer
        self.host = 'localhost'
        self.presenting = False
        self.presenter_writer = None
        self.presenter_reader = None
        self.presenter_task = None
        self.presenter_fps = 3
        self.presenter_quality = 70
        self.presenter_scale = 0.5
        self.message_handler: Optional[Callable] = None
    
    def set_writer(self, writer: asyncio.StreamWriter):
        """Set the writer for sending messages."""
        self.writer = writer
    
    def set_host(self, host: str):
        """Set the server host for screen sharing."""
        self.host = host
    
    def set_message_handler(self, handler: Callable):
        """Set the message handler for incoming messages."""
        self.message_handler = handler
    
    async def send_message(self, message: dict) -> bool:
        """Send a JSON message to the server."""
        if not self.writer:
            print("[ERROR] Not connected to server")
            return False
        
        try:
            import json
            msg_data = json.dumps(message).encode('utf-8') + b'\n'
            self.writer.write(msg_data)
            await self.writer.drain()
            return True
        except Exception as e:
            print(f"[ERROR] Failed to send message: {e}")
            return False
    
    async def start_presentation(self, topic: str = None, fps: int = 3, quality: int = 70) -> bool:
        """Start screen sharing presentation."""
        if not SCREEN_SHARE_AVAILABLE:
            print("[ERROR] Screen sharing not available. Install: pip install mss Pillow PyQt5")
            return False
        
        if self.presenting:
            print("[ERROR] Already presenting")
            return False
        
        print("[PRESENT] Starting screen share...")
        
        # Update settings
        self.presenter_fps = fps
        self.presenter_quality = quality
        
        # Send present_start to server
        if topic is None:
            topic = "Screen Share"
        
        await self.send_message(create_present_start_message(topic))
        
        return True
    
    async def do_start_presentation(self, presenter_port: int) -> bool:
        """Actually start presenting after receiving port from server."""
        print(f"[PRESENT] Received presenter port: {presenter_port}")
        
        try:
            # Connect to presenter port
            self.presenter_reader, self.presenter_writer = await asyncio.open_connection(
                self.host, presenter_port
            )
            print(f"[PRESENT] Connected! Starting capture at {self.presenter_fps} FPS...")
            
            self.presenting = True
            
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
    
    async def stop_presentation(self) -> bool:
        """Stop screen sharing."""
        if not self.presenting:
            print("[ERROR] Not currently presenting")
            return False
        
        print("[PRESENT] Stopping screen share...")
        
        # Send present_stop to server
        await self.send_message(create_present_stop_message())
        
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
        return True
    
    async def handle_message(self, message: dict):
        """Handle different types of screen sharing messages from server."""
        msg_type = message.get('type', '')
        
        if msg_type == MessageTypes.SCREEN_SHARE_PORTS:
            await self._handle_screen_share_ports(message)
        elif msg_type == MessageTypes.PRESENT_START_BROADCAST:
            await self._handle_present_start(message)
        elif msg_type == MessageTypes.PRESENT_STOP_BROADCAST:
            await self._handle_present_stop(message)
    
    async def _handle_screen_share_ports(self, message: dict):
        """Handle screen share ports response."""
        presenter_port = message.get('presenter_port')
        viewer_port = message.get('viewer_port')
        print(f"[PRESENT] Server assigned ports - Presenter: {presenter_port}, Viewer: {viewer_port}")
        # Start the actual presentation
        await self.do_start_presentation(presenter_port)
    
    async def _handle_present_start(self, message: dict):
        """Handle present start broadcast."""
        uid = message.get('uid')
        username = message.get('username')
        topic = message.get('topic')
        viewer_port = message.get('viewer_port')
        
        if hasattr(self, 'uid') and uid == self.uid:
            print(f"[PRESENT] Your presentation '{topic}' is now live!")
        else:
            print(f"[PRESENT] 🎬 {username} started presentation: {topic}")
            print(f"[PRESENT] Type '/view' to watch")
    
    async def _handle_present_stop(self, message: dict):
        """Handle present stop broadcast."""
        uid = message.get('uid')
        username = message.get('username')
        print(f"[PRESENT] {username} stopped presentation")
    
    def set_uid(self, uid: int):
        """Set the client's UID for message filtering."""
        self.uid = uid
