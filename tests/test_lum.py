#!/usr/bin/env python3
"""
Test script to verify Loominum server connection and browser state.
Checks if browser is connected, tests communication, etc.
"""

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from loominum.config import LumConf
from loominum.client import LumClient
from loominum.server import lum


async def test_lum():
    """Test Loominum connection and browser status."""
    print("=" * 60)
    print("Loominum Connection Test")
    print("=" * 60)

    print(f"1. Server browser connected: {lum.is_connected()}")
    print(f"2. Server python clients: {len(lum.python_clients)}")
    print()

    print("3. Testing Python client connection...")
    conf = LumConf()
    try:
        async with LumClient(conf=conf) as client:
            print("   OK Python client connected to Loominum")

            print("4. Testing browser communication...")
            try:
                result = await client.exec('return "Hello from browser"', timeout=5)
                print(f"   OK Browser response: {result}")

                url = await client.exec('return window.location.href', timeout=5)
                print(f"   OK Current page: {url}")

                print("5. Testing page-state query...")
                page_state = await client.exec('''
                    return {
                        url: window.location.href,
                        title: document.title,
                        cookies: document.cookie.length
                    };
                ''', timeout=5)
                print(f"   OK Page state: {page_state}")

                print()
                print("=" * 60)
                print("ALL TESTS PASSED - Loominum is working correctly!")
                print("=" * 60)

            except Exception as e:
                print(f"   FAIL Browser communication failed: {e}")
                print()
                print("ISSUE: Browser not connected to Loominum")
                print("SOLUTION:")
                print("   1. Open the browser to the page you want to drive")
                print("   2. Open DevTools (F12)")
                print("   3. Go to Console tab")
                print("   4. Paste and press Enter:")
                print("      fetch('http://localhost:7773/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);")
                print()

    except Exception as e:
        print(f"   FAIL Python client connection failed: {e}")
        print()
        print("ISSUE: Loominum server not running")
        print("SOLUTION: Start it with: lum")
        print()

if __name__ == "__main__":
    asyncio.run(test_lum())
