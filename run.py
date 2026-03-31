import uvicorn
import os
from dotenv import load_dotenv

if __name__ == "__main__":
    # Load environment variables explicitly if needed
    load_dotenv()
    
    # Run the application using Uvicorn on aviation-themed port 7477
    uvicorn.run(
        "src.app:app", 
        host="0.0.0.0", 
        port=7477, 
        reload=True if os.getenv("DEBUG", "True").lower() == "true" else False,
        log_level="info"
    )
