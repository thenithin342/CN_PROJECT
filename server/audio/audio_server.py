#!/usr/bin/env python3
"""
Audio Server - Receives, mixes, and broadcasts audio to clients.

This module implements a UDP audio server that receives raw PCM audio from clients,
mixes them together, and broadcasts the mixed audio back to all clients.
"""

import struct
import threading
import time
import argparse
import socket
from typing import Dict, Tuple, Optional
from collections import deque
import numpy as np


class ClientInfo:
    """Information about a connected audio client."""
    
    def __init__(self, uid: int, address: Tuple[str, int]):
        self.uid = uid
        self.address = address
        self.volume = 1.0  # 0.0 to 1.0
        self.muted = False
        self.last_packet_time = time.time()
        self.expected_sequence = 0
        self.received_packets = 0
        self.dropped_packets = 0


class AudioServer:
    """Server for mixing and broadcasting audio to multiple clients."""
    
    # Audio settings (must match client)
    SAMPLE_RATE = 16000  # Hz (reduced for pyaudio compatibility)
    CHANNELS = 1  # Mono
    CHUNK_SIZE = 1600  # Samples per chunk (100ms at 16kHz)
    BYTES_PER_SAMPLE = 2  # 16-bit audio
    
    # Timeout
    CLIENT_TIMEOUT = 10.0  # seconds
    
    def __init__(self, host: str = '0.0.0.0', port: int = 11000):
        """Initialize the audio server."""
        self.host = host
        self.port = port
        
        # Clients
        self.clients: Dict[int, ClientInfo] = {}  # uid -> ClientInfo
        self.client_lock = threading.Lock()
        
        # UDP socket
        self.socket = None
        self.running = False
        
        # Mixing thread
        self.mixing_thread = None
        self.mix_queue = deque()
        self.mix_queue_lock = threading.Lock()
        
        # Cleanup task
        self.cleanup_task = None
        
        # Late packet detection
        self.MAX_LATE_MS = 250
        self.last_timestamp_by_client: Dict[int, int] = {}
        
        # Client audio buffers
        self.client_audio: Dict[int, np.ndarray] = {}
        self.audio_lock = threading.Lock()
    
    def _parse_packet_header(self, data: bytes) -> Optional[Tuple]:
        """Parse packet header: (sequence, timestamp, uid, payload)."""
        if len(data) < 16:
            return None
        sequence, timestamp, uid = struct.unpack('>I Q I', data[:16])
        return (sequence, timestamp, uid, data[16:])
    
    def _start_mixing(self):
        """Start the audio mixing loop."""
        while self.running:
            try:
                # Get all clients
                with self.client_lock:
                    clients = list(self.clients.keys())
                
                if len(clients) <= 1:
                    # Not enough clients to mix
                    time.sleep(0.01)
                    continue
                
                # Mix audio for all clients
                for uid in clients:
                    # Get all other clients' audio
                    other_clients = [cuid for cuid in clients if cuid != uid]
                    
                    if not other_clients:
                        continue
                    
                    # Mix audio
                    mixed_audio = None
                    for other_uid in other_clients:
                        with self.audio_lock:
                            if other_uid in self.client_audio:
                                other_audio = self.client_audio[other_uid]
                                
                                if mixed_audio is None:
                                    mixed_audio = other_audio.copy()
                                else:
                                    # Add audio with saturation
                                    mixed_audio = np.clip(mixed_audio + other_audio, -1.0, 1.0)
                    
                    # Send mixed audio to this client
                    if mixed_audio is not None:
                        try:
                            with self.client_lock:
                                if uid in self.clients:
                                    client_info = self.clients[uid]
                                    
                            if not client_info.muted:
                                # Convert to int16
                                audio_int16 = (mixed_audio * 32768.0).astype(np.int16)
                                audio_bytes = audio_int16.tobytes()
                                
                                # Create packet
                                timestamp = int(time.time() * 1000)
                                header = struct.pack('>I Q I', 0, timestamp, 0)
                                packet = header + audio_bytes
                                
                                # Send to client
                                self.socket.sendto(packet, client_info.address)
                        except Exception as e:
                            print(f"[AUDIO SERVER] Error sending to client {uid}: {e}")
                
                time.sleep(0.01)
            
            except Exception as e:
                print(f"[AUDIO SERVER] Error in mixing loop: {e}")
    
    def _start_cleanup(self):
        """Clean up inactive clients periodically."""
        while self.running:
            try:
                current_time = time.time()
                inactive_uids = []
                
                with self.client_lock:
                    for uid, client_info in self.clients.items():
                        if current_time - client_info.last_packet_time > self.CLIENT_TIMEOUT:
                            inactive_uids.append(uid)
                    
                    for uid in inactive_uids:
                        print(f"[AUDIO SERVER] Client {uid} timed out")
                        del self.clients[uid]
                
                # Clean up audio buffers for inactive clients
                with self.audio_lock:
                    for uid in inactive_uids:
                        if uid in self.client_audio:
                            del self.client_audio[uid]
                
                time.sleep(1.0)
            
            except Exception as e:
                print(f"[AUDIO SERVER] Error in cleanup task: {e}")
    
    def _handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming audio packet."""
        header_info = self._parse_packet_header(data)
        if header_info is None:
            return
        
        sequence, timestamp, uid, payload = header_info
        
        # Update client info
        with self.client_lock:
            if uid not in self.clients:
                self.clients[uid] = ClientInfo(uid, addr)
                print(f"[AUDIO SERVER] New client: uid={uid}")
            else:
                self.clients[uid].address = addr
            
            client_info = self.clients[uid]
            client_info.last_packet_time = time.time()
            client_info.received_packets += 1
        
        # Store audio data
        audio_int16 = np.frombuffer(payload, dtype=np.int16)
        audio_float = audio_int16.astype(np.float32) / 32768.0
        
        with self.audio_lock:
            self.client_audio[uid] = audio_float
    
    def start(self):
        """Start the audio server."""
        print(f"[AUDIO SERVER] Starting audio server on {self.host}:{self.port}")
        
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.host, self.port))
        self.socket.settimeout(1.0)
        
        self.running = True
        
        # Start mixing thread
        self.mixing_thread = threading.Thread(target=self._start_mixing, daemon=True)
        self.mixing_thread.start()
        
        # Start cleanup thread
        self.cleanup_task = threading.Thread(target=self._start_cleanup, daemon=True)
        self.cleanup_task.start()
        
        print(f"[AUDIO SERVER] Server started on {self.host}:{self.port}")
        
        # Receive loop
        buffer_size = 65536
        while self.running:
            try:
                data, addr = self.socket.recvfrom(buffer_size)
                self._handle_packet(data, addr)
            except socket.timeout:
                continue
            except Exception as e:
                if self.running:
                    print(f"[AUDIO SERVER] Error receiving packet: {e}")
    
    def stop(self):
        """Stop the audio server."""
        print("[AUDIO SERVER] Stopping...")
        self.running = False
        
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
        
        if self.mixing_thread:
            self.mixing_thread.join(timeout=1.0)
        
        if self.cleanup_task:
            self.cleanup_task.join(timeout=1.0)
        
        print("[AUDIO SERVER] Stopped")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Audio Server - Mixes and broadcasts audio')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=11000,
                       help='UDP port (default: 11000)')
    
    args = parser.parse_args()
    
    server = AudioServer(host=args.host, port=args.port)
    
    try:
        server.start()
    except KeyboardInterrupt:
        print("\n[AUDIO SERVER] Shutting down...")
        server.stop()
    except Exception as e:
        print(f"[ERROR] {e}")
        server.stop()


if __name__ == "__main__":
    main()
