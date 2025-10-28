# Setup Guide - LAN Collaboration System

## First Time Setup

### Step 1: Install Python Dependencies

Run this command on **both** the server and client computers:

```bash
pip install -r requirements.txt
```

This will install all required packages including:
- PyQt6 (GUI)
- OpenCV (Video features)
- opuslib (Audio features)
- Sounddevice (Audio playback)
- mss (Screen sharing)
- Pillow (Image processing)

**Note:** If this is your first time running the code from GitHub, you need to install all dependencies first!

### Step 2: Run the Server

On the server computer:

```bash
python main_server.py
```

The server will display its IP address, something like:
```
Server binding to 192.168.2.22:9000
```

### Step 3: Run the Client

On each client computer:

```bash
python main_client.py
```

When prompted, enter:
- **Server IP:** The IP address shown by the server (e.g., `192.168.2.22`)
- **Server Port:** `9000` (default)
- **Username:** Your name (e.g., `nithin`)

## Features That May Be Disabled

If some dependencies are not installed:

- **No opuslib:** Audio/video features disabled (chat still works)
- **No OpenCV:** Video features disabled (chat still works)
- **No mss:** Screen sharing disabled (chat still works)

**Chat and file transfer will always work** even without optional dependencies.

## Troubleshooting

### "Failed to initialize client modules"
This is **normal** if you haven't installed the optional packages yet. You can still use:
- ✅ Chat messaging
- ✅ File upload/download

Install missing packages if you want:
- Video: `pip install opencv-python`
- Audio: `pip install opuslib sounddevice numpy`

### "File client not initialized"
This should be fixed now, but if it happens, chat and file transfer should still work.

## Quick Start Commands

**Server:**
```bash
pip install -r requirements.txt
python main_server.py
```

**Client:**
```bash
pip install -r requirements.txt
python main_client.py
```

Enter server details when prompted!

