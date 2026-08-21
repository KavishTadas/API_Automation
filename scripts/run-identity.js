const os = require('os');
const path = require('path');
const { execFileSync } = require('child_process');

const projectRoot = path.resolve(__dirname, '..');

function gitConfigValue(key, options) {
  try {
    return options.execFile(
      'git',
      ['config', '--get', key],
      {
        cwd: options.cwd,
        encoding: 'utf8',
        stdio: ['ignore', 'pipe', 'ignore']
      }
    ).trim();
  } catch (error) {
    return '';
  }
}

function resolveLastRunBy(options = {}) {
  const environment = options.environment || process.env;
  const cwd = options.cwd || projectRoot;
  const execFile = options.execFile || execFileSync;
  const userInfo = options.userInfo || (() => os.userInfo());

  if (environment.GITHUB_ACTIONS === 'true') {
    const actor = String(environment.GITHUB_ACTOR || '').trim();
    if (!actor) {
      throw new Error(
        'Cannot determine Last Run By: GITHUB_ACTOR is missing in GitHub Actions'
      );
    }
    return actor;
  }

  const gitName = gitConfigValue('user.name', { cwd, execFile });
  const gitEmail = gitConfigValue('user.email', { cwd, execFile });

  if (gitName && gitEmail) {
    return `${gitName} <${gitEmail}>`;
  }
  if (gitName || gitEmail) {
    return gitName || gitEmail;
  }

  let username = '';
  try {
    username = String(userInfo()?.username || '').trim();
  } catch (error) {
    username = '';
  }
  username ||= String(environment.USERNAME || environment.USER || '').trim();

  if (!username) {
    throw new Error(
      'Cannot determine Last Run By from Git configuration or OS username'
    );
  }
  return username;
}

module.exports = { resolveLastRunBy };
