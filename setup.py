#!/usr/bin/env python3
"""
Setup script for Telegram NFT Market Monitor Bot
Installs dependencies and sets up the environment
"""

import subprocess
import sys
import os

def install_requirements():
    """Install Python requirements"""
    print("📦 Installing Python dependencies...")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"])
        print("✅ Python dependencies installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install Python dependencies: {e}")
        return False
    return True

def install_playwright():
    """Install Playwright browsers"""
    print("🌐 Installing Playwright browsers...")
    try:
        subprocess.check_call([sys.executable, "-m", "playwright", "install", "chromium"])
        print("✅ Playwright Chromium browser installed successfully")
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install Playwright browsers: {e}")
        return False
    return True

def create_directories():
    """Create necessary directories"""
    print("📁 Creating directories...")
    directories = ["logs", "data"]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"✅ Created directory: {directory}")
    return True

def main():
    """Main setup function"""
    print("🚀 Setting up Telegram NFT Market Monitor Bot")
    print("=" * 50)
    
    success = True
    
    # Install Python requirements
    if not install_requirements():
        success = False
    
    # Install Playwright browsers
    if not install_playwright():
        success = False
    
    # Create directories
    if not create_directories():
        success = False
    
    print("=" * 50)
    if success:
        print("🎉 Setup completed successfully!")
        print("\nNext steps:")
        print("1. Run: python telegram_nft_monitor.py")
        print("2. The bot will open a browser window for token extraction")
        print("3. Log in to Telegram Web when prompted")
        print("4. Navigate to Portals Market bot")
        print("5. The bot will automatically capture tokens and start monitoring")
    else:
        print("❌ Setup failed. Please check the errors above.")
    
    return success

if __name__ == "__main__":
    main()
