import unittest
from application.tool_recovery.policy import RecoveryPolicy, classify_error, can_retry, failure_status


class PolicyTests(unittest.TestCase):
    def test_retry_limit_counts_retries_not_first_call(self):
        policy = RecoveryPolicy.parse({'mode': 'read_only'})
        self.assertEqual([can_retry(policy, 'timeout', n) for n in (1, 2, 3)], [True, True, False])

    def test_only_explicit_transient_errors_retry(self):
        policy = RecoveryPolicy.parse({'mode': 'read_only'})
        for kind in ('permission', 'parameters', 'business', 'unknown'):
            self.assertFalse(can_retry(policy, kind, 1))
        self.assertEqual(classify_error(ValueError('timeout')), 'parameters')
        self.assertEqual(classify_error(RuntimeError('timeout')), 'unknown')
        self.assertEqual(classify_error(TimeoutError()), 'timeout')
        self.assertEqual(classify_error(PermissionError()), 'permission')

    def test_unprotected_write_cannot_retry_unknown_outcome(self):
        for mode in ('unknown', 'unprotected_write'):
            policy = RecoveryPolicy.parse({'mode': mode})
            self.assertFalse(can_retry(policy, 'timeout', 1))
            self.assertEqual(failure_status(policy, 'timeout'), 'outcome_unknown')
        self.assertEqual(failure_status(RecoveryPolicy.parse({}), 'business'), 'failed')

    def test_idempotent_write_requires_contract(self):
        with self.assertRaises(ValueError):
            RecoveryPolicy.parse({'mode': 'idempotent_write'})
        policy = RecoveryPolicy.parse({'mode': 'idempotent_write', 'key_field': 'request_id',
                                       'retention_hours': 24})
        self.assertTrue(can_retry(policy, 'timeout', 1))

    def test_invalid_policy_rejected(self):
        for data in ({'timeout': 0}, {'timeout': 121}, {'retries': 6}, {'retries': True},
                     {'mode': 'safe'}, {'extra': 1}, {'retry_errors': ['business']}):
            with self.subTest(data=data), self.assertRaises(ValueError):
                RecoveryPolicy.parse(data)

    def test_configured_error_allowlist_is_respected(self):
        p = RecoveryPolicy.parse({'mode': 'read_only', 'retry_errors': ['transient']})
        self.assertFalse(can_retry(p, 'timeout', 1))
        self.assertTrue(can_retry(p, 'transient', 1))
