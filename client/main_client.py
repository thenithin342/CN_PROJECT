#!/usr/bin/env python3
"""
LAN Multi-User Collaboration Client - Main Entry Point

This is the main entry point for the client application.
It integrates all client modules (chat, files, screen sharing, UI) into a cohesive application.
"""

import asyncio
import sys
import os
from datetime import datetime

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from client.chat.chat_client import ChatClient
from client.files.file_client import FileClient
from client.screen.screen_presenter import ScreenPresenter
from client.screen.screen_viewer import ScreenViewer
from client.audio.audio_client import AudioClient
from client.video.video_client import VideoClient
from client.ui.client_gui import ClientMainWindow
from client.utils.config import ClientConfig
from client.utils.logger import logger
from common.constants import MessageTypes, MAX_RETRY_ATTEMPTS, RECONNECT_ATTEMPTS, RECONNECT_DELAY_BASE
from common.protocol_definitions import create_login_message, create_logout_message


class CollaborationClient:
    """Main client class that integrates all functionality."""
    
    def __init__(self, host: str = 'localhost', port: int = 9000, username: str = None, 
                 audio_port: int = 11000, video_port: int = 10000):
        self.config = ClientConfig(host, port, username)
        self.reader = None
        self.writer = None
        self.running = False
        self.uid = None
        
        # Initialize modules
        self.chat_client = ChatClient()
        self.file_client = FileClient()
        self.screen_presenter = ScreenPresenter()
        self.screen_viewer = ScreenViewer()
        self.audio_client = AudioClient(server_ip=host, server_port=audio_port, uid=None)
        self.video_client = VideoClient(server_ip=host, server_port=video_port, uid=None)
        # GUI is not used in this main client - it's a standalone app
        self.gui = None
        
        # Set up module connections
        self._setup_modules()
    
    def _setup_modules(self):
        """Set up connections between modules."""
        # Set message handlers
        self.chat_client.set_message_handler(self.handle_message)
        self.file_client.set_message_handler(self.handle_message)
        self.screen_presenter.set_message_handler(self.handle_message)
        self.screen_viewer.set_message_handler(self.handle_message)
        
        # Set host for modules that need it
        self.file_client.set_host(self.config.host)
        self.screen_presenter.set_host(self.config.host)
        self.screen_viewer.set_host(self.config.host)
    
    async def connect(self, retry_count: int = MAX_RETRY_ATTEMPTS, base_delay: float = 1.0):
        """Establish connection to the server with retry logic and exponential backoff."""
        attempt = 0
        
        while attempt < retry_count:
            try:
                self.reader, self.writer = await asyncio.open_connection(self.config.host, self.config.port)
                logger.log_connection(self.config.host, self.config.port, True)
                self.running = True
                
                # Set writer for all modules
                self.chat_client.set_writer(self.writer)
                self.file_client.set_writer(self.writer)
                self.screen_presenter.set_writer(self.writer)
                self.screen_viewer.set_writer(self.writer)
                
                return True
            except Exception as e:
                attempt += 1
                logger.log_connection(self.config.host, self.config.port, False)
                logger.log_error("connection", e)
                
                if attempt < retry_count:
                    delay = base_delay * (2 ** (attempt - 1))  # Exponential backoff
                    logger.info(f"[INFO] Retrying connection in {delay}s (attempt {attempt}/{retry_count})...")
                    await asyncio.sleep(delay)
                else:
                    logger.error(f"[ERROR] Failed to connect after {retry_count} attempts")
                    return False
        return False
    
    async def send_login(self):
        """Send login message to server."""
        login_msg = create_login_message(self.config.username)
        logger.show_login_info(self.config.username)
        await self.chat_client.send_message(login_msg)
    
    async def send_heartbeat(self):
        """Send periodic heartbeat messages."""
        while self.running:
            await asyncio.sleep(10)
            if self.running:
                from common.protocol_definitions import create_heartbeat_message
                heartbeat_msg = create_heartbeat_message()
                await self.chat_client.send_message(heartbeat_msg)
    
    async def send_logout(self):
        """Send logout message to server."""
        logout_msg = create_logout_message()
        logger.info("[INFO] Sending logout...")
        await self.chat_client.send_message(logout_msg)
    
    async def listen_for_messages(self):
        """Listen for incoming messages from server with automatic reconnection."""
        while self.running:
            try:
                data = await self.reader.readline()
                if not data:
                    logger.info("[INFO] Server closed connection, attempting to reconnect...")
                    await self._reconnect()
                    continue
                
                try:
                    import json
                    message = json.loads(data.decode('utf-8').strip())
                    await self.handle_message(message)
                except json.JSONDecodeError as e:
                    logger.error(f"[ERROR] Malformed JSON received: {e}")
                except Exception as e:
                    logger.error(f"[ERROR] Error processing message: {e}")
        
            except asyncio.CancelledError:
                logger.info("[INFO] Listener cancelled")
                break
            except ConnectionError as e:
                logger.error(f"[ERROR] Connection lost: {e}")
                if self.running:
                    if await self._reconnect():
                        continue  # Resume listening after successful reconnection
                break
            except Exception as e:
                logger.error(f"[ERROR] Connection error: {e}")
                if self.running:
                    if await self._reconnect():
                        continue  # Resume listening after successful reconnection
                self.running = False
                break
    
    async def _reconnect(self):
        """Reconnect to the server with exponential backoff."""
        max_attempts = RECONNECT_ATTEMPTS
        base_delay = RECONNECT_DELAY_BASE
        
        for attempt in range(max_attempts):
            delay = base_delay * (2 ** attempt)
            logger.info(f"[INFO] Attempting to reconnect in {delay}s (attempt {attempt + 1}/{max_attempts})...")
            await asyncio.sleep(delay)
            
            if await self.connect(retry_count=1):
                logger.info("[INFO] Reconnected successfully!")
                await self.send_login()
                return True
        
        logger.error("[ERROR] Failed to reconnect after multiple attempts")
        self.running = False
        return False
    
    async def handle_message(self, message: dict):
        """Handle different types of messages from server."""
        msg_type = message.get('type', '')
        
        if msg_type == MessageTypes.LOGIN_SUCCESS:
            self.uid = message.get('uid')
            username = message.get('username')
            logger.show_login_success(username, self.uid)
            
            # Set UID for modules that need it
            self.chat_client.set_uid(self.uid)
            self.screen_presenter.set_uid(self.uid)
            self.screen_viewer.set_uid(self.uid)
            self.audio_client.set_uid(self.uid)
            self.video_client.set_uid(self.uid)
            
            # Request chat history after successful login
            await self.chat_client.request_history()
        
        elif msg_type == MessageTypes.PARTICIPANT_LIST:
            participants = message.get('participants', [])
            logger.show_participants(participants)
        
        elif msg_type == MessageTypes.USER_JOINED:
            uid = message.get('uid')
            username = message.get('username')
            logger.show_user_joined(username, uid, self.uid)
        
        elif msg_type == MessageTypes.USER_LEFT:
            uid = message.get('uid')
            username = message.get('username')
            logger.show_user_left(username, uid)
        
        elif msg_type == MessageTypes.HEARTBEAT_ACK:
            # Silently acknowledge heartbeat
            pass
        
        elif msg_type == MessageTypes.ERROR:
            error_msg = message.get('message', 'Unknown error')
            logger.error(f"[ERROR] Server error: {error_msg}")
        
        else:
            # Delegate to appropriate modules
            await self.chat_client.handle_message(message)
            await self.file_client.handle_message(message)
            await self.screen_presenter.handle_message(message)
            await self.screen_viewer.handle_message(message)
    
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
            
            # Clean up audio and video clients
            self.audio_client.cleanup()
            self.video_client.cleanup()
            
            logger.info("[INFO] Disconnected from server")
    
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
        logger.show_interactive_mode_info()
        
        try:
            while self.running:
                # Get user input (blocking, but that's ok for demo)
                try:
                    user_input = await asyncio.get_event_loop().run_in_executor(
                        None, sys.stdin.readline
                    )
                    if user_input.strip():
                        # Handle user input directly in this module
                        await self.chat_client.send_message({"type": "chat", "text": user_input.strip()})
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
            
            # Clean up audio and video clients
            self.audio_client.cleanup()
            self.video_client.cleanup()
            
            logger.info("[INFO] Disconnected from server")


async def main():
    """Main entry point."""
    if len(sys.argv) > 1:
        username = sys.argv[1]
    else:
        username = input("Enter username: ").strip() or "anonymous"
    
    client = CollaborationClient(
        host='localhost',
        port=9000,
        username=username,
        audio_port=11000,
        video_port=10000
    )
    
    try:
        await client.interactive_mode()
    except KeyboardInterrupt:
        print("\n[INFO] Interrupted by user")
    except Exception as e:
        logger.log_error("client", e)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\n[INFO] Client terminated")
