#!/usr/bin/env python3
"""
Advanced Telegram NFT Market Monitor - Bot Version
Monitors Portals Market API with automatic token refresh, rate limiting, and duplicate detection.
"""

import asyncio
import aiohttp
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple
from playwright.async_api import async_playwright, Page, Browser
from aiogram import Bot
from aiogram.exceptions import TelegramRetryAfter, TelegramAPIError
from aiogram.enums import ParseMode
import config

# Fix Windows console encoding for emojis
if sys.platform == "win32":
    import codecs
    sys.stdout = codecs.getwriter("utf-8")(sys.stdout.detach())
    sys.stderr = codecs.getwriter("utf-8")(sys.stderr.detach())

# Configure logging with UTF-8 encoding
class UTF8FileHandler(logging.FileHandler):
    def __init__(self, filename, mode='a', encoding='utf-8', delay=False):
        super().__init__(filename, mode, encoding, delay)

logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        UTF8FileHandler(config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

class TelegramNFTMonitor:
    def __init__(self):
        # Telegram Bot Client
        self.bot = Bot(token=config.BOT_TOKEN)
        
        # Configuration from centralized config
        self.channel_username = config.CHANNEL_USERNAME
        self.api_url = config.PORTALS_API_URL
        
        # Token management
        self.auth_token: Optional[str] = None
        self.token_last_updated: Optional[datetime] = None
        self.token_refresh_interval = config.TOKEN_REFRESH_INTERVAL
        self.token_extraction_in_progress = False
        
        # Browser automation
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[Browser] = None
        self.page: Optional[Page] = None
        
        # State management with price tracking
        self.seen_actions: set[str] = set()
        self.price_history: Dict[str, Dict] = {}  # NFT ID -> {price, timestamp, action_id}
        self.last_check_time = None
        
        # Batch processing state
        self.initial_batch_sent = False
        self.last_processed_timestamp = None
        self.waiting_for_new_sales = False
        
        # Rate limiting
        self.message_timestamps = []
        self.daily_message_count = 0
        self.last_daily_reset = datetime.now().date()
        
        # Request settings
        self.request_timeout = config.REQUEST_TIMEOUT
        self.retry_attempts = config.RETRY_ATTEMPTS
        self.sleep_interval = config.CHECK_INTERVAL
        self.running = False
        
        # Load previous state
        self.load_state()
        
        # Setup signal handlers for graceful shutdown
        import signal
        signal.signal(signal.SIGINT, self._signal_handler)
        signal.signal(signal.SIGTERM, self._signal_handler)
    
    def _signal_handler(self, signum, frame):
        """Handle shutdown signals gracefully"""
        logger.info(f"Received signal {signum}, shutting down gracefully...")
        self.running = False
    
    def load_state(self):
        """Load previously seen actions and price history from file"""
        try:
            if os.path.exists('monitor_state.json'):
                with open('monitor_state.json', 'r') as f:
                    data = json.load(f)
                    self.seen_actions = set(data.get('seen_actions', []))
                    self.price_history = data.get('price_history', {})
                    self.last_check_time = data.get('last_check_time')
                    self.daily_message_count = data.get('daily_message_count', 0)
                    
                    # Check if we need to reset daily counter
                    last_reset = data.get('last_daily_reset')
                    if last_reset:
                        try:
                            last_reset_date = datetime.fromisoformat(last_reset).date()
                            if last_reset_date != datetime.now().date():
                                self.daily_message_count = 0
                                self.last_daily_reset = datetime.now().date()
                        except Exception as e:
                            logger.warning(f"⚠️ Error parsing last_daily_reset: {e}")
                            self.daily_message_count = 0
                            self.last_daily_reset = datetime.now().date()
                    
                logger.info(f"Loaded {len(self.seen_actions)} previously seen actions")
                logger.info(f"Loaded {len(self.price_history)} price history entries")
        except Exception as e:
            logger.warning(f"Could not load previous state: {e}")
    
    def save_state(self):
        """Save current state to file"""
        try:
            with open('monitor_state.json', 'w') as f:
                json.dump({
                    'seen_actions': list(self.seen_actions),
                    'price_history': self.price_history,
                    'last_check_time': self.last_check_time,
                    'daily_message_count': self.daily_message_count,
                    'last_daily_reset': self.last_daily_reset.isoformat()
                }, f)
        except Exception as e:
            logger.error(f"Could not save state: {e}")
    
    def cleanup_old_price_history(self):
        """Remove old price history entries"""
        cutoff_time = datetime.now().replace(tzinfo=None) - timedelta(hours=config.DUPLICATE_MEMORY_HOURS)
        
        to_remove = []
        for nft_id, data in self.price_history.items():
            try:
                # Parse timestamp and make it timezone-naive for comparison
                timestamp_str = data['timestamp']
                if 'Z' in timestamp_str or '+' in timestamp_str:
                    # Parse ISO format with timezone
                    timestamp = datetime.fromisoformat(timestamp_str.replace('Z', '+00:00'))
                    # Convert to naive datetime for comparison
                    timestamp = timestamp.replace(tzinfo=None)
                else:
                    # Already naive
                    timestamp = datetime.fromisoformat(timestamp_str)
                
                if timestamp < cutoff_time:
                    to_remove.append(nft_id)
            except Exception as e:
                logger.warning(f"⚠️ Error parsing timestamp for {nft_id}: {e}")
                to_remove.append(nft_id)  # Remove problematic entries
        
        for nft_id in to_remove:
            del self.price_history[nft_id]
        
        if to_remove:
            logger.info(f"Cleaned up {len(to_remove)} old price history entries")
    
    async def check_rate_limits(self) -> bool:
        """Check if we can send a message without hitting rate limits"""
        now = datetime.now()
        
        # Reset daily counter if needed
        if now.date() != self.last_daily_reset:
            self.daily_message_count = 0
            self.last_daily_reset = now.date()
            logger.info("Daily message counter reset")
        
        # Clean old timestamps (older than 1 hour)
        hour_ago = now - timedelta(hours=1)
        self.message_timestamps = [ts for ts in self.message_timestamps if ts > hour_ago]
        
        # Check hourly limit
        if len(self.message_timestamps) >= config.MAX_MESSAGES_PER_HOUR:
            logger.warning(f"Hourly message limit reached ({config.MAX_MESSAGES_PER_HOUR})")
            return False
        
        # Check per-minute limit
        minute_ago = now - timedelta(minutes=1)
        recent_messages = [ts for ts in self.message_timestamps if ts > minute_ago]
        if len(recent_messages) >= config.MAX_MESSAGES_PER_MINUTE:
            logger.warning(f"Per-minute message limit reached ({config.MAX_MESSAGES_PER_MINUTE})")
            return False
        
        return True
    
    def is_duplicate_or_price_change(self, action: Dict) -> Tuple[bool, bool]:
        """Enhanced duplicate detection for gifts with same name but different price/number"""
        nft = action['nft']
        nft_id = nft['id']
        nft_name = nft['name']
        external_number = nft['external_collection_number']
        current_price = float(action['amount'])
        current_timestamp = action['created_at']
        
        # Check exact NFT ID first (same exact NFT)
        if nft_id in self.price_history:
            previous_data = self.price_history[nft_id]
            previous_price = previous_data['price']
            price_diff = abs(current_price - previous_price)
            
            if price_diff < config.PRICE_CHANGE_THRESHOLD:
                # Same NFT, same price - this is a duplicate
                return True, False
            else:
                # Same NFT, different price - this is a price change (allow)
                return False, True
        
        # Check for similar gifts (same name but different external number)
        similar_gifts = []
        for stored_nft_id, data in self.price_history.items():
            if stored_nft_id.startswith(f"{nft_name}_"):
                similar_gifts.append((stored_nft_id, data))
        
        if similar_gifts:
            # Check if this exact combination (name + external_number + price) was already sent
            for stored_id, data in similar_gifts:
                stored_price = data['price']
                stored_timestamp = data['timestamp']
                
                # If same name, same external number, and similar price - likely duplicate
                if (external_number in stored_id and 
                    abs(current_price - stored_price) < config.PRICE_CHANGE_THRESHOLD):
                    
                    # Check timestamp to avoid sending very recent duplicates (within 5 minutes)
                    try:
                        from datetime import datetime
                        current_dt = datetime.fromisoformat(current_timestamp.replace('Z', '+00:00'))
                        stored_dt = datetime.fromisoformat(stored_timestamp.replace('Z', '+00:00'))
                        time_diff = abs((current_dt - stored_dt).total_seconds())
                        
                        if time_diff < 300:  # 5 minutes
                            logger.info(f"🔄 Similar gift detected within 5 minutes: {nft_name} #{external_number}")
                            return True, False  # Treat as duplicate
                    except:
                        pass
        
        # Not a duplicate - new gift or significantly different
        return False, False

    def update_price_history(self, action: Dict, action_id: str):
        """Enhanced price history tracking with gift name and external number"""
        nft = action['nft']
        nft_id = nft['id']
        nft_name = nft['name']
        external_number = nft['external_collection_number']
        price = float(action['amount'])
        
        # Store with enhanced key for better tracking
        enhanced_key = f"{nft_name}_{external_number}_{nft_id}"
        
        self.price_history[nft_id] = {
            'price': price,
            'timestamp': action['created_at'],
            'action_id': action_id,
            'name': nft_name,
            'external_number': external_number,
            'enhanced_key': enhanced_key
        }
    
    async def validate_token(self, token: str) -> bool:
        """Validate token by making a test API request"""
        if not token:
            return False
            
        headers = {
            'authorization': token,
            'accept': 'application/json, text/plain, */*'
        }
        params = {'offset': 0, 'limit': 1, 'action_types': 'buy'}
        
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(
                    self.api_url,
                    params=params,
                    headers=headers,
                    timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    is_valid = response.status == 200
                    if is_valid:
                        logger.info("✅ Token validation successful")
                    else:
                        logger.warning(f"❌ Token validation failed: {response.status}")
                    return is_valid
        except Exception as e:
            logger.error(f"❌ Token validation error: {e}")
            return False
    
    async def ensure_valid_token(self) -> bool:
        """Ensure we have a valid token, refresh if needed"""
        # Load existing token if available
        if self.load_auth_token():
            # Check if existing token is valid
            if await self.validate_token(self.auth_token):
                logger.info("✅ Existing token is valid")
                return True
        
        # Check if existing token is recent enough to skip browser extraction
        if self.is_token_valid():
            try:
                with open('auth_token.txt', 'r') as f:
                    self.auth_token = f.read().strip()
                logger.info("🔑 Using recent token file, skipping validation")
                return True
            except Exception as e:
                logger.error(f"💥 Error loading recent token: {e}")
        
        # Extract fresh token
        logger.info("🔄 Token refresh needed, extracting fresh token...")
        if await self.extract_fresh_token():
            return True
        
        logger.error("❌ Failed to obtain valid authorization token")
        return False
    
    async def fetch_market_actions(self) -> list[dict] | None:
        """Fetch latest market actions from the API"""
        if not self.auth_token:
            logger.error("❌ No auth token available")
            return None
            
        headers = {
            'authorization': self.auth_token,
            'accept': 'application/json, text/plain, */*',
            'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36'
        }
        
        params = {
            'offset': 0,
            'limit': 20,
            'action_types': 'buy'
        }
        
        for attempt in range(self.retry_attempts):
            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        self.api_url,
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=self.request_timeout)
                    ) as response:
                        
                        if response.status == 200:
                            data = await response.json()
                            actions = data.get('actions', [])
                            logger.info(f"📊 Fetched {len(actions)} actions from API")
                            return actions
                        elif response.status == 401:
                            logger.warning("🔐 Authorization failed - token expired")
                            return None
                        else:
                            logger.warning(f"⚠️ API returned status {response.status}")
                            
            except Exception as e:
                logger.error(f"💥 Request failed (attempt {attempt + 1}): {e}")
                if attempt < self.retry_attempts - 1:
                    await asyncio.sleep(2 ** attempt)
        
        return None
    
    async def send_telegram_message(self, message: str) -> bool:
        """Send message to Telegram channel"""
        try:
            # Send the message first
            sent_message = await self.bot.send_message(
                chat_id=self.channel_username, 
                text=message,
                parse_mode=ParseMode.HTML
            )
            logger.info("📢 Message sent successfully to Telegram")
            return sent_message
        except TelegramRetryAfter as e:
            logger.warning(f"⏰ Rate limit exceeded, waiting {e.retry_after} seconds...")
            await asyncio.sleep(e.retry_after)
            return await self.send_telegram_message(message)
        except TelegramAPIError as e:
            logger.error(f"❌ Telegram API error: {e}")
            return False

    async def pin_message_if_high_value(self, message_obj, purchase_amount: float):
        """Pin message if purchase amount is above threshold"""
        try:
            if purchase_amount >= config.PIN_MESSAGE_THRESHOLD:
                await self.bot.pin_chat_message(
                    chat_id=self.channel_username,
                    message_id=message_obj.message_id,
                    disable_notification=False  # Send notification about pinning
                )
                logger.info(f"📌 Pinned high-value message: {purchase_amount} TON")
                return True
        except TelegramAPIError as e:
            logger.error(f"❌ Failed to pin message: {e}")
        except Exception as e:
            logger.error(f"💥 Error pinning message: {e}")
        return False
    
    async def process_new_actions(self, actions: List[Dict]):
        """Smart batch processing: send first 5 gifts immediately, then real-time monitoring"""
        if not actions:
            return
            
        # Filter only purchase actions and sort by timestamp (newest first)
        purchase_actions = [a for a in actions if a.get('type') == 'purchase']
        if not purchase_actions:
            return
            
        new_actions = []
        for action in purchase_actions:
            action_id = f"{action['nft']['id']}_{action['created_at']}_{action['amount']}"
            if action_id not in self.seen_actions:
                new_actions.append(action)
                self.seen_actions.add(action_id)
        
        if not new_actions:
            # No new actions, we're in waiting mode
            if not self.waiting_for_new_sales:
                logger.info("💤 No new sales detected, entering waiting mode...")
                self.waiting_for_new_sales = True
            return
        
        # Reset waiting mode when we find new sales
        if self.waiting_for_new_sales:
            logger.info("🎯 New sales detected! Resuming notifications...")
            self.waiting_for_new_sales = False
        
        # Initial batch: send first 5 gifts immediately
        if not self.initial_batch_sent:
            batch_to_send = new_actions[:5]  # Take first 5
            logger.info(f"🚀 Sending initial batch of {len(batch_to_send)} gifts...")
            
            for action in batch_to_send:
                await self.send_single_notification(action)
                # Very short delay for initial batch
                await asyncio.sleep(1)
            
            self.initial_batch_sent = True
            if new_actions:
                self.last_processed_timestamp = new_actions[0].get('created_at')
            
            # If there were more than 5, mark the rest as seen but don't send
            for action in new_actions[5:]:
                action_id = f"{action['nft']['id']}_{action['created_at']}_{action['amount']}"
                self.seen_actions.add(action_id)
                
        else:
            # Real-time mode: send new purchases immediately as they occur
            truly_new_actions = []
            
            if self.last_processed_timestamp:
                for action in new_actions:
                    action_timestamp = action.get('created_at')
                    if action_timestamp and action_timestamp > self.last_processed_timestamp:
                        truly_new_actions.append(action)
            else:
                truly_new_actions = new_actions
            
            if truly_new_actions:
                logger.info(f"⚡ Sending {len(truly_new_actions)} new purchases in real-time...")
                
                for action in truly_new_actions:
                    await self.send_single_notification(action)
                    # Minimal delay for real-time notifications
                    await asyncio.sleep(0.5)
                
                # Update last processed timestamp
                self.last_processed_timestamp = truly_new_actions[0].get('created_at')
        
        self.save_state()

    async def send_single_notification(self, action: Dict):
        """Send notification for a single purchase"""
        try:
            is_duplicate, is_price_change = self.is_duplicate_or_price_change(action)
            
            if is_duplicate:
                logger.info(f"Skipping duplicate: {action['nft']['name']}")
                return
            
            if is_price_change:
                logger.info(f"Price change detected: {action['nft']['name']}")
            
            message = self.format_message(action)
            message_obj = await self.send_telegram_message(message)
            
            if message_obj:
                purchase_amount = float(action['amount'])
                logger.info(f"✅ Sent: {action['nft']['name']} for {purchase_amount} TON")
                await self.pin_message_if_high_value(message_obj, purchase_amount)
            else:
                logger.error(f"❌ Failed to send: {action['nft']['name']}")
            
            # Update price history
            action_id = f"{action['nft']['id']}_{action['created_at']}_{action['amount']}"
            self.update_price_history(action, action_id)
            
        except Exception as e:
            logger.error(f"💥 Error sending notification: {e}")
    
    def format_message(self, action: dict) -> str:
        """Format the purchase action into a Telegram message"""
        nft = action['nft']
        
        # Extract NFT details
        name = nft['name']
        external_number = nft['external_collection_number']
        floor_price = nft['floor_price']
        sold_price = action['amount']
        created_at = action['created_at']
        
        # Format NFT name for URL
        formatted_name = name.replace(' ', '')
        nft_url = f"https://t.me/nft/{formatted_name}-{external_number}"
        
        # Extract attributes
        attributes = nft.get('attributes', [])
        model = next((attr for attr in attributes if attr['type'] == 'model'), None)
        symbol = next((attr for attr in attributes if attr['type'] == 'symbol'), None)
        backdrop = next((attr for attr in attributes if attr['type'] == 'backdrop'), None)
        
        # Get model emoji if model exists
        model_emoji = ""
        if model:
            logger.info(f"Model found: {model['value']} ({model['rarity_per_mille']}‰)")
        else:
            logger.info(f"No model data found")
        
        # Debug log the final emoji
        logger.info(f"Final model emoji for {name}: '{model_emoji}'")
        
        # Format date
        try:
            dt = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
            formatted_date = dt.strftime('%Y-%m-%d %H:%M UTC')
        except:
            formatted_date = created_at
        
        # Build message with decorative box design and hyperlinked name with emoji
        message_parts = [
            f"<a href='{nft_url}'>{model_emoji} {name} #{external_number}</a>",
            "",
            "┌─🎉 GIFT SOLD!",
            "│",
            f"├ Gift Name: {model_emoji} {name}",
            f"├ Floor Price: {floor_price} TON",
            f"├ Sold For: {sold_price} TON",
            "│"
        ]
        
        # Add attributes if available
        if model:
            message_parts.append(f"├ Model: {model['value']} ({model['rarity_per_mille']}‰) {model_emoji}")
        if symbol:
            message_parts.append(f"├ Symbol: {symbol['value']} ({symbol['rarity_per_mille']}‰)")
        if backdrop:
            message_parts.append(f"├ Backdrop: {backdrop['value']} ({backdrop['rarity_per_mille']}‰)")
        
        message_parts.extend([
            "│",
            f"└─ Date: {formatted_date}"
        ])
        
        return "\n".join(message_parts)
    
    async def monitoring_loop(self):
        """Main monitoring loop with smart waiting and batch processing"""
        logger.info("🚀 Starting NFT monitoring loop...")
        consecutive_failures = 0
        max_consecutive_failures = 3
        token_refresh_counter = 0
        
        while self.running:
            try:
                # Check if token needs refresh
                if (self.token_last_updated and 
                    (datetime.now() - self.token_last_updated).total_seconds() > self.token_refresh_interval) or \
                   token_refresh_counter >= 720:
                    logger.info("🔄 Periodic token refresh...")
                    await self.extract_fresh_token()
                    token_refresh_counter = 0
                
                # Ensure we have a valid token
                if not await self.ensure_valid_token():
                    logger.error("❌ No valid token available, retrying in 10 seconds...")
                    await asyncio.sleep(10)
                    consecutive_failures += 1
                    if consecutive_failures >= max_consecutive_failures:
                        logger.error("💥 Too many consecutive failures, stopping...")
                        break
                    continue
                
                # Fetch market actions
                actions = await self.fetch_market_actions()
                
                if actions is not None:
                    # Process actions with smart batch logic
                    await self.process_new_actions(actions)
                    consecutive_failures = 0
                    token_refresh_counter += 1
                else:
                    logger.warning("⚠️ Failed to fetch market actions")
                    consecutive_failures += 1
                    if consecutive_failures >= 1:
                        logger.info("🔄 Attempting token refresh due to API failures...")
                        await self.extract_fresh_token()
                        consecutive_failures = 0
                        token_refresh_counter = 0
                
                self.last_check_time = datetime.now().isoformat()
                
                # Smart waiting: faster checks when expecting new sales, slower when waiting
                if self.waiting_for_new_sales:
                    # Slower checks when no new sales expected (every 10 seconds)
                    await asyncio.sleep(10)
                elif not self.initial_batch_sent:
                    # Very fast checks during initial batch discovery (every 2 seconds)
                    await asyncio.sleep(2)
                else:
                    # Normal real-time monitoring (every 5 seconds)
                    await asyncio.sleep(self.sleep_interval)
                
            except KeyboardInterrupt:
                logger.info("👋 Shutdown requested by user")
                break
            except Exception as e:
                consecutive_failures += 1
                logger.error(f"💥 Unexpected error in monitoring loop: {e}")
                
                if consecutive_failures >= max_consecutive_failures:
                    logger.error("💥 Too many consecutive failures, stopping...")
                    break
                    
                # Reduced backoff on errors for faster recovery
                await asyncio.sleep(min(30, 5 * consecutive_failures))
    
    async def cleanup(self):
        """Clean up resources"""
        logger.info("🧹 Cleaning up resources...")
        
        try:
            # Close bot session
            await self.bot.session.close()
            logger.info("📱 Telegram bot session closed")
                
        except Exception as e:
            logger.warning(f"⚠️ Error during cleanup: {e}")
        
        self.save_state()
        logger.info("✅ Cleanup completed")
    
    async def run(self):
        """Main entry point for the bot"""
        self.running = True
        logger.info("🎯 Starting Telegram NFT Market Monitor - Bot Version")
        logger.info(f"📡 Monitoring: {self.api_url}")
        logger.info(f"📢 Telegram Channel: {self.channel_username}")
        logger.info(f"⏱️ Check Interval: {self.sleep_interval} seconds")
        logger.info(f"🛡️ Rate Limits: {config.MAX_MESSAGES_PER_MINUTE}/min, {config.MAX_MESSAGES_PER_HOUR}/hour, {config.MAX_DAILY_MESSAGES}/day")
        
        try:
            # Try to load existing token first
            if os.path.exists('auth_token.txt'):
                try:
                    with open('auth_token.txt', 'r') as f:
                        self.auth_token = f.read().strip()
                    logger.info("📁 Loaded existing token from file")
                except Exception as e:
                    logger.error(f"💥 Error loading token: {e}")
            
            # Cleanup old price history
            self.cleanup_old_price_history()
            
            # Start monitoring
            await self.monitoring_loop()
            
        except Exception as e:
            logger.error(f"💥 Fatal error: {e}")
        finally:
            await self.cleanup()

    def load_auth_token(self):
        """Load auth token from file if exists and not expired"""
        try:
            if os.path.exists('auth_token.txt'):
                # Check file age
                file_age = datetime.now() - datetime.fromtimestamp(os.path.getmtime('auth_token.txt'))
                if file_age.total_seconds() < self.token_refresh_interval:
                    with open('auth_token.txt', 'r') as f:
                        token = f.read().strip()
                        if token:
                            self.auth_token = token
                            self.token_last_updated = datetime.fromtimestamp(os.path.getmtime('auth_token.txt'))
                            logger.info("✅ Loaded valid auth token from file")
                            return True
                else:
                    logger.info("⏰ Token file is old, will refresh")
            return False
        except Exception as e:
            logger.warning(f"Could not load token from file: {e}")
            return False
    
    def save_auth_token(self, token: str):
        """Save auth token to file"""
        try:
            with open('auth_token.txt', 'w') as f:
                f.write(token)
            self.token_last_updated = datetime.now()
            logger.info("💾 Token saved to file")
        except Exception as e:
            logger.warning(f"Could not save token to file: {e}")

    async def setup_browser(self) -> bool:
        """Initialize Playwright browser for token extraction"""
        try:
            logger.info("🌐 Setting up browser for token extraction...")
            self.playwright = await async_playwright().start()
            
            # Use persistent browser data to avoid logout
            user_data_dir = os.path.join(os.getcwd(), "browser_data")
            os.makedirs(user_data_dir, exist_ok=True)
            
            # Launch browser with persistent session
            self.browser = await self.playwright.chromium.launch_persistent_context(
                user_data_dir=user_data_dir,
                headless=False,  # Keep visible for debugging
                args=[
                    '--no-sandbox',
                    '--disable-dev-shm-usage',
                    '--disable-blink-features=AutomationControlled',
                    '--disable-extensions',
                    '--no-first-run',
                    '--disable-default-apps',
                    '--disable-web-security',
                    '--disable-features=VizDisplayCompositor',
                    '--start-maximized',  # Start maximized
                    '--disable-infobars',
                    '--disable-notifications'
                ],
                user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                viewport={'width': 1920, 'height': 1080},
                ignore_default_args=['--enable-automation']  # Remove automation indicators
            )
            
            # The context is the browser itself in persistent mode
            self.context = self.browser
            
            # Enable request interception to capture auth tokens
            await self.context.route("**/*", self._intercept_requests)
            
            self.page = await self.context.new_page()
            
            # Maximize the page window
            await self.page.set_viewport_size({"width": 1920, "height": 1080})
            
            logger.info("✅ Browser setup completed - Chrome should be fully visible")
            return True
            
        except Exception as e:
            logger.error(f"❌ Failed to setup browser: {e}")
            return False

    async def _intercept_requests(self, route):
        """Intercept network requests to capture authorization tokens"""
        request = route.request
        
        # Check if this is a request to Portals Market API
        if 'portals-market.com/api' in request.url and 'actions' in request.url:
            headers = request.headers
            auth_header = headers.get('authorization', '')
            
            if auth_header and ('tma ' in auth_header or 'query_id=' in auth_header):
                # Ensure we have the full token with 'tma ' prefix
                if not auth_header.startswith('tma '):
                    new_token = f'tma {auth_header}'
                else:
                    new_token = auth_header
                    
                if new_token != self.auth_token:
                    self.auth_token = new_token
                    self.save_auth_token(new_token)
                    logger.info("🔑 Captured fresh authorization token!")
                    logger.info(f"🔍 Token preview: {new_token[:50]}...")
        
        # Continue with the request
        await route.continue_()

    async def extract_fresh_token(self) -> bool:
        """Extract fresh token by navigating to Portals channel"""
        if self.token_extraction_in_progress:
            return False
            
        self.token_extraction_in_progress = True
        
        try:
            logger.info("🚀 Extracting fresh authorization token...")
            
            if not self.page:
                if not await self.setup_browser():
                    return False
            
            # Navigate to Portals channel on Telegram Web
            portals_url = "https://web.telegram.org/k/#@portals"
            logger.info(f"🌐 Navigating to: {portals_url}")
            
            try:
                # Set referrer to match the expected flow
                await self.page.set_extra_http_headers({
                    'Referer': 'https://portals-market.com/market-activity'
                })
                
                await self.page.goto(portals_url, wait_until='networkidle', timeout=60000)
                await asyncio.sleep(5)
                
                # Check current URL to see if we need login
                current_url = self.page.url
                logger.info(f"📍 Current URL: {current_url}")
                
                # If redirected to login, wait for user
                if 'login' in current_url.lower() or 'auth' in current_url.lower():
                    logger.info("🔐 Please complete login in the browser window...")
                    logger.info("⏳ Waiting for login completion and navigation to Portals...")
                    
                    # Wait for redirect to Portals
                    login_timeout = 180  # 3 minutes
                    start_time = time.time()
                    
                    while time.time() - start_time < login_timeout:
                        current_url = self.page.url
                        if '@portals' in current_url or 'portals' in current_url.lower():
                            logger.info("✅ Successfully navigated to Portals channel")
                            break
                        await asyncio.sleep(3)
                    else:
                        logger.error("⏰ Login/navigation timeout")
                        return False
                
                # Wait for the channel to load
                logger.info("⏳ Waiting for Portals channel to load...")
                await asyncio.sleep(5)
                
                # Look for the "VIEW IN TELEGRAM" button or similar elements
                try:
                    # Try to find and click the "VIEW IN TELEGRAM" button
                    view_button_selectors = [
                        'button:has-text("VIEW IN TELEGRAM")',
                        'a:has-text("VIEW IN TELEGRAM")',
                        '[class*="view"]:has-text("TELEGRAM")',
                        'button[class*="btn"]',
                        '.btn-primary'
                    ]
                    
                    for selector in view_button_selectors:
                        try:
                            element = await self.page.wait_for_selector(selector, timeout=5000)
                            if element:
                                await element.click()
                                logger.info(f"🖱️ Clicked: {selector}")
                                await asyncio.sleep(3)
                                break
                        except:
                            continue
                    
                    # Wait for potential redirect to portals-market.com
                    await asyncio.sleep(5)
                    current_url = self.page.url
                    logger.info(f"📍 After click, URL: {current_url}")
                    
                    # If we're now on portals-market.com, great!
                    if 'portals-market.com' in current_url:
                        logger.info("✅ Successfully navigated to Portals Market!")
                        await asyncio.sleep(5)  # Wait for the page to fully load
                        
                        # Try to navigate to market activity page
                        try:
                            await self.page.goto('https://portals-market.com/market-activity', wait_until='networkidle')
                            await asyncio.sleep(5)
                            logger.info("📊 Navigated to market activity page")
                        except:
                            logger.info("📊 Staying on current portals-market.com page")
                    
                except Exception as e:
                    logger.debug(f"Button interaction error: {e}")
                
                # Try to interact with the page to trigger API calls
                try:
                    # Wait a bit for the page to fully load
                    await asyncio.sleep(5)
                    
                    # Try clicking various elements to trigger API requests
                    selectors_to_try = [
                        'button',
                        '[role="button"]',
                        '.btn',
                        'div[onclick]',
                        'a',
                        '[class*="button"]',
                        '[class*="btn"]',
                        '[class*="market"]',
                        '[class*="activity"]'
                    ]
                    
                    for selector in selectors_to_try:
                        try:
                            elements = await self.page.query_selector_all(selector)
                            for element in elements[:5]:  # Try first 5 elements
                                try:
                                    await element.click()
                                    await asyncio.sleep(2)
                                    logger.info(f"🖱️ Clicked element: {selector}")
                                    if self.auth_token:  # Break if token captured
                                        break
                                except:
                                    continue
                            if self.auth_token:  # Break if token captured
                                break
                        except:
                            continue
                    
                    # Scroll to trigger lazy loading and more API calls
                    await self.page.evaluate('window.scrollTo(0, document.body.scrollHeight)')
                    await asyncio.sleep(3)
                    await self.page.evaluate('window.scrollTo(0, 0)')
                    await asyncio.sleep(2)
                    
                    # Try refreshing the page to trigger more requests
                    if not self.auth_token:
                        logger.info("🔄 Refreshing page to trigger more API calls...")
                        await self.page.reload(wait_until='networkidle')
                        await asyncio.sleep(5)
                    
                except Exception as e:
                    logger.debug(f"Interaction error: {e}")
                
                # Wait for token to be captured
                wait_time = 0
                max_wait = 120  # 2 minutes
                while not self.auth_token and wait_time < max_wait:
                    await asyncio.sleep(2)
                    wait_time += 2
                    if wait_time % 20 == 0:
                        logger.info(f"⏳ Still waiting for token... ({wait_time}/{max_wait}s)")
                        # Try another interaction
                        try:
                            await self.page.evaluate('window.location.reload()')
                            await asyncio.sleep(3)
                        except:
                            pass
                
                if self.auth_token:
                    logger.info("🎉 Successfully extracted fresh token!")
                    return True
                else:
                    logger.warning("⚠️ Could not capture token automatically")
                    logger.info("📝 Please interact with the Portals Market app manually to trigger API calls")
                    logger.info("💡 Try clicking on different sections, scrolling, or refreshing the page")
                    return False
                    
            except Exception as e:
                logger.error(f"🚨 Navigation error: {e}")
                return False
                
        except Exception as e:
            logger.error(f"💥 Token extraction failed: {e}")
            return False
        finally:
            self.token_extraction_in_progress = False

    def is_token_valid(self) -> bool:
        """Check if the current token file exists and is recent enough"""
        try:
            if not os.path.exists('auth_token.txt'):
                return False
            
            # Check file age
            file_age = time.time() - os.path.getmtime('auth_token.txt')
            # Consider token valid if less than 25 minutes old (instead of 30)
            if file_age < 25 * 60:  # 25 minutes in seconds
                logger.info("🔑 Token file is recent, skipping browser extraction")
                return True
            else:
                logger.info("⏰ Token file is old, will refresh")
                return False
        except Exception as e:
            logger.error(f"💥 Error checking token validity: {e}")
            return False

async def main():
    """Entry point"""
    monitor = TelegramNFTMonitor()
    
    try:
        await monitor.run()
    except KeyboardInterrupt:
        logger.info("👋 Shutting down...")
    except Exception as e:
        logger.error(f"💥 Fatal error in main: {e}")

if __name__ == "__main__":
    asyncio.run(main())
