import os
import json
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
import stripe
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

# ローカル開発時の環境変数読み込み
load_dotenv()

# Stripe秘密キーとWebhook署名キーを環境変数から取得
stripe.api_key = os.getenv("STRIPE_SECRET_KEY")
endpoint_secret = os.getenv("STRIPE_WEBHOOK_SECRET")

# Google Sheets 認証情報
SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SCOPES = ['https://www.googleapis.com/auth/spreadsheets', 'https://www.googleapis.com/auth/drive']
SERVICE_ACCOUNT_FILE = 'credentials.json'  # Render上では環境変数 or 永続ストレージで配置

# Flaskアプリ作成
app = Flask(__name__)

# Webhookエンドポイント
@app.route('/webhook', methods=['POST'])
def stripe_webhook():
    payload = request.data
    sig_header = request.headers.get('Stripe-Signature')

    try:
        event = stripe.Webhook.construct_event(payload, sig_header, endpoint_secret)
    except ValueError:
        return 'Invalid payload', 400
    except stripe.error.SignatureVerificationError:
        return 'Invalid signature', 400

    if event['type'] == 'checkout.session.completed':
        session = event['data']['object']
        user_id = session['metadata'].get('user_id')
        plan = session['metadata'].get('plan')  # "standard"など

        if user_id and plan:
            try:
                update_user_plan_sheet(user_id, plan)
                print(f"{user_id} を {plan} プランとして登録しました。")
            except Exception as e:
                print(f"スプレッドシート更新エラー: {e}")
                return 'Sheet update failed', 500

    return jsonify({'status': 'success'}), 200

# Google Sheets を更新する処理
def update_user_plan_sheet(user_id, plan):
    credentials = Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES
    )
    client = gspread.authorize(credentials)
    sheet = client.open_by_key(SPREADSHEET_ID).sheet1

    now = datetime.now()
    today_str = now.strftime('%Y/%m/%d')
    expire_str = (now + timedelta(days=30)).strftime('%Y/%m/%d')

    # シート内を検索して更新、存在しない場合は新規追加
    records = sheet.get_all_records()
    for i, row in enumerate(records, start=2):  # 1行目はヘッダー
        if row.get("user_id") == user_id:
            sheet.update(f"D{i}", plan)
            sheet.update(f"E{i}", today_str)
            sheet.update(f"F{i}", expire_str)
            return

    # 新規ユーザー
    sheet.append_row([user_id, 0, '', plan, today_str, expire_str])

if __name__ == '__main__':
    app.run(port=5000)
