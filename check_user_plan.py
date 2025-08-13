import os
import json
import traceback
from datetime import datetime, timedelta, timezone
import gspread
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

SPREADSHEET_ID = os.getenv("SPREADSHEET_ID")
SHEET_NAME = os.getenv("SHEET_NAME", "ユーザー管理")
SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

def _build_credentials():
    env_json = os.getenv("GOOGLE_CREDENTIALS_JSON")
    if env_json:
        info = json.loads(env_json)
        return Credentials.from_service_account_info(info, scopes=SCOPES)
    return Credentials.from_service_account_file("credentials.json", scopes=SCOPES)

def _get_sheet():
    creds = _build_credentials()
    client = gspread.authorize(creds)
    return client.open_by_key(SPREADSHEET_ID).worksheet(SHEET_NAME)

def _header_map(sheet):
    headers = sheet.row_values(1)
    return {h: i+1 for i, h in enumerate(headers)}

def check_user_plan(user_id: str):
    """
    返却例:
      {"status":"ok", "plan":"standard", "used": 1, "limit": 3}
      {"status":"today_limit", "plan":"trial", "used": 1, "limit": 1}
      {"status":"limit", "plan":"trial"}   # 期限切れ など
    """
    sheet = _get_sheet()
    idx = _header_map(sheet)
    rows = sheet.get_all_records()
    today = datetime.now().date()

    # デフォルト制限
    max_counts = {"free": 1, "trial": 1, "standard": 3}

    for i, row in enumerate(rows, start=2):
        if str(row.get("user_id", "")) != str(user_id):
            continue

        plan = (row.get("plan") or "free").strip()
        daily_count = int(row.get("daily_count") or 0)
        last_used_date_str = (row.get("last_used_date") or "").strip()
        registered_date_str = (row.get("registered_date") or "").strip()
        expire_date_str = (row.get("expire_date") or "").strip()

        # 期限チェック（trial/standard どちらでも expire があれば見る）
        if expire_date_str:
            expire = datetime.strptime(expire_date_str, "%Y-%m-%d").date()
            if today > expire:
                return {"status": "limit", "plan": plan}

        # 日付が変わっていれば daily_count をリセット
        if last_used_date_str:
            last_used_date = datetime.strptime(last_used_date_str, "%Y-%m-%d").date()
        else:
            last_used_date = None

        if last_used_date != today:
            daily_count = 0
            if "daily_count" in idx:
                sheet.update_cell(i, idx["daily_count"], 0)
            if "last_used_date" in idx:
                sheet.update_cell(i, idx["last_used_date"], today.strftime("%Y-%m-%d"))

        limit = max_counts.get(plan, 1)
        if daily_count >= limit:
            return {"status": "today_limit", "plan": plan, "used": daily_count, "limit": limit}

        # ここで 1 回分インクリメント
        used = daily_count + 1
        if "daily_count" in idx:
            sheet.update_cell(i, idx["daily_count"], used)
        if "last_used_date" in idx:
            sheet.update_cell(i, idx["last_used_date"], today.strftime("%Y-%m-%d"))

        return {"status": "ok", "plan": plan, "used": used, "limit": limit}

    # 未登録ユーザーは trial でも free でも方針次第。ここでは「free未登録」とみなす
    return {"status": "limit", "plan": "free"}



