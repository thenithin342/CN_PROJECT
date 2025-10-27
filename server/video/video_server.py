#!/usr/bin/env python3
"""
Video Server - Receives video packets and broadcasts to all clients.

This module implements a UDP video server that receives chunked video packets
from clients, reassembles them into complete frames, and broadcasts the
complete frames to all other clients.
"""

import asyncio
import socket
import argparse
import struct
import time
import threading
from typing import Dict, Tuple, Optional, List
from collections import defaultdict, deque


class VideoFrameChunk:
    """Represents a chunk of a video frame."""
    
    def __init__(self, uid: int, frame_id: int, chunk_idx: int, total_chunks: int,
                 seq: int, timestamp: int, chunk_size: int, data: bytes):
        """
        Initialize a video frame chunk.
        
        Args:
            uid: User ID who sent the frame
            frame_id: Unique ID for the frame
            chunk_idx: Index of this chunk (0-based)
            total_chunks: Total number of chunks in the frame
            seq: Sequence number
            timestamp: Timestamp in milliseconds
            chunk_size: Size of chunk data in bytes
            data: Chunk data
        """
        self.uid = uid
        self.frame_id = frame_id
        self.chunk_idx = chunk_idx
        self.total_chunks = total_chunks
        self.seq = seq
        self.timestamp = timestamp
        self.chunk_size = chunk_size
        self.data = data


class AssembledFrame:
    """Represents a complete assembled video frame."""
    
    def __init__(self, uid: int, frame_id: int, timestamp: int, data: bytes):
        """Initialize an assembled frame."""
        self.uid = uid
        self.frame_id = frame_id
        self.timestamp = timestamp
        self.data = data


class ClientVideoInfo:
    """Information about a video client."""

    def __init__(self, uid: int, address: Tuple[str, int]):
        """Initialize client info."""
        self.uid = uid
        self.address = address  # Client's IP and port for sending chunks
        self.last_packet_time = time.time()
        self.received_frames = 0
        self.total_bytes = 0


class VideoServer:
    """Server for receiving and broadcasting video to multiple clients."""
    
    # Timeout settings
    CLIENT_TIMEOUT = 10.0  # seconds
    CHUNK_TIMEOUT = 5.0  # seconds for chunk reassembly (increased for slower networks)
    
    # Header format size
    CHUNK_HEADER_SIZE = 36  # bytes (increased for receive port)
    
    # Resource limits
    MAX_FRAMES_PER_CLIENT = 50  # Maximum concurrent frames per client (increased to handle burst)
    MAX_FRAME_SIZE = 10 * 1024 * 1024  # 10MB max frame size
    MAX_CHUNKS = 100  # Maximum chunks per frame (10MB / 100KB typical chunk)
    MAX_CHUNK_SIZE = 1024 * 1024  # 1MB max chunk size
    
    # Broadcast port (not used anymore - we send to each client's ephemeral port)
    BROADCAST_PORT = 10001
    
    def __init__(self, host: str = '0.0.0.0', port: int = 10000):
        """
        Initialize the video server.
        
        Args:
            host: Host to bind to
            port: UDP port to listen on
        """
        self.host = host
        self.port = port
        
        # UDP sockets
        self.receive_socket = None  # For receiving chunks (port 10000)
        self.broadcast_socket = None  # For broadcasting frames (bound to port 10001 for sending)
        self.running = False
        
        # Clients
        self.clients: Dict[int, ClientVideoInfo] = {}  # uid -> ClientVideoInfo
        self.client_lock = threading.Lock()
        
        # Chunk reassembly buffers
        # Structure: {uid: {frame_id: [chunks, total_chunks, remaining_count]}}
        # Optimized: Use pre-allocated list instead of sorting
        self.chunk_buffers: Dict[int, Dict[int, tuple]] = defaultdict(dict)
        self.chunk_timeouts: Dict[int, Dict[int, float]] = defaultdict(dict)
        self.chunk_lock = threading.Lock()
        
        # Broadcasting
        self.broadcast_queue = deque()
        self.broadcast_lock = threading.Lock()
    
    def _parse_chunk_header(self, data: bytes) -> Optional[Tuple]:
        """
        Parse chunk header from packet data.
        
        Returns:
            Tuple of (uid, frame_id, chunk_idx, total_chunks, seq, timestamp, chunk_size, payload)
            or None if header is invalid
        """
        if len(data) < self.CHUNK_HEADER_SIZE:
            return None
        
        header = data[:self.CHUNK_HEADER_SIZE]
        payload = data[self.CHUNK_HEADER_SIZE:]
        
        try:
            uid, frame_id, chunk_idx, total_chunks, seq, timestamp, chunk_size, receive_port = struct.unpack('>I I I I I Q I I', header)
        except struct.error as e:
            print(f"[VIDEO SERVER] Error parsing header: {e}")
            return None
        
        # Validate payload size matches chunk_size
        if len(payload) != chunk_size:
            print(f"[VIDEO SERVER] Invalid packet: chunk_size mismatch (header={chunk_size}, actual={len(payload)})")
            return None
        
        # Validate total_chunks is within bounds
        if total_chunks <= 0 or total_chunks > self.MAX_CHUNKS:
            print(f"[VIDEO SERVER] Invalid packet: total_chunks out of range ({total_chunks}, max={self.MAX_CHUNKS})")
            return None
        
        # Validate chunk_idx is within bounds
        if chunk_idx < 0 or chunk_idx >= total_chunks:
            print(f"[VIDEO SERVER] Invalid packet: chunk_idx out of range ({chunk_idx}, total={total_chunks})")
            return None
        
        # Validate chunk_size is within bounds
        if chunk_size < 0 or chunk_size > self.MAX_CHUNK_SIZE:
            print(f"[VIDEO SERVER] Invalid packet: chunk_size out of range ({chunk_size}, max={self.MAX_CHUNK_SIZE})")
            return None
        
        return (uid, frame_id, chunk_idx, total_chunks, seq, timestamp, chunk_size, receive_port, payload)
    
    def _process_chunk(self, chunk: VideoFrameChunk, addr: Tuple[str, int]):
        """
        Process a received chunk and attempt to reassemble frame.
        
        Optimized: Use pre-allocated list instead of sorting.
        
        Args:
            chunk: The video frame chunk
            addr: Source address
        """
        with self.chunk_lock:
            # Initialize chunk buffer for this uid if needed
            if chunk.uid not in self.chunk_buffers:
                self.chunk_buffers[chunk.uid] = {}
                self.chunk_timeouts[chunk.uid] = {}
            
            # Initialize chunk buffer for this frame_id if needed
            if chunk.frame_id not in self.chunk_buffers[chunk.uid]:
                # Check per-client frame limit
                if len(self.chunk_buffers[chunk.uid]) >= self.MAX_FRAMES_PER_CLIENT:
                    print(f"[VIDEO SERVER] Discarding frame {chunk.frame_id} from uid={chunk.uid}: too many concurrent frames (max={self.MAX_FRAMES_PER_CLIENT})")
                    return
                
                # Estimate frame size and check against max
                estimated_size = chunk.total_chunks * chunk.chunk_size
                if estimated_size > self.MAX_FRAME_SIZE:
                    print(f"[VIDEO SERVER] Discarding frame {chunk.frame_id} from uid={chunk.uid}: estimated size {estimated_size} exceeds limit {self.MAX_FRAME_SIZE}")
                    return
                
                # Pre-allocate list of None values for all chunks
                chunk_list = [None] * chunk.total_chunks
                # Store: (chunk_list, total_chunks, chunk_size, remaining_count)
                # We store chunk_size to validate incoming chunks match the original
                self.chunk_buffers[chunk.uid][chunk.frame_id] = (chunk_list, chunk.total_chunks, chunk.chunk_size, chunk.total_chunks)
                self.chunk_timeouts[chunk.uid][chunk.frame_id] = time.time()
            
            # Get buffer info
            buffer_info = self.chunk_buffers[chunk.uid][chunk.frame_id]
            chunk_list, stored_total_chunks, stored_chunk_size, remaining = buffer_info
            
            # Validate incoming chunk matches stored frame parameters
            if chunk.total_chunks != stored_total_chunks:
                print(f"[VIDEO SERVER] Discarding chunk: total_chunks mismatch (incoming={chunk.total_chunks}, stored={stored_total_chunks})")
                return
            
            if chunk.chunk_size != stored_chunk_size:
                print(f"[VIDEO SERVER] Discarding chunk: chunk_size mismatch (incoming={chunk.chunk_size}, stored={stored_chunk_size})")
                return
            
            # Validate chunk_idx is within bounds using stored total_chunks
            if chunk.chunk_idx >= stored_total_chunks:
                print(f"[VIDEO SERVER] Discarding chunk: chunk_idx out of range (chunk_idx={chunk.chunk_idx}, total_chunks={stored_total_chunks})")
                return
            
            # Place chunk at correct index
            if chunk_list[chunk.chunk_idx] is None:
                chunk_list[chunk.chunk_idx] = chunk
                remaining -= 1
                # Update buffer with new remaining count
                self.chunk_buffers[chunk.uid][chunk.frame_id] = (chunk_list, stored_total_chunks, stored_chunk_size, remaining)
                
                # Check if we have all chunks
                if remaining == 0:
                    print(f"[VIDEO SERVER] All chunks received for frame {chunk.frame_id} from uid={chunk.uid}")
                    
                    # Reassemble frame data (already in correct order, no sorting needed)
                    frame_data = b''.join(c.data for c in chunk_list)
                    
                    # Create assembled frame
                    assembled_frame = AssembledFrame(
                        uid=chunk.uid,
                        frame_id=chunk.frame_id,
                        timestamp=chunk.timestamp,
                        data=frame_data
                    )
                    
                    # Add to broadcast queue
                    with self.broadcast_lock:
                        self.broadcast_queue.append(assembled_frame)
                    
                    # Clean up chunks for this frame
                    del self.chunk_buffers[chunk.uid][chunk.frame_id]
                    if chunk.frame_id in self.chunk_timeouts[chunk.uid]:
                        del self.chunk_timeouts[chunk.uid][chunk.frame_id]
    
    def _cleanup_timeout_chunks(self):
        """Remove chunks that have timed out during reassembly."""
        current_time = time.time()
        
        with self.chunk_lock:
            for uid in list(self.chunk_buffers.keys()):
                for frame_id in list(self.chunk_buffers[uid].keys()):
                    timeout = self.chunk_timeouts[uid].get(frame_id, current_time)
                    if current_time - timeout > self.CHUNK_TIMEOUT:
                        # Timeout - discard these chunks
                        # Unpack the 4-element tuple: (chunk_list, stored_total_chunks, stored_chunk_size, remaining)
                        chunk_list, stored_total_chunks, stored_chunk_size, remaining = self.chunk_buffers[uid][frame_id]
                        received = stored_total_chunks - remaining
                        del self.chunk_buffers[uid][frame_id]
                        if frame_id in self.chunk_timeouts[uid]:
                            del self.chunk_timeouts[uid][frame_id]
                        print(f"[VIDEO SERVER] Discarded timeout chunks for uid={uid}, frame_id={frame_id} (received {received}/{stored_total_chunks})")
    
    async def handle_packet(self, data: bytes, addr: Tuple[str, int]):
        """Handle incoming UDP packet from client."""
        try:
            # Parse chunk header
            header_info = self._parse_chunk_header(data)
            if header_info is None:
                print(f"[VIDEO SERVER] Invalid chunk header from {addr}")
                return
            
            uid, frame_id, chunk_idx, total_chunks, seq, timestamp, chunk_size, receive_port, payload = header_info
            print(f"[VIDEO SERVER] Received chunk: uid={uid}, frame={frame_id}, chunk={chunk_idx+1}/{total_chunks}")
            
            # Update or add client
            with self.client_lock:
                if uid in self.clients:
                    client = self.clients[uid]
                    client.address = addr
                    client.receive_port = receive_port
                    client.last_packet_time = time.time()
                else:
                    # New client
                    client = ClientVideoInfo(uid, addr)
                    client.receive_port = receive_port
                    self.clients[uid] = client
                    print(f"[VIDEO SERVER] New video client connected: uid={uid} from {addr}")
                    print(f"[VIDEO SERVER] Client {uid} will receive broadcasts on {addr[0]}:{receive_port}")
            
            # Create chunk object
            chunk = VideoFrameChunk(
                uid=uid,
                frame_id=frame_id,
                chunk_idx=chunk_idx,
                total_chunks=total_chunks,
                seq=seq,
                timestamp=timestamp,
                chunk_size=chunk_size,
                data=payload
            )
            
            # Process chunk
            self._process_chunk(chunk, addr)
            
        except Exception as e:
            print(f"[VIDEO SERVER] Error handling packet from {addr}: {e}")
            import traceback
            traceback.print_exc()
    
    async def _broadcast_worker(self):
        """Async worker that broadcasts frames to all clients."""
        loop = asyncio.get_event_loop()

        while self.running:
            try:
                # Get frame from queue
                assembled_frame = None
                with self.broadcast_lock:
                    if len(self.broadcast_queue) > 0:
                        assembled_frame = self.broadcast_queue.popleft()

                if assembled_frame is None:
                    await asyncio.sleep(0.001)  # Reduced sleep for faster processing
                    continue

                print(f"[VIDEO SERVER] Broadcasting frame {assembled_frame.frame_id} from uid={assembled_frame.uid}")

                # Broadcast to all clients except sender
                with self.client_lock:
                    active_clients = list(self.clients.values())

                print(f"[VIDEO SERVER] Active clients: {[c.uid for c in active_clients]}, sender uid={assembled_frame.uid}")

                broadcast_count = 0
                for client in active_clients:
                    if client.uid == assembled_frame.uid:
                        # Don't send back to sender
                        print(f"[VIDEO SERVER] Skipping sender uid={client.uid}")
                        continue

                    try:
                        # Create a broadcast header with uid and timestamp
                        # Format: uid (4 bytes) + timestamp (8 bytes)
                        broadcast_header = struct.pack('>I Q',
                                                        assembled_frame.uid,
                                                        assembled_frame.timestamp)

                        # Send header + frame data to the client's receive port
                        packet_data = broadcast_header + assembled_frame.data
                        broadcast_addr = (client.address[0], client.receive_port)
                        await loop.sock_sendto(self.broadcast_socket, packet_data, broadcast_addr)
                        broadcast_count += 1
                        print(f"[VIDEO SERVER] Sent frame from uid={assembled_frame.uid} to uid={client.uid} at {broadcast_addr} (size={len(packet_data)} bytes)")
                    except Exception as e:
                        print(f"[VIDEO SERVER] Error broadcasting to uid={client.uid} at {broadcast_addr}: {e}")
                        import traceback
                        traceback.print_exc()

                print(f"[VIDEO SERVER] Broadcasted to {broadcast_count} clients")

            except Exception as e:
                print(f"[VIDEO SERVER] Error in broadcast worker: {e}")
                import traceback
                traceback.print_exc()
                await asyncio.sleep(0.01)
    
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
                print(f"[VIDEO SERVER] Client timed out: uid={uid}")
    
    async def start(self):
        """Start the video server."""
        # Socket for receiving chunks (port 10000)
        self.receive_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.receive_socket.bind((self.host, self.port))
        self.receive_socket.setblocking(False)
        
        # Socket for broadcasting (port 10001) - bound to BROADCAST_PORT
        self.broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.broadcast_socket.bind((self.host, self.BROADCAST_PORT))
        self.broadcast_socket.setblocking(False)
        
        self.running = True
        
        print(f"[VIDEO SERVER] Receiving chunks on {self.host}:{self.port}")
        print(f"[VIDEO SERVER] Broadcasting frames on {self.host}:{self.BROADCAST_PORT}")
        
        # Start broadcast worker and cleanup as background tasks
        broadcast_task = asyncio.create_task(self._broadcast_worker())
        
        async def cleanup_task():
            while self.running:
                await asyncio.sleep(1)  # Clean up more frequently
                self._cleanup_timeout_chunks()
                self._cleanup_timeout_clients()
        
        cleanup_task_handle = asyncio.create_task(cleanup_task())
        
        # Main receive loop
        loop = asyncio.get_event_loop()
        try:
            while self.running:
                try:
                    data, addr = await loop.sock_recvfrom(self.receive_socket, 65536)
                    await self.handle_packet(data, addr)
                except Exception as e:
                    if self.running:
                        print(f"[VIDEO SERVER] Error in receive loop: {e}")
        finally:
            # Cancel background tasks
            broadcast_task.cancel()
            cleanup_task_handle.cancel()
            try:
                await asyncio.gather(broadcast_task, cleanup_task_handle, return_exceptions=True)
            except Exception:
                pass
    
    def stop(self):
        """Stop the video server."""
        self.running = False
        
        if self.receive_socket:
            self.receive_socket.close()
        if self.broadcast_socket:
            self.broadcast_socket.close()
        
        # Clear clients
        with self.client_lock:
            self.clients.clear()
        
        # Clear chunk buffers
        with self.chunk_lock:
            self.chunk_buffers.clear()
            self.chunk_timeouts.clear()
        
        # Clear broadcast queue
        with self.broadcast_lock:
            self.broadcast_queue.clear()
        
        print("[VIDEO SERVER] Stopped")


async def run_server(host: str, port: int):
    """Run the video server."""
    server = VideoServer(host=host, port=port)
    
    try:
        await server.start()
    except KeyboardInterrupt:
        print("\n[VIDEO SERVER] Shutting down...")
    finally:
        server.stop()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description='Video Server - Receives and broadcasts video')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=10000,
                       help='UDP port to listen on (default: 10000)')
    
    args = parser.parse_args()
    
    try:
        asyncio.run(run_server(args.host, args.port))
    except Exception as e:
        print(f"[ERROR] {e}")


if __name__ == "__main__":
    main()
