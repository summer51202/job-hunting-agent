import tempfile
import unittest
from pathlib import Path

from job_agent.application import notion_suggestion, run
from job_agent.core import reconcile
from job_agent.prepare import application_docs, rank, weekly_jobs
from job_agent.review import apply_approved, fingerprint


class AcceptanceTests(unittest.TestCase):
    def test_review_uses_current_record_and_is_idempotent(self):
        jobs = [{'company': 'Example', 'job_id': '54321', 'status': '已投遞', 'url': 'record'}]
        email = {'id': 'm1', 'date': '2026-09-01T17:50:00Z', 'body_complete': True,
                 'body': 'Job ID 54321. We decided not to move forward.'}
        report = reconcile(jobs, [{**email, 'body_complete': False}, email, {**email, 'id': 'm2'}])
        self.assertEqual(1, report['summary']['propose_update'])
        event = report['events'][0]
        self.assertEqual('2026-09-02', event['proposed']['closed_date'])
        approvals = {fingerprint(event): 'approve'}

        class Gateway:
            current = {'status': '已投遞', 'closed_date': ''}
            writes = 0

            def read(self, url):
                return self.current

            def update(self, url, fields):
                self.current = fields
                self.writes += 1

        gateway = Gateway()
        apply_approved(report, approvals, gateway)
        self.assertEqual(0, gateway.writes)
        gateway.current = {'status': 'Offer', 'closed_date': ''}
        with self.assertRaises(ValueError):
            apply_approved(report, approvals, gateway, dry_run=False)
        gateway.current = event['current']
        for _ in range(2):
            apply_approved(report, approvals, gateway, dry_run=False)
        self.assertEqual(1, gateway.writes)

    def test_quotes_and_unknown_completeness_do_not_propose(self):
        job = {'job_id': '54321', 'status': '已投遞'}
        bare = {'id': 'a', 'date': '2026-09-02', 'body': 'ID 54321. Decided not to move forward.'}
        quoted = {**bare, 'id': 'b', 'body_complete': True, 'body_html': True,
                  'body': '<p>Your application was received.</p><blockquote>Job ID 54321. Decided not to move forward.</blockquote>'}
        result = reconcile([job], [bare, quoted])
        self.assertEqual(['manual_review', 'ignore'], [x['action'] for x in result['events']])

    def test_ranking_and_document_pairs(self):
        from pypdf import PdfReader
        from docx import Document
        rows = [
            f'| 1 | <Link url="https://example.com/{city}">Example — Systems Engineer</Link>'
            f' | {city} | 80–90% | gap | referral |'
            for city in ('Taipei', 'Hsinchu')]
        jobs = rank(weekly_jobs('\n'.join(rows)))
        self.assertEqual(['Taipei', 'Hsinchu'], [job['location'] for job in jobs])
        self.assertEqual(10.5, jobs[0]['score'] - jobs[1]['score'])
        profile = {'name': 'Example Candidate', 'contact': 'candidate@example.com',
                   'sections': [{'heading': 'Experience', 'bullets': [
                       'Built a C++ inference runtime used by a synthetic project team.',
                       'Maintained Python integration tests for the example runtime across two local operating systems.',
                       'Profiled Linux memory use to identify a regression in the example application.',
                   ]}, {'heading': 'Education', 'bullets': ['Completed an example systems course.']}]}
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp)
            application_docs(profile, jobs[0], 'C++ inference Linux systems Python', out)
            self.assertEqual(2, len(PdfReader(out / 'resume.pdf').pages))
            self.assertEqual(1, len(PdfReader(out / 'cover-letter.pdf').pages))
            from job_agent.ats_audit import audit
            self.assertTrue(audit(out / 'resume.docx', out / 'resume.pdf', expected_pages=2,
                                  source_bullets=profile['sections'][0]['bullets'])['passed'])
            self.assertTrue(audit(out / 'cover-letter.docx', out / 'cover-letter.pdf',
                                  expected_pages=1, cover_letter=True)['passed'])
            text = ' '.join(p.text for p in Document(out / 'resume.docx').paragraphs)
            for bullet in profile['sections'][0]['bullets']:
                self.assertIn(bullet, text)

    def test_browser_fill_upload_and_stop(self):
        import shutil
        chromium = shutil.which('chromium')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            html = root / 'form.html'
            html.write_text('<form action="https://example.com/apply" method="post">'
                            '<label for="name">Name</label><input id="name" required>'
                            '<input type="file" id="resume"><button>Apply</button></form>')
            resume = root / 'resume.pdf'
            resume.write_bytes(b'%PDF-1.4 synthetic upload fixture')
            preview = run(None, fixture=html, values={'name': 'Example Candidate'},
                          uploads={'resume': str(resume)}, executable=chromium)
            self.assertEqual(['name', 'resume'], preview['filled_field_ids'])
            self.assertEqual('awaiting_user_confirmation', preview['submission_state'])
            html.write_text('<body>Verify you are human</body>')
            self.assertTrue(run(None, fixture=html, executable=chromium)['blocked'])
            with self.assertRaises(ValueError):
                run('https://example.com/apply', values={'name': 'Example Candidate'})
            with self.assertRaises(ValueError):
                notion_suggestion({}, {'job_id': '1'})
            proposed = notion_suggestion({'confirmed_by_user': True, 'date': '2026-11-24',
                                          'evidence_url': 'https://example.com/receipt'}, {'job_id': '1'})
            self.assertEqual('已投遞', proposed['suggested_fields']['狀態'])

    def test_historical_conflict_and_terminal_states(self):
        jobs = [{'company': 'Example', 'job_id': '54321', 'status': '已投遞',
                 'applied_date': '2026-09-02', 'url': 'record'}]
        reject = {'id': 'z', 'date': '2026-09-02T08:00:00+08:00',
                  'body': 'Job ID 54321. Not moving forward with your candidacy.',
                  'body_complete': True}
        interview = {**reject, 'id': 'a', 'date': '2026-09-02T12:00:00+08:00',
                     'body': 'Job ID 54321. Interview invitation.'}
        report = reconcile(jobs, [interview, reject])
        self.assertEqual(['z', 'a'], [event['message_id'] for event in report['events']])
        self.assertEqual(0, report['summary']['propose_update'])
        self.assertEqual(report, reconcile(jobs, [reject, interview]))
        for status in ('Rejected', 'Offer', '停止追蹤'):
            self.assertEqual(0, reconcile([{**jobs[0], 'status': status}], [reject])['summary']['propose_update'])
        old = {**reject, 'date': '2026-09-01'}
        self.assertEqual('郵件早於目前投遞日期', reconcile(jobs, [old])['events'][0]['reason'])

    def test_response_lost_after_update_can_be_retried(self):
        jobs = [{'job_id': '54321', 'status': '已投遞', 'url': 'record'}]
        email = {'id': 'm1', 'date': '2026-09-02', 'body_complete': True,
                 'body': 'Job ID 54321. We decided not to move forward.'}
        report = reconcile(jobs, [email])
        approvals = {fingerprint(report['events'][0]): 'approve'}

        class Gateway:
            current = {'status': '已投遞', 'closed_date': ''}
            writes = 0

            def read(self, url):
                return self.current

            def update(self, url, fields):
                self.writes += 1
                self.current = fields
                raise TimeoutError('Committed before the client timed out')

        gateway = Gateway()
        with self.assertRaises(TimeoutError):
            apply_approved(report, approvals, gateway, dry_run=False)
        apply_approved(report, approvals, gateway, dry_run=False)
        self.assertEqual(1, gateway.writes)

    def test_platform_allowlist_and_static_form(self):
        from job_agent.platforms import PLATFORMS, PageFacts, probe
        for platform in PLATFORMS:
            with self.assertRaises(ValueError):
                probe(platform, 'https://' + platform.hosts[0] + '.example.com/')
        page = PageFacts()
        page.feed('<title>Job example</title><form><input type="file"></form>')
        self.assertEqual(('Job example', 1, 1), (page.title, page.forms, page.upload_fields))
