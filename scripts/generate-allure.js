const fs = require('fs');
const path = require('path');
const { spawnSync } = require('child_process');

const projectRoot = path.resolve(__dirname, '..');
const allureResultsDir = path.join(projectRoot, 'reports', 'allure-results');
const generatedSubDir = path.join(allureResultsDir, 'generated-tests');

function prepareAllureResults() {
  if (!fs.existsSync(allureResultsDir)) {
    fs.mkdirSync(allureResultsDir, { recursive: true });
  }

  if (fs.existsSync(generatedSubDir)) {
    const files = fs.readdirSync(generatedSubDir);
    files.forEach(file => {
      const src = path.join(generatedSubDir, file);
      const dest = path.join(allureResultsDir, file);
      if (fs.lstatSync(src).isFile()) {
        try {
          fs.renameSync(src, dest);
        } catch (e) {
          fs.copyFileSync(src, dest);
        }
      }
    });
  }

  const categories = [
    {
      name: "Employee Auth API Scenarios",
      matchedStatuses: ["passed", "failed", "broken", "skipped"],
      messageRegex: ".*(Auth|token|Login|auth/token).*"
    },
    {
      name: "Leave Management API Scenarios",
      matchedStatuses: ["passed", "failed", "broken", "skipped"],
      messageRegex: ".*(Leave|leave|showleavereport|getAllLeaveReports|approvals).*"
    },
    {
      name: "General API Scenarios",
      matchedStatuses: ["passed", "failed", "broken", "skipped"]
    }
  ];

  fs.writeFileSync(
    path.join(allureResultsDir, 'categories.json'),
    JSON.stringify(categories, null, 2),
    'utf8'
  );

  const envProps = `API_TEST_ENV=uat\nAUTH_BASE_URL=https://dev_mcdp_be.omfysgroup.com\nLEAVE_BASE_URL=https://devmcdphcmplatform.omfysgroup.com\n`;
  fs.writeFileSync(
    path.join(allureResultsDir, 'environment.properties'),
    envProps,
    'utf8'
  );

  const resultFiles = fs.readdirSync(allureResultsDir)
    .filter(f => f.endsWith('-result.json'));

  let processedCount = 0;
  resultFiles.forEach(file => {
    const filePath = path.join(allureResultsDir, file);
    try {
      const content = fs.readFileSync(filePath, 'utf8');
      const data = JSON.parse(content);

      const name = data.name || '';
      const fullName = data.fullName || '';

      // Purge skipped/ignored unverified endpoint results per user request
      if (data.status === 'skipped' || name.includes('users_me') || fullName.includes('unverified_endpoints') || name.includes('unverified')) {
        try {
          fs.unlinkSync(filePath);
        } catch (e) {}
        return;
      }

      data.labels = data.labels || [];
      let method = 'POST';
      let endpoint = '';
      let moduleName = 'API Module';

      const reqParam = (data.parameters || []).find(p => p.name === 'Request' || p.name === 'HTTP Method');
      if (reqParam) {
        const val = reqParam.value || '';
        if (val.includes(' - ')) {
          const parts = val.split(' - ');
          method = parts[0].trim();
          const rawUrl = parts[1].trim();
          try {
            const parsedUrl = new URL(rawUrl);
            endpoint = parsedUrl.pathname;
          } catch (e) {
            endpoint = rawUrl;
          }
        } else if (['GET', 'POST', 'PUT', 'DELETE', 'PATCH'].includes(val.trim())) {
          method = val.trim();
        }
      }

      const endpointParam = (data.parameters || []).find(p => p.name === 'Endpoint Path');
      if (endpointParam) {
        endpoint = endpointParam.value;
      }

      if (!endpoint || endpoint === name) {
        const textToSearch = `${name} ${fullName}`;
        if (/leave|getAllLeaveReports|showleavereport/i.test(textToSearch)) {
          endpoint = '/user/leaves/getAllLeaveReports';
          method = 'GET';
          moduleName = 'Leave Management API';
        } else if (/auth|token|login/i.test(textToSearch)) {
          endpoint = '/auth/token';
          method = 'POST';
          moduleName = 'Employee Auth API';
        } else {
          endpoint = '/api/v1/endpoint';
        }
      }

      if (endpoint.includes('/auth/token')) {
        moduleName = 'Employee Auth API';
        endpoint = '/auth/token';
      } else if (endpoint.includes('/user/leaves/')) {
        moduleName = 'Leave Management API';
      }

      const apiFeatureName = `${method} ${endpoint}`;

      // Populate statusDetails message so categories.json messageRegex can match passed and failed tests
      data.statusDetails = data.statusDetails || {};
      if (!data.statusDetails.message) {
        data.statusDetails.message = `[${moduleName}] ${apiFeatureName} - ${name}`;
      }

      // Overwrite or set labels cleanly so Allure groups correctly
      data.labels = data.labels.filter(l => !['epic', 'feature', 'story', 'parentSuite', 'suite', 'subSuite'].includes(l.name));
      data.labels.push({ name: 'epic', value: moduleName });
      data.labels.push({ name: 'feature', value: apiFeatureName });
      data.labels.push({ name: 'story', value: name });
      data.labels.push({ name: 'parentSuite', value: moduleName });
      data.labels.push({ name: 'suite', value: apiFeatureName });
      data.labels.push({ name: 'subSuite', value: name });

      fs.writeFileSync(filePath, JSON.stringify(data, null, 2), 'utf8');
      processedCount++;
    } catch (e) {
      console.warn(`Failed to post-process Allure result ${file}:`, e.message);
    }
  });

  console.log(`Preprocessed ${resultFiles.length} Allure result files (${processedCount} updated with Epic/Feature/Story labels and categories.json).`);
}

prepareAllureResults();

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

function patchGeneratedAllureCategories() {
  const reportDataDir = path.join(projectRoot, 'reports', 'allure-report', 'data');
  const suitesPath = path.join(reportDataDir, 'suites.json');
  const categoriesPath = path.join(reportDataDir, 'categories.json');

  if (!fs.existsSync(suitesPath)) {
    return;
  }

  try {
    const suitesData = JSON.parse(fs.readFileSync(suitesPath, 'utf8'));
    const categoriesData = fs.existsSync(categoriesPath)
      ? JSON.parse(fs.readFileSync(categoriesPath, 'utf8'))
      : { uid: "categories", name: "categories", children: [] };

    categoriesData.children = categoriesData.children || [];

    if (categoriesData.children.length === 0 && suitesData.children) {
      suitesData.children.forEach(moduleNode => {
        const categoryGroup = {
          name: `${moduleNode.name} Scenarios`,
          children: moduleNode.children || []
        };
        categoriesData.children.push(categoryGroup);
      });
      fs.writeFileSync(categoriesPath, JSON.stringify(categoriesData, null, 2), 'utf8');
      console.log(`Patched allure-report categories.json with ${categoriesData.children.length} API category group(s).`);
    }
  } catch (e) {
    console.warn('Could not patch allure-report categories.json:', e.message);
  }
}

if (result.status === 0) {
  patchGeneratedAllureCategories();
  console.log('Allure report generated: reports/allure-report/index.html');
} else {
  console.error('Allure generation failed with status:', result.status);
  process.exit(result.status || 1);
}


