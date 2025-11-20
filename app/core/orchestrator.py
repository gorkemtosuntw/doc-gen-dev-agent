import os
import shutil
import uuid
import re
from git import Repo
from github import Github
from app.config import Config
from app.services import trello_service, ai_agent
from app.utils.file_ops import apply_patches

def run_agent_pipeline(card_id, card_name, card_desc):
    print(f"🚀 Pipeline Started: {card_name}")
    trello_service.move_card(card_id, Config.LIST_IN_PROGRESS)
    
    # Workspace Setup
    work_dir = os.path.join(os.getcwd(), "workspace", str(uuid.uuid4()))
    if not os.path.exists(work_dir): os.makedirs(work_dir)
    
    try:
        # 1. Clone
        print(f"📥 Cloning...")
        repo = Repo.clone_from(Config.REPO_URL, work_dir)
        repo.config_writer().set_value("credential", "helper", "").release() # Windows fix
        
        branch_name = f"feature/ticket-{card_id[-5:]}"
        repo.create_head(branch_name).checkout()
        
        # 2. AI Think
        generated_code = ai_agent.run_smart_agent(work_dir, card_name, card_desc)
        
        # 3. Parse & Patch
        target_file = None
        search_match = re.search(r"FILE:\s*(.*?)\n", generated_code)
        
        if search_match:
            filename = search_match.group(1).strip()
            target_path = os.path.join(work_dir, filename)
            
            if os.path.exists(target_path):
                with open(target_path, "r", encoding="utf-8") as f:
                    original = f.read()
                
                new_content, applied = apply_patches(original, generated_code)
                
                if applied:
                    with open(target_path, "w", encoding="utf-8", newline="\n") as f:
                        f.write(new_content)
                    repo.index.add([target_path])
                    repo.index.commit(f"Fix: {card_name} (AI)")
                    target_file = filename
        
        # 4. Push & PR
        if target_file:
            origin = repo.remote(name='origin')
            origin.push(branch_name)
            
            g = Github(Config.GITHUB_TOKEN)
            gh_repo = g.get_repo(Config.GITHUB_REPO_NAME)
            pr = gh_repo.create_pull(
                title=f"AI Feat: {card_name}",
                body=f"Auto-generated for Trello Card: {card_name}",
                head=branch_name,
                base="main"
            )
            
            trello_service.add_comment(card_id, f"✅ PR Opened: {pr.html_url}")
            trello_service.move_card(card_id, Config.LIST_REVIEW)
        else:
            trello_service.add_comment(card_id, "⚠️ AI could not apply changes.")

    except Exception as e:
        print(f"❌ Error: {e}")
        trello_service.add_comment(card_id, f"⚠️ Error: {str(e)}")
        
    finally:
        if os.path.exists(work_dir):
            def on_rm_error(func, path, exc_info):
                import stat
                os.chmod(path, stat.S_IWRITE)
                os.unlink(path)
            shutil.rmtree(work_dir, onerror=on_rm_error)