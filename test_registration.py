import httpx
import json

BASE_URL = "http://localhost:8000/api"

def test_registration():
    payload = {
        "email": "maverick@topgun.com",
        "password": "FlySafePassword1!",
        "first_name": "Pete",
        "last_name": "Mitchell"
    }
    
    print(f"Testing Registration for: {payload['email']}...")
    
    try:
        response = httpx.post(f"{BASE_URL}/auth/register", json=payload, timeout=10.0)
        
        if response.status_code == 201:
            data = response.json()
            print("✅ Registration Successful!")
            print(f"User ID: {data.get('user_id')}")
            if data.get('access_token'):
                print("✅ Session created automatically.")
            else:
                print("ℹ️ Email confirmation may be required (no session returned).")
        else:
            print(f"❌ Registration Failed (Status {response.status_code})")
            print(f"Error: {response.text}")
            
    except Exception as e:
        print(f"❌ Connection Error: {str(e)}")

if __name__ == "__main__":
    test_registration()
