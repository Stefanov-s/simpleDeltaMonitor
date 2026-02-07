# DeltaMonitorBot

Ubuntu X11 only. Monitor a screen region, read a number, alert (and optionally click) when it changes by the set delta.

---

## Copy-paste setup

**1. Install system packages**

```bash
sudo apt update
sudo apt install -y python3-tk tesseract-ocr python3-xlib
```

**2. Go to project folder** (change path to where you put DeltaMonitorBot)

```bash
cd ~/Desktop/DeltaMonitorBot
```

**3. Create venv and install Python deps**

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt
```

**4. Run**

```bash
python main.py
```

---

## Run again later (from terminal)

```bash
cd ~/Desktop/DeltaMonitorBot
source .venv/bin/activate
python main.py
```

(Or start **DeltaMonitorBot** from the application menu after first run.)

---

## Require X11

```bash
echo $XDG_SESSION_TYPE
```

Must print `x11`. If it says `wayland`, switch to X11 session.
