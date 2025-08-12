import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import stripe
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

# Stripe
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Google Sheets
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "ユーザー管理")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _build_credentials():
    """GOOGLE_CREDENTIALS_JSON（1行JSON）> credentials.json の順で読み込む"""
    env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if env_json:
        info = json.loads(env_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    # フォールバック（ローカル等）
    return Credentials.from_service_account_file("credentials.json", scopes=SCOPES)

def _get_sheet():
    creds = _build_credentials()
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

def _header_map(sheet):
    headers = sheet.row_values(1)
    idx = {h: i+1 for i, h in enumerate(headers)}
    # 想定ヘッダー：user_id, plan, daily_count, last_used_date, registered_date, expire_date
    return idx

def update_user_plan_sheet(user_id: str, plan: str):
    sheet = _get_sheet()
    idx = _header_map(sheet)
    rows = sheet.get_all_records()
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    # 期限は standard:30日, trial:7日 と仮定
    period = 30 if plan == "standard" else 7
    expire = (now + timedelta(days=period)).strftime("%Y-%m-%d")

    # 既存行の探索
    for i, row in enumerate(rows, start=2):
        if str(row.get("user_id", "")) == str(user_id):
            # plan / registered_date / expire_date を更新
            if "plan" in idx:
                sheet.update_cell(i, idx["plan"], plan)
            if "registered_date" in idx:
                sheet.update_cell(i, idx["registered_date"], today)
            if "expire_date" in idx:
                sheet.update_cell(i, idx["expire_date"], expire)
            # daily_count はリセット
            if "daily_count" in idx:
                sheet.update_cell(i, idx["daily_count"], 0)
            if "last_used_date" in idx:
                sheet.update_cell(i, idx["last_used_date"], today)
            return

    # 無ければ新規追加（ヘッダー順と同じ並びにするのが安全）
    values = {
        "user_id": user_id,
        "plan": plan,
        "daily_count": 0,
        "last_used_date": today,
        "registered_date": today,
        "expire_date": expire,
    }
    headers = sheet.row_values(1)
    row_out = [values.get(h, "") for h in headers]
    sheet.append_row(row_out, value_input_option="USER_ENTERED")

app = Flask(__name__)

@app.route("/webhook", methods=["POST"])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get("Stripe-Signature", "")

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return "Invalid payload", 400
    except stripe.error.SignatureVerificationError:
        return "Invalid signature", 400

    if event["type"] == "checkout.session.completed":
        session = event["data"]["object"]
        meta = session.get("metadata") or {}
        user_id = meta.get("user_id")
        plan = meta.get("plan")  # "standard" or "trial"
        if user_id and plan:
            try:
                update_user_plan_sheet(user_id, plan)
            except Exception as e:
                print(f"[SHEET UPDATE ERROR] {e}")
                return "Sheet update failed", 500

    return jsonify({"status": "ok"}), 200

# Render の Free 環境でもローカルでも動くように
if __name__ == "__main__":
    # ローカル実行用（Render では Start Command に gunicorn を使う）
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
