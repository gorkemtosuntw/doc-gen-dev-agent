import json
from openai import OpenAI
from app.config import Config
from app.utils.file_ops import list_files_in_repo, read_file_content

client = OpenAI(api_key=Config.OPENAI_API_KEY)

def run_smart_agent(root_dir, task_title, task_desc):
    print(f"🕵️ AI Agent Analysis: {task_title}")
    files_tree = list_files_in_repo(root_dir)
    
    system_prompt = f"""
    You are an expert Full-Stack developer. 
    Task: {task_title}
    Files:
    {files_tree}
    
    RULES:
    1. Provide 'SEARCH/REPLACE' blocks.
    2. Use 'read_file' tool.
    3. SILENCE MODE: Output must start with 'FILE: ...'. No talk.
    4. MATCH IDENTATION perfectly.
    
    FORMAT:
    FILE: path/to/file.ts
    <<<<<<< SEARCH
    old_code
    =======
    new_code
    >>>>>>> REPLACE
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Details: {task_desc}"}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Reads file content",
                "parameters": {
                    "type": "object",
                    "properties": {"file_path": {"type": "string"}},
                    "required": ["file_path"],
                },
            }
        }
    ]

    for i in range(3): 
        response = client.chat.completions.create(
            model="gpt-4o", messages=messages, tools=tools, tool_choice="auto"
        )
        msg = response.choices[0].message
        messages.append(msg)

        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                if tool_call.function.name == "read_file":
                    args = json.loads(tool_call.function.arguments)
                    content = read_file_content(root_dir, args['file_path'])
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": "read_file",
                        "content": content
                    })
        else:
            content = msg.content
            if "FILE:" in content and "<<<<<<< SEARCH" in content:
                return content
            
    return "No solution found."