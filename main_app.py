#!/usr/bin/env python3
"""
LAN Collaboration System - Main Application Launcher
Complete Zoom-like functionality with all features integrated
"""

import sys
import os
import argparse
from PyQt6.QtWidgets import QApplication, QMessageBox
from PyQt6.QtCore import Qt

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from client.ui.client_gui import ClientMainWindow


def check_dependencies():
    """Check if all required dependencies are installed."""
    missing = []
    
    # Check PyQt6
    try:
        import PyQt6
    except ImportError:
        missing.append("PyQt6")
    
    # Check OpenCV
    try:
        import cv2
    except ImportError:
        missing.append("opencv-python")
    
    # Check sounddevice
    try:
        import sounddevice
    except ImportError:
        missing.append("sounddevice")
    
    # Check opuslib
    try:
        import opuslib
    except ImportError:
        missing.append("opuslib")
    
    # Check mss
    try:
        import mss
    except ImportError:
        missing.append("mss")
    
    # Check Pillow
    try:
        import PIL
    except ImportError:
        missing.append("Pillow")
    
    # Check numpy
    try:
        import numpy
    except ImportError:
        missing.append("numpy")
    
    return missing


def main():
    """Main entry point for the application."""
    parser = argparse.ArgumentParser(
        description='LAN Collaboration System - Complete Zoom-like Application',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Features:
  - Real-time video conferencing with multiple participants
  - High-quality audio communication with mixing
  - Screen sharing with adjustable quality
  - Text chat with broadcast and private messaging
  - File sharing with progress tracking
  - Participant management and controls

Examples:
  # Connect to local server
  python main_app.py
  
  # Connect to remote server
  python main_app.py --server 192.168.1.100
  
  # Specify custom ports
  python main_app.py --server 192.168.1.100 --port 9000 --audio-port 11000 --video-port 10000
        """
    )
    
    parser.add_argument(
        '--server', 
        type=str, 
        default='localhost',
        help='Server IP address (default: localhost)'
    )
    
    parser.add_argument(
        '--port', 
        type=int, 
        default=9000,
        help='Server TCP port (default: 9000)'
    )
    
    parser.add_argument(
        '--audio-port', 
        type=int, 
        default=11000,
        help='Audio server UDP port (default: 11000)'
    )
    
    parser.add_argument(
        '--video-port', 
        type=int, 
        default=10000,
        help='Video server UDP port (default: 10000)'
    )
    
    parser.add_argument(
        '--username', 
        type=str, 
        default=None,
        help='Username (will prompt if not provided)'
    )
    
    parser.add_argument(
        '--check-deps', 
        action='store_true',
        help='Check dependencies and exit'
    )
    
    args = parser.parse_args()
    
    # Check dependencies
    missing_deps = check_dependencies()
    
    if args.check_deps:
        if missing_deps:
            print("Missing dependencies:")
            for dep in missing_deps:
                print(f"  - {dep}")
            print("\nInstall with: pip install -r requirements.txt")
            return 1
        else:
            print("All dependencies are installed!")
            return 0
    
    if missing_deps:
        print("WARNING: Missing dependencies:")
        for dep in missing_deps:
            print(f"  - {dep}")
        print("\nSome features may not work. Install with: pip install -r requirements.txt")
        print("Continuing anyway...\n")
    
    # Create Qt application
    app = QApplication(sys.argv)
    app.setApplicationName("LAN Collaboration System")
    app.setOrganizationName("LAN Collab")
    
    # Enable high DPI scaling
    app.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    app.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)
    
    # Create main window
    try:
        window = ClientMainWindow(
            server_host=args.server,
            server_port=args.port
        )
        
        # Set username if provided
        if args.username:
            window.username = args.username
        
        window.show()
        
        # Connect to server
        if not window.connect_to_server():
            QMessageBox.critical(
                None,
                "Connection Failed",
                f"Failed to connect to server at {args.server}:{args.port}\n\n"
                "Please ensure:\n"
                "1. The server is running\n"
                "2. The server address and port are correct\n"
                "3. Your firewall allows the connection"
            )
            return 1
        
        # Run application
        return app.exec()
        
    except Exception as e:
        QMessageBox.critical(
            None,
            "Application Error",
            f"Failed to start application:\n{str(e)}\n\n"
            "Please check the console for more details."
        )
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())