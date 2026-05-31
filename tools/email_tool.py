import hashlib
import logging
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formataddr
import os
from langgraph.prebuilt import ToolRuntime
import asyncio

import smtplib
from langchain_core.tools import tool
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type, retry_if_not_exception_type

from errors import *
from config import _trace_id_var
from middleware import idempotent

logger = logging.getLogger(__name__)
def generate_email_event_key(*args, **kwargs):
    """生成email_event_key"""
    subject = kwargs.get("subject")
    to = kwargs.get("to")
    cc = kwargs.get("cc", [])
    body = kwargs.get("body")
    runtime = kwargs.get("runtime")

    trace_id = runtime.config["configurable"].get("trace_id")
    user_id = runtime.config["configurable"].get("user_id", "default")

    to_sorted = sorted(to) if to else []
    cc_sorted = sorted(cc) if cc else []

    raw = f"""
    email_event:
    {user_id}:
    {to_sorted}:
    {cc_sorted}:
    {subject}:
    {body}
    """

    key = hashlib.md5(raw.encode()).hexdigest()
    logger.info(f"[email_event幂等Key] raw={raw[:50]}... hash={key}")

    return key
def build_email_msg(sender, to, cc, subject, body, attachments=None):
    """构建邮件，支持附件"""
    msg = MIMEMultipart()
    msg["From"] = formataddr(["Agent助手", sender])
    msg["To"] = ", ".join(to)
    msg["Subject"] = subject
    if cc:
        msg["Cc"] = ", ".join(cc)

    # 正文
    msg.attach(MIMEText(body, "plain", "utf-8"))

    # 附件（attachments是list of tuple: [(filename, file_bytes), ...]）
    if attachments:
        for filename, file_bytes in attachments:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(file_bytes)
            encoders.encode_base64(part)
            part.add_header(
                "Content-Disposition",
                f"attachment; filename={filename}"
            )
            msg.attach(part)

    return msg
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(min=1, max=5),
    retry=retry_if_exception_type(smtplib.SMTPException) &  # 只在SMTPException时重试
          retry_if_not_exception_type(smtplib.SMTPAuthenticationError),  # 认证失败不重试
    before_sleep=lambda retry_state: logger.warning(
        f"[邮件发送] 第{retry_state.attempt_number}次重试 trace_id={_trace_id_var.get()}"
    )
)
def _send_smtp(sender, password, all_recipients, msg):
    server = smtplib.SMTP_SSL("smtp.qq.com", 465)
    server.login(sender, password)
    server.sendmail(sender, all_recipients, msg.as_string())
    server.quit()
@tool
@idempotent(generate_email_event_key)
async def send_email(
    to: list[str],             # 收件人邮箱地址列表
    subject: str,              # 邮件主题
    body: str,                 # 邮件正文
    runtime: ToolRuntime,
    cc: list[str] | None = None,         # 抄送人邮箱地址列表（可选）
    attachments: list | None = None  # [(filename, file_bytes), ...]
) -> str:
    """通过邮件API发送邮件。需要正确格式的邮箱地址。"""
    # 占位实现：实际使用时，这里会调用 SendGrid、Gmail API 等
    # 1. 读取配置
    trace_id = runtime.config["configurable"].get("trace_id")
    sender = os.getenv("EMAIL_SENDER")  # 发件人QQ邮箱
    password = os.getenv("EMAIL_PASSWORD")  # QQ邮箱授权码
    if sender is None or password is None:
        raise FatalError(f"trace_id={trace_id} 缺少必要的环境变量：EMAIL_SENDER 或 EMAIL_PASSWORD")

    # 3. 合并所有收件人地址（收件人 + 抄送）
    all_recipients = to + (cc or [])
    # 构建邮件（含附件）
    msg = build_email_msg(sender, to, cc or [], subject, body, attachments or [])
    try:
        # 4. 连接QQ邮箱SMTP服务器（SSL加密，端口465）
        await asyncio.to_thread(_send_smtp, sender, password, all_recipients, msg)
        return f"trace_id={trace_id} 邮件已发送 - 主题：{subject}，收件人：{', '.join(to)}"

    except smtplib.SMTPAuthenticationError:
        raise FatalError(f"trace_id={trace_id} 邮件发送失败：QQ邮箱认证失败，请检查授权码是否正确")
    except smtplib.SMTPException as e:
        raise BusinessError(f"trace_id={trace_id} 邮件发送失败：{e}")

