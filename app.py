from flask import Flask, request, jsonify
from flask_cors import CORS
import json, os, re
from datetime import datetime
from werkzeug.utils import secure_filename
from flask import Flask, request, jsonify, url_for, send_from_directory
import uuid
app = Flask(__name__)
CORS(app)

#python version 3.11.9


# --- app + dirs ---
app = Flask(__name__)
CORS(app)

BASE_DATA_DIR = r"C:\PythonProjects\Plastic_mgr\Backend\data"  #--> use on private PC
# --- app + dirs ---
# BASE_DATA_DIR = r"C:\Users\rueedit\test\plastic_mgr\backend\data"   # <-- align with your real folders

ATTACH_DIR  = os.path.join(BASE_DATA_DIR, "attachments")
STAGING_DIR = os.path.join(BASE_DATA_DIR, "uploads")                # you already use "uploads" for staging
CARDS_FILE  = os.path.join(BASE_DATA_DIR, "cards.json")

for p in (BASE_DATA_DIR, ATTACH_DIR, STAGING_DIR):
    os.makedirs(p, exist_ok=True)

app.config.update(PREFERRED_URL_SCHEME="http")
# app.config.update(SERVER_NAME="127.0.0.1:5000")  # only if you run behind proxies or need stable ext URLs

#normalize legacy records that only have path
def _abs_url(card_id, meta):
    if meta.get("url", "").startswith(("http://","https://")):
        return meta["url"]
    rest = meta.get("path","").split(f"/files/{card_id}/", 1)[-1]
    try:
        return url_for("download_file", card_id=card_id, filename=rest, _external=True)
    except Exception:
        return request.url_root.rstrip("/") + f"/files/{card_id}/{rest}"


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



def ensure_card_dirs(card_id, item_id=None):
    base = os.path.join(ATTACH_DIR, card_id)
    os.makedirs(base, exist_ok=True)
    if item_id:
        base = os.path.join(base, item_id)
        os.makedirs(base, exist_ok=True)
    return base

def staged_path_from_token(token: str):
    # staged file names look like: <token>__<original_name>
    for name in os.listdir(STAGING_DIR):
        if name.startswith(f"{token}__"):
            return os.path.join(STAGING_DIR, name), name.split("__", 1)[1]
    return None, None

# --- commit staged file to a card/item ---
@app.route("/attachments/commit", methods=["POST"])
def commit_attachment():
    data = request.json or {}
    token   = data.get("token")
    card_id = data.get("card_id")
    item_id = data.get("item_id") or None
    if not token or not card_id:
        return jsonify({"error":"token and card_id required"}), 400

    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify({"error":"card not found"}), 404
    if item_id:
        it = next((i for i in card.get("items", []) if i["item_id"].upper()==item_id.upper()), None)
        if not it:
            return jsonify({"error":"item not found"}), 404

    staged_path, original_name = staged_path_from_token(token)
    if not staged_path or not os.path.exists(staged_path):
        return jsonify({"error":"staged file not found"}), 404

    target_dir = ensure_card_dirs(card["card_id"], item_id)
    final_name = secure_filename(original_name or "upload.bin")
    final_path = os.path.join(target_dir, final_name)
    os.replace(staged_path, final_path)

    rest = f"{item_id}/{final_name}" if item_id else final_name
    meta = {
        "filename": final_name,
        "mime": data.get("mime") or "",
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "path": f"/files/{card['card_id']}/{rest}",
    }
    meta["url"] = _abs_url(card["card_id"], meta)


    if item_id:
        it.setdefault("attachments", []).append(meta)
    else:
        card.setdefault("attachments", []).append(meta)

    save_cards(cards)
    return jsonify({"status":"committed","meta":meta}), 200





@app.route("/uploads", methods=["POST"])
def stage_upload():
    try:
        if "file" not in request.files:
            return jsonify({"error": "missing file"}), 400
        f = request.files["file"]
        if not f or not f.filename:
            return jsonify({"error": "empty filename"}), 400

        token = uuid.uuid4().hex
        fname = secure_filename(f.filename or "upload.bin")
        staged_name = f"{token}__{fname}"
        dst = os.path.join(STAGING_DIR, staged_name)

        os.makedirs(STAGING_DIR, exist_ok=True)
        f.save(dst)

        size = os.path.getsize(dst)
        meta = {
            "token": token,
            "filename": fname,
            "mime": f.mimetype or "",
            "size": size,
            "uploaded_at": datetime.utcnow().isoformat() + "Z",
        }
        return jsonify({"status": "staged", "meta": meta}), 201

    except Exception as e:
        app.logger.exception("stage_upload failed")
        return jsonify({"error": "internal", "detail": str(e)}), 500





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



@app.route("/files/<card_id>/<path:filename>", methods=["GET"])
def download_file(card_id, filename):
    return send_from_directory(os.path.join(ATTACH_DIR, card_id), filename, as_attachment=False)


@app.route("/cards/<card_id>/attachments", methods=["POST"])
def upload_card_attachment(card_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify({"error": "card not found"}), 404

    if "file" not in request.files:
        return jsonify({"error": "missing file"}), 400

    f = request.files["file"]
    if not f or not f.filename:
        return jsonify({"error": "empty filename"}), 400

    item_id = request.form.get("item_id") or None
    if item_id:
        it = next((i for i in card.get("items", []) if i.get("item_id","").upper() == item_id.upper()), None)
        if not it:
            return jsonify({"error":"item not found"}), 404

    # filesystem destination
    dest_dir = ensure_card_dirs(card["card_id"], item_id)
    fname = secure_filename(f.filename or "upload.bin")
    final_path = os.path.join(dest_dir, fname)
    os.makedirs(dest_dir, exist_ok=True)
    f.save(final_path)

    # build metadata (path + absolute url)
    rest = f"{item_id}/{fname}" if item_id else fname
    meta = {
        "filename": fname,
        "mime": getattr(f, "mimetype", "") or "",
        "uploaded_at": datetime.utcnow().isoformat() + "Z",
        "path": f"/files/{card['card_id']}/{rest}",
    }
 
 

    # persist on card or item
    meta["url"] = _abs_url(card["card_id"], meta) 
    if item_id:
        it.setdefault("attachments", []).append(meta)
    else:
        card.setdefault("attachments", []).append(meta)

    save_cards(cards)
    return jsonify({"status":"uploaded","meta":meta}), 201

@app.route("/cards/<card_id>/attachments", methods=["GET"])
def list_card_attachments(card_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify([]), 200  # keep UI simple

    out = []
    for a in card.get("attachments", []) or []:
        meta = dict(a)
        meta["url"] = _abs_url(card["card_id"], meta)   # normalize ALWAYS
        out.append(meta)
    return jsonify(out), 200

@app.route("/cards/<card_id>/items/<item_id>/attachments", methods=["GET"])
def list_item_attachments(card_id, item_id):
    cards = load_cards()
    card = find_card(cards, card_id)
    if not card:
        return jsonify([]), 200
    it = next((i for i in card.get("items", []) if i.get("item_id","").upper() == item_id.upper()), None)
    if not it:
        return jsonify([]), 200

    out = []
    for a in it.get("attachments", []) or []:
        meta = dict(a)
        meta["url"] = _abs_url(card["card_id"], meta)
        out.append(meta)
    return jsonify(out), 200


if __name__ == "__main__":
    # Local dev: http://127.0.0.1:5000
    app.run(host="0.0.0.0", port=5000)
