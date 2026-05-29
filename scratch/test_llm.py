import asyncio
import os
from dotenv import load_dotenv
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from langchain_core.messages import HumanMessage
from core.llm_client import get_llm_client

load_dotenv()

async def main():
    print("=== Testing LLM Client Connection ===")
    print(f"ANTHROPIC_BASE_URL: {os.getenv('ANTHROPIC_BASE_URL')}")
    print(f"ANTHROPIC_MODEL: {os.getenv('ANTHROPIC_MODEL')}")
    
    try:
        client = get_llm_client(model_type="sonnet")
        print("LLM Client obtained successfully.")
        
        print("Sending test message...")
        response = await client.ainvoke([HumanMessage(content="你好，请回复：123")])
        print("Response received:")
        content = response.content
        print(f"Content Type: {type(content)}")
        print(f"Content Items Count: {len(content)}")
        for idx, item in enumerate(content):
            print(f"Item {idx}: {type(item)}")
            if isinstance(item, dict):
                for k, v in item.items():
                    safe_v = str(v).encode('gbk', errors='ignore').decode('gbk')
                    print(f"  {k}: {safe_v[:200]}")
            else:
                safe_item = str(item).encode('gbk', errors='ignore').decode('gbk')
                print(f"  Value: {safe_item[:200]}")
    except Exception as e:
        print("Error during LLM call:")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    asyncio.run(main())
