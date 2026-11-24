"""Local review and guarded execution through a caller-supplied Notion adapter."""
import hashlib
import json
import os
from tempfile import NamedTemporaryFile
from pathlib import Path

from .core import clean


def fingerprint(event):
    fields = ('message_id', 'record_url', 'current', 'proposed', 'evidence_url', 'evidence_sha256')
    data = {key: event[key] for key in fields}
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()


def review_report(report, approvals):
    proposals = {fingerprint(e): e for e in report['events'] if e['action'] == 'propose_update'}
    if set(approvals) - proposals.keys():
        raise ValueError('Approval refers to a missing or changed proposal')
    if any(decision not in ('approve', 'reject') for decision in approvals.values()):
        raise ValueError('Review decisions must be approve or reject')
    return [{'fingerprint': key, 'decision': approvals.get(key, 'pending'), 'event': event}
            for key, event in proposals.items()]


def apply_approved(report, approvals, gateway=None, *, dry_run=True):
    reviewed = review_report(report, approvals)
    approved = [item for item in reviewed if item['decision'] == 'approve']
    if dry_run:
        return reviewed
    if gateway is None:
        raise ValueError('A production gateway must be explicitly provided')
    for item in approved:
        event = item['event']
        fields = event['proposed']
        if not event['record_url'] or not fields or fields.get('status') != 'Rejected':
            raise ValueError('Invalid target or proposed status')
        current = gateway.read(event['record_url'])
        if all(current.get(key) == value for key, value in fields.items()):
            continue
        if current != event['current']:
            raise ValueError('Notion record changed after review')
        gateway.update(event['record_url'], fields)


def write_reports(report, json_path):
    json_path = Path(json_path)
    json_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    markdown = ['# Gmail → Notion 差異報告', '', '模式：DRY RUN', '',
                f"Notion {report['jobs_count']} 筆，Gmail {report['emails_count']} 封。",
                '', '## 統計', '']
    markdown.extend(f'- {key}: {count}' for key, count in report['summary'].items())
    markdown.extend(['', '## 待處理項目', ''])
    for event in report['events']:
        if event['action'] not in ('propose_update', 'manual_review'):
            continue
        markdown.append(f"- {event['action']} · {event['event']} · "
                        f"{event['company'] or '未匹配'} {event['job_id'] or ''} · "
                        f"{clean(event['subject'])} · {event['reason']}")
        if event['proposed']:
            markdown.append(f"  - {event['current']} → {event['proposed']}")
        if event['evidence_url']:
            markdown.append(f"  - {event['evidence_url']}")
    for path, content in ((json_path, json.dumps(report, ensure_ascii=False, indent=2)),
                          (json_path.with_suffix('.md'), '\n'.join(markdown) + '\n')):
        atomic_text(path, content)


def atomic_text(path, content):
    path = Path(path)
    with NamedTemporaryFile(mode='w', encoding='utf-8', dir=path.parent, delete=False) as stream:
        temporary = Path(stream.name)
        try:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
            os.replace(temporary, path)
        finally:
            temporary.unlink(missing_ok=True)


def save_evidence(report, emails, folder):
    folder = Path(folder)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    by_id = {email['id']: email for email in emails if email.get('body_complete') is True}
    for event in report['events']:
        if event['action'] != 'propose_update':
            continue
        message_id = event['message_id']
        matches = [email for email in emails if email.get('id') == message_id
                   and email.get('body_complete') is True
                   and hashlib.sha256(str(email.get('body') or '').encode()).hexdigest()
                   == event['evidence_sha256']]
        if not matches or message_id not in by_id:
            raise ValueError('Proposal has no matching original evidence')
        key = hashlib.sha256(message_id.encode()).hexdigest()
        filename = f"{key}-{event['evidence_sha256']}.json"
        atomic_text(folder / filename, json.dumps(matches[-1], ensure_ascii=False, indent=2))
        event['evidence_file'] = filename
