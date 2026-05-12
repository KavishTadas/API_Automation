const fs = require('fs');
const path = require('path');
const { execSync } = require('child_process');

const workspaceRoot = path.resolve(__dirname, '..');

const report = {
  timestamp: new Date().toISOString(),
  workspace: workspaceRoot,
  folders: {},
  files: {},
  packages: {},
  nodeModules: {},
  collections: {},
  git: {},
  env: {}
};

// 1. Check folders
const foldersToCheck = [
  'collections',
  'environments',
  'test-data',
  'scripts',
  'reports/html',
  'reports/allure-results',
  'openapi',
  'bruno',
  'monitoring',
  '.github/workflows'
];

foldersToCheck.forEach(folder => {
  const folderPath = path.join(workspaceRoot, folder);
  const exists = fs.existsSync(folderPath) && fs.statSync(folderPath).isDirectory();
  let hasContent = false;

  if (exists) {
    try {
      const files = fs.readdirSync(folderPath);
      hasContent = files.some(file => file !== '.gitkeep');
    } catch (e) {
      // Permission denied or other error
    }
  }

  report.folders[folder] = {
    exists,
    hasContent
  };
});

// 2. Check files
const filesToCheck = [
  'package.json',
  '.gitignore',
  '.env.example',
  '.env',
  'openapi/openapi.yaml',
  'openapi/.spectral.yaml',
  'scripts/run-newman.js',
  'scripts/reporter-config.js',
  'scripts/postman-cli-run.sh',
  'scripts/collections.conf',
  'allure.properties',
  'reports/allure-results/categories.json',
  'Jenkinsfile',
  '.github/workflows/api-tests.yml',
  'monitoring/health-check.js',
  'monitoring/schedule-config.json'
];

filesToCheck.forEach(file => {
  const filePath = path.join(workspaceRoot, file);
  const exists = fs.existsSync(filePath) && fs.statSync(filePath).isFile();
  report.files[file] = {
    exists
  };
});

// 3. Parse package.json
const packageJsonPath = path.join(workspaceRoot, 'package.json');
if (fs.existsSync(packageJsonPath)) {
  try {
    const packageJson = JSON.parse(fs.readFileSync(packageJsonPath, 'utf8'));
    report.packages.scripts = Object.keys(packageJson.scripts || {});
    report.packages.devDependencies = Object.keys(packageJson.devDependencies || {});
  } catch (e) {
    report.packages.error = `Failed to parse package.json: ${e.message}`;
  }
} else {
  report.packages.error = 'package.json not found';
}

// 4. Check node_modules
const nodeModulesPath = path.join(workspaceRoot, 'node_modules');
report.nodeModules.exists = fs.existsSync(nodeModulesPath) && fs.statSync(nodeModulesPath).isDirectory();

let newmanResolvable = false;
try {
  require.resolve('newman');
  newmanResolvable = true;
} catch (e) {
  newmanResolvable = false;
}
report.nodeModules.newmanResolvable = newmanResolvable;

// 5. List collections
const collectionsPath = path.join(workspaceRoot, 'collections');
report.collections.jsonFiles = [];
if (fs.existsSync(collectionsPath)) {
  try {
    const files = fs.readdirSync(collectionsPath);
    report.collections.jsonFiles = files.filter(f => f.endsWith('.json'));
  } catch (e) {
    report.collections.error = `Failed to read collections: ${e.message}`;
  }
}

report.collections.bruFiles = [];
const brunoPath = path.join(workspaceRoot, 'bruno');
if (fs.existsSync(brunoPath)) {
  try {
    const findBruFiles = (dir) => {
      let bruFiles = [];
      const entries = fs.readdirSync(dir, { withFileTypes: true });
      entries.forEach(entry => {
        const fullPath = path.join(dir, entry.name);
        if (entry.isDirectory()) {
          bruFiles = bruFiles.concat(findBruFiles(fullPath));
        } else if (entry.name.endsWith('.bru')) {
          bruFiles.push(path.relative(brunoPath, fullPath));
        }
      });
      return bruFiles;
    };
    report.collections.bruFiles = findBruFiles(brunoPath);
  } catch (e) {
    report.collections.bruError = `Failed to read bruno: ${e.message}`;
  }
}

// 6. Git information
try {
  const branch = execSync('git branch --show-current', {
    cwd: workspaceRoot,
    encoding: 'utf8'
  }).trim();
  report.git.branch = branch;
} catch (e) {
  report.git.branch = 'not initialised';
}

try {
  const status = execSync('git status --short', {
    cwd: workspaceRoot,
    encoding: 'utf8'
  });
  report.git.status = status.split('\n').filter(line => line.trim());
} catch (e) {
  report.git.status = [];
  if (report.git.branch === 'not initialised') {
    report.git.statusError = 'not initialised';
  }
}

// 7. ENV file
const envPath = path.join(workspaceRoot, '.env');
report.env.exists = fs.existsSync(envPath) && fs.statSync(envPath).isFile();

// Output the report
console.log(JSON.stringify(report, null, 2));
