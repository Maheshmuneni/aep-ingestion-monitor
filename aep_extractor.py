import os
import time
from datetime import datetime, timezone
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import requests
from tabulate import tabulate

# ==========================================
# 1. AEP AUTHENTICATION & SANDBOX CONFIG
# ==========================================
IMS_HOST = "https://ims-na1.adobelogin.com"
CLIENT_ID = "03d80028f77f4d37a36457708cf28271"
CLIENT_SECRET = os.getenv("AEP_CLIENT_SECRET", "p8e-7hK9-XATrOVMwrn5jET9cnW5EpqHEbaQ")
IMS_ORG = "0E851E5A66D23F230A495CC6@AdobeOrg"
SANDBOX_NAME = "pldt-prod"
SCOPE = "openid,AdobeID,read_organizations,additional_info.projectedProductContext,session"

DATASETS = [
    {
        "name": "csp_provisioning_status_bkp",
        "id": "6abdcc440c46e9d30b178754"
    },
    {
        "name": "jai Scores -sto _10118.0",
        "id": "6aaae95df34dc5a150a26190"
    }
]

# ==========================================
# 2. EMAIL CONFIGURATION
# ==========================================
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587
SENDER_EMAIL = "maheshmuneni@gmail.com"
SENDER_PASSWORD = os.getenv("GMAIL_APP_PASSWORD", "mijk hvtg sjcq ovjh")
RECIPIENT_EMAILS = ["maheshmuneni@gmail.com"]

SEND_ONLY_ON_ALERT = False


# ==========================================
# 3. IMS TOKEN GENERATION
# ==========================================
def get_valid_token():
    url = f"{IMS_HOST}/ims/token/v3"
    headers = {"Content-Type": "application/x-www-form-urlencoded"}
    payload = {
        "grant_type": "client_credentials",
        "client_id": CLIENT_ID,
        "client_secret": CLIENT_SECRET,
        "scope": SCOPE
    }

    resp = requests.post(url, headers=headers, data=payload, timeout=30)
    resp.raise_for_status()
    return resp.json()["access_token"]


# ==========================================
# 4. FETCH BATCH INGESTION DETAILS
# ==========================================
def fetch_batch_info(dataset_id, dataset_name):
    token = get_valid_token()
    url = "https://platform.adobe.io/data/foundation/catalog/batches"

    headers = {
        "Authorization": f"Bearer {token}",
        "x-api-key": CLIENT_ID,
        "x-gw-ims-org-id": IMS_ORG,
        "x-sandbox-name": SANDBOX_NAME,
        "Content-Type": "application/json"
    }

    params = {
        "dataSet": dataset_id,
        "orderBy": "desc:created",
        "limit": 1
    }

    try:
        response = requests.get(url, headers=headers, params=params, timeout=30)
        response.raise_for_status()
        data = response.json()

        if not data:
            return {
                "name": dataset_name,
                "status": "NO_BATCHES",
                "records": 0,
                "created_time": "N/A",
                "duration": "N/A",
                "action": "Check Pipeline"
            }

        batch_id = list(data.keys())[0]
        batch = data[batch_id]

        status = batch.get("status", "Unknown").upper()
        metrics = batch.get("metrics", {})

        created_epoch = batch.get("created", 0) / 1000
        completed_epoch = batch.get("completed", 0) / 1000
        created_str = (
            datetime.fromtimestamp(created_epoch, tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
            if created_epoch else "N/A"
        )

        duration = "N/A"
        if created_epoch and completed_epoch and completed_epoch >= created_epoch:
            duration = f"{int(completed_epoch - created_epoch)}s"

        records = (
            metrics.get("outputRecordCount")
            if metrics.get("outputRecordCount") is not None
            else metrics.get("inputRecordCount")
            if metrics.get("inputRecordCount") is not None
            else metrics.get("recordsWritten")
            if metrics.get("recordsWritten") is not None
            else metrics.get("recordsRead", 0)
        )

        action = "Healthy"
        if status == "FAILED":
            action = "Raise Ticket to Adobe"
        elif records == 0 and status not in ["LOADING", "STAGING"]:
            action = "Mail Data Tech Team"
        elif status in ["LOADING", "STAGING"]:
            action = "Ingestion In Progress"

        return {
            "name": dataset_name,
            "status": status,
            "records": records,
            "created_time": created_str,
            "duration": duration,
            "action": action
        }

    except Exception as e:
        return {
            "name": dataset_name,
            "status": "ERROR",
            "records": 0,
            "created_time": "N/A",
            "duration": "N/A",
            "action": f"Error: {str(e)[:30]}"
        }


# ==========================================
# 5. HTML EMAIL DISPATCH
# ==========================================
def send_email_report(results, timestamp_str):
    msg = MIMEMultipart("alternative")

    has_alert = any(r["action"] in ["Raise Ticket to Adobe", "Mail Data Tech Team"] for r in results)
    subject_tag = "[ALERT]" if has_alert else "[STATUS]"
    msg["Subject"] = f"{subject_tag} AEP Ingestion Monitor - Sandbox: {SANDBOX_NAME} ({timestamp_str})"
    msg["From"] = SENDER_EMAIL
    msg["To"] = ", ".join(RECIPIENT_EMAILS)

    rows = []
    for r in results:
        status_color = "#28a745" if r["status"] == "SUCCESS" else "#ffc107" if r["status"] in ["STAGING", "LOADING"] else "#dc3545"
        action_color = "#28a745" if r["action"] == "Healthy" else "#fd7e14" if r["action"] == "Ingestion In Progress" else "#dc3545"

        row = (
            '<tr style="border-bottom: 1px solid #ddd; text-align: left;">'
            f'<td style="padding: 10px 12px; font-weight: 500;">{r["name"]}</td>'
            f'<td style="padding: 10px 12px;"><span style="background-color: {status_color}; color: white; padding: 3px 8px; border-radius: 4px; font-size: 12px;">{r["status"]}</span></td>'
            f'<td style="padding: 10px 12px; text-align: right;">{r["records"]:,}</td>'
            f'<td style="padding: 10px 12px;">{r["created_time"]}</td>'
            f'<td style="padding: 10px 12px; text-align: center;">{r["duration"]}</td>'
            f'<td style="padding: 10px 12px; font-weight: 600; color: {action_color};">{r["action"]}</td>'
            '</tr>'
        )
        rows.append(row)

    rows_html = "".join(rows)

    html_content = (
        '<html>'
        '<body style="font-family: Arial, sans-serif; color: #333; line-height: 1.5; padding: 20px;">'
        '<h2 style="color: #004d99; margin-bottom: 5px;">Adobe Experience Platform - Ingestion Health Report</h2>'
        f'<p style="margin-top: 0; color: #666; font-size: 14px;"><strong>Sandbox:</strong> {SANDBOX_NAME} | <strong>Execution Time:</strong> {timestamp_str}</p>'
        '<table style="width: 100%; border-collapse: collapse; margin-top: 15px; font-size: 13px;">'
        '<thead>'
        '<tr style="background-color: #f2f4f7; border-bottom: 2px solid #ccc; text-align: left;">'
        '<th style="padding: 10px 12px;">Dataset Name</th>'
        '<th style="padding: 10px 12px;">Status</th>'
        '<th style="padding: 10px 12px; text-align: right;">Records Ingested</th>'
        '<th style="padding: 10px 12px;">Created Time (UTC)</th>'
        '<th style="padding: 10px 12px;">Duration</th>'
        '<th style="padding: 10px 12px;">Action / Alert</th>'
        '</tr>'
        '</thead>'
        f'<tbody>{rows_html}</tbody>'
        '</table>'
        '<p style="margin-top: 25px; font-size: 12px; color: #999;">Automated notification generated by GitHub Actions AEP Monitor.</p>'
        '</body>'
        '</html>'
    )

    msg.attach(MIMEText(html_content, "html"))

    try:
        with smtplib.SMTP(SMTP_SERVER, SMTP_PORT) as server:
            server.starttls()
            server.login(SENDER_EMAIL, SENDER_PASSWORD)
            server.sendmail(SENDER_EMAIL, RECIPIENT_EMAILS, msg.as_string())
        print(f" -> Email notification successfully dispatched to {RECIPIENT_EMAILS}")
    except Exception as e:
        print(f" -> Failed to send email alert: {e}")


# ==========================================
# 6. MAIN EXECUTION
# ==========================================
def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n[AEP INGESTION MONITOR] Check at: {now_str} (Sandbox: {SANDBOX_NAME})")

    results = []
    table_rows = []
    for ds in DATASETS:
        res = fetch_batch_info(ds["id"], ds["name"])
        results.append(res)
        table_rows.append([
            res["name"],
            res["status"],
            f"{res['records']:,}",
            res["created_time"],
            res["duration"],
            res["action"]
        ])

    headers = ["Dataset Name", "Status", "Records Ingested", "Created Time (UTC)", "Duration", "Action / Alert"]
    print(tabulate(table_rows, headers=headers, tablefmt="grid"))

    has_alert = any(r["action"] in ["Raise Ticket to Adobe", "Mail Data Tech Team"] for r in results)
    if not SEND_ONLY_ON_ALERT or has_alert:
        send_email_report(results, now_str)


if __name__ == "__main__":
    main()
