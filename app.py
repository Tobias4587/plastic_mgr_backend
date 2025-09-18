from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os, re
from datetime import datetime

app = Flask(__name__)
CORS(app)

# --- Storage paths (Windows local testing) ---
BASE_DATA_DIR = r"C:\Users\rueedit\test\plastic_mgr\backend\data"
os.makedirs(BASE_DATA_DIR, exist_ok=True)
CARDS_FILE = os.path.join(BASE_DATA_DIR, "cards.json")

# --- Helpers: load/save ---
def load_cards():
    try:
        if os.path.exists(CARDS_FILE):
            with open(CARDS_FILE, "r", encoding="utf-8") as f:
                txt = f.read().strip()
                cards = json.loads(txt) if txt else []
                # ---- NEW: ensure defaults for existing data ----
                for c in cards:
                    if "unit" not in c or not c["unit"]:
                        c["unit"] = "kg"
                    if "currency" not in c or not c["currency"]:
                        c["currency"] = "CFA"
                    for it in c.get("items", []):
                        # quantity/amount may be missing; leave as-is (optional)
                        pass
                return cards
    except json.JSONDecodeError:
        return []
    return []

def save_cards(cards):
    with open(CARDS_FILE, "w", encoding="utf-8") as f:
        json.dump(cards, f, indent=2, ensure_ascii=False)

# --- ID generators ---
CARD_RE = re.compile(r"^C_(\d+)$", re.IGNORECASE)
ITEM_RE = re.compile(r"^Item_(\d+)$", re.IGNORECASE)

def next_card_id(cards):
    nums = []
    for c in cards:
        m = CARD_RE.match(c.get("card_id",""))
        if m: 
            try: nums.append(int(m.group(1)))
            except: pass
    n = (max(nums) + 1) if nums else 1
    # 3 digits until 999, then expand automatically
    width = 3 if n <= 999 else 4 if n <= 9999 else len(str(n))
    return f"C_{n:0{width}d}"

def next_item_id(card):
    items = card.get("items", [])
    nums = []
    for it in items:
        m = ITEM_RE.match(it.get("item_id",""))
        if m:
            try: nums.append(int(m.group(1)))
            except: pass
    # Start at 10 and increment by 10 (…010, …020, …030…)
    n = (max(nums) + 10) if nums else 10
    width = 3 if n <= 999 else 4 if n <= 9999 else len(str(n))
    return f"Item_{n:0{width}d}"

def find_card(cards, card_id):
    for c in cards:
        if c.get("card_id","").upper() == card_id.upper():
            return c
    return None

# --- Root ---
@app.route("/", methods=["GET"])
def root():
    return jsonify({"message": "Cards API running", "data_file": CARDS_FILE})

# --- Cards ---
@app.route("/cards", methods=["POST"])
def create_card():
    cards = load_cards()
    data = request.json or {}

    new_card = {
        "card_id": next_card_id(cards),
        "business_partner": data.get("business_partner",""),
        "description": data.get("description",""),
        "type": data.get("type",""),              # e.g., "sale" | "procurement" | "expense"
        "quantity": data.get("quantity", 0),
        "unit": data.get("unit", "kg"),
        "amount": data.get("amount", 0),
        "currency": data.get("currency", "CFA"),
        "date": data.get("date") or datetime.utcnow().strftime("%Y-%m-%d"),
        "items": []  # items stored under the card
    }
    cards.append(new_card)
    save_cards(cards)
    return jsonify({"status":"created","card":new_card}), 201

@app.route("/cards/<card_id>", methods=["PATCH"])
def update_card(card_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify({"error":"card not found"}), 404

    allowed = {"business_partner","description","type","quantity","unit","amount","currency","date"}
    updated = {}
    for k, v in (request.json or {}).items():
        if k in allowed:
            card[k] = v
            updated[k] = v
    save_cards(cards)
    return jsonify({"card_id": card["card_id"], "updated": updated}), 200

@app.route("/cards", methods=["GET"])
def list_cards():
    cards = load_cards()
    qp = request.args
    # Simple contains-filters
    for key in ["business_partner","description","type","date"]:
        if key in qp:
            val = qp.get(key,"").lower()
            cards = [c for c in cards if str(c.get(key,"")).lower().find(val) >= 0]
    return jsonify(cards), 200

# --- Items under a card ---
@app.route("/cards/<card_id>/items", methods=["POST"])
def add_item(card_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify({"error":"card not found"}), 404

    data = request.json or {}
    new_item = {
        "item_id": next_item_id(card),
        "card_id": card["card_id"],
        "description": data.get("description",""),
        "quantity": data.get("quantity"),
        "amount": data.get("amount"),
        "date": data.get("date") or card.get("date") or datetime.utcnow().strftime("%Y-%m-%d")
    }
    card.setdefault("items", []).append(new_item)
    save_cards(cards)
    return jsonify({"status":"created","item":new_item}), 201

@app.route("/cards/<card_id>/items", methods=["GET"])
def list_items(card_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify({"error":"card not found"}), 404
    return jsonify(card.get("items", [])), 200

@app.route("/cards/<card_id>/items/<item_id>", methods=["PATCH"])
def update_item(card_id, item_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify({"error":"card not found"}), 404
    items = card.get("items", [])
    item = next((i for i in items if i.get("item_id","").upper() == item_id.upper()), None)
    if not item:
        return jsonify({"error":"item not found"}), 404

    allowed = {"description","quantity","amount","date"}
    updated = {}
    for k, v in (request.json or {}).items():
        if k in allowed:
            item[k] = v
            updated[k] = v
    save_cards(cards)
    return jsonify({"card_id": card["card_id"], "item_id": item["item_id"], "updated": updated}), 200

# --- OpenAPI placeholder (optional) ---
@app.route("/openapi.json", methods=["GET"])
def openapi():
    spec = {
        "openapi": "3.0.0",
        "info": {"title": "Cards API", "version": "1.0.0"},
        "paths": {
            "/cards": {"get": {}, "post": {}},
            "/cards/{card_id}": {"patch": {}},
            "/cards/{card_id}/items": {"get": {}, "post": {}},
            "/cards/{card_id}/items/{item_id}": {"patch": {}},
        },
    }
    return jsonify(spec), 200

if __name__ == "__main__":
    # Local dev: http://127.0.0.1:5000
    app.run(host="0.0.0.0", port=5000)
