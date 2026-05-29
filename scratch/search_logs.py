import os

tasks_dir = r"C:\Users\17381\.gemini\antigravity\brain\0dc0436b-72b2-46b3-8fb5-2966e8de2d91\.system_generated\tasks"

def main():
    if not os.path.exists(tasks_dir):
        print(f"Directory {tasks_dir} does not exist.")
        return

    log_files = [f for f in os.listdir(tasks_dir) if f.endswith(".log")]
    log_files.sort(key=lambda x: os.path.getmtime(os.path.join(tasks_dir, x)), reverse=True)

    print(f"Searching {len(log_files)} log files for '45' or error tracebacks...")
    found = False
    for filename in log_files:
        filepath = os.path.join(tasks_dir, filename)
        try:
            with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                if "45" in content or "exception" in content.lower() or "error" in content.lower():
                    # Check if Task 45 specifically is mentioned
                    if "45" in content:
                        print(f"\n--- Found mention in {filename} (Last modified: {os.path.getmtime(filepath)}) ---")
                        lines = content.splitlines()
                        for i, line in enumerate(lines):
                            if "45" in line or "exception" in line.lower() or "error" in line.lower():
                                start = max(0, i - 3)
                                end = min(len(lines), i + 4)
                                print(f"Context from {filename} around line {i+1}:")
                                for idx in range(start, end):
                                    print(f"  {idx+1}: {lines[idx]}")
                                print("-" * 40)
                        found = True
        except Exception as e:
            print(f"Error reading {filename}: {e}")

    if not found:
        print("No specific error traces or references to Task 45 found in the logs.")

if __name__ == "__main__":
    main()
