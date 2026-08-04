const { spawnSync } = require('child_process');
const path = require('path');

const projectRoot = path.resolve(__dirname, '..');
const allureDist = path.join(projectRoot, 'node_modules', 'allure-commandline', 'dist');
const allureBin = process.platform === 'win32'
  ? 'java'
  : path.join(projectRoot, 'node_modules', '.bin', 'allure');
const allureArgs = process.platform === 'win32'
  ? [
      '-classpath',
      `${path.join(allureDist, 'lib', '*')};${path.join(allureDist, 'lib', 'config')}`,
      'io.qameta.allure.CommandLine'
    ]
  : [];

console.log('Opening Allure HTML report...');
const result = spawnSync(
  allureBin,
  [...allureArgs, 'open', 'reports/allure-report'],
  { stdio: 'inherit', shell: false, cwd: projectRoot }
);

if (result.error) {
  console.error('Allure report open failed:', result.error.message);
  process.exit(1);
}

if (result.status !== 0) {
  console.error('Allure report open failed with status:', result.status);
  process.exit(result.status || 1);
}
