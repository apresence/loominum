#!/usr/bin/env python3
"""
Test script to verify executor server connection and browser state.
Checks if browser is connected, tests communication, etc.
"""

import asyncio
import sys
from pathlib import Path

# Add src directory to path
sys.path.insert(0, str(Path(__file__).parent.parent / 'src'))

from executor.client import ExecutorClient
from executor.server import executor


async def test_executor():
    """Test executor connection and browser status."""
    print("=" * 60)
    print("🔧 Executor Connection Test")
    print("=" * 60)
    
    # Check server state
    print(f"1. Server browser connected: {executor.is_connected()}")
    print(f"2. Server python clients: {len(executor.python_clients)}")
    print()
    
    # Test Python client connection
    print("3. Testing Python client connection...")
    try:
        async with ExecutorClient() as client:
            print("   ✓ Python client connected to executor")
            
            print("4. Testing browser communication...")
            try:
                # Test basic JS execution
                result = await client.exec('return "Hello from browser"', timeout=5)
                print(f"   ✓ Browser response: {result}")
                
                # Test page info
                url = await client.exec('return window.location.href', timeout=5)
                print(f"   ✓ Current page: {url}")
                
                # Test Suno auth check
                print("5. Testing Suno authentication...")
                auth_result = await client.exec('''
                    const url = window.location.href;
                    const onSuno = url.includes('suno.com');
                    const sessionCookie = document.cookie.split(';').find(c => c.trim().startsWith('__session='));
                    const hasSession = !!sessionCookie;
                    
                    return {
                        onSuno: onSuno,
                        hasSession: hasSession,
                        authenticated: onSuno && hasSession
                    };
                ''', timeout=5)
                print(f"   ✓ Auth check: {auth_result}")
                
                print()
                print("=" * 60)
                print("🎉 ALL TESTS PASSED - Executor is working correctly!")
                print("=" * 60)
                
            except Exception as e:
                print(f"   ❌ Browser communication failed: {e}")
                print()
                print("💡 ISSUE: Browser not connected to executor")
                print("📋 SOLUTION:")
                print("   1. Open browser to https://suno.com")
                print("   2. Open DevTools (F12)")  
                print("   3. Go to Console tab")
                print("   4. Paste and press Enter:")
                print("      fetch('http://localhost:7993/remote.js?t='+Date.now()).then(r=>r.text()).then(eval);")
                print()
                
    except Exception as e:
        print(f"   ❌ Python client connection failed: {e}")
        print()
        print("💡 ISSUE: Executor server not running")
        print("📋 SOLUTION: Run './ctl start' to start executor server")
        print()

if __name__ == "__main__":
    asyncio.run(test_executor())