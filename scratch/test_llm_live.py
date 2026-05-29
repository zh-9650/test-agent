import os
import sys
from dotenv import load_dotenv
from langchain_core.messages import HumanMessage

# Add project root to path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

load_dotenv()

from core.llm_client import get_llm_client

def main():
    try:
        print("Testing LLM client initialization...")
        client = get_llm_client("sonnet")
        print(f"Model resolved: {client.model}")
        print("Sending simple test message...")
        response = client.invoke([HumanMessage(content="你好，请回复'pong'")])
        print("Response received successfully:")
        print(response.content)
    except Exception as e:
        print("LLM Call Failed with Exception:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
