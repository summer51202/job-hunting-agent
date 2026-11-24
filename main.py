"""Run the agent through connector snapshots or read-only API retrieval."""
import argparse
import json
import os
from pathlib import Path

from job_agent.adapters import (
    fetch_gmail_readonly, fetch_notion_readonly, gmail_queries,
    normalize_gmail_summaries, normalize_notion_rows,
)
from job_agent.core import reconcile
from job_agent.review import review_report, save_evidence, write_reports


def load(path):
    return json.loads(Path(path).read_text(encoding='utf-8'))


def main():
    parser = argparse.ArgumentParser(description='Job Hunting Agent · Dry Run')
    jobs_input = parser.add_mutually_exclusive_group(required=True)
    jobs_input.add_argument('--jobs')
    jobs_input.add_argument('--notion-database-id')
    jobs_input.add_argument('--notion-data-source-id')
    email_input = parser.add_mutually_exclusive_group(required=True)
    email_input.add_argument('--emails')
    email_input.add_argument('--gmail-live', action='store_true')
    parser.add_argument('--since', default='2026-09-01')
    parser.add_argument('--aliases', default=str(Path(__file__).parent / 'examples/aliases.json'))
    parser.add_argument('--out', default='report.json')
    parser.add_argument('--evidence-dir', type=Path)
    parser.add_argument('--review', help='JSON mapping proposal fingerprint to approve or reject')
    args = parser.parse_args()
    if args.jobs:
        jobs = normalize_notion_rows(load(args.jobs))
    else:
        jobs = fetch_notion_readonly(args.notion_data_source_id or args.notion_database_id,
                                     data_source=bool(args.notion_data_source_id))
    if args.gmail_live:
        token = os.environ.get('GMAIL_ACCESS_TOKEN')
        if not token:
            parser.error('Missing GMAIL_ACCESS_TOKEN')
        emails = fetch_gmail_readonly(token, gmail_queries(args.since))
    else:
        emails = normalize_gmail_summaries(load(args.emails))
    report = reconcile(jobs, emails, load(args.aliases), since=args.since)
    if args.evidence_dir:
        save_evidence(report, emails, args.evidence_dir)
    report['review'] = review_report(report, load(args.review) if args.review else {})
    write_reports(report, args.out)
    print(json.dumps(report['summary'], ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
