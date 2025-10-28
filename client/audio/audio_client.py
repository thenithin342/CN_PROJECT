#!/usr/bin/env python3
"""
Audio Client - Captures and sends audio to the audio server.

This module implements audio capture using pyaudio and sends raw PCM frames
via UDP to the audio server.
"""

import asyncio
import socket
import struct
import threading
import time
import argparse
from typing import Optional
import numpy as np

try:
    import pyaudio
    HAS_PYAUDIO = True
except ImportError:
    HAS_PYAUDIO = False
    print("[WARNING] pyaudio not installed. Audio capture will not work.")
    print("Install with: pip install pyaudio")


class AudioClient:
    """Client for capturing and sending audio to the server."""
    
    # Audio settings
    SAMPLE_RATE = 16000  # Hz (reduced for pyaudio compatibility)
    CHANNELS = 1  # Mono
    CHUNK_SIZE = 1600  # Samples per chunk (100ms at 16kHz)
    BYTES_PER_SAMPLE = 2  # 16-bit audio
    
    def __init__(self, server_ip: str = 'localhost', server_port: int = 11000, uid: Optional[int] = 1):
        """Initialize the audio client."""
        self.server_ip = server_ip
        self.server_port = server_port
        self.set_uid(uid)
        
        # State
        self.is_recording = False
        self.sequence_number = 0
        self.socket = None
        self.receive_socket = None
        
        # Audio processing
        self.p = None  # PyAudio instance
        self.input_stream = None
        self.output_stream = None
        self.audio_thread = None
        self.receive_thread = None
        
        # Jitter buffer for playback
        self.jitter_buffer = []
        self.jitter_buffer_lock = threading.Lock()
        self.jitter_buffer_size = 3  # Buffer 3 frames
        self.jitter_buffer_max_size = 10  # Hard limit to prevent memory leak
        
        # Participant mute list
        self.muted_participants = set()
        
        # Check dependencies
        if not HAS_PYAUDIO:
            raise ImportError("pyaudio is required for audio capture")
    
    def set_uid(self, uid: Optional[int]):
        """Set the client's UID."""
        if uid is None:
            self.uid = 0  # Default placeholder UID
        elif uid < 0 or uid > 0xFFFFFFFF:
            raise ValueError(f"UID must be between 0 and {0xFFFFFFFF}, got {uid}")
        else:
            self.uid = uid
    
    def _create_packet_header(self) -> bytes:
        """Create packet header with sequence, timestamp, and uid."""
        timestamp = int(time.time() * 1000)  # milliseconds
        # Header format: seq (4 bytes), timestamp (8 bytes), uid (4 bytes)
        uid = self.uid if self.uid is not None else 0
        header = struct.pack('>I Q I', self.sequence_number, timestamp, uid)
        self.sequence_number += 1
        return header
    
    def _parse_packet_header(self, data: bytes) -> tuple:
        """Parse packet header: (sequence, timestamp, uid, payload)."""
        if len(data) < 16:
            return None
        sequence, timestamp, uid = struct.unpack('>I Q I', data[:16])
        return (sequence, timestamp, uid, data[16:])
    
    def _audio_capture_loop(self):
        """Thread function to capture audio using pyaudio."""
        try:
            while self.is_recording:
                try:
                    # Read audio data (non-blocking)
                    data = self.input_stream.read(self.CHUNK_SIZE, exception_on_overflow=False)
                    
                    if not self.is_recording:
                        break
                    
                    # Convert bytes to numpy array
                    audio_data = np.frombuffer(data, dtype=np.int16)
                    
                    # Convert to float32 normalized
                    audio_float = audio_data.astype(np.float32) / 32768.0
                    
                    # Log audio levels for debugging
                    rms_level = np.sqrt(np.mean(audio_float**2))
                    if rms_level > 0.01:
                        print(f"[AUDIO] Input RMS: {rms_level:.4f}")
                    
                    # Send audio data
                    header = self._create_packet_header()
                    packet = header + data
                    
                    try:
                        self.socket.sendto(packet, (self.server_ip, self.server_port))
                        print(f"[AUDIO] Sent packet seq={self.sequence_number-1}, size={len(packet)} bytes")
                    except socket.error as e:
                        print(f"[AUDIO] Network error: {e}")
                    except Exception as e:
                        print(f"[AUDIO] Unexpected error sending packet: {e}")
                
                except Exception as e:
                    if self.is_recording:
                        print(f"[AUDIO] Error in capture loop: {e}")
                    break
        
        except Exception as e:
            print(f"[AUDIO] Error in audio capture thread: {e}")
            import traceback
            traceback.print_exc()
    
    def _output_audio_loop(self):
        """Thread function to play audio using pyaudio."""
        try:
            while self.is_recording:
                try:
                    # Get audio from jitter buffer
                    audio_frame = None
                    with self.jitter_buffer_lock:
                        if len(self.jitter_buffer) > 0:
                            audio_frame = self.jitter_buffer.pop(0)
                    
                    if audio_frame is not None:
                        # Ensure proper size
                        if len(audio_frame) >= self.CHUNK_SIZE:
                            audio_frame = audio_frame[:self.CHUNK_SIZE]
                        
                        # Convert float32 back to int16
                        audio_int16 = (audio_frame * 32768.0).astype(np.int16)
                        
                        # Play audio
                        self.output_stream.write(audio_int16.tobytes())
                    else:
                        # No data, output silence
                        silence = np.zeros(self.CHUNK_SIZE, dtype=np.int16)
                        self.output_stream.write(silence.tobytes())
                
                except Exception as e:
                    if self.is_recording:
                        print(f"[AUDIO] Error in playback loop: {e}")
                    break
        
        except Exception as e:
            print(f"[AUDIO] Error in audio playback thread: {e}")
            import traceback
            traceback.print_exc()
    
    def _receive_audio(self):
        """Thread worker to receive audio from server."""
        buffer_size = 65536
        
        while self.is_recording:
            try:
                self.receive_socket.settimeout(0.5)
                data, addr = self.receive_socket.recvfrom(buffer_size)
                
                # Parse packet header
                header_info = self._parse_packet_header(data)
                if header_info is None:
                    continue
                
                sequence, timestamp, uid, payload = header_info
                print(f"[AUDIO] Received packet seq={sequence}, uid={uid}")
                
                # Check if this participant is muted
                if uid in self.muted_participants:
                    continue
                
                # Convert PCM bytes to numpy array
                audio_int16 = np.frombuffer(payload, dtype=np.int16)
                audio_float = audio_int16.astype(np.float32) / 32768.0
                
                # Add to jitter buffer
                with self.jitter_buffer_lock:
                    if len(self.jitter_buffer) >= self.jitter_buffer_max_size:
                        self.jitter_buffer.pop(0)
                    self.jitter_buffer.append(audio_float)
                
            except socket.timeout:
                continue
            except OSError as e:
                if self.is_recording:
                    print(f"[AUDIO] Network error receiving audio: {e}")
            except Exception as e:
                if self.is_recording:
                    print(f"[AUDIO] Unexpected error receiving audio: {e}")
    
    def start_recording(self):
        """Start audio recording and transmission."""
        if self.is_recording:
            return
        
        try:
            # Initialize PyAudio
            self.p = pyaudio.PyAudio()
            
            # Create UDP sockets
            self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self.receive_socket.bind(('', 0))
            recv_port = self.receive_socket.getsockname()[1]
            
            # Open input stream
            self.input_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.SAMPLE_RATE,
                input=True,
                frames_per_buffer=self.CHUNK_SIZE
            )
            
            # Open output stream
            self.output_stream = self.p.open(
                format=pyaudio.paInt16,
                channels=self.CHANNELS,
                rate=self.SAMPLE_RATE,
                output=True,
                frames_per_buffer=self.CHUNK_SIZE
            )
            
            self.is_recording = True
            
            # Start capture thread
            self.audio_thread = threading.Thread(target=self._audio_capture_loop, daemon=True)
            self.audio_thread.start()
            
            # Start playback thread
            playback_thread = threading.Thread(target=self._output_audio_loop, daemon=True)
            playback_thread.start()
            
            # Start receive thread
            self.receive_thread = threading.Thread(target=self._receive_audio, daemon=True)
            self.receive_thread.start()
            
            print(f"[AUDIO] Started recording. Sending to {self.server_ip}:{self.server_port}")
            print(f"[AUDIO] Receiving audio on port {recv_port}")
            print(f"[AUDIO] Sample rate: {self.SAMPLE_RATE} Hz, Channels: {self.CHANNELS}")
        
        except OSError as e:
            print(f"[AUDIO] Network error during startup: {e}")
            self.is_recording = False
        except Exception as e:
            print(f"[AUDIO] Error starting recording: {e}")
            import traceback
            traceback.print_exc()
            self.is_recording = False
    
    def stop_recording(self):
        """Stop audio recording and transmission."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        # Stop audio streams
        if self.input_stream:
            try:
                self.input_stream.stop_stream()
                self.input_stream.close()
            except Exception as e:
                print(f"[AUDIO] Error stopping input stream: {e}")
            finally:
                self.input_stream = None
        
        if self.output_stream:
            try:
                self.output_stream.stop_stream()
                self.output_stream.close()
            except Exception as e:
                print(f"[AUDIO] Error stopping output stream: {e}")
            finally:
                self.output_stream = None
        
        # Terminate PyAudio
        if self.p:
            try:
                self.p.terminate()
            except Exception as e:
                print(f"[AUDIO] Error terminating PyAudio: {e}")
            finally:
                self.p = None
        
        # Close sockets
        if self.socket:
            try:
                self.socket.close()
            except Exception as e:
                pass
            finally:
                self.socket = None
        
        if self.receive_socket:
            try:
                self.receive_socket.close()
            except Exception as e:
                pass
            finally:
                self.receive_socket = None
        
        # Wait for threads
        if self.audio_thread and self.audio_thread.is_alive():
            self.audio_thread.join(timeout=1.0)
        
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        print("[AUDIO] Stopped recording")
    
    def mute_participant(self, uid: int):
        """Mute audio from a specific participant."""
        self.muted_participants.add(uid)
        print(f"[AUDIO] Muted participant {uid}")
    
    def unmute_participant(self, uid: int):
        """Unmute audio from a specific participant."""
        if uid in self.muted_participants:
            self.muted_participants.discard(uid)
            print(f"[AUDIO] Unmuted participant {uid}")
    
    def is_participant_muted(self, uid: int) -> bool:
        """Check if a participant is muted."""
        return uid in self.muted_participants
    
    def cleanup(self):
        """Clean up resources."""
        self.stop_recording()


async def run_client(server_ip: str, uid: int):
    """Run the audio client."""
    client = AudioClient(server_ip=server_ip, server_port=11000, uid=uid)
    
    try:
        # Start recording
        client.start_recording()
        
        # Keep running until interrupted
        print("[AUDIO] Press Ctrl+C to stop...")
        while True:
            await asyncio.sleep(1)
    
    except KeyboardInterrupt:
        print("\n[AUDIO] Stopping client...")
    finally:
        client.cleanup()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Audio Client - Captures and sends audio to server')
    parser.add_argument('--server-ip', type=str, default='localhost',
                       help='Server IP address (default: localhost)')
    parser.add_argument('--uid', type=int, default=1,
                       help='User ID (default: 1)')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(run_client(args.server_ip, args.uid))
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
