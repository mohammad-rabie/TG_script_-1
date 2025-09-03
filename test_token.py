#!/usr/bin/env python3
"""
Test script to validate Portals Market token extraction and API calls
"""

import asyncio
import aiohttp
import json
from datetime import datetime

async def test_api_call(token):
    """Test API call with provided token"""
    headers = {
        'authorization': token,
        'accept': 'application/json, text/plain, */*',
        'authority': 'portals-market.com',
        'method': 'GET',
        'path': '/api/market/actions/?offset=0&limit=5&action_types=buy',
        'scheme': 'https',
        'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    params = {
        'offset': 0,
        'limit': 5,
        'action_types': 'purchase'
    }
    
    api_url = "https://portals-market.com/api/market/actions/"
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                api_url,
                params=params,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=30)
            ) as response:
                
                print(f"Status Code: {response.status}")
                
                if response.status == 200:
                    data = await response.json()
                    actions = data.get('actions', [])
                    print(f"✅ Success! Found {len(actions)} actions")
                    
                    if actions:
                        print("\n📊 Sample action:")
                        sample = actions[0]
                        print(f"  - NFT: {sample['nft']['name']}")
                        print(f"  - Price: {sample['amount']} TON")
                        print(f"  - Date: {sample['created_at']}")
                    
                    return True
                else:
                    error_text = await response.text()
                    print(f"❌ Error: {response.status}")
                    print(f"Response: {error_text}")
                    return False
                    
    except Exception as e:
        print(f"💥 Request failed: {e}")
        return False

async def main():
    """Main test function"""
    print("🧪 Portals Market API Test")
    print("=" * 40)
    
    # Try to load token from file
    token = None
    try:
        with open('auth_token.txt', 'r') as f:
            token = f.read().strip()
        print(f"📁 Loaded token from file: {token[:50]}...")
    except:
        print("❌ No token file found")
        
    if not token:
        print("\n💡 Manual token input:")
        print("1. Open browser and go to https://t.me/portalsmarket_bot/app")
        print("2. Open Developer Tools (F12)")
        print("3. Go to Network tab")
        print("4. Interact with the app to trigger API calls")
        print("5. Look for requests to portals-market.com/api/market/actions/")
        print("6. Copy the full 'authorization' header value")
        
        token = input("\nPaste the authorization token here: ").strip()
        
        if token:
            # Save token for future use
            with open('auth_token.txt', 'w') as f:
                f.write(token)
            print("💾 Token saved to auth_token.txt")
    
    if token:
        print(f"\n🔍 Testing API call...")
        success = await test_api_call(token)
        
        if success:
            print("\n🎉 Token is valid and working!")
        else:
            print("\n❌ Token validation failed")
    else:
        print("\n⚠️ No token provided")

if __name__ == "__main__":
    asyncio.run(main())
