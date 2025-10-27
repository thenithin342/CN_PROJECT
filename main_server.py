#!/usr/bin/env python3
"""
LAN Collaboration Server - Main Entry Point

Unified entry point for the server application that integrates:
- Chat messaging
- File transfer
- Screen sharing
- Audio streaming (UDP)
- Video streaming (UDP)

Usage:
    python main_server.py

Optional arguments:
    --host HOST           Bind address (default: 0.0.0.0)
    --port PORT           Main TCP port (default: 9000)
    --audio-port PORT     Audio UDP port (default: 11000)
    --video-port PORT     Video UDP port (default: 10000)
    --upload-dir DIR      Upload directory (default: uploads)
"""

if __name__ == "__main__":
    import asyncio
    import sys
    import argparse
    
    # Import the server components directly
    from server.main_server import CollaborationServer
    from server.utils.logger import logger
    
    # Parse command line arguments
    parser = argparse.ArgumentParser(description='LAN Collaboration Server')
    parser.add_argument('--host', type=str, default='0.0.0.0',
                       help='Host to bind to (default: 0.0.0.0)')
    parser.add_argument('--port', type=int, default=9000,
                       help='TCP port for main server (default: 9000)')
    parser.add_argument('--audio-port', type=int, default=11000,
                       help='UDP port for audio server (default: 11000)')
    parser.add_argument('--video-port', type=int, default=10000,
                       help='UDP port for video server (default: 10000)')
    parser.add_argument('--upload-dir', type=str, default='uploads',
                       help='Directory for file uploads (default: uploads)')

    args = parser.parse_args()

    # Create and start the server
    server = None
    try:
        server = CollaborationServer(
            host=args.host,
            port=args.port,
            audio_port=args.audio_port,
            video_port=args.video_port,
            upload_dir=args.upload_dir
        )
        asyncio.run(server.start())
    except KeyboardInterrupt:
        logger.info("Server shutting down...")
        if server and hasattr(server, 'audio_server') and server.audio_server:
            server.audio_server.stop()
        if server and hasattr(server, 'video_server') and server.video_server:
            server.video_server.stop()
    except Exception as e:
        logger.log_error("server", e)
        if server and hasattr(server, 'audio_server') and server.audio_server:
            server.audio_server.stop()
        if server and hasattr(server, 'video_server') and server.video_server:
            server.video_server.stop()

