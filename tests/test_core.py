import unittest
from job_agent.core import reconcile, classify, clean

class TestReconciliation(unittest.TestCase):
    def test_html(self):
        self.assertEqual(clean('<b>991230045</b><br />'), '991230045')
    def test_rejection_priority(self):
        self.assertEqual(classify('Thank you for applying', 'decided not to move forward'), 'rejected')
    def test_exact_id_isolation(self):
        jobs=[{'company':'Example Robotics','job_id':'99124001','status':'Rejected'},{'company':'Example Robotics','job_id':'99124002','status':'已投遞'}]
        emails=[{'id':'1','subject':'status update','body':'ID: 99124001. decided not to move forward'}]
        r=reconcile(jobs, emails)
        self.assertEqual(r['events'][0]['job_id'], '99124001')
        self.assertEqual(r['summary']['propose_update'], 0)
    def test_unknown_not_auto_create(self):
        r=reconcile([], [{'id':'1','subject':'Thank you for applying','body':'received your application'}])
        self.assertEqual(r['events'][0]['action'],'manual_review')

if __name__ == '__main__': unittest.main()
