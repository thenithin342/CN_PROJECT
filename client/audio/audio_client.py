#!/usr/bin/env python3
"""
Audio Client - Captures and sends audio to the audio server.

This module implements audio capture using sounddevice, encodes to Opus,
and sends encoded frames via UDP to the audio server.
"""

import asyncio
import struct
import threading
import time
import argparse
from typing import Optional
import numpy as np

try:
    import sounddevice as sd
    HAS_SOUNDDEVICE = True
except ImportError:
    HAS_SOUNDDEVICE = False
    print("[WARNING] sounddevice not installed. Audio capture will not work.")
    print("Install with: pip install sounddevice")

try:
    from opuslib import Encoder, Decoder
    HAS_OPUS = True
    HAS_AV = False  # Prefer opuslib if available
except ImportError:
    HAS_OPUS = False
    try:
        import av
        HAS_AV = True
        print("[WARNING] Using PyAV (av) for Opus - may have limitations")
    except ImportError:
        HAS_AV = False
        print("[WARNING] Neither opuslib nor av (PyAV) is installed. Audio encoding will not work.")
        print("Install with: pip install opuslib or pip install av")


class AudioClient:
    """Client for capturing and sending audio to the server."""
    
    # Audio settings
    SAMPLE_RATE = 48000  # Hz
    CHANNELS = 1  # Mono
    FRAME_DURATION_MS = 40  # ms
    SAMPLES_PER_FRAME = (SAMPLE_RATE * FRAME_DURATION_MS) // 1000  # 1920 samples
    BYTES_PER_SAMPLE = 2  # 16-bit audio
    
    # Opus settings
    OPUS_APPLICATION = 2048  # OPUS_APPLICATION_VOIP
    OPUS_BITRATE = 64000  # 64 kbps
    
    def __init__(self, server_ip: str = 'localhost', server_port: int = 11000, uid: int = 1):
        """Initialize the audio client."""
        self.server_ip = server_ip
        self.server_port = server_port
        self.uid = uid
        
        # State
        self.is_recording = False
        self.sequence_number = 0
        self.socket = None
        self.receive_socket = None
        
        # Audio processing
        self.encoder = None
        self.decoder = None
        self.stream = None
        self.output_stream = None
        self.audio_thread = None
        self.receive_thread = None
        
        # Jitter buffer for playback
        self.jitter_buffer = []
        self.jitter_buffer_lock = threading.Lock()
        self.jitter_buffer_size = 3  # Buffer 3 frames
        
        # Check dependencies
        if not HAS_SOUNDDEVICE:
            raise ImportError("sounddevice is required for audio capture")
        if not HAS_OPUS and not HAS_AV:
            raise ImportError("opuslib or av (PyAV) is required for audio encoding")
    
    def _initialize_encoder(self):
        """Initialize the Opus encoder."""
        if HAS_OPUS:
            self.encoder = Encoder(
                self.SAMPLE_RATE,
                self.CHANNELS,
                self.OPUS_APPLICATION
            )
            self.encoder.bitrate = self.OPUS_BITRATE
        elif HAS_AV:
            # Create a PyAV Opus encoder using container
            self.encoder_container = av.open('', format='null', mode='w')
            self.encoder = self.encoder_container.add_stream(
                'libopus', 
                rate=self.SAMPLE_RATE,
                layout='mono'  # Set layout for channels
            )
            self.encoder.bit_rate = self.OPUS_BITRATE
    
    def _initialize_decoder(self):
        """Initialize the Opus decoder for playback."""
        if self.decoder is None:
            if HAS_OPUS:
                self.decoder = Decoder(self.SAMPLE_RATE, self.CHANNELS)
            elif HAS_AV:
                # PyAV decoder - use Codec directly
                self.decoder = av.Codec('libopus', 'r').create()
    
    def _encode_frame(self, audio_data: np.ndarray) -> bytes:
        """Encode audio frame to Opus."""
        if HAS_OPUS:
            # Convert to int16
            audio_int16 = (audio_data * 32767).astype(np.int16)
            # Encode
            encoded = self.encoder.encode(audio_int16.tobytes(), self.SAMPLES_PER_FRAME)
            return encoded
        elif HAS_AV:
            # Create a PyAV frame - ensure 2D array
            if audio_data.ndim == 1:
                audio_data = audio_data.reshape(1, -1)
            frame = av.AudioFrame.from_ndarray(audio_data, format='fltp', layout='mono')
            frame.sample_rate = self.SAMPLE_RATE
            # time_base should be a Fraction object (1/48000)
            from fractions import Fraction
            frame.time_base = Fraction(1, self.SAMPLE_RATE)
            
            # Encode
            for packet in self.encoder.encode(frame):
                return bytes(packet)
            return b''
        return b''
    
    def _create_packet_header(self) -> bytes:
        """Create packet header with sequence, timestamp, and uid."""
        timestamp = int(time.time() * 1000)  # milliseconds
        # Header format: seq (4 bytes), timestamp (8 bytes), uid (4 bytes)
        # Ensure uid is not None
        uid = self.uid if self.uid is not None else 0
        header = struct.pack('>I Q I', self.sequence_number, timestamp, uid)
        self.sequence_number += 1
        return header
    
    def _audio_callback(self, indata, frames, time_info, status):
        """Callback for audio capture."""
        if status:
            print(f"[AUDIO] Status: {status}")
        
        if not self.is_recording:
            return
        
        try:
            # Convert to float32
            audio_data = indata[:, 0].astype(np.float32)  # Take first channel if stereo
            
            # Encode the frame
            encoded = self._encode_frame(audio_data)
            
            if encoded:
                # Create packet
                header = self._create_packet_header()
                packet = header + encoded
                
                # Send via UDP (non-blocking)
                try:
                    self.socket.sendto(packet, (self.server_ip, self.server_port))
                except Exception as e:
                    print(f"[AUDIO] Error sending packet: {e}")
        
        except Exception as e:
            import traceback
            print(f"[AUDIO] Error in audio callback: {e}")
            traceback.print_exc()
    
    def _decode_frame(self, encoded_data: bytes) -> Optional[np.ndarray]:
        """Decode Opus frame to raw audio."""
        try:
            if self.decoder is None:
                self._initialize_decoder()
            
            if HAS_OPUS:
                pcm_data = self.decoder.decode(encoded_data, self.SAMPLES_PER_FRAME)
                audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)
                audio = audio_int16.astype(np.float32) / 32768.0
                return audio
            elif HAS_AV:
                # Server sends raw PCM int16 when using PyAV
                audio_int16 = np.frombuffer(encoded_data, dtype=np.int16)
                audio = audio_int16.astype(np.float32) / 32768.0
                audio = np.clip(audio, -1.0, 1.0)
                return audio
        except Exception as e:
            print(f"[AUDIO] Error decoding frame: {e}")
        return None
    
    def _output_audio_callback(self, outdata, frames, time_info, status):
        """Callback for audio playback."""
        if status:
            print(f"[AUDIO PLAYBACK] Status: {status}")
        
        try:
            with self.jitter_buffer_lock:
                if len(self.jitter_buffer) > 0:
                    audio_frame = self.jitter_buffer.pop(0)
                    outdata[:, 0] = audio_frame[:frames]
                else:
                    # No data, output silence
                    outdata[:, 0] = np.zeros(frames, dtype=np.float32)
        except Exception as e:
            print(f"[AUDIO] Error in playback callback: {e}")
            outdata[:, 0] = np.zeros(frames, dtype=np.float32)
    
    def _receive_audio(self):
        """Thread worker to receive and decode audio from server."""
        buffer_size = 65536
        
        while self.is_recording:
            try:
                data, addr = self.receive_socket.recvfrom(buffer_size)
                
                # Decode audio frame
                audio_frame = self._decode_frame(data)
                
                if audio_frame is not None and len(audio_frame) > 0:
                    # Add to jitter buffer
                    with self.jitter_buffer_lock:
                        self.jitter_buffer.append(audio_frame)
                        
                        # Limit buffer size to prevent memory issues
                        if len(self.jitter_buffer) > self.jitter_buffer_size * 2:
                            # Drop oldest frames if buffer is too large
                            self.jitter_buffer = self.jitter_buffer[-self.jitter_buffer_size:]
            
            except Exception as e:
                if self.is_recording:
                    print(f"[AUDIO] Error receiving audio: {e}")
    
    def start_recording(self):
        """Start audio recording and transmission."""
        if self.is_recording:
            return
        
        try:
            # Initialize encoder
            self._initialize_encoder()
            self._initialize_decoder()
            
            # Create UDP sockets
            import socket as socket_module
            self.socket = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
            self.receive_socket = socket_module.socket(socket_module.AF_INET, socket_module.SOCK_DGRAM)
            
            # Bind receive socket to a random port
            self.receive_socket.bind(('', 0))  # Let OS assign port
            recv_port = self.receive_socket.getsockname()[1]
            
            # Start input audio stream (capture)
            self.stream = sd.InputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                blocksize=self.SAMPLES_PER_FRAME,
                dtype='float32',
                callback=self._audio_callback
            )
            
            # Start output audio stream (playback)
            self.output_stream = sd.OutputStream(
                samplerate=self.SAMPLE_RATE,
                channels=self.CHANNELS,
                blocksize=self.SAMPLES_PER_FRAME,
                dtype='float32',
                callback=self._output_audio_callback
            )
            
            self.is_recording = True
            self.stream.start()
            self.output_stream.start()
            
            # Start receive thread
            self.receive_thread = threading.Thread(target=self._receive_audio, daemon=True)
            self.receive_thread.start()
            
            print(f"[AUDIO] Started recording. Sending to {self.server_ip}:{self.server_port}")
            print(f"[AUDIO] Receiving audio on port {recv_port}")
            print(f"[AUDIO] Sample rate: {self.SAMPLE_RATE} Hz, Channels: {self.CHANNELS}")
            print(f"[AUDIO] Frame duration: {self.FRAME_DURATION_MS} ms")
        
        except Exception as e:
            print(f"[AUDIO] Error starting recording: {e}")
            self.is_recording = False
    
    def stop_recording(self):
        """Stop audio recording and transmission."""
        if not self.is_recording:
            return
        
        self.is_recording = False
        
        # Stop audio streams
        if self.stream:
            self.stream.stop()
            self.stream.close()
            self.stream = None
        
        if self.output_stream:
            self.output_stream.stop()
            self.output_stream.close()
            self.output_stream = None
        
        # Close sockets
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
        
        if self.receive_socket:
            try:
                self.receive_socket.close()
            except:
                pass
            self.receive_socket = None
        
        # Wait for receive thread
        if self.receive_thread and self.receive_thread.is_alive():
            self.receive_thread.join(timeout=1.0)
        
        # Clean up encoders/decoders
        self.encoder = None
        self.decoder = None
        
        print("[AUDIO] Stopped recording")
    
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
