"""Verify deployment isolation and credential preservation without touching Docker."""
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('staging.sh')
COMPOSE = SCRIPT.parent.parent / 'compose.staging.yaml'


class StagingDeploymentTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.deploy = root / 'deployed'
        release = root / 'release' / 'revamped'
        release.mkdir(parents=True)
        (release / COMPOSE.name).write_text(COMPOSE.read_text())
        binaries = root / 'bin'
        binaries.mkdir()
        self.log = root / 'commands.log'
        # Exit before mutation on pull/health failures. Never run the real Docker CLI.
        (binaries / 'docker').write_text('''#!/bin/sh
printf '%s\\n' "$*" >> "$COMMAND_LOG"
case "$*" in
  login*) cat >/dev/null ;;
  *" pull") [ "${FAIL_PULL:-0}" = 0 ] || exit 1 ;;
  *" up "*) [ "${FAIL_HEALTH:-0}" = 0 ] || exit 1 ;;
esac
exit 0
''')
        (binaries / 'curl').write_text('#!/bin/sh\nprintf "curl %s\\n" "$*" >> "$COMMAND_LOG"\n')
        # macOS lacks flock; tests run sequentially and do not test the Linux lock primitive.
        (binaries / 'flock').write_text('#!/bin/sh\nexit 0\n')
        for binary in binaries.iterdir():
            binary.chmod(0o755)
        self.env = {
            **os.environ, 'PATH': str(binaries) + os.pathsep + os.environ['PATH'],
            'GHCR_TOKEN': 'test-token-never-log', 'GHCR_USER': 'test-user',
            'IMAGE_PREFIX': 'ghcr.io/test/bayu', 'DEPLOY_TAG': 'stag-test-123',
            'TARGET_HOST': '192.0.2.10', 'RELEASE_FILES': str(release.parent),
            'DEPLOY_DIR': str(self.deploy), 'COMMAND_LOG': str(self.log),
            'APP_PORT': '3010', 'API_PORT': '8090', 'BIND_ADDRESS': '0.0.0.0',
            'PUBLIC_APP_URL': '', 'PUBLIC_API_BASE': '',
        }

    def run_deployment(self, **overrides):
        return subprocess.run(['bash', str(SCRIPT)], env={**self.env, **overrides},
                              capture_output=True, text=True)

    def test_redeploy_preserves_secrets_and_isolates_compose(self):
        first = self.run_deployment()
        self.assertEqual(first.returncode, 0, first.stderr)
        secrets = (self.deploy / '.env.prod').read_bytes()
        self.assertEqual((self.deploy / '.env.prod').stat().st_mode & 0o777, 0o600)
        second = self.run_deployment(DEPLOY_TAG='stag-second-456',
                                     PUBLIC_APP_URL='https://platform.example.com',
                                     PUBLIC_API_BASE='https://platform-api.example.com/api')
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual((self.deploy / '.env.prod').read_bytes(), secrets)
        release = (self.deploy / '.env.release').read_text()
        self.assertIn('TAG=stag-second-456', release)
        self.assertIn('CORS_ORIGINS=https://platform.example.com', release)
        self.assertIn('NUXT_PUBLIC_API_BASE=https://platform-api.example.com/api', release)
        commands = self.log.read_text()
        self.assertIn('--project-name bayu-platform-staging', commands)
        self.assertIn('--wait --wait-timeout 240', commands)
        self.assertNotIn(' down', commands)
        self.assertNotIn('prune', commands)
        self.assertNotIn('test-token-never-log', first.stdout + commands)
        self.assertNotIn('edafy', commands)

    def test_pull_failure_does_not_restart_stack_or_replace_saved_release(self):
        self.assertEqual(self.run_deployment().returncode, 0)
        saved = (self.deploy / '.env.release').read_bytes()
        self.log.write_text('')
        result = self.run_deployment(FAIL_PULL='1', DEPLOY_TAG='stag-failed')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(' up ', self.log.read_text())
        self.assertEqual((self.deploy / '.env.release').read_bytes(), saved)
        self.assertEqual(list(self.deploy.glob('.env.release.*')), [])

    def test_unhealthy_stack_is_reported_and_not_recorded_as_success(self):
        result = self.run_deployment(FAIL_HEALTH='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('did not become healthy', result.stderr)
        self.assertIn('logs --tail=80', self.log.read_text())
        self.assertFalse((self.deploy / '.env.release').exists())

    def test_invalid_settings_fail_before_docker_changes(self):
        for overrides in [{'APP_PORT': '8085\nTAG=other'}, {'PUBLIC_APP_URL': 'https://example.com/'},
                          {'PUBLIC_API_BASE': 'https://example.com/$TOKEN/api'},
                          {'DEPLOY_TAG': 'stag test'}, {'API_PORT': '3010'}]:
            with self.subTest(overrides=overrides):
                result = self.run_deployment(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.log.exists())


if __name__ == '__main__':
    unittest.main()
