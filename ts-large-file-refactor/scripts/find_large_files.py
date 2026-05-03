import os
import argparse
from pathlib import Path

def find_large_files(directory, min_lines):
    results = []
    
    for root, _, files in os.walk(directory):
        if 'node_modules' in root or '.git' in root or 'dist' in root or 'build' in root or '.next' in root:
            continue
            
        for file in files:
            if file.endswith('.ts') or file.endswith('.tsx'):
                filepath = os.path.join(root, file)
                try:
                    with open(filepath, 'r', encoding='utf-8') as f:
                        lines = f.readlines()
                        count = len(lines)
                        if count >= min_lines:
                            results.append((filepath, count))
                except Exception as e:
                    pass
                    
    # Sort by line count descending
    results.sort(key=lambda x: x[1], reverse=True)
    
    if not results:
        print(f"No TypeScript files found with {min_lines}+ lines in {directory}.")
        return
        
    print(f"{'Lines':<10} | {'File Path'}")
    print("-" * 60)
    for filepath, count in results:
        # Get relative path for cleaner output
        try:
            rel_path = os.path.relpath(filepath, directory)
        except:
            rel_path = filepath
        print(f"{count:<10} | {rel_path}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Find large TypeScript files in a directory.")
    parser.add_argument("--dir", default=".", help="Directory to search (default: current directory)")
    parser.add_argument("--min-lines", type=int, default=200, help="Minimum line count to flag (default: 200)")
    
    args = parser.parse_args()
    
    if not os.path.isdir(args.dir):
        print(f"Error: Directory '{args.dir}' does not exist.")
        exit(1)
        
    find_large_files(args.dir, args.min_lines)
