#!/usr/bin/env python3
"""렌더러 출력 폴더(subject.txt, email.txt, email.html)를 SMTP로 한 통 보낸다.

  python3 briefing/send_mail.py <출력폴더>              # 발송 (send-briefing.yml 이 부른다)
  python3 briefing/send_mail.py <출력폴더> --dry-run    # 보내지 않고 <출력폴더>/message.eml 만 쓴다

환경 변수: SMTP_USER, SMTP_PASSWORD (Gmail 앱 비밀번호), MAIL_TO (쉼표 구분),
          SUBJECT_PREFIX (선택, 예 "[테스트] "), SMTP_HOST·SMTP_PORT (선택, 기본 smtp.gmail.com:465)

2026-10-20 추가. routine 이 메일 도구에 6만 자 HTML 을 옮겨 적다 응답이 끊겨 HTML 이 잘린 채 나갔다.
본문은 이제 파일에서 그대로 읽어 보내므로 옮겨 적는 단계가 없다.
"""
import os, smtplib, ssl, sys
from email.message import EmailMessage
from email.utils import formatdate, make_msgid


def read(out, name):
    return open(os.path.join(out, name), encoding="utf-8").read()


def build(out):
    subject = os.environ.get("SUBJECT_PREFIX", "") + read(out, "subject.txt").strip()
    txt, html = read(out, "email.txt"), read(out, "email.html")
    # 렌더러 검사를 통과한 파일만 온다. 잘린 파일이 섞이지 않았는지 끝만 한 번 더 본다.
    if not html.rstrip().endswith("</html>") or len(txt) < 1000:
        sys.exit("본문 파일이 완전하지 않음(email.html 끝에 </html> 없음 또는 email.txt 1,000자 미만). 발송 중단")
    to = [a.strip() for a in os.environ.get("MAIL_TO", "").split(",") if a.strip()]
    if not to:
        sys.exit("MAIL_TO 가 비어 있음. 발송 중단")
    sender = os.environ.get("SMTP_USER", "")
    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(to)
    msg["Date"] = formatdate()
    msg["Message-ID"] = make_msgid(domain=sender.split("@")[-1] or None)
    msg.set_content(txt)
    msg.add_alternative(html, subtype="html")
    return msg, to, len(html), len(txt)


def main():
    if len(sys.argv) not in (2, 3) or (len(sys.argv) == 3 and sys.argv[2] != "--dry-run"):
        print(__doc__); sys.exit(2)
    out = sys.argv[1]
    msg, to, n_html, n_txt = build(out)
    if len(sys.argv) == 3:
        open(os.path.join(out, "message.eml"), "wb").write(bytes(msg))
        print(f"DRY-RUN {msg['Subject']} → {', '.join(to)} (HTML {n_html:,}자, 평문 {n_txt:,}자)")
        return
    user, pw = os.environ.get("SMTP_USER", ""), os.environ.get("SMTP_PASSWORD", "")
    if not user or not pw:
        sys.exit("SMTP_USER/SMTP_PASSWORD 없음. 저장소 Secrets 에 GMAIL_USER, GMAIL_APP_PASSWORD 를 넣는다")
    host, port = os.environ.get("SMTP_HOST", "smtp.gmail.com"), int(os.environ.get("SMTP_PORT", "465"))
    with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=60) as s:
        s.login(user, pw)
        s.send_message(msg)
    print(f"SENT {msg['Subject']} → {', '.join(to)} (HTML {n_html:,}자, 평문 {n_txt:,}자)")


if __name__ == "__main__":
    main()
