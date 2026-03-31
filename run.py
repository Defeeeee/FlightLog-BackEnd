import uvicorn
import os
from dotenv import load_dotenv

if __name__ == "__main__":
    # Load environment variables explicitly if needed
    load_dotenv()
    
    # Run the application using Uvicorn
    # 'src.app:app' refers to the 'app' instance in 'src/app.py'
    uvicorn.run(
        "src.app:app", 
        host="0.0.0.0", 
        port=8000, 
        reload=True if os.getenv("DEBUG", "True").lower() == "true" else False,
        log_level="info"
    )
