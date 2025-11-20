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

TRELLO_API_KEY = os.getenv("TRELLO_API_KEY")
TRELLO_TOKEN = os.getenv("TRELLO_TOKEN")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
GITHUB_REPO_NAME = "gorkemtosuntw/doc-gen-mvp" # Örn: "ahmet/proje-x"
REPO_URL = f"https://{GITHUB_TOKEN}@github.com/{GITHUB_REPO_NAME}.git"

LIST_IN_PROGRESS = "691d9d7f9faff31f3cc13819" 
LIST_REVIEW = "691d9d7f9faff31f3cc1381a"
BOT_USERNAME = "gorkemt1" # Trello'daki bot kullanıcı adı
app = FastAPI()
client = OpenAI(api_key=OPENAI_API_KEY)

def list_files_in_repo(root_dir):
    """
    Repodaki dosyaların listesini verir (Gereksizleri filtreler).
    Cost Efficiency için çok önemlidir.
    """
    file_list = []
    ignore_dirs = {".git", "__pycache__", "venv", "env", "node_modules", ".idea", ".vscode", "pnpm-lock.yaml", "yarn.lock", "package-lock.json"}
    
    for root, dirs, files in os.walk(root_dir):
        # Ignore edilecek klasörleri çıkart
        dirs[:] = [d for d in dirs if d not in ignore_dirs]
        
        for file in files:
            # Sadece kod dosyalarını al (Resimleri vs alma)
            if file.endswith((".py", ".js", ".ts", ".html", ".css", ".md", ".txt", ".json")):
                full_path = os.path.join(root, file)
                # Root path'i silip relative path gösterelim (Token tasarrufu)
                rel_path = os.path.relpath(full_path, root_dir)
                file_list.append(rel_path)
    
    return "\n".join(file_list)

def read_file_content(root_dir, file_path):
    """Seçilen dosyanın içeriğini okur."""
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
        # --- GÜÇLENDİRİLMİŞ EŞLEŞTİRME ---
        # 1. Direkt eşleşme dene
        if search_block in new_content:
            new_content = new_content.replace(search_block, replace_block, 1)
            success_count += 1
            continue
            
        # 2. Eğer bulamazsan, satır sonlarındaki boşlukları temizleyerek dene (strip)
        # Bu işlem risklidir, çok dikkatli yapılmalı ama genelde işe yarar.
        search_block_stripped = search_block.strip()
        if search_block_stripped in new_content:
             new_content = new_content.replace(search_block_stripped, replace_block, 1)
             success_count += 1
             continue
             
        # 3. Hala bulamıyorsan, satır satır boşluk temizleyerek ara (Advanced Normalization)
        # (Burada kod karmaşıklaşır, şimdilik ilk 2 adım %90 sorunu çözer)
        
        print(f"⚠️ UYARI: Search bloğu tam eşleşmedi:\n---\n{search_block}\n---")

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
    print(f"🕵️ Smart Agent Analize Başlıyor: {task_title}")
    files_tree = list_files_in_repo(root_dir)
    
    system_prompt = f"""
    Sen uzman bir Full-Stack geliştiricisisin. Mevcut bir kod tabanı üzerinde çalışıyorsun.
    
    GÖREVİN:
    Verilen Task'ı ({task_title}) yerine getirmek için gerekli dosyalarda 'Cerrahi Müdahale' yap.

    MEVCUT DOSYALAR:
    {files_tree}

    KURALLAR (ÇOK ÖNEMLİ):
    1. ASLA tüm dosyayı baştan sona tekrar yazma. Bu yasaktır.
    2. Sadece değiştirmek istediğin kısımları 'SEARCH/REPLACE' blokları halinde ver.
    3. Dosya okumak için 'read_file' aracını kullan.
    4. Hangi dosyanın görevle ilgili olduğunu bul.
    5. Kodu analiz et ve düzeltilmiş tam halini yaz.
    6. KOD STİLİ: Dosyanın mevcut indentation yapısına (Tab mı Space mi?) sadık kal. 
    Eğer dosya 4 space kullanıyorsa sen de 4 space kullan.
    7. (ÇOK ÖNEMLİ) SESSİZLİK MODU:
       - Asla "Şöyle yapacağım", "İşte kodunuz", "Bu değişikliği yaptım" gibi açıklamalar yapma.
       - Çıktın doğrudan ve sadece 'FILE: ...' satırı ile başlamalı.
       - Başka hiçbir kelime etme.

    FORMAT:
    Değişiklik yapmak için şu formatı kullanmalısın (kod blokları içinde değil, düz metin olarak):

    FORMAT ÖRNEĞİ:
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
    
    Eğer birden fazla dosyada değişiklik yapacaksan, her biri için FILE: satırını tekrar yaz.

    İPUÇLARI:
    - 'SEARCH' bloğundaki kod, hedef dosyadakiyle KARAKTERİ KARAKTERİNE aynı olmalı (indentation dahil). Yoksa eşleşme başarısız olur.
    - Benzersizliği sağlamak için değiştireceğin satırın bir üstündeki ve altındaki satırları da SEARCH bloğuna dahil et.
    """

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Task Detayı: {task_desc}. Lütfen gerekiyorsa dosyaları oku ve düzelt."}
    ]

    tools = [
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Bir dosyanın içeriğini okur.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "file_path": {"type": "string", "description": "Okunacak dosyanın relative yolu (örn: src/main.py)"},
                    },
                    "required": ["file_path"],
                },
            }
        }
    ]

    for i in range(3): 
        print(f"🔄 Tur {i+1}/3 çalışıyor...")
        
        response = client.chat.completions.create(
            model="gpt-4o",
            messages=messages,
            tools=tools,
            tool_choice="auto" 
        )
        
        msg = response.choices[0].message
        messages.append(msg) # Geçmişe ekle (Memory)

        # Eğer Agent bir Tool çağırmak istiyorsa (Örn: Dosya okumak)
        if msg.tool_calls:
            for tool_call in msg.tool_calls:
                fn_name = tool_call.function.name
                fn_args = json.loads(tool_call.function.arguments)
                
                if fn_name == "read_file":
                    print(f"📖 Agent dosya okuyor: {fn_args['file_path']}")
                    content = read_file_content(root_dir, fn_args['file_path'])
                    
                    # Tool sonucunu AI'ya geri besle
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "name": fn_name,
                        "content": content
                    })
        else:
            # Eğer Tool çağırmadıysa, demek ki cevabı (Kodu) buldu.
            # Cevap içinde kod bloğu var mı bakalım.
            content = msg.content
            print(content)
            if "FILE:" in content and "<<<<<<< SEARCH" in content:
                print("💡 Agent çözümü buldu!")
                return content # Kodu ve açıklamayı döndür
            else:
                # Kod yoksa, belki daha fazla bilgi istiyordur ama biz zorlayalım.
                print("⚠️ Agent kod üretmedi, döngü devam ediyor.")
    
    return "Agent bir çözüm üretemedi."

def run_agent_task(card_id, card_name, card_desc):
    print(f"🚀 Agent çalışmaya başladı: {card_name}")

    move_trello_card(card_id, LIST_IN_PROGRESS)
    # Çalıştığımız dizinin tam yolunu alıyoruz
    base_dir = os.getcwd() 
    workspace_root = os.path.join(base_dir, "workspace")
    
    # UUID ile unique bir klasör yolu oluştur
    folder_name = str(uuid.uuid4())
    work_dir = os.path.join(workspace_root, folder_name)

    # Workspace ana klasörü yoksa oluştur
    if not os.path.exists(workspace_root):
        os.makedirs(workspace_root)
    
    # Temizlik (Eğer uuid çakışırsa ki zor ihtimal)
    if os.path.exists(work_dir):
        shutil.rmtree(work_dir)
    
    try:
        # 3. Repoyu Clone'la
        print(f"📥 Repo çekiliyor: {work_dir}")
        repo = Repo.clone_from(REPO_URL, work_dir)

        branch_name = f"feature/ticket-{card_id[-5:]}" # Card ID'nin son 5 hanesi
        current = repo.create_head(branch_name)
        current.checkout()

        print(f"🤖 AI kodluyor: {card_name}")
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
            print(f"🎯 Hedef dosya tespit edildi: {target_file_path}")
            new_content, applied = apply_patches(original_content, generated_code)

            if applied:
                with open(target_file_path, "w", encoding="utf-8", newline="\n") as f:
                    f.write(new_content)
                print("✅ Yama başarıyla uygulandı!")
                repo.index.add([target_file_path])
                commit_msg = f"Fix: {card_name} (AI Search/Replace)"
            else:
                print("⚠️ Yama uygulanamadı (Search bloğu eşleşmedi).")
                commit_msg = "Docs: AI çözüm önerdi ama uygulanamadı."
                # Yine de AI cevabını log olarak kaydedelim
                with open(os.path.join(work_dir, "AI_PATCH_FAILED.md"), "w") as f:
                    f.write(generated_code)
                repo.index.add(["AI_PATCH_FAILED.md"])
        else:
            print("⚠️ Hedef dosya bulunamadı veya AI yeni dosya oluşturmak istedi.")
            # Eğer dosya bulamazsa, belki sıfırdan kod yazmıştır.
            # Eski mantıkla 'ai_generated.py' oluşturabiliriz.
            filename = "ai_generated_v2.ts"
            with open(os.path.join(work_dir, filename), "w") as f:
                f.write(generated_code) # Ham cevabı yaz
            repo.index.add([filename])
            commit_msg = f"Feat: {card_name} (New File)"

        repo.index.commit(commit_msg)
        origin = repo.remote(name='origin')
        origin.push(branch_name)
        print("📤 Kod pushlandı.")

        g = Github(GITHUB_TOKEN)
        gh_repo = g.get_repo(GITHUB_REPO_NAME)
        pr_body = f"🤖 **AI Agent PR**\n\n**Görev:** {card_name}\n**İstek:** {card_desc}\n\nAI bu kodu otomatik üretti."
        pr = gh_repo.create_pull(
            title=f"AI Feat: {card_name}",
            body=pr_body,
            head=branch_name,
            base="main"
        )

        add_comment_trello(card_id, f"✅ Geliştirme tamamlandı! PR Linki: {pr.html_url}")
        move_trello_card(card_id, LIST_REVIEW)
        print("🏁 Süreç başarıyla bitti.")

    except Exception as e:
        print(f"❌ HATA OLUŞTU: {e}")
        add_comment_trello(card_id, f"⚠️ Bir hata oluştu: {str(e)}")

    finally:
        # Windows temizlik kodu
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

                # Kartın detaylı açıklamasını almak için API çağrısı yapalım
                full_card = get_card_details(card_id)
                card_desc = full_card.get('desc', '')

                background_tasks.add_task(run_agent_task, card_id, card_name, card_desc)
                print(f"Request alındı, işlem sıraya kondu: {card_name}")

        return {"status": "ok"}        
    except Exception as e:
        print(f"Webhook Hatası: {e}")
        return {"status": "error"}

@app.head("/webhook")
async def trello_webhook_check():
    """Trello webhook'u ilk kurarken HEAD isteği atar, buna OK dönmek şarttır."""
    return {"status": "ok"}