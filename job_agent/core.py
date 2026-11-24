"""Conservative, read-only reconciliation engine. Never modifies Gmail or Notion."""
from __future__ import annotations
import hashlib
import html, re
from email.utils import parseaddr
from datetime import date, datetime
from email.utils import parsedate_to_datetime
from zoneinfo import ZoneInfo
from typing import Any


def clean(value: Any) -> str:
    return re.sub(r'\s+', ' ', html.unescape(re.sub(r'<[^>]+>', ' ', str(value or '')))).strip()


def normalize_id(value: Any) -> str:
    return re.sub(r'[^a-zA-Z0-9]', '', clean(value)).upper()


def classify(subject: str, body: str) -> str:
    primary = primary_body(body)
    text = (subject+'\n'+primary).lower()
    if any(x in text for x in ('decided not to move forward', 'decided not to progress',
            'not to progress with your application', 'progress other candidates forward',
            'no longer under consideration', 'not moving forward with your candidacy',
            'will not be moving forward', 'will not move forward with your application',
            'decided to pursue other candidates', 'will not be progressing your application')):
        return 'rejected'
    if any(x in text for x in ('interview invitation', 'phone interview is confirmed',
            'would like your availability for a phone interview', 'schedule your interviews',
            'invite you to the next step - phone interview')):
        return 'interview'
    if any(x in text for x in ('assessment invitation', 'online assessment', 'coding test')):
        return 'assessment'
    if any(x in text for x in ('action required', 'please complete', 'additional information')):
        return 'action_required'
    if any(x in text for x in ('received your application', 'thank you for applying',
            'successfully submitted application', 'thank you for your application',
            'thank you for your interest in the position')):
        return 'application_confirmed'
    return 'other'


def id_candidates(text: str) -> set[str]:
    patterns = [r'(?:job\s*(?:number|id)|position\s*id|req(?:uisition)?\s*id|\bid)\s*[:#-]?\s*([A-Z]?\d{5,18})',
                r'\b(R\d{7})\b', r'(?:jobs?/|pid=)(\d{5,18})\b']
    found = set()
    for pat in patterns:
        found.update(normalize_id(x) for x in re.findall(pat, text, re.I))
    return found


def primary_body(body):
    return re.split(r'\n\s*(?:From:|On .+ wrote:|-----Original Message-----|>)',
                    body, maxsplit=1, flags=re.I)[0]


def taipei_date(value):
    if not value:
        return ''
    try:
        if len(value) == 10:
            return date.fromisoformat(value).isoformat()
        try:
            parsed = datetime.fromisoformat(value)
        except ValueError:
            parsed = parsedate_to_datetime(value)
        zone = ZoneInfo('Asia/Taipei')
        return (parsed.astimezone(zone) if parsed.tzinfo else parsed).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ''


def body_text(email):
    body = str(email.get('body') or email.get('snippet') or '')
    if email.get('body_html'):
        body = re.split(r'<blockquote\b|<[^>]+class=["\']gmail_quote', body, 1, flags=re.I)[0]
        body = re.sub(r'<(script|style)\b.*?</\1\s*>', ' ', body, flags=re.I | re.S)
        body = html.unescape(re.sub(r'<[^>]+>', ' ',
                                   re.sub(r'<br\b[^>]*>|</(?:p|div|li)>', '\n', body, flags=re.I)))
    return primary_body(body)


def _sender_context(email, subject):
    sender = parseaddr(email.get('from') or '')[1].casefold()
    domain = sender.rpartition('@')[2]
    def belongs(site):
        return domain == site or domain.endswith('.' + site)
    if any(belongs(s) for s in ('linkedin.com', 'fireflies.ai', 'indeed.com', 'glassdoor.com')):
        return 'notification'
    if belongs('gmail.com') and subject.casefold().startswith('re:'):
        return 'reply'
    if belongs('myworkday.com'):
        return 'workday'
    if belongs('talent.icims.com'):
        return 'amd'
    if belongs('waymo.com'):
        return 'waymo'
    if belongs('cerence.com'):
        return 'cerence'
    return ''


def _title_terms(title):
    return ' '.join(re.findall(r'[a-z0-9]+', title.casefold()))


def _title_matches(jobs, sender, text):
    title_text = ' ' + _title_terms(text) + ' '
    companies = {'amd': {'amd'}, 'waymo': {'waymo'}, 'cerence': {'cerence', 'cerenceai'}}
    if sender == 'workday' and 'cerence' in title_text.split():
        sender = 'cerence'
    if sender not in companies:
        return set()
    return {i for i, job in enumerate(jobs)
            if _title_terms(job.get('company') or '') in companies[sender]
            and len(_title_terms(job.get('title') or '').split()) >= 3
            and ' ' + _title_terms(job['title']) + ' ' in title_text}


def _time_order(email):
    value = email.get('date') or ''
    try:
        try:
            stamp = datetime.fromisoformat(value)
        except ValueError:
            stamp = parsedate_to_datetime(value)
        if stamp.tzinfo is None:
            stamp = stamp.replace(tzinfo=ZoneInfo('Asia/Taipei'))
        return stamp.timestamp()
    except (TypeError, ValueError, OverflowError):
        return float('inf')


def _evidence_order(email):
    return (email.get('body_complete') is True,
            len(email.get('body') or ''),
            str(email.get('body') or ''),
            str(email.get('date') or ''),
            str(email.get('subject') or ''))


def reconcile(jobs: list[dict], emails: list[dict], aliases=None, *, since=None) -> dict:
    by_id = {}
    for index, job in enumerate(jobs):
        jid = normalize_id(job.get('job_id'))
        if jid:
            by_id.setdefault(jid, set()).add(index)
    direct = {key: set(indices) for key, indices in by_id.items()}
    for canonical, variants in (aliases or {}).items():
        ids = {normalize_id(canonical), *(normalize_id(variant) for variant in variants)}
        indices = set().union(*(direct.get(key, set()) for key in ids))
        for variant in ids:
            if indices and normalize_id(variant):
                by_id.setdefault(normalize_id(variant), set()).update(indices)
    best = {}
    for email in emails:
        mid = str(email.get('id') or '')
        if not mid:
            continue
        existing = best.get(mid)
        if existing is None or _evidence_order(email) > _evidence_order(existing):
            best[mid] = email

    events = []
    for mid, email in sorted(best.items(), key=lambda pair: (_time_order(pair[1]), pair[0])):
        day = taipei_date(email.get('date'))
        if since and day and day < since:
            continue
        subject, body = clean(email.get('subject')), body_text(email)
        sender = _sender_context(email, subject)
        event = classify(subject, body)
        if sender in ('notification', 'reply'):
            event = 'other'
        complete = email.get('body_complete') is True
        ids = id_candidates(subject + ' ' + body)
        # Allow standalone known IDs (e.g. "Software Engineer 2, 991230045").
        ids.update(normalize_id(value) for value in re.findall(r'\b[A-Za-z]?\d{5,18}\b', subject + ' ' + body)
                   if normalize_id(value) in by_id)
        if sender == 'workday':
            ids.update(re.findall(r'\s[-–—]\s*(3\d{6})\b', body))
        indices = {i for jid in ids for i in by_id.get(jid, ())}
        match_kind = 'exact_id'
        if not indices and not ids and complete and event in ('application_confirmed', 'rejected'):
            indices = _title_matches(jobs, sender, subject + ' ' + body)
            match_kind = 'company_title'
        matched = jobs[next(iter(indices))] if len(indices) == 1 else None
        current = ({'status': clean(matched.get('status')), 'closed_date': matched.get('closed_date') or ''}
                   if matched is not None else None)
        action, reason, proposal = 'ignore', '無可識別的招募事件', None
        if sender in ('notification', 'reply'):
            reason = '第三方通知或個人回覆'
        if event != 'other' and matched is None:
            action = 'manual_review'
            reason = ('有多筆可能的投遞紀錄' if indices else
                      '有 Job ID 但找不到對應投遞' if ids else '缺少足以識別投遞的 Job ID 或職稱')
        elif event != 'other':
            status = current['status']
            action, reason = 'no_change', '現況不需自動提出變更'
            applied = matched.get('applied_date') or ''
            if day and applied and day < applied:
                action, reason = 'manual_review', '郵件早於目前投遞日期'
            elif event == 'rejected' and status.lower() not in ('rejected', '拒絕', '已拒絕'):
                if complete and day and match_kind == 'exact_id' and status in ('已投遞', '有回覆', '面試中') and not current['closed_date']:
                    action, reason = 'propose_update', '完整正文顯示拒絕，需人工核准'
                    proposal = {'status': 'Rejected', 'closed_date': day}
                else:
                    action, reason = 'manual_review', '正文、日期或目前狀態需確認'
            elif event in ('interview', 'assessment', 'action_required') and status not in ('Rejected', 'Offer', '停止追蹤'):
                action, reason = 'manual_review', '確認下一步或面試活動'
            elif event == 'application_confirmed' and status == '待投遞':
                action, reason = 'manual_review', '郵件與目前投遞狀態不同'
        events.append({'message_id': mid, 'job_id': matched.get('job_id') if matched else None,
                       'company': matched.get('company') if matched else None,
                       'record_url': matched.get('url') if matched else None,
                       'event': event, 'date': day, 'candidate_ids': sorted(ids),
                       'match': match_kind if matched else ('ambiguous' if indices else 'unmatched'),
                       'action': action, 'current': current, 'proposed': proposal,
                       'reason': reason, 'subject': subject, 'evidence_url': email.get('url'),
                       'body_complete': complete,
                       'source_date': email.get('date'),
                       'evidence_sha256': hashlib.sha256(str(email.get('body') or '').encode()).hexdigest()
                                          if complete else None})
    proposals = {}
    live_events = {}
    for event in events:
        if (event['record_url'] and event['match'] == 'exact_id' and event['body_complete']
                and event['event'] in ('application_confirmed', 'assessment', 'interview')):
            live_events[event['record_url']] = event['source_date']
    for event in events:
        if event['action'] == 'propose_update':
            # The earliest observed rejection is the proposed closing date.
            key = event['record_url'] or (event['company'], event['job_id'])
            latest = live_events.get(event['record_url'])
            if latest and _time_order({'date': latest}) > _time_order({'date': event['source_date']}):
                event.update(action='manual_review', proposed=None, reason='拒絕後有較新的招募活動')
                continue
            if key in proposals:
                event.update(action='no_change', proposed=None, reason='同一職缺已有拒絕變更提議')
            else:
                proposals[key] = event
    return {'mode': 'DRY_RUN', 'since': since, 'jobs_count': len(jobs),
            'emails_count': len(emails), 'unique_in_scope': len(events), 'events': events,
            'summary': {action: sum(e['action'] == action for e in events)
                        for action in ('propose_update', 'manual_review', 'no_change', 'ignore')}}
