#!/usr/bin/env python3
"""
Audio Server - Receives, mixes, and broadcasts audio to clients.

This module implements a UDP audio server that receives encoded audio from clients,
mixes them together, and broadcasts the mixed audio back to all clients.
"""

import asyncio
import struct
import threading
import time
import argparse
import socket
from typing import Dict, Tuple, Optional, Any
from collections import defaultdict, deque
import numpy as np

try:
    from opuslib import Decoder, Encoder
    HAS_OPUS = True
    HAS_AV = False  # Prefer opuslib if available
# Handle import failures: ImportError/ModuleNotFoundError when opuslib is missing,
# AttributeError when Decoder/Encoder don't exist in opuslib
except (ImportError, ModuleNotFoundError, AttributeError) as e:
    HAS_OPUS = False
    try:
        import av
        HAS_AV = True
        print("[WARNING] Using PyAV (av) for Opus - may have limitations")
    except ImportError:
        HAS_AV = False
        print("[WARNING] Neither opuslib nor av (PyAV) is installed. Audio processing will not work.")
        print("Install with: pip install opuslib or pip install av")


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
    SAMPLE_RATE = 48000  # Hz
    CHANNELS = 1  # Mono
    FRAME_DURATION_MS = 40  # ms
    SAMPLES_PER_FRAME = (SAMPLE_RATE * FRAME_DURATION_MS) // 1000  # 1920 samples
    BYTES_PER_SAMPLE = 2  # 16-bit audio
    
    # Opus settings
    OPUS_APPLICATION = 2048  # OPUS_APPLICATION_VOIP
    OPUS_BITRATE = 64000  # 64 kbps
    
    # Timeout
    CLIENT_TIMEOUT = 10.0  # seconds
    
    def __init__(self, host: str = '0.0.0.0', port: int = 11000):
        """Initialize the audio server."""
        self.host = host
        self.port = port
        
        # Clients
        self.clients: Dict[int, ClientInfo] = {}  # uid -> ClientInfo
        self.client_lock = threading.Lock()
        
        # Audio processing
        self.decoders: Dict[int, Any] = {}  # uid -> decoder
        self.mixer_encoder = None
        
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
        self.MAX_LATE_MS = 250  # Drop packets more than 250ms late to align with real-time voice latency guidelines
        self.last_timestamp_by_client: Dict[int, int] = {}
        
        # Check dependencies
        if not HAS_OPUS and not HAS_AV:
            raise ImportError("opuslib or av (PyAV) is required for audio processing")
        
        # Require opuslib for server (more reliable Opus support)
        if not HAS_OPUS:
            raise ImportError(
                "opuslib is required for the audio server. "
                "Please install with: pip install opuslib"
            )
    
    def _initialize_decoder(self, uid: int):
        """Initialize Opus decoder for a client."""
        if uid not in self.decoders:
            # Only opuslib is supported (PyAV path fails fast during initialization)
            if HAS_OPUS:
                self.decoders[uid] = Decoder(self.SAMPLE_RATE, self.CHANNELS)
    
    def _initialize_mixer_encoder(self):
        """Initialize the encoder for mixed audio."""
        if self.mixer_encoder is None:
            # Only opuslib is supported (PyAV path fails fast during initialization)
            if HAS_OPUS:
                self.mixer_encoder = Encoder(
                    self.SAMPLE_RATE,
                    self.CHANNELS,
                    self.OPUS_APPLICATION
                )
                self.mixer_encoder.bitrate = self.OPUS_BITRATE
    
    def _decode_frame(self, uid: int, encoded_data: bytes) -> Optional[np.ndarray]:
        """Decode Opus frame to raw audio."""
        try:
            if uid not in self.decoders:
                self._initialize_decoder(uid)
            
            decoder = self.decoders[uid]
            
            # Decode using opuslib (PyAV path fails fast during initialization)
            if HAS_OPUS:
                # Decode
                pcm_data = decoder.decode(encoded_data, self.SAMPLES_PER_FRAME)
                # Convert bytes to numpy array
                audio_int16 = np.frombuffer(pcm_data, dtype=np.int16)
                # Normalize to float32 [-1.0, 1.0]
                audio = audio_int16.astype(np.float32) / 32768.0
                return audio
            
        except Exception as e:
            print(f"[AUDIO SERVER] Error decoding frame for uid={uid}: {e}")
        
        return None
    
    def _encode_frame(self, audio_data: np.ndarray) -> bytes:
        """Encode mixed audio frame to Opus."""
        if self.mixer_encoder is None:
            self._initialize_mixer_encoder()
        
        try:
            # Only opuslib is supported (PyAV path fails fast during initialization)
            if HAS_OPUS:
                # Convert to int16 with proper scaling and clipping
                audio_int16 = np.clip(audio_data * 32768.0, -32768.0, 32767.0).astype(np.int16)
                # Encode
                encoded = self.mixer_encoder.encode(audio_int16.tobytes(), len(audio_data))
                return encoded
        
        except Exception as e:
            print(f"[AUDIO SERVER] Error encoding frame: {e}")
        
        return b''
    
    def _is_packet_late(self, uid: int, timestamp: int) -> bool:
        """Check if packet is late and should be dropped."""
        if uid in self.last_timestamp_by_client:
            last_timestamp = self.last_timestamp_by_client[uid]
            time_diff = timestamp - last_timestamp
            # If timestamp is significantly behind, consider it late
            if time_diff < -self.MAX_LATE_MS:
                return True
            
            # Update last timestamp for any forward progress
            if time_diff >= 0:
                self.last_timestamp_by_client[uid] = timestamp
        else:
            self.last_timestamp_by_client[uid] = timestamp
        
        return False
    
    async def handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming UDP packet from client."""
        try:
            # Parse header: seq (4 bytes), timestamp (8 bytes), uid (4 bytes)
            if len(data) < 16:
                print(f"[AUDIO SERVER] Packet too short: {len(data)} bytes from {addr}")
                return

            header = data[:16]
            payload = data[16:]

            seq, timestamp, uid = struct.unpack('>I Q I', header)
            print(f"[AUDIO SERVER] Processing packet: seq={seq}, uid={uid}, payload_size={len(payload)} from {addr}")

            # Update or add client
            with self.client_lock:
                if uid in self.clients:
                    client = self.clients[uid]
                    client.address = addr
                    client.last_packet_time = time.time()

                    # Check for dropped packets using RFC1982-style modular arithmetic for uint32
                    seq_uint32 = seq & 0xFFFFFFFF
                    expected_uint32 = client.expected_sequence & 0xFFFFFFFF
                    diff = (seq_uint32 - expected_uint32) & 0xFFFFFFFF

                    if diff == 0:
                        # Duplicate packet - skip processing
                        print(f"[AUDIO SERVER] Duplicate packet from uid={uid}: seq={seq}")
                        return
                    elif diff == 1:
                        # In-order packet
                        client.expected_sequence = (seq + 1) & 0xFFFFFFFF
                        client.received_packets += 1
                        print(f"[AUDIO SERVER] In-order packet from uid={uid}: seq={seq}")
                    elif diff > 1 and diff <= 0x7FFFFFFF:
                        # Forward gap - count dropped packets
                        client.dropped_packets += (diff - 1)
                        client.expected_sequence = (seq + 1) & 0xFFFFFFFF
                        client.received_packets += 1
                        print(f"[AUDIO SERVER] Gap detected from uid={uid}: dropped {diff-1} packets")
                    else:
                        # Backward/old packet - drop it
                        client.dropped_packets += 1
                        print(f"[AUDIO SERVER] Dropped backward packet from uid={uid}: seq={seq}, expected={client.expected_sequence}, diff={diff}")
                        return
                else:
                    # New client
                    client = ClientInfo(uid, addr)
                    client.expected_sequence = (seq + 1) & 0xFFFFFFFF
                    client.received_packets = 1
                    self.clients[uid] = client
                    print(f"[AUDIO SERVER] New client connected: uid={uid} from {addr}")

            # Check if packet is late (after releasing lock to avoid blocking)
            if self._is_packet_late(uid, timestamp):
                with self.client_lock:
                    if uid in self.clients:
                        self.clients[uid].dropped_packets += 1
                print(f"[AUDIO SERVER] Dropped late packet from uid={uid}: timestamp={timestamp}")
                return

            # Decode audio frame
            audio_data = self._decode_frame(uid, payload)
            if audio_data is None or len(audio_data) == 0:
                print(f"[AUDIO SERVER] Failed to decode audio frame from uid={uid}")
                return

            # Log input audio levels
            rms_level = np.sqrt(np.mean(audio_data**2))
            print(f"[AUDIO SERVER] Decoded audio RMS: {rms_level:.4f} from uid={uid}")

            # Apply client volume and mute (read atomically with lock)
            with self.client_lock:
                if uid not in self.clients:
                    # Client was removed while decoding
                    return
                local_client = self.clients[uid]
                local_muted = local_client.muted
                local_volume = local_client.volume

            # Apply the local muted/volume values to audio_data
            if local_muted:
                audio_data = np.zeros_like(audio_data)
                print(f"[AUDIO SERVER] Applied mute to uid={uid}")
            else:
                audio_data = audio_data * local_volume
                print(f"[AUDIO SERVER] Applied volume {local_volume:.2f} to uid={uid}")

            # Add to mix queue
            with self.mix_queue_lock:
                self.mix_queue.append((uid, audio_data, timestamp))
                print(f"[AUDIO SERVER] Added frame to mix queue, queue size: {len(self.mix_queue)}")

        except Exception as e:
            print(f"[AUDIO SERVER] Error handling packet from {addr}: {e}")
            import traceback
            traceback.print_exc()
    
    def _mixing_thread_worker(self):
        """Thread worker that mixes audio frames.
        
        Note: This is a real-time audio thread running on a strict 40ms schedule.
        Logging is minimized to avoid I/O operations that could cause jitter or dropped frames.
        """
        frame_interval = self.FRAME_DURATION_MS / 1000.0
        mix_count = 0
        # Use DEBUG flag to enable verbose logging (disabled in production for performance)
        DEBUG_AUDIO_MIXING = False

        while self.running:
            try:
                start_time = time.time()
                mix_count += 1

                # Gather frames for this mixing period
                frames_to_mix = []
                with self.mix_queue_lock:
                    while len(self.mix_queue) > 0:
                        uid, audio_data, timestamp = self.mix_queue.popleft()
                        frames_to_mix.append((uid, audio_data, timestamp))

                if DEBUG_AUDIO_MIXING:
                    print(f"[AUDIO SERVER] Mix cycle {mix_count}: processing {len(frames_to_mix)} frames")

                if len(frames_to_mix) == 0:
                    # No frames to mix, create silence
                    mixed_audio = np.zeros(self.SAMPLES_PER_FRAME, dtype=np.float32)
                    if DEBUG_AUDIO_MIXING:
                        print("[AUDIO SERVER] No frames to mix - sending silence")
                else:
                    # Mix all frames (sum with clipping)
                    mixed_audio = np.zeros(self.SAMPLES_PER_FRAME, dtype=np.float32)

                    for uid, audio_data, timestamp in frames_to_mix:
                        # Ensure audio_data matches expected length
                        if len(audio_data) == self.SAMPLES_PER_FRAME:
                            mixed_audio += audio_data
                            if DEBUG_AUDIO_MIXING:
                                print(f"[AUDIO SERVER] Added uid={uid} to mix")
                        else:
                            # Log errors even in production
                            print(f"[AUDIO SERVER] Skipped uid={uid} - wrong frame size: {len(audio_data)}")

                    # Improved mixing: Use square-root normalization for better volume consistency
                    # This maintains audible output even with many clients
                    num_clients = len([f for f in frames_to_mix])
                    if num_clients > 0:
                        # Use sqrt of num_clients to reduce volume drop with many clients
                        normalization_factor = 1.0 / np.sqrt(num_clients) if num_clients > 1 else 1.0
                        mixed_audio = mixed_audio * normalization_factor
                        if DEBUG_AUDIO_MIXING:
                            print(f"[AUDIO SERVER] Normalized by sqrt({num_clients})={normalization_factor:.3f}")

                    # Clip to prevent overflow
                    mixed_audio = np.clip(mixed_audio, -1.0, 1.0)

                    if DEBUG_AUDIO_MIXING:
                        # Log output levels only in debug mode
                        rms_level = np.sqrt(np.mean(mixed_audio**2))
                        print(f"[AUDIO SERVER] Mixed audio RMS: {rms_level:.4f}")

                # Encode mixed audio
                encoded = self._encode_frame(mixed_audio)

                if encoded:
                    if DEBUG_AUDIO_MIXING:
                        print(f"[AUDIO SERVER] Encoded mixed frame: {len(encoded)} bytes")
                    # Broadcast to all clients
                    with self.client_lock:
                        active_clients = list(self.clients.values())
                        if DEBUG_AUDIO_MIXING:
                            print(f"[AUDIO SERVER] Broadcasting to {len(active_clients)} clients")
                        for client in active_clients:
                            try:
                                self.socket.sendto(encoded, client.address)
                                if DEBUG_AUDIO_MIXING:
                                    print(f"[AUDIO SERVER] Sent to uid={client.uid} at {client.address}")
                            except Exception as e:
                                # Always log errors
                                print(f"[AUDIO SERVER] Error broadcasting to {client.address}: {e}")
                else:
                    # Always log encoding failures
                    print("[AUDIO SERVER] Encoding failed - no broadcast")

                # Sleep to maintain frame rate
                elapsed = time.time() - start_time
                sleep_time = max(0, frame_interval - elapsed)
                if DEBUG_AUDIO_MIXING:
                    print(f"[AUDIO SERVER] Mix cycle took {elapsed:.3f}s, sleeping {sleep_time:.3f}s")
                
                # Critical: Maintain real-time schedule by sleeping only as needed
                if sleep_time > 0:
                    time.sleep(sleep_time)

            except Exception as e:
                print(f"[AUDIO SERVER] Error in mixing thread: {e}")
                import traceback
                traceback.print_exc()
                time.sleep(0.001)  # Brief pause before retry
    
    def _cleanup_timeout_clients(self):
        """Remove clients that haven't sent packets recently."""
        current_time = time.time()
        
        with self.client_lock:
            clients_to_remove = []
            for uid, client in self.clients.items():
                if current_time - client.last_packet_time > self.CLIENT_TIMEOUT:
                    clients_to_remove.append(uid)
            
            for uid in clients_to_remove:
                del self.clients[uid]
                if uid in self.decoders:
                    del self.decoders[uid]
                print(f"[AUDIO SERVER] Client timed out: uid={uid}")
    
    async def start(self):
        """Start the audio server."""
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.socket.bind((self.host, self.port))
        self.socket.setblocking(False)
        
        self.running = True
        
        # Start mixing thread
        self.mixing_thread = threading.Thread(target=self._mixing_thread_worker, daemon=True)
        self.mixing_thread.start()
        
        print(f"[AUDIO SERVER] Listening on {self.host}:{self.port}")
        print(f"[AUDIO SERVER] Sample rate: {self.SAMPLE_RATE} Hz, Channels: {self.CHANNELS}")
        print(f"[AUDIO SERVER] Frame duration: {self.FRAME_DURATION_MS} ms")
        
        # Start periodic cleanup
        async def cleanup_task():
            while self.running:
                await asyncio.sleep(5)
                self._cleanup_timeout_clients()
        
        self.cleanup_task = asyncio.create_task(cleanup_task())
        
        # Main receive loop
        loop = asyncio.get_event_loop()
        while self.running:
            try:
                data, addr = await loop.sock_recvfrom(self.socket, 65536)
                await self.handle_packet(data, addr)
            except Exception as e:
                if self.running:
                    print(f"[AUDIO SERVER] Error in receive loop: {e}")
    
    def stop(self):
        """Stop the audio server."""
        self.running = False
        
        # Cancel cleanup task
        if self.cleanup_task and not self.cleanup_task.done():
            self.cleanup_task.cancel()
        
        if self.socket:
            self.socket.close()
        
        # Wait for mixing thread
        if self.mixing_thread:
            self.mixing_thread.join(timeout=2.0)
        
        # Clear decoders
        self.decoders.clear()
        
        # Clear clients
        with self.client_lock:
            self.clients.clear()
        
        # Clear mix queue
        with self.mix_queue_lock:
            self.mix_queue.clear()
        
        # Clear last timestamp tracking
        self.last_timestamp_by_client.clear()
        
        print("[AUDIO SERVER] Stopped")


async def run_server(host: str, port: int):
    """Run the audio server."""
    server = AudioServer(host=host, port=port)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        print("\n[AUDIO SERVER] Shutting down...")
    finally:
        server.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Audio Server - Mixes and broadcasts audio')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=11000,
                       help='UDP port to listen on (default: 11000)')
    
    args = parser.parse_args()
    
    # Import socket here for compatibility
    import socket
    
    try:
        asyncio.run(run_server(args.host, args.port))
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
