import unittest
from job_agent.adapters import normalize_notion_rows,normalize_gmail_summaries
from job_agent.core import reconcile,classify

class TestAdapters(unittest.TestCase):
    def test_connector_rows(self):
        rows={'text':'{"results":[{"公司":"Example Systems","職位":"<b>Software Engineer 2</b>","Job ID":"<br />991230045","狀態":"已投遞","date:結案日期:start":null,"url":"https://notion.so/x"}]}'}
        x=normalize_notion_rows(rows)[0]
        self.assertEqual((x['job_id'],x['title']),('991230045','Software Engineer 2'))
    def test_gmail_connector(self):
        x=normalize_gmail_summaries({'result':{'emails':[{'id':'1','subject':'S','snippet':'Hi','email_ts':'2026-11-08'}]}})[0]
        self.assertFalse(x['body_complete'])
    def test_snippet_not_authoritative(self):
        jobs=[{'company':'Example Systems','job_id':'991230045','status':'已投遞'}]
        emails=[{'id':'1','subject':'Thank you','body':'decided not to move forward ID: 991230045','body_complete':False}]
        self.assertEqual(reconcile(jobs,emails)['events'][0]['action'],'manual_review')
    def test_full_body_rejection(self):
        jobs=[{'company':'Example Systems','job_id':'991230045','status':'已投遞'}]
        emails=[{'id':'1','date':'2026-11-08','subject':'Thank you','body':'decided not to move forward ID: 991230045','body_complete':True}]
        self.assertEqual(reconcile(jobs,emails)['events'][0]['proposed']['status'],'Rejected')
    def test_quoted_text(self):
        self.assertEqual(classify('Re: Online assessment','Thank you for completing the online assessment.\nFrom: Old\ndecided not to move forward'),'assessment')
    def test_alias(self):
        jobs=[{'company':'Example Silicon','job_id':'9912501','status':'已投遞'}]
        emails=[{'id':'1','subject':'Received','body':'Job ID: 991250100001. received your application'}]
        self.assertEqual(reconcile(jobs,emails,{'9912501':['991250100001']})['events'][0]['job_id'],'9912501')

if __name__=='__main__': unittest.main()
