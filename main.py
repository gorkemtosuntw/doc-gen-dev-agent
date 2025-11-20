import os
import shutil
import uuid
from fastapi import FastAPI, Request, BackgroundTasks
from github import Github
from git import Repo
import requests
from dotenv import load_dotenv
from openai import OpenAI
import re
import json

load_dotenv()

# API Configurations
TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_REPO_NAME = "gorkemtosuntw/doc-gen-mvp" # Ex: "username/repo-name"
REPO_URL = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO_NAME}.git"

# Trello Lists & Bot Config
LIST_IN_PROGRESS = "691d9d7f9faff31f3cc13819" 
LIST_REVIEW = "691d9d7f9faff31f3cc1381a"
BOT_USERNAME = "gorkemt1" # Bot username in Trello
app = FastAPI()
client = OpenAI(api_key=OPENAI_API_KEY)

def list_files_in_repo(root_dir):
    """
    Lists files in the repo (Filters out unnecessary ones).
    Crucial for Cost Efficiency.
    """
    file_list = []
    # Remove folders to ignore
    ignore_dirs = {".git", "__pycache__", "venv", "env", "node_modules", ".idea", ".vscode", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"}
    
    for root, dirs, files in os.walk(root_dir):
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for file in files:
            # Include only code files (skip images, etc.)
            if file.endswith((".py", ".js", ".ts", ".html", ".css", ".md", ".txt", ".json")):
                full_path = os.path.join(root, file)
                # Remove root path to show relative path (Token saving)
                rel_path = os.path.relpath(full_path, root_dir)
                file_list.append(rel_path)
    
    return "\n".join(file_list)

def read_file_content(root_dir, file_path):
    """Reads the content of the selected file."""
    full_path = os.path.join(root_dir, file_path)
    try:
        with open(full_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {str(e)}"

def apply_patches(original_content, ai_response):
    pattern = r"<<<<<<< SEARCH\n(.*?)\n=======\n(.*?)\n>>>>>>> REPLACE"
    matches = re.findall(pattern, ai_response, re.DOTALL)
    
    if not matches:
        return original_content, False

    new_content = original_content
    success_count = 0

    for search_block, replace_block in matches:
        # --- ENHANCED MATCHING ---
        # 1. Try direct match
        if search_block in new_content:
            new_content = new_content.replace(search_block, replace_block, 1)
            success_count += 1
            continue
            
        # 2. If not found, try stripping whitespace at line ends. 
        # This is risky but usually works.
        search_block_stripped = search_block.strip()
        if search_block_stripped in new_content:
             new_content = new_content.replace(search_block_stripped, replace_block, 1)
             success_count += 1
             continue
             
        # 3. If still not found, try advanced normalization (skipping for now, first 2 steps solve 90%)
        
        print(f"⚠️ WARNING: Search block did not match exactly:\n---\n{search_block}\n---")

    return new_content, (success_count > 0)
    
def move_trello_card(card_id, list_id):
    url = f"https://api.trello.com/1/cards/{card_id}"
    query = {
        'idList': list_id,
        'key': TRELLO_API_KEY,
        'token': TRELLO_TOKEN
    }
    requests.put(url, params=query)

def add_comment_trello(card_id, text):
    url = f"https://api.trello.com/1/cards/{card_id}/actions/comments"
    query = {
        'text': text,
        'key': TRELLO_API_KEY,
        'token': TRELLO_TOKEN
    }
    requests.post(url, params=query)

def get_card_details(card_id):
    url = f"https://api.trello.com/1/cards/{card_id}"
    query = {'key': TRELLO_API_KEY, 'token': TRELLO_TOKEN}
    resp = requests.get(url, params=query)
    return resp.json()

def run_smart_agent(root_dir, task_title, task_desc):
    print(f"🕵️ Smart Agent Starting Analysis: {task_title}")
    files_tree = list_files_in_repo(root_dir)
    
    system_prompt = f"""
    You are an expert Full-Stack developer. You are working on an existing codebase.
    
    YOUR TASK:
    Perform 'Surgical Intervention' on the necessary files to fulfill the given Task ({task_title}).

    EXISTING FILES:
    {files_tree}

    RULES (VERY IMPORTANT):
    1. NEVER rewrite the whole file from scratch. This is forbidden.
    2. Only provide the parts you want to change in 'SEARCH/REPLACE' blocks.
    3. Use the 'read_file' tool to read files.
    4. Find which file is relevant to the task.
    5. Analyze the code and write the corrected full version (of the block).
    6. CODE STYLE: Stick to the file's existing indentation structure (Tab or Space?). 
       If the file uses 4 spaces, you use 4 spaces.
    7. (VERY IMPORTANT) SILENCE MODE:
       - Never make explanations like "I will do this", "Here is your code", "I made this change".
       - Your output must start directly and only with the 'FILE: ...' line.
       - Do not say any other words.

    FORMAT:
    You must use the following format to make changes (as plain text, not inside code blocks):

    FORMAT EXAMPLE:
    FILE: common/types.ts
    <<<<<<< SEARCH
    interface A {{
        x: string;
    }}
    =======
    interface A {{
        x: string;
        y: number;
    }}
    >>>>>>> REPLACE
    
    If you are making changes in multiple files, write the FILE: line again for each one.

    TIPS:
    - The code in the 'SEARCH' block must match the target file CHARACTER BY CHARACTER (including indentation). Otherwise, the match will fail.
    - To ensure uniqueness, include the lines above and below the line you are changing in the SEARCH block.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Task Detail: {task_desc}. Please read files if necessary and fix."}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Reads the content of a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Relative path of the file to read (e.g., src/main.py)"},
                    },
                    "required": ["file_path"],
                },
            }
        }
    ]

    for i in range(3): 
        print(f"🔄 Round {i+1}/3 running...")
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto" 
        )
        
        msg = response.choices[0].message
        messages.append(msg) # Add to history (Memory)

        # If Agent wants to call a Tool (e.g., Read File)
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                
                if fn_name == "read_file":
                    print(f"📖 Agent reading file: {fn_args['file_path']}")
                    content = read_file_content(root_dir, fn_args['file_path'])
                    
                    # Feed tool result back to AI
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": content
                    })
        else:
            # If no Tool called, it means the answer (Code) is found.
            # Check if answer contains code block.
            content = msg.content
            print(content)
            if "FILE:" in content and "<<<<<<< SEARCH" in content:
                print("💡 Agent found the solution!")
                return content # Return code and explanation
            else:
                # If no code, maybe it needs more info but we force loop continuation or exit.
                print("⚠️ Agent did not produce code, loop continues.")
    
    return "Agent could not produce a solution."

def run_agent_task(card_id, card_name, card_desc):
    print(f"🚀 Agent started working: {card_name}")

    move_trello_card(card_id, LIST_IN_PROGRESS)
    # Get absolute path of current working directory
    base_dir = os.getcwd() 
    workspace_root = os.path.join(base_dir, "workspace")
    
    # Create a unique folder path with UUID
    folder_name = str(uuid.uuid4())
    work_dir = os.path.join(workspace_root, folder_name)

    # Create workspace root folder if not exists
    if not os.path.exists(workspace_root):
        os.makedirs(workspace_root)
    
    # Cleanup (In the unlikely event of UUID collision)
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    
    try:
        # 3. Clone Repo
        print(f"📥 Cloning repo: {work_dir}")
        repo = Repo.clone_from(REPO_URL, work_dir)

        branch_name = f"feature/ticket-{card_id[-5:]}" # Last 5 digits of Card ID
        current = repo.create_head(branch_name)
        current.checkout()

        print(f"🤖 AI is coding: {card_name}")
        generated_code = run_smart_agent(work_dir, card_name, card_desc)

        target_file_path = None
        original_content = ""
        search_match = re.search(r"<<<<<<< SEARCH\n(.*?)\n", generated_code)
        if search_match:
            first_line_of_code = search_match.group(1).strip()
            for root, _, files in os.walk(work_dir):
                for file in files:
                    if file.endswith(".ts"):
                        path = os.path.join(root, file)
                        with open(path, "r", encoding="utf-8") as f:
                            content = f.read()
                            if first_line_of_code in content:
                                target_file_path = path
                                original_content = content
                                break
                if target_file_path: break
        
        if target_file_path:
            print(f"🎯 Target file detected: {target_file_path}")
            new_content, applied = apply_patches(original_content, generated_code)

            if applied:
                with open(target_file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_content)
                print("✅ Patch applied successfully!")
                repo.index.add([target_file_path])
                commit_msg = f"Fix: {card_name} (AI Search/Replace)"
            else:
                print("⚠️ Patch failed (Search block did not match).")
                commit_msg = "Docs: AI suggested solution but failed to apply."
                # Log AI response anyway
                with open(os.path.join(work_dir, "AI_PATCH_FAILED.md"), "w") as f:
                    f.write(generated_code)
                repo.index.add(["AI_PATCH_FAILED.md"])
        else:
            print("⚠️ Target file not found or AI wanted to create a new file.")
            # If file not found, maybe it wrote code from scratch.
            # Create 'ai_generated.ts' with old logic.
            filename = "ai_generated_v2.ts"
            with open(os.path.join(work_dir, filename), "w") as f:
                f.write(generated_code) # Write raw response
            repo.index.add([filename])
            commit_msg = f"Feat: {card_name} (New File)"

        repo.index.commit(commit_msg)
        origin = repo.remote(name='origin')
        origin.push(branch_name)
        print("📤 Code pushed.")

        g = Github(GITHUB_TOKEN)
        gh_repo = g.get_repo(GITHUB_REPO_NAME)
        pr_body = f"🤖 **AI Agent PR**\n\n**Task:** {card_name}\n**Request:** {card_desc}\n\nAI generated this code automatically."
        pr = gh_repo.create_pull(
            title=f"AI Feat: {card_name}",
            body=pr_body,
            head=branch_name,
            base="main"
        )

        add_comment_trello(card_id, f"✅ Development complete! PR Link: {pr.html_url}")
        move_trello_card(card_id, LIST_REVIEW)
        print("🏁 Process finished successfully.")

    except Exception as e:
        print(f"❌ ERROR OCCURRED: {e}")
        add_comment_trello(card_id, f"⚠️ An error occurred: {str(e)}")

    finally:
        # Windows cleanup code
        try:
            if os.path.exists(work_dir):
                def on_rm_error(func, path, exc_info):
                    import stat
                    os.chmod(path, stat.S_IWRITE)
                    os.unlink(path)
                shutil.rmtree(work_dir, onerror=on_rm_error)
        except Exception:
            pass

@app.post("/webhook")
async def trello_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        action = data.get('action', {})
        action_type = action.get('type')

        if action_type == 'addMemberToCard':
            member_name = action.get('member', {}).get('username')

            if member_name == BOT_USERNAME:
                card_data = action.get('data', {}).get('card', {})
                card_id = card_data.get('id')
                card_name = card_data.get('name')

                # Call API to get detailed card description
                full_card = get_card_details(card_id)
                card_desc = full_card.get('desc', '')

                background_tasks.add_task(run_agent_task, card_id, card_name, card_desc)
                print(f"Request received, task queued: {card_name}")

        return {"status": "ok"}        
    except Exception as e:
        print(f"Webhook Error: {e}")
        return {"status": "error"}

@app.head("/webhook")
async def trello_webhook_check():
    """Trello sends HEAD request when setting up webhook initially, must return OK."""
    return {"status": "ok"}