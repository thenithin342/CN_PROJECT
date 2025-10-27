#!/usr/bin/env python3
"""
Video Client - Captures webcam and sends video to the video server.

This module implements webcam capture using OpenCV, encodes frames to JPEG,
and sends encoded frames via UDP to the video server with chunking support
for frames larger than MTU.
"""

import cv2
import socket
import time
import threading
import argparse
import struct
from typing import Optional, Tuple
from collections import deque


class VideoClient:
    """Client for capturing and sending video to the server."""
    
    # Video settings
    DEFAULT_WIDTH = 640
    DEFAULT_HEIGHT = 360
    DEFAULT_FPS = 15  # frames per second
    
    # Network settings
    MTU_SIZE = 1400  # Maximum transmission unit (conservative for UDP)
    CHUNK_HEADER_SIZE = 36  # bytes for chunk header (increased for receive port)
    
    def __init__(self, server_ip: str = 'localhost', server_port: int = 10000, 
                 uid: Optional[int] = 1, fps: int = DEFAULT_FPS, 
                 resolution: Tuple[int, int] = (DEFAULT_WIDTH, DEFAULT_HEIGHT)):
        """
        Initialize the video client.
        
        Args:
            server_ip: Server IP address
            server_port: Server UDP port for video
            uid: User ID
            fps: Target frames per second
            resolution: Frame resolution (width, height)
        """
        self.server_ip = server_ip
        self.server_port = server_port
        self.uid = uid
        self.target_fps = fps
        self.width, self.height = resolution
        
        # State
        self.is_streaming = False
        self.frame_id = 0
        self.sequence_number = 0
        self.socket = None
        
        # Webcam capture
        self.cap = None
        self.capture_thread = None
        
        # Frame buffer for sending
        self.frame_buffer = deque()
        self.frame_buffer_lock = threading.Lock()
        
        # Frame receiver callback (set by GUI to receive frames)
        self.frame_received_callback = None
        
        # Timing
        self.frame_interval = 1.0 / self.target_fps
        self.last_frame_time = 0
    
    def start_streaming(self):
        """Start video streaming from webcam."""
        if self.is_streaming:
            return

        try:
            # Open webcam
            self.cap = cv2.VideoCapture(0)
            if not self.cap.isOpened():
                raise RuntimeError("Failed to open webcam")

            # Set camera properties
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.height)

            # Create UDP socket for sending chunks
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

            # Create separate UDP socket for receiving frames (bind to ephemeral port)
            self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.receive_socket.bind(('', 0))  # Bind to ephemeral port
            self.receive_port = self.receive_socket.getsockname()[1]  # Get the assigned port
            self.receive_socket.settimeout(1.0)
            print(f"[VIDEO] Receive socket bound to port {self.receive_port}")

            # Start frame receiver thread
            self.receiver_thread = threading.Thread(target=self._receive_frames, daemon=True)
            self.receiver_thread.start()

            # Start streaming
            self.is_streaming = True
            self.frame_id = 0
            self.sequence_number = 0

            # Start capture thread
            self.capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
            self.capture_thread.start()

            print(f"[VIDEO] Started streaming from webcam")
            print(f"[VIDEO] Resolution: {self.width}x{self.height}")
            print(f"[VIDEO] Target FPS: {self.target_fps}")
            print(f"[VIDEO] Sending to {self.server_ip}:{self.server_port}")
            print(f"[VIDEO] Receiving on port 10001")

        except cv2.error as e:
            print(f"[VIDEO] OpenCV error: {e}")
            print(f"[VIDEO] Ensure webcam is connected and not in use by another application")
            self.cleanup()
            raise
        except OSError as e:
            print(f"[VIDEO] Network error: {e}")
            print(f"[VIDEO] Unable to connect to server at {self.server_ip}:{self.server_port}")
            print(f"[VIDEO] Ensure server is running and firewall permits UDP")
            self.cleanup()
            raise
        except Exception as e:
            print(f"[VIDEO] Error starting streaming: {e}")
            self.cleanup()
            raise
    
    def _capture_loop(self):
        """Main capture loop running in separate thread."""
        while self.is_streaming:
            try:
                start_time = time.time()
                
                # Check if it's time to capture a new frame
                elapsed = start_time - self.last_frame_time
                if elapsed < self.frame_interval:
                    time.sleep(self.frame_interval - elapsed)
                    continue
                
                # Capture frame from webcam
                ret, frame = self.cap.read()
                if not ret:
                    print("[VIDEO] Failed to capture frame")
                    time.sleep(0.1)
                    continue
                
                # Resize frame to target resolution
                frame = cv2.resize(frame, (self.width, self.height))
                
                # Encode frame to JPEG
                encode_params = [int(cv2.IMWRITE_JPEG_QUALITY), 80]  # 80% quality
                success, encoded_frame = cv2.imencode('.jpg', frame, encode_params)
                
                if not success:
                    print("[VIDEO] Failed to encode frame")
                    time.sleep(0.1)
                    continue
                
                # Convert to bytes
                frame_bytes = encoded_frame.tobytes()
                
                # Send frame via UDP (with chunking if necessary)
                self._send_frame(frame_bytes)
                
                self.last_frame_time = time.time()
                print(f"[VIDEO] Captured and sent frame {self.frame_id}, size: {len(frame_bytes)} bytes")
                
            except Exception as e:
                print(f"[VIDEO] Error in capture loop: {e}")
                if not self.is_streaming:
                    break
                time.sleep(0.1)
    
    
    def _send_frame(self, frame_bytes: bytes):
        """Send frame to server, splitting into chunks if necessary."""
        frame_size = len(frame_bytes)
        
        # Calculate number of chunks needed
        max_chunk_payload = self.MTU_SIZE - self.CHUNK_HEADER_SIZE
        num_chunks = (frame_size + max_chunk_payload - 1) // max_chunk_payload  # Ceiling division
        
        print(f"[VIDEO] Sending frame {self.frame_id} in {num_chunks} chunks")
        
        # Send chunks
        for chunk_idx in range(num_chunks):
            # Calculate chunk boundaries
            start_idx = chunk_idx * max_chunk_payload
            end_idx = min(start_idx + max_chunk_payload, frame_size)
            chunk_data = frame_bytes[start_idx:end_idx]
            
            # Create chunk header (include receive port for server to know where to send frames)
            timestamp = int(time.time() * 1000)  # milliseconds
            chunk_size = len(chunk_data)

            header = struct.pack('>I I I I I Q I I',
                                  self.uid,
                                  self.frame_id,
                                  chunk_idx,
                                  num_chunks,
                                  self.sequence_number,
                                  timestamp,
                                  chunk_size,
                                  self.receive_port)
            
            # Create packet: header + chunk data
            packet = header + chunk_data
            
            # Send via UDP
            try:
                self.socket.sendto(packet, (self.server_ip, self.server_port))
                self.sequence_number = (self.sequence_number + 1) % 0xFFFFFFFF
                print(f"[VIDEO] Sent chunk {chunk_idx + 1}/{num_chunks} of frame {self.frame_id}, size: {len(packet)} bytes")
            except OSError as e:
                print(f"[VIDEO] Network error sending chunk to {self.server_ip}:{self.server_port}: {e}")
                print(f"[VIDEO] Ensure server is running and firewall permits UDP on port {self.server_port}")
            except Exception as e:
                print(f"[VIDEO] Unexpected error sending chunk: {e}")
        
        # Increment frame ID for next frame
        self.frame_id += 1
    
    def _receive_frames(self):
        """Receive frames on the receive socket (runs in separate thread)."""
        while self.is_streaming:
            try:
                data, addr = self.receive_socket.recvfrom(65536)
                # Parse broadcast header
                if len(data) >= 12:
                    uid, timestamp = struct.unpack('>I Q', data[:12])
                    frame_data = data[12:]
                    # Decode and call callback
                    try:
                        import numpy as np
                        import cv2
                        nparr = np.frombuffer(frame_data, np.uint8)
                        frame = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                        if frame is not None and self.frame_received_callback:
                            self.frame_received_callback(uid, frame)
                            print(f"[VIDEO] Received and decoded frame from uid={uid}, size={len(frame_data)} bytes")
                    except Exception as e:
                        print(f"[VIDEO] Error decoding received frame: {e}")
            except socket.timeout:
                continue
            except Exception as e:
                if self.is_streaming:
                    print(f"[VIDEO] Error receiving frame: {e}")
    
    def set_frame_received_callback(self, callback):
        """Set callback for when frames are received."""
        self.frame_received_callback = callback
    
    def set_uid(self, uid: Optional[int]):
        """Set the client's UID."""
        if uid is None:
            self.uid = 0  # Default placeholder UID
        else:
            self.uid = uid
    
    def stop_streaming(self):
        """Stop video streaming."""
        if not self.is_streaming:
            return

        self.is_streaming = False

        # Wait for capture thread to finish
        if self.capture_thread and self.capture_thread.is_alive():
            self.capture_thread.join(timeout=1.0)

        # Release webcam
        if self.cap:
            self.cap.release()
            self.cap = None

        # Close sockets
        if self.socket:
            self.socket.close()
            self.socket = None

        if self.receive_socket:
            self.receive_socket.close()
            self.receive_socket = None

        print("[VIDEO] Stopped streaming")
    
    def cleanup(self):
        """Clean up resources."""
        self.stop_streaming()


def run_client(server_ip: str, uid: int, fps: int = 15, resolution: Tuple[int, int] = (640, 360)):
    """Run the video client."""
    client = VideoClient(server_ip=server_ip, server_port=10000, uid=uid, fps=fps, resolution=resolution)
    
    try:
        # Start streaming
        client.start_streaming()
        
        # Keep running until interrupted
        print("[VIDEO] Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n[VIDEO] Stopping client...")
    finally:
        client.cleanup()

def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Video Client - Captures and sends webcam video to server')
    parser.add_argument('--server-ip', type=str, default='localhost',
                       help='Server IP address (default: localhost)')
    parser.add_argument('--video-port', type=int, default=10000,
                       help='Server UDP port for video (default: 10000)')
    parser.add_argument('--uid', type=int, default=1,
                       help='User ID (default: 1)')
    parser.add_argument('--fps', type=int, default=15,
                       help='Target frames per second (default: 15)')
    parser.add_argument('--resolution', type=str, default='640x360',
                       help='Frame resolution WIDTHxHEIGHT (default: 640x360)')
    
    args = parser.parse_args()
    
    # Parse resolution
    try:
        width, height = map(int, args.resolution.split('x'))
        resolution = (width, height)
    except ValueError:
        print("[ERROR] Invalid resolution format. Use WIDTHxHEIGHT (e.g., 640x360)")
        return
    
    try:
        client = VideoClient(server_ip=args.server_ip, server_port=args.video_port, 
                           uid=args.uid, fps=args.fps, resolution=resolution)
        
        # Start streaming
        client.start_streaming()
        
        # Keep running until interrupted
        print("[VIDEO] Press Ctrl+C to stop...")
        while True:
            time.sleep(1)
    
    except KeyboardInterrupt:
        print("\n[VIDEO] Stopping client...")
    finally:
        client.cleanup()


if __name__ == "__main__":
    main()
