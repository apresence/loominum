#!/usr/bin/env python3
"""
Test script to verify UnBilliCord server connection and browser state.
Checks if browser is connected, tests communication, etc.
"""

import asyncio
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from unbillicord.client import UBCClient
from unbillicord.server import ubc


async def test_ubc():
    """Test UnBilliCord connection and browser status."""
    print("=" * 60)
    print("🔧 UnBilliCord Connection Test")
    print("=" * 60)

    # Check server state
    print(f"1. Server browser connected: {ubc.is_connected()}")
    print(f"2. Server python clients: {len(ubc.python_clients)}")
    print()
    
    # Test Python client connection
    print("3. Testing Python client connection...")
    try:
        async with UBCClient() as client:
            print("   ✓ Python client connected to UnBilliCord")
            
            print("4. Testing browser communication...")
            try:
                # Test basic JS execution
                result = await client.exec('return "Hello from browser"', timeout=5)
                print(f"   ✓ Browser response: {result}")
                
                # Test page info
                url = await client.exec('return window.location.href', timeout=5)
                print(f"   ✓ Current page: {url}")
                
                # Test a basic page-state query
                print("5. Testing page-state query...")
                page_state = await client.exec('''
                    return {
                        url: window.location.href,
                        title: document.title,
                        cookies: document.cookie.length
                    };
                ''', timeout=5)
                print(f"   ✓ Page state: {page_state}")
                
                print()
                print("=" * 60)
                print("🎉 ALL TESTS PASSED - UnBilliCord is working correctly!")
                print("=" * 60)
                
            except Exception as e:
                print(f"   ❌ Browser communication failed: {e}")
                print()
                print("💡 ISSUE: Browser not connected to UnBilliCord")
                print("📋 SOLUTION:")
                print("   1. Open the browser to the page you want to drive")
                print("   2. Open DevTools (F12)")
                print("   3. Go to Console tab")
                print("   4. Paste and press Enter:")
                print("      fetch('http://localhost:7773/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);")
                print()
                
    except Exception as e:
        print(f"   ❌ Python client connection failed: {e}")
        print()
        print("💡 ISSUE: UnBilliCord server not running")
        print("📋 SOLUTION: Start it with: PYTHONPATH=src python -m unbillicord.server")
        print()

if __name__ == "__main__":
    asyncio.run(test_ubc())