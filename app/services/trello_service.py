import requests
from app.config import Config

def move_card(card_id, list_id):
    url = f"https://api.trello.com/1/cards/{card_id}"
    query = {
        'idList': list_id,
        'key': Config.TRELLO_API_KEY,
        'token': Config.TRELLO_TOKEN
    }
    requests.put(url, params=query)

def add_comment(card_id, text):
    url = f"https://api.trello.com/1/cards/{card_id}/actions/comments"
    query = {
        'text': text,
        'key': Config.TRELLO_API_KEY,
        'token': Config.TRELLO_TOKEN
    }
    requests.post(url, params=query)

def get_card_details(card_id):
    url = f"https://api.trello.com/1/cards/{card_id}"
    query = {'key': Config.TRELLO_API_KEY, 'token': Config.TRELLO_TOKEN}
    resp = requests.get(url, params=query)
    return resp.json()