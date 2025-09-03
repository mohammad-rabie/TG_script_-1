#!/usr/bin/env python3
"""
Separate Telegram authentication script
Run this once to authenticate your Telegram account for Premium emoji support
"""

import asyncio
from telegram_nft_monitor import TelegramNFTMonitor

async def authenticate_telegram():
    """Authenticate Telegram account separately from monitoring"""
    print("🔐 Telegram Authentication Setup")
    print("=" * 40)
    
    monitor = TelegramNFTMonitor()
    success = await monitor.authenticate_telegram_interactive()
    
    if success:
        print("\n✅ Authentication successful!")
        print("🎁 Premium animated emojis are now enabled")
        print("🚀 You can now run the main monitor: python telegram_nft_monitor.py")
    else:
        print("\n❌ Authentication failed")
        print("📱 The monitor will use standard emojis as fallback")
    
    await monitor.cleanup()

if __name__ == "__main__":
    asyncio.run(authenticate_telegram())
