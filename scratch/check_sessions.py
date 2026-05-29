import os
import sys
from pathlib import Path
from datetime import datetime

def main():
    sessions_dir = Path("data/sessions")
    if not sessions_dir.exists():
        print("Sessions directory not found.")
        return
        
    print("=== Listing recent sessions ===")
    sessions = []
    for item in sessions_dir.iterdir():
        if item.is_dir() and item.name != "task-rt-001" and item.name != "debug-local":
            mtime = item.stat().st_mtime
            sessions.append((item, mtime))
            
    # Sort by mtime descending
    sessions.sort(key=lambda x: x[1], reverse=True)
    
    for s, mtime in sessions[:10]:
        dt = datetime.fromtimestamp(mtime).isoformat()
        print(f"\nSession: {s.name} | Modified: {dt}")
        
        # Check videos
        video_dir = s / "videos"
        if video_dir.exists():
            videos = list(video_dir.glob("*.webm"))
            print(f"  Videos found: {len(videos)}")
            for v in videos:
                v_size = v.stat().st_size
                print(f"    - {v.name} ({v_size} bytes)")
        else:
            print("  No videos folder.")
            
        # Check trace
        trace = s / "trace.zip"
        if trace.exists():
            print(f"  Trace zip found ({trace.stat().st_size} bytes)")
        else:
            print("  No trace zip.")

if __name__ == "__main__":
    main()
