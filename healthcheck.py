import datetime
import json

def healthcheck():
    """
    Returns a simple health status dictionary.
    """
    return {
        "status": "online",
        "service": "Alpaca MCP Remote",
        "timestamp": datetime.datetime.utcnow().isoformat()
    }

if __name__ == "__main__":
    print(json.dumps(healthcheck()))
