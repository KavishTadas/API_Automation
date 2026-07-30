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

console.log('Generating Allure HTML report...');
const result = spawnSync(
  allureBin,
  [...allureArgs, 'generate', 'reports/allure-results', '--clean',
   '-o', 'reports/allure-report'],
  { stdio: 'inherit', shell: false, cwd: projectRoot }
);

if (result.status === 0) {
  console.log('Allure report generated: reports/allure-report/index.html');
} else {
  console.error('Allure generation failed with status:', result.status);
  process.exit(result.status || 1);
}
