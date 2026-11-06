import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
import logging

logger = logging.getLogger("notification_service")


class NotificationService:
    @staticmethod
    def send_f1_excess_alert(
        wo: any,
        stage: str,
        planned_qty: int,
        produced_qty: int,
        excess_qty: int,
        heat_number: str = None,
        operator_name: str = None,
        reason: str = None
    ) -> bool:
        """Sends an in-system and email alert when F1 records excess production."""
        wo_number = getattr(wo, "wo_number", "Unknown WO")
        order = getattr(wo, "order", None)
        part = getattr(order, "part", None) if order else None
        part_name = getattr(part, "name", "N/A") if part else "N/A"
        part_number = getattr(part, "part_number", "N/A") if part else "N/A"
        customer = getattr(order, "customer", None) if order else None
        customer_name = getattr(customer, "name", "N/A") if customer else "N/A"
        
        subject = f"[VSPL SMES Alert] F1 Excess Production Logged — {wo_number} (+{excess_qty} pcs)"
        
        body_text = f"""
VSPL Smart Manufacturing Execution System (SMES) — Production Alert
===================================================================

An excess casting / production entry was recorded at stage {stage}:

• Work Order:       {wo_number}
• Customer:         {customer_name}
• Part Name/Number: {part_name} ({part_number})
• Heat Number:      {heat_number or 'Not Assigned'}
• Operator / Cell:  {operator_name or 'Floor Operator'}
• Original Target:  {planned_qty} pcs
• Actual Cast/Made: {produced_qty} pcs
• Excess Quantity:  +{excess_qty} pcs
• Reason / Notes:   {reason or 'Foundry excess mould poured'}
• Timestamp:        {datetime.now().strftime('%d %b %Y, %H:%M:%S IST')}

The Work Order route and downstream stages have been automatically adjusted
to track all {produced_qty} pieces through subsequent manufacturing stages.

-------------------------------------------------------------------
Automated alert from VSPL SMES Engine v3.3 (https://oms.vijayspheroidals.in)
"""

        # SMTP configuration
        smtp_host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
        smtp_port = int(os.environ.get("SMTP_PORT", "587"))
        smtp_user = os.environ.get("SMTP_USER", "data.analyst@vijayspheroidals.in")
        smtp_pass = os.environ.get("SMTP_PASSWORD", os.environ.get("GMAIL_APP_PASSWORD", ""))
        
        # Recipient list: defaults to data.analyst@vijayspheroidals.in plus ALERT_EMAIL_RECIPIENTS
        recipients = [smtp_user]
        extra_recipients = os.environ.get("ALERT_EMAIL_RECIPIENTS", "")
        if extra_recipients:
            for r in extra_recipients.split(","):
                clean = r.strip()
                if clean and clean not in recipients:
                    recipients.append(clean)

        logger.info(f"F1 EXCESS ALERT: WO {wo_number}, Excess: +{excess_qty} pcs. Notifying: {recipients}")
        print(f"[F1_EXCESS_ALERT] {subject}\n{body_text}")

        if not smtp_pass:
            logger.warning("SMTP_PASSWORD not set; email alert logged to console and audit trail.")
            return True

        try:
            msg = MIMEMultipart()
            msg["From"] = smtp_user
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = subject
            msg.attach(MIMEText(body_text, "plain"))

            with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
                server.starttls()
                server.login(smtp_user, smtp_pass)
                server.send_message(msg)
            logger.info("Email alert delivered successfully.")
            return True
        except Exception as e:
            logger.error(f"Failed to deliver SMTP email alert: {e}")
            return False
