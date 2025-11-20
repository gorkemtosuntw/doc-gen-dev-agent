import os
import re

def list_files_in_repo(root_dir):
    """Lists relevant code files in the repo."""
    file_list = []
    ignore_dirs = {".git", "__pycache__", "venv", "env", "node_modules", ".idea", ".vscode", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"}
    
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        for file in files:
            if file.endswith((".py", ".js", ".ts", ".html", ".css", ".md", ".txt", ".json")):
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, root_dir)
                file_list.append(rel_path)
    return "\n".join(file_list)

def read_file_content(root_dir, file_path):
    full_path = os.path.join(root_dir, file_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def apply_patches(original_content, ai_response):
    """Parses and applies SEARCH/REPLACE blocks."""
    pattern = r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE"
    matches = re.findall(pattern, ai_response, re.DOTALL)
    
    if not matches:
        return original_content, False

    new_content = original_content
    success_count = 0

    for search_block, replace_block in matches:
        if search_block in new_content:
            new_content = new_content.replace(search_block, replace_block, 1)
            success_count += 1
            continue
            
        search_block_stripped = search_block.strip()
        if search_block_stripped in new_content:
             new_content = new_content.replace(search_block_stripped, replace_block, 1)
             success_count += 1
             continue
        
        print(f"⚠️ WARNING: Search block mismatch:\n{search_block[:50]}...")

    return new_content, (success_count > 0)