"""
Test Script for Claude Chat Setup
Python 3.12.7
Run this to verify your setup is working correctly
"""

import os
import sys
from dotenv import load_dotenv

def test_imports():
    """Test if all required packages are installed"""
    print("1. Testing package imports...")
    
    packages = {
        'streamlit': 'streamlit',
        'anthropic': 'anthropic',
        'dotenv': 'python-dotenv'
    }
    
    missing = []
    for module, package in packages.items():
        try:
            __import__(module)
            print(f"   ✅ {package} - OK")
        except ImportError:
            print(f"   ❌ {package} - NOT INSTALLED")
            missing.append(package)
    
    if missing:
        print(f"\n   Please install missing packages:")
        print(f"   pip install {' '.join(missing)}")
        return False
    
    return True


def test_env_file():
    """Test if .env file exists and has API key"""
    print("\n2. Testing .env file...")
    
    if not os.path.exists('.env'):
        print("   ❌ .env file NOT FOUND")
        print("   Please create a .env file with:")
        print("   KEY=your-anthropic-api-key")
        return False
    
    print("   ✅ .env file found")
    
    # Load and check API key
    load_dotenv()
    api_key = os.getenv('KEY')
    
    if not api_key:
        print("   ❌ API key NOT FOUND in .env")
        print("   Please add to .env file:")
        print("   KEY=your-anthropic-api-key")
        return False
    
    if not api_key.startswith('sk-ant-'):
        print("   ⚠️  API key format might be incorrect")
        print("   Anthropic keys usually start with 'sk-ant-'")
    else:
        print(f"   ✅ API key found: {api_key[:15]}...")
    
    return True


def test_api_connection():
    """Test if API key works"""
    print("\n3. Testing API connection...")
    
    try:
        import anthropic
        load_dotenv()
        
        api_key = os.getenv('KEY')
        if not api_key:
            print("   ❌ No API key to test")
            return False
        
        client = anthropic.Anthropic(api_key=api_key)
        
        # Try a minimal request
        response = client.messages.create(
            model="claude-3-haiku-20240307",  # Most likely to be available
            max_tokens=10,
            messages=[{"role": "user", "content": "Hi"}]
        )
        
        print("   ✅ API connection successful!")
        print(f"   Response: {response.content[0].text[:50]}")
        return True
        
    except anthropic.AuthenticationError:
        print("   ❌ Invalid API key")
        print("   Please check your API key at:")
        print("   https://console.anthropic.com")
        return False
    
    except anthropic.PermissionDeniedError:
        print("   ⚠️  API key valid but no model access")
        print("   Check your subscription at:")
        print("   https://console.anthropic.com")
        return True  # Key works, just limited access
    
    except Exception as e:
        print(f"   ❌ Connection failed: {str(e)[:100]}")
        return False


def test_streamlit():
    """Test if Streamlit is properly configured"""
    print("\n4. Testing Streamlit configuration...")
    
    try:
        import streamlit
        version = streamlit.__version__
        print(f"   ✅ Streamlit version: {version}")
        
        # Check if it's a recent version
        major, minor = map(int, version.split('.')[:2])
        if major < 1 or (major == 1 and minor < 30):
            print(f"   ⚠️  Consider updating Streamlit:")
            print(f"   pip install --upgrade streamlit")
        
        return True
        
    except Exception as e:
        print(f"   ❌ Streamlit test failed: {e}")
        return False


def test_file_structure():
    """Test if all required files are present"""
    print("\n5. Testing file structure...")
    
    required_files = {
        'app.py': 'Main application file',
        'requirements.txt': 'Dependencies list',
        '.env': 'API key configuration'
    }
    
    all_present = True
    for file, description in required_files.items():
        if os.path.exists(file):
            print(f"   ✅ {file} - {description}")
        else:
            print(f"   ❌ {file} - MISSING ({description})")
            all_present = False
    
    return all_present


def main():
    """Run all tests"""
    print("=" * 50)
    print("Claude Chat Setup Test")
    print("=" * 50)
    
    tests = [
        test_imports,
        test_env_file,
        test_api_connection,
        test_streamlit,
        test_file_structure
    ]
    
    results = []
    for test in tests:
        try:
            results.append(test())
        except Exception as e:
            print(f"\n❌ Test failed with error: {e}")
            results.append(False)
    
    print("\n" + "=" * 50)
    print("Test Summary:")
    print("=" * 50)
    
    if all(results):
        print("✅ All tests passed! Your setup is ready.")
        print("\nYou can now run the application with:")
        print("streamlit run app.py")
    else:
        failed = sum(1 for r in results if not r)
        print(f"⚠️  {failed} test(s) failed or had warnings.")
        print("\nPlease fix the issues above before running the app.")
        print("Check TROUBLESHOOTING.md for help.")
    
    print("\n" + "=" * 50)


if __name__ == "__main__":
    main()