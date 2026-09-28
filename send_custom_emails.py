#!/usr/bin/env python3
"""
Send custom personalized emails to verified emails
Uses Claude AI to write personal messages
"""

import os
import csv
import sys
import smtplib
import time
import logging
from pathlib import Path
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from typing import List, Dict
from datetime import datetime

try:
    import anthropic
except ImportError:
    print("Install anthropic: pip install anthropic")
    sys.exit(1)

try:
    from dotenv import load_dotenv
except ImportError:
    print("Install python-dotenv: pip install python-dotenv")
    sys.exit(1)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)
log = logging.getLogger("send_emails")

# Load env
load_dotenv()


# ════════════════════════════════════════════════════════════════════════════
#  EMAIL WRITER
# ════════════════════════════════════════════════════════════════════════════

class EmailWriter:
    """Write custom personalized emails using Claude"""

    def __init__(self):
        self.client = anthropic.Anthropic()
        self.model = "claude-sonnet-5"

    def write_email(self, recipient_email: str, company: str,
                   custom_context: str = "") -> Dict:
        """
        Write a custom email using Claude

        Args:
            recipient_email: Email address
            company: Company name
            custom_context: Any custom info about the person/company

        Returns:
            {"subject": "...", "body": "..."}
        """

        your_name = os.getenv("MY_NAME", "Anshu")
        target_role = os.getenv("MY_TARGET_ROLE", "AI Engineer")
        linkedin_url = os.getenv("LINKEDIN_URL", "https://www.linkedin.com/in/your-profile")
        github_url = os.getenv("GITHUB_URL", "https://github.com/your-profile")

        prompt = f"""Write a FORMAL, PROFESSIONAL cold email for job opportunities.

TO: {recipient_email} at {company}
FROM: {your_name}
TARGET ROLE: {target_role}
LINKEDIN: {linkedin_url}
GITHUB: {github_url}

Email Structure:
1. Greeting: Dear [Name], or Hello [Name],
2. Introduction (2-3 lines):
   - Your name and role/title
   - Brief 1-2 line background (technologies/expertise)
   - Example: "I'm an AI Engineer with experience in developing AI-powered applications, automation workflows, and full-stack solutions."
3. Why This Company (2-3 lines):
   - Mention specific work/products they do
   - Show you researched them
   - Express genuine interest
4. Your Relevant Skills (2-3 lines):
   - List 4-5 key technologies/skills relevant to company
   - Match your skills to their work
5. Call to Action (2 lines):
   - Express interest in opportunities
   - Mention you can share resume/portfolio
6. Closing (2 lines):
   - Thank them for their time
   - Professional sign-off with name, title, LinkedIn, GitHub

Requirements:
- Subject: Specific and professional (not "Application for", not generic)
- Body: Formal, complete, professional tone (200-300 words)
- Multiple paragraphs (4-5 short paragraphs)
- Include social links at the end
- Be specific about company's work/products
- NO emojis, NO hype words ("passionate", "leverage", "synergy")
- Professional but genuine

TEMPLATE STRUCTURE:
Dear [Name],

I hope you're doing well.

I'm [Your Name], [brief background]. I've worked across [key technologies].

I've been exploring [Company Name] and was particularly interested in [specific product/work]. [Reason why it interests you].

I'm currently looking for opportunities where I can contribute to [specific area]. If you happen to know of a team or role that aligns with my background, I would be grateful for any direction.

I'd be happy to share my resume and portfolio for context.

Thank you for your time and consideration.

Best regards,
[Your Name]
[Your Title]
LinkedIn: [URL]
GitHub: [URL]

Return JSON only:
{{"subject": "...", "body": "..."}}
"""

        try:
            response = self.client.messages.create(
                model=self.model,
                max_tokens=800,
                messages=[{"role": "user", "content": prompt}]
            )

            text = response.content[0].text

            # Parse JSON
            import json
            # Clean up markdown code blocks if present
            if "```json" in text:
                text = text.split("```json")[1].split("```")[0]
            elif "```" in text:
                text = text.split("```")[1].split("```")[0]

            result = json.loads(text.strip())
            return result

        except Exception as e:
            log.error(f"Error writing email: {e}")
            return {
                "subject": f"Quick question about {company}",
                "body": f"Hi,\n\nI'm interested in connecting with {company}. Would love to chat!\n\nBest,\n{your_name}"
            }


# ════════════════════════════════════════════════════════════════════════════
#  EMAIL SENDER
# ════════════════════════════════════════════════════════════════════════════

class EmailSender:
    """Send emails via Gmail SMTP"""

    def __init__(self):
        self.smtp_user = os.getenv("SMTP_USER")
        self.smtp_pass = os.getenv("SMTP_PASSWORD")
        self.smtp_host = os.getenv("SMTP_HOST", "smtp.gmail.com")
        self.smtp_port = int(os.getenv("SMTP_PORT", "465"))
        self.sender_name = os.getenv("MY_NAME", "Anshu")

        if not self.smtp_user or not self.smtp_pass:
            raise ValueError("SMTP_USER and SMTP_PASSWORD required in .env")

    def send_email(self, to_email: str, subject: str, body: str,
                   attachment_path: str = None) -> bool:
        """
        Send email via Gmail

        Args:
            to_email: Recipient email
            subject: Email subject
            body: Email body
            attachment_path: Optional file to attach (resume.pdf)

        Returns:
            True if sent, False if failed
        """
        try:
            # Create message
            msg = MIMEMultipart()
            msg['From'] = f"{self.sender_name} <{self.smtp_user}>"
            msg['To'] = to_email
            msg['Subject'] = subject

            # Add body
            msg.attach(MIMEText(body, 'plain'))

            # Add attachment if provided
            if attachment_path and Path(attachment_path).exists():
                with open(attachment_path, 'rb') as attachment:
                    part = MIMEBase('application', 'octet-stream')
                    part.set_payload(attachment.read())
                    encoders.encode_base64(part)
                    part.add_header('Content-Disposition', f'attachment; filename= {Path(attachment_path).name}')
                    msg.attach(part)

            # Send
            with smtplib.SMTP_SSL(self.smtp_host, self.smtp_port) as server:
                server.login(self.smtp_user, self.smtp_pass)
                server.send_message(msg)

            return True

        except Exception as e:
            log.error(f"Failed to send to {to_email}: {e}")
            return False

    def send_batch(self, emails_list: List[Dict], delay: int = 60) -> Dict:
        """
        Send to multiple emails with delays

        Args:
            emails_list: List of {"email": "...", "company": "...", "subject": "...", "body": "..."}
            delay: Delay in seconds between emails

        Returns:
            {"sent": 5, "failed": 2, "total": 7}
        """
        sent = 0
        failed = 0

        for i, email_data in enumerate(emails_list, 1):
            log.info(f"\n[{i}/{len(emails_list)}] Sending to {email_data['email']}...")

            success = self.send_email(
                email_data['email'],
                email_data['subject'],
                email_data['body'],
                attachment_path="resume.pdf"
            )

            if success:
                sent += 1
                log.info(f"  ✓ Sent to {email_data['email']}")
            else:
                failed += 1
                log.warning(f"  ✗ Failed to send to {email_data['email']}")

            # Delay between emails
            if i < len(emails_list):
                log.info(f"  Waiting {delay}s before next email...")
                time.sleep(delay)

        return {"sent": sent, "failed": failed, "total": len(emails_list)}


# ════════════════════════════════════════════════════════════════════════════
#  CUSTOM EMAIL GENERATOR
# ════════════════════════════════════════════════════════════════════════════

class CustomEmailGenerator:
    """Generate and send custom emails"""

    def __init__(self):
        self.writer = EmailWriter()
        self.sender = EmailSender()

    def generate_for_all(self, emails_csv: str = "verified_emails.csv") -> List[Dict]:
        """Generate custom emails for all in CSV"""
        log.info(f"Reading emails from {emails_csv}...")

        emails_list = []

        with open(emails_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                email = row['email']
                company = row['company']

                log.info(f"Generating email for {email} ({company})...")

                # Write email using Claude
                email_content = self.writer.write_email(email, company)

                emails_list.append({
                    'email': email,
                    'company': company,
                    'domain': row.get('domain', ''),
                    'subject': email_content['subject'],
                    'body': email_content['body']
                })

                log.info(f"  ✓ Generated: {email_content['subject']}")

                # Small delay between API calls
                time.sleep(0.5)

        return emails_list

    def save_drafts(self, emails_list: List[Dict],
                   output_file: str = "email_drafts.csv") -> str:
        """Save drafted emails to CSV for review"""
        log.info(f"Saving drafts to {output_file}...")

        with open(output_file, 'w', newline='', encoding='utf-8') as f:
            writer = csv.DictWriter(f, fieldnames=['email', 'company', 'domain', 'subject', 'body', 'approved'])
            writer.writeheader()

            for email_data in emails_list:
                writer.writerow({
                    'email': email_data['email'],
                    'company': email_data['company'],
                    'domain': email_data['domain'],
                    'subject': email_data['subject'],
                    'body': email_data['body'],
                    'approved': 'yes'  # Set to 'no' to skip sending
                })

        log.info(f"✓ Saved {len(emails_list)} drafts to {output_file}")
        return output_file

    def send_approved(self, drafts_csv: str = "email_drafts.csv",
                     max_send: int = 5, delay: int = 60) -> Dict:
        """Send approved emails from CSV"""
        log.info(f"Reading approved emails from {drafts_csv}...")

        emails_to_send = []

        with open(drafts_csv, 'r', encoding='utf-8') as f:
            reader = csv.DictReader(f)

            for row in reader:
                if row.get('approved', '').lower() in ['yes', 'y', '1', 'true']:
                    emails_to_send.append(row)

        if not emails_to_send:
            log.warning("No approved emails to send")
            return {"sent": 0, "failed": 0, "total": 0}

        log.info(f"Found {len(emails_to_send)} approved emails")

        # Limit
        emails_to_send = emails_to_send[:max_send]

        # Confirm
        log.info(f"\nAbout to send {len(emails_to_send)} emails:")
        for email in emails_to_send:
            log.info(f"  • {email['email']} - {email['subject']}")

        confirm = input("\nProceed? (yes/no): ").lower().strip()
        if confirm not in ['yes', 'y']:
            log.info("Cancelled")
            return {"sent": 0, "failed": 0, "total": 0}

        # Send
        return self.sender.send_batch(emails_to_send, delay=delay)


# ════════════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════════════

def main():
    """Main entry point"""
    log.info("\n")
    log.info("╔" + "="*68 + "╗")
    log.info("║       Send Custom Personalized Emails                          ║")
    log.info("║       Each email written by Claude AI                           ║")
    log.info("╚" + "="*68 + "╝")
    log.info("\n")

    generator = CustomEmailGenerator()

    try:
        # Step 1: Generate custom emails
        log.info("STEP 1: Generating custom emails using Claude AI...\n")
        emails_list = generator.generate_for_all("verified_emails.csv")

        if not emails_list:
            log.error("No emails generated")
            return

        log.info(f"\n✓ Generated {len(emails_list)} custom emails")

        # Step 2: Save drafts for review
        log.info("\nSTEP 2: Saving drafts for review...\n")
        drafts_file = generator.save_drafts(emails_list)

        log.info(f"\n✓ Drafts saved to {drafts_file}")
        log.info(f"  ⚠ IMPORTANT: Review the drafts before sending!")
        log.info(f"  • Open {drafts_file}")
        log.info(f"  • Edit any drafts you want to change")
        log.info(f"  • Set 'approved' to 'no' to skip any emails")
        log.info(f"  • Save and close the file")

        # Step 3: Ask to send
        log.info("\n" + "="*70)
        send_now = input("Send emails now? (yes/no): ").lower().strip()

        if send_now in ['yes', 'y']:
            log.info("\nSTEP 3: Sending emails...\n")
            max_send = input("Max emails to send (default 5): ").strip() or "5"
            max_send = int(max_send)

            results = generator.send_approved(drafts_file, max_send=max_send)

            log.info("\n" + "="*70)
            log.info("RESULTS")
            log.info("-"*70)
            log.info(f"  Sent:     {results['sent']}")
            log.info(f"  Failed:   {results['failed']}")
            log.info(f"  Total:    {results['total']}")

            if results['sent'] > 0:
                log.info("\n✓ Emails sent successfully!")
                log.info("  Check your sent folder for copies")
                log.info("  Replies will come to your Gmail inbox")
        else:
            log.info("Skipped sending. Review drafts and run again when ready.")

    except KeyboardInterrupt:
        log.info("\n\n⚠ Interrupted by user")
    except Exception as e:
        log.error(f"Error: {str(e)}", exc_info=True)


if __name__ == "__main__":
    main()
