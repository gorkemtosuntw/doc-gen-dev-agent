from fastapi import FastAPI, Request, BackgroundTasks
from app.config import Config
from app.services import trello_service
from app.core.orchestrator import run_agent_pipeline

app = FastAPI()

@app.post("/webhook")
async def trello_webhook(request: Request, background_tasks: BackgroundTasks):
    try:
        data = await request.json()
        action = data.get('action', {})
        
        if action.get('type') == 'addMemberToCard':
            member = action.get('member', {}).get('username')
            if member == Config.BOT_USERNAME:
                card = action.get('data', {}).get('card', {})
                full_card = trello_service.get_card_details(card.get('id'))
                
                background_tasks.add_task(
                    run_agent_pipeline, 
                    full_card['id'], 
                    full_card['name'], 
                    full_card.get('desc', '')
                )
        return {"status": "ok"}
    except Exception as e:
        print(f"Error: {e}")
        return {"status": "error"}

@app.head("/webhook")
async def trello_webhook_check():
    return {"status": "ok"}