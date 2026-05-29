import os
import time

videos_dir = r"data/sessions/46/videos"

def main():
    if not os.path.exists(videos_dir):
        print(f"Directory {videos_dir} does not exist.")
        return

    files = os.listdir(videos_dir)
    print(f"=== Active Videos in Task 46 (Total: {len(files)}) ===")
    for f in files:
        filepath = os.path.join(videos_dir, f)
        mtime = os.path.getmtime(filepath)
        size = os.path.getsize(filepath)
        print(f"File: {f}")
        print(f"  Size: {size / 1024:.2f} KB")
        print(f"  Last Modified: {time.ctime(mtime)}")
        print(f"  Current Time: {time.ctime()}")
        print()

if __name__ == "__main__":
    main()
